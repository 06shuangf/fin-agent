# -*- coding: utf-8 -*-
"""全局配置:模型、循环上限、成本门禁。所有参数集中在一处,便于调参与评测。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    # ---- LM ----
    api_base: str = "https://token.pixdance.top/v1"
    api_key_env: str = "PIXDANCE_CHAT_KEY"
    model: str = "kimi-k3"            # 主模型:规划 / 工具调用 / 综述
    reviewer_model: str = "kimi-k3"   # 审阅模型(Reflection),可与主模型不同
    temperature: float | None = None  # None = 不传(部分模型如 kimi-k3 仅支持默认值)

    # ---- ReAct 循环 ----
    max_steps: int = 8                # 单次任务最大工具轮数(延迟/成本护栏)
    max_retries_per_tool: int = 1     # 工具失败重试上限
    max_reflect_loops: int = 1        # Review 不通过时最多重规划次数

    # ---- 成本门禁 ----
    max_total_tokens: int = 60000     # 单任务 token 预算,超出即熔断

    # ---- 延迟/成本优化 ----
    parallel_tools: bool = True        # 同一轮多个 tool_calls 并发执行
    observation_keep_full: int = 6     # 最近 K 条工具观测保留全文,更早的压缩为摘要
    review_digest_chars: int = 1800    # Reviewer 注入的工具观测摘要长度上限

    # ---- RAG ----
    rag_top_k: int = 4

    # ---- 路径 ----
    workspace_dir: str = "workspace"   # 记忆/报告落盘根目录

    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise RuntimeError(f"环境变量 {self.api_key_env} 未设置")
        return key


def load_config(**overrides) -> AgentConfig:
    cfg = AgentConfig()
    for k, v in overrides.items():
        if not hasattr(cfg, k):
            raise ValueError(f"未知配置项: {k}")
        setattr(cfg, k, v)
    return cfg
