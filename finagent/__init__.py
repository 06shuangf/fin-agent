# -*- coding: utf-8 -*-
"""FinResearchAgent — 金融研究 Agent

架构与 JD 三大职责的映射:
  agent/          Agent 核心能力建设 —— LLM 循环、工具调用链、Plan/Memory/Reflection
  knowledge/      金融知识工程     —— 规则库、知识库、RAG 检索、合规红线
  runtime/        系统工程化       —— 可观测性(trace)、容错、评测体系、质量门禁
"""

from .config import AgentConfig, load_config
from .agent.runner import AgentRunner
from .knowledge.engine import KnowledgeEngine

__all__ = ["AgentConfig", "load_config", "AgentRunner", "KnowledgeEngine"]
