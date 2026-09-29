# -*- coding: utf-8 -*-
"""工具层:Function Call 工具注册表。

每个工具 = JSON Schema 描述(给 LLM 看)+ Python 实现(给运行时执行)。
描述质量直接决定 Agent 行为 —— 所以工具描述按 prompt engineering 标准撰写:
  - 说清"何时该用 / 何时不该用"
  - 参数给正例
  - 返回结构里显式带 as_of / 单位,防止模型脑补数据时效

容错:工具异常不炸循环,而是返回 {"error": ...} 让 LLM 自己修正参数(自愈),
失败超过 max_retries 次才真正中断。
"""
from __future__ import annotations

import statistics
from typing import Any, Callable

from .mock_data import MarketData

# 全局单例数据源(生产环境替换为真实 API 客户端)
DATA = MarketData()


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, dict[str, Any]] = {}

    # ---- 注册 ----
    def register(self, name: str, description: str, parameters: dict,
                 fn: Callable[..., Any]) -> None:
        self._tools[name] = {
            "spec": {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            },
            "fn": fn,
        }

    # ---- 供 LLM ----
    def specs(self) -> list[dict]:
        return [t["spec"] for t in self._tools.values()]

    # ---- 供运行时 ----
    def get(self, name: str) -> Callable[..., Any]:
        if name not in self._tools:
            raise KeyError(f"未注册工具: {name}")
        return self._tools[name]["fn"]

    def names(self) -> list[str]:
        return list(self._tools)


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        "get_quote",
        ("获取单只股票的实时行情快照:最新价、涨跌幅、PE/PB、市值、股息率。"
         "需要回答『当前股价/估值多少』时使用;若任务还需要财务或同行对比,请与 get_fundamentals/"
         "get_peer_valuation 在同一轮并行调用。参数 ticker 为 6 位 A 股代码,如 '600519'。"
         "返回含 as_of 数据时点,引用时必须注明。已成功返回过的 ticker 不必重复查询。"),
        {"type": "object",
         "properties": {"ticker": {"type": "string", "description": "6位A股代码,如 600519"}},
         "required": ["ticker"]},
        DATA.quote,
    )
    reg.register(
        "get_peer_valuation",
        ("获取同行业可比公司列表及行业平均 PE/PB,用于相对估值对标。"
         "回答『贵不贵/和同行比如何』必须先调用本工具,禁止凭记忆给行业均值。"),
        {"type": "object",
         "properties": {"ticker": {"type": "string", "description": "6位A股代码"}},
         "required": ["ticker"]},
        DATA.peers,
    )
    reg.register(
        "get_price_history",
        ("获取近 N 日收盘价序列,用于趋势/波动/回撤等技术面观察。"
         "默认 120 日。只做客观描述(区间涨跌幅、最大回撤),不预测未来走势。"),
        {"type": "object",
         "properties": {
             "ticker": {"type": "string"},
             "days": {"type": "integer", "description": "回看天数,默认120", "default": 120},
         },
         "required": ["ticker"]},
        DATA.price_history,
    )
    reg.register(
        "get_fundamentals",
        ("获取财务基本面:营收及增速、毛利率、净利率、ROE、负债率、现金流质量"
         "(经营现金流/净利润)、商誉占比、客户集中度、股东质押比例。"
         "做任何基本面判断前必须调用,数据报告期为 2026H1。"),
        {"type": "object",
         "properties": {"ticker": {"type": "string"}},
         "required": ["ticker"]},
        DATA.fundamentals,
    )
    reg.register(
        "get_news",
        ("获取个股近期新闻标题列表(带情绪标签)。用于了解事件面驱动,"
         "注意:新闻标题是线索不是结论,引用时保持中性转述。"),
        {"type": "object",
         "properties": {"ticker": {"type": "string"},
                        "limit": {"type": "integer", "description": "条数,默认5", "default": 5}},
         "required": ["ticker"]},
        DATA.news,
    )
    reg.register(
        "calc_financial_ratio",
        ("精确计算财务比率表达式,避免心算出错。expr 只支持 + - * / ( ) 和数字,"
         "如 '(52.8 - 45.1) / 45.1 * 100'。所有派生指标必须用本工具计算,禁止在文本里心算。"),
        {"type": "object",
         "properties": {"expr": {"type": "string", "description": "算术表达式"}},
         "required": ["expr"]},
        _calc_ratio,
    )
    reg.register(
        "search_knowledge",
        ("检索金融领域知识库(估值方法/财务分析/风险信号/行业框架)。"
         "遇到方法论问题(如『PE 和 PB 该用哪个』『质押率多高算危险』)应先检索再回答,"
         "而不是凭模型记忆。query 用自然语言。"),
        {"type": "object",
         "properties": {"query": {"type": "string"}},
         "required": ["query"]},
        _search_kb,
    )
    return reg


# ---- 纯计算工具(无外部依赖) ----
def _calc_ratio(expr: str) -> dict[str, Any]:
    """安全算术求值:白名单字符 + ast 编译,杜绝代码注入。"""
    import ast
    allowed = set("+-*/(). 0123456789")
    if not expr or set(expr) - allowed:
        return {"error": f"表达式含非法字符: {expr!r}", "allowed": "+ - * / ( ) 数字"}
    try:
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp,
                                     ast.Constant, ast.Add, ast.Sub, ast.Mult,
                                     ast.Div, ast.USub, ast.UAdd)):
                return {"error": "仅支持算术表达式"}
            if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
                return {"error": "仅支持数字常量"}
        val = eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, {})
        if isinstance(val, complex) or val != val or math_isinf(val):
            return {"error": "计算结果无效(除零或无穷)"}
        return {"expr": expr, "value": round(float(val), 4)}
    except ZeroDivisionError:
        return {"error": "除零错误"}
    except Exception as e:
        return {"error": f"解析失败: {e}"}


def math_isinf(x: float) -> bool:
    return x in (float("inf"), float("-inf"))


# ---- 知识检索工具(延迟绑定引擎,由 runner 注入) ----
_kb_engine = None


def bind_knowledge(engine) -> None:
    global _kb_engine
    _kb_engine = engine


def _search_kb(query: str) -> dict[str, Any]:
    if _kb_engine is None:
        return {"error": "知识引擎未初始化"}
    hits = _kb_engine.search(query)
    return {"query": query,
            "results": [{"id": h["card"]["id"], "topic": h["card"]["topic"],
                         "content": h["card"]["content"], "score": h["score"]} for h in hits]}


# ---- 供 price_history 衍生统计(内部使用) ----
def max_drawdown(prices: list[float]) -> float:
    peak = -1e18
    mdd = 0.0
    for p in prices:
        peak = max(peak, p)
        mdd = min(mdd, (p - peak) / peak)
    return mdd
