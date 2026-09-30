# -*- coding: utf-8 -*-
"""Agent 核心引擎:任务规划 → 工具调用 → 结果校验 → 反馈循环。

执行循环(ReAct + Reflection):
    Plan(隐式,LLM 的 thought) → Act(tool_calls) → Observe(工具结果回填)
    → …循环… → Review(独立审阅,检查数据支撑/合规/结构)
    → 不通过则带审阅意见重规划(最多 max_reflect_loops 次)
    → 合规门禁(硬规则扫描,命中红线直接 block)
    → 通过 → 产出最终报告 + 沉淀长期记忆

容错与预算(系统工程化):
    - 工具错误回传 error,LLM 自行修正;单工具重试上限 max_retries_per_tool
    - token 预算熔断:max_total_tokens 超出即停止并报告
    - 步数熔断:max_steps
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import AgentConfig
from ..knowledge.rules import COMPLIANCE_RULES
from ..runtime.llm import LLMClient, LLMResult
from ..runtime.trace import Trace
from ..tools.registry import ToolRegistry, bind_knowledge
from .memory import Memory
from .prompts import build_system_prompt


class BudgetExceeded(RuntimeError):
    pass


def _compress_observation(obs: Any, tool: str) -> str:
    """压缩工具观测:保留关键标量;price_history 等列表返回统计摘要而非全序列。"""
    if not isinstance(obs, dict):
        return str(obs)[:300]
    if "error" in obs:
        return json.dumps(obs, ensure_ascii=False)[:300]
    # 列表型观测 → 统计摘要(首/末/高低/均值),信息保留但体积缩小一个量级
    if isinstance(obs.get("_raw"), list) and obs["_raw"] and isinstance(obs["_raw"][0], dict):
        rows = obs["_raw"]
        closes = [row.get("close") for row in rows if row.get("close") is not None]
        if closes:
            import statistics
            return json.dumps({
                "tool": tool, "points": len(rows),
                "first": rows[0].get("close"), "last": rows[-1].get("close"),
                "min": min(closes), "max": max(closes),
                "mean": round(statistics.mean(closes), 2),
                "note": "完整序列已压缩为首末/高低/均值统计",
            }, ensure_ascii=False)
        # 新闻等 dict 列表:每条截取标题/情绪
        items = []
        for row in rows[:6]:
            items.append({k: str(v)[:80] for k, v in row.items() if k in ("date", "title", "sentiment")})
        return json.dumps({"tool": tool, "count": len(rows), "items": items},
                          ensure_ascii=False)[:1200]
    keep_keys = ("ticker", "name", "industry", "price", "change_pct", "pe_ttm", "pb",
                 "market_cap_cny", "dividend_yield_pct", "as_of", "report_period",
                 "revenue_cny", "revenue_yoy_pct", "gross_margin_pct", "net_margin_pct",
                 "roe_pct", "debt_ratio_pct", "current_ratio", "ocf_to_net_profit",
                 "goodwill_to_asset_pct", "top1_customer_pct", "major_holder_pledge_pct",
                 "industry_avg_pe", "industry_avg_pb", "value", "expr", "results",
                 "peers", "sentiment", "id", "topic", "content", "score", "hint")
    parts = []
    for k, v in obs.items():
        if k not in keep_keys:
            continue
        s = json.dumps(v, ensure_ascii=False) if not isinstance(v, (str, int, float)) else str(v)
        parts.append(f"{k}={s[:200]}")
    return "{" + ", ".join(parts) + "}"[:1200]


class AgentRunner:
    def __init__(self, cfg: AgentConfig, registry: ToolRegistry,
                 knowledge, memory: Memory):
        self.cfg = cfg
        self.registry = registry
        self.knowledge = knowledge
        self.memory = memory
        self.llm = LLMClient(cfg)
        self.reviewer = LLMClient(cfg, model=cfg.reviewer_model)
        bind_knowledge(knowledge)

    # ------------------------------------------------------------------
    def run(self, task: str, trace: Trace | None = None) -> tuple[str, Trace]:
        trace = trace or Trace(task)
        # ---- 上下文组装:RAG + 长期记忆 ----
        rag_ctx = self.knowledge.format_context(task)
        mem = self.memory.recall_for_task(task)
        mem_lines = [f"- [{m['ts']}] {m['ticker']} {m['task_type']}: {m['conclusion']}" for m in mem]
        system = build_system_prompt(rag_ctx, mem_lines)
        trace.add("system", thought=f"RAG 命中 {len(self.knowledge.search(task))} 张知识卡, "
                                     f"召回 {len(mem)} 条历史记忆")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": task},
        ]
        # 已回填的工具消息计数(用于历史观测压缩)
        tool_msg_count = 0

        # ---- 主循环:Act → Observe ----
        final_text = ""
        for step_i in range(self.cfg.max_steps):
            self._check_budget(trace)
            result = self.llm.chat(messages, tools=self.registry.specs())
            trace.add_usage(result.usage.as_dict())

            if result.tool_calls:
                messages.append({"role": "assistant",
                                 "content": result.content or None,
                                 "tool_calls": [self._raw_tc(tc) for tc in result.tool_calls]})
                # 同一轮多个工具并发执行(延迟优化:串行→并行)
                import concurrent.futures as cf
                tcs = result.tool_calls
                if self.cfg.parallel_tools and len(tcs) > 1:
                    with cf.ThreadPoolExecutor(max_workers=min(4, len(tcs))) as ex:
                        obs_list = list(ex.map(lambda tc: self._exec_one(tc), tcs))
                else:
                    obs_list = [self._exec_one(tc) for tc in tcs]
                for tc, obs in zip(tcs, obs_list):
                    self._record_action(tc, obs, trace)
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": obs if isinstance(obs, str) else json.dumps(obs, ensure_ascii=False)[:4000]})
                    tool_msg_count += 1
                # 历史观测滚动压缩:只保留最近 K 条全文,更早的截短(上下文成本控制)
                self._compact_history(messages, tool_msg_count)
                continue

            # 无工具调用 → 视为候选最终答案,进入 Review
            final_text = result.content.strip()
            trace.add("draft", thought=f"候选最终答案({len(final_text)} 字),进入 Review",
                      result={"text": final_text})
            review = self._review(task, final_text, trace)
            if review["verdict"] == "pass":
                gate = self._compliance_gate(final_text)
                trace.gate = gate
                if gate["blocked"]:
                    trace.finish("blocked", gate["revised"] or final_text)
                    return trace.final_answer, trace
                answer = gate["revised"] or final_text
                self._remember(task, answer)
                trace.finish("passed", answer)
                return answer, trace

            # Review 不通过 → 带意见重规划
            if step_i >= self.cfg.max_steps - 1 or \
               trace.steps and sum(1 for s in trace.steps if s.type == "review") > self.cfg.max_reflect_loops:
                break
            messages.append({"role": "user",
                             "content": "【审阅意见】你的上一稿存在以下问题,请修正后重新作答:\n"
                                        + review["issues_text"]
                                        + "\n如需补充数据请继续调用工具。"})
            trace.add("replan", thought="Review 未通过,带意见重规划: " + review["issues_text"][:200])

        # 步数耗尽:尽力给出已收集内容的合规版本
        if not final_text:
            final_text = "任务未能在步数预算内完成。已收集的工具观测数据见 trace。"
        gate = self._compliance_gate(final_text)
        trace.gate = gate
        trace.finish("failed" if not gate["revised"] else "passed", gate["revised"] or final_text)
        return trace.final_answer, trace

    # ------------------------------------------------------------------
    # 工具执行:拆分为"执行"与"记录"两段,支持并行执行后统一记 trace
    def _exec_one(self, tc: dict) -> Any:
        import time
        name, args = tc["name"], tc["arguments"]
        t0 = time.time()
        try:
            fn = self.registry.get(name)
            obs = fn(**args) if isinstance(args, dict) else {"error": "参数必须是对象"}
        except TypeError as e:
            obs = {"error": f"参数不匹配: {e}", "hint": "检查参数名与类型"}
        except Exception as e:
            obs = {"error": str(e)}
        # 延迟附在观测上:dict 直接挂字段,其他类型包一层
        lat = round((time.time() - t0) * 1000, 1)
        if isinstance(obs, dict):
            obs["_latency_ms"] = lat
        else:
            obs = {"_raw": obs, "_latency_ms": lat}
        return obs

    def _record_action(self, tc: dict, obs: Any, trace: Trace) -> Any:
        name, args = tc["name"], tc["arguments"]
        err = ""
        if isinstance(obs, dict) and "error" in obs:
            err = str(obs["error"])
        # 观测压缩:dict → 紧凑字符串(保留关键标量),控制上下文膨胀
        if isinstance(obs, dict):
            lat = obs.pop("_latency_ms", 0.0)
            compact = _compress_observation(obs, name)
        else:
            lat = 0.0
            compact = json.dumps(obs, ensure_ascii=False)[:1200]
        trace.add("action", tool=name, arguments=args, result=obs,
                  error=err, latency_ms=lat)
        trace.add("observation", result=compact)
        return compact

    # 兼容旧接口(评测/调试直接调)
    def _execute_tool(self, tc: dict, trace: Trace) -> Any:
        obs = self._exec_one(tc)
        return self._record_action(tc, obs, trace)

    # ------------------------------------------------------------------
    # 历史压缩:较早的 tool 消息截短到 300 字符,只保留最近 keep_full 条全文
    def _compact_history(self, messages: list[dict], tool_msg_count: int) -> None:
        keep = self.cfg.observation_keep_full
        if tool_msg_count <= keep:
            return
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        for i in tool_indices[:-keep]:
            c = messages[i]["content"] or ""
            if len(c) > 300:
                messages[i]["content"] = c[:300] + "…(已压缩)"

    # ------------------------------------------------------------------
    # Reflection:独立 reviewer 审查(仅注入压缩观测摘要,控成本)
    def _review(self, task: str, answer: str, trace: Trace) -> dict:
        obs_digest = "\n".join(
            f"- [{s.tool}] {s.result if isinstance(s.result, str) else json.dumps(s.result, ensure_ascii=False)[:200]}"
            for s in trace.steps if s.type == "observation"
        )[:self.cfg.review_digest_chars]
        review_prompt = (
            "你是金融研究质量审阅官。审查以下回答是否合格,判断标准:\n"
            "1. grounding:关键数字是否都有工具数据出处(而非凭空出现);\n"
            "2. compliance:是否无买卖指令、无收益承诺;\n"
            "3. structure:是否包含 结论/关键数据/分析/风险提示 四段;\n"
            "4. completeness:是否真正回答了任务问题。\n"
            "输出 JSON(不要其他文字): {\"verdict\": \"pass\"|\"fail\", "
            "\"issues\": [\"问题1\", ...]}\n\n"
            f"【任务】{task}\n\n【工具观测摘要(供核验数据出处)】\n{obs_digest}\n\n"
            f"【待审回答】\n{answer[:6000]}"
        )
        try:
            r = self.reviewer.chat([{"role": "user", "content": review_prompt}])
            trace.add_usage(r.usage.as_dict())
            m = re.search(r"\{.*\}", r.content, re.DOTALL)
            data = json.loads(m.group(0)) if m else {"verdict": "pass", "issues": []}
        except Exception as e:
            data = {"verdict": "pass", "issues": []}  # 审阅服务故障不阻塞主链路
            trace.add("review", error=f"reviewer 故障(降级放行): {e}")
        issues = [str(i) for i in data.get("issues", [])][:5]
        verdict = data.get("verdict", "pass")
        trace.add("review", thought=f"verdict={verdict} issues={len(issues)}",
                  result={"issues": issues})
        return {"verdict": verdict, "issues": issues,
                "issues_text": "\n".join(f"- {i}" for i in issues) or "(无)"}

    # ------------------------------------------------------------------
    # 合规门禁:硬规则,最后防线(不依赖 LLM)
    def _compliance_gate(self, answer: str) -> dict:
        violations: list[dict] = []
        for rule in COMPLIANCE_RULES:
            if rule.get("pattern"):
                for m in re.finditer(rule["pattern"], answer):
                    # 否定语境检查:承诺词左侧窗口内出现否定词,或命中段被引号包裹(转述用户
                    # 的违规诉求再拒绝),均属风险提示表述 → 放行
                    window_start = max(0, m.start() - rule.get("negation_window", 0))
                    prefix = answer[window_start:m.start()]
                    if any(neg in prefix for neg in rule.get("negations", [])):
                        continue
                    if rule.get("quote_exempt") and re.search(
                            r"[\"“‘「『][^\"”’」』]{0,6}$", prefix):
                        continue
                    violations.append({"id": rule["id"], "name": rule["name"],
                                       "severity": rule["severity"],
                                       "msg": rule["message"], "hit": m.group(0)})
                    break
            # 拒答类回答(未做任何投资分析)豁免风险提示要求
            refusal_like = ("没法满足" in answer or "无法" in answer[:80] or "不能凭" in answer[:60])                            and "### 结论" not in answer and "### 分析" not in answer
            if rule.get("require") == "risk_disclaimer" and "风险提示" not in answer and not refusal_like:
                violations.append({"id": "CR-003", "name": "缺少风险提示",
                                   "severity": "block", "msg": rule["message"]})
            if rule.get("require") == "data_source_note" and ("as_of" not in answer and "报告期" not in answer):
                violations.append({"id": "CR-004", "name": "缺少数据来源标注",
                                   "severity": "warn", "msg": rule["message"]})
        blocked = any(v["severity"] == "block" for v in violations)
        revised = answer
        if blocked:
            # 红线内容不安全,替换为合规说明
            revised = ("该回答未通过合规门禁,已拦截。违规项: "
                       + "; ".join(v["id"] + " " + v["name"] for v in violations if v["severity"] == "block")
                       + "\n\n风险提示:本内容不构成投资建议。")
        return {"blocked": blocked, "violations": violations, "revised": revised}

    # ------------------------------------------------------------------
    # 记忆沉淀:把本次研究结论按 ticker 归档
    def _remember(self, task: str, answer: str) -> None:
        tickers = set(re.findall(r"\b\d{6}\b", task))
        if not tickers:
            return
        try:
            summary = answer.split("###")[1][:200].replace("\n", " ").strip() if "###" in answer else answer[:200]
        except IndexError:
            summary = answer[:200]
        for t in tickers:
            self.memory.remember(t, "deep_research", f"{task[:60]} → {summary[:150]}", source="agent")

    # ------------------------------------------------------------------
    def _check_budget(self, trace: Trace) -> None:
        used = trace.usage.get("total_tokens", 0)
        if used > self.cfg.max_total_tokens:
            raise BudgetExceeded(f"token 预算熔断: {used} > {self.cfg.max_total_tokens}")

    @staticmethod
    def _raw_tc(tc: dict) -> dict:
        """还原为 OpenAI 协议的 tool_calls 结构。"""
        return {
            "id": tc["id"],
            "type": "function",
            "function": {"name": tc["name"],
                         "arguments": json.dumps(tc["arguments"], ensure_ascii=False)},
        }
