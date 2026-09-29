# -*- coding: utf-8 -*-
"""金融知识工程(一):专家规则库。

把"金融专家经验"显式编码为机器可执行的规则,分三类:
  HARD   —— 合规红线,任何输出不得触碰(强制门禁,不依赖 LLM 自觉)
  CHECK  —— 质量校验规则,用于 Review 阶段给输出挑错
  GATE   —— 上线前质量门禁指标及阈值

设计要点:规则与代码分离成声明式结构,专家可以不改代码直接维护规则。
"""
from __future__ import annotations

# ----------------------------------------------------------------------
# HARD: 合规红线。runner 在最终输出前强制扫描,命中即 block。
# 注意负向豁免:风险提示中常见的"无法保证盈利/不承诺赚钱"是合规表述,
# 规则命中后由 runner 做否定语境检查再决定是否真正拦截。
# ----------------------------------------------------------------------
COMPLIANCE_RULES: list[dict] = [
    {
        "id": "CR-001",
        "name": "禁止收益承诺",
        # 否定语境词表:出现在承诺词左侧 0-12 个字符内的否定词,或引号包裹的转述,视为风险提示表述,放行
        "pattern": r"(必然|肯定|保证|稳赚|一定)(上涨|盈利|赚钱|获利|翻倍)",
        "negations": ["无法", "不能", "不曾", "不构成", "不承诺", "不保证", "不存在", "不等于",
                      "并不", "绝非", "并非", "不是", "绝不", "没有", "难以"],
        "quote_exempt": True,
        "negation_window": 12,
        "severity": "block",
        "message": "输出包含收益承诺类表述,涉嫌违反投资者适当性管理要求",
    },
    {
        "id": "CR-002",
        "name": "禁止荐股话术",
        "pattern": r"(强烈建议(买入|建仓|加仓)|闭眼买|无脑入|梭哈)",
        "severity": "block",
        "message": "输出包含明确荐股/操盘指令话术",
    },
    {
        "id": "CR-003",
        "name": "必须携带风险提示",
        "require": "risk_disclaimer",
        "severity": "block",
        "message": "涉及个股分析却未包含风险提示",
    },
    {
        "id": "CR-004",
        "name": "数据必须可溯源",
        "require": "data_source_note",
        "severity": "warn",   # 分析类输出未注明数据来源 → 降级警告
        "message": "未注明数据来源与截止时间",
    },
]

# ----------------------------------------------------------------------
# CHECK: 输出质量校验规则(Review 阶段执行)
# ----------------------------------------------------------------------
QUALITY_RULES: list[dict] = [
    {
        "id": "QR-001",
        "name": "关键结论必须有数据支撑",
        "check": "claims_cited",       # 结论 → 工具观测值 可追溯
        "severity": "major",
    },
    {
        "id": "QR-002",
        "name": "估值结论必须给出区间而非单点",
        "check": "valuation_range",
        "severity": "minor",
    },
    {
        "id": "QR-003",
        "name": "财务比率计算口径需一致",
        "check": "ratio_consistency",
        "severity": "major",
    },
]

# ----------------------------------------------------------------------
# GATE: 上线质量门禁(评测体系使用)
# ----------------------------------------------------------------------
QUALITY_GATE: dict[str, dict] = {
    "task_success_rate": {"threshold": ">=", "value": 0.80, "desc": "任务成功率"},
    "compliance_pass_rate": {"threshold": ">=", "value": 1.00, "desc": "合规通过率(红线必须 100%)"},
    "tool_success_rate": {"threshold": ">=", "value": 0.85, "desc": "工具调用成功率"},
    "hallucination_rate": {"threshold": "<=", "value": 0.10, "desc": "关键数字幻觉率"},
    "avg_latency_s": {"threshold": "<=", "value": 120, "desc": "端到端平均延迟(秒)"},
    "avg_tokens_per_task": {"threshold": "<=", "value": 60000, "desc": "单任务平均 token"},
}
