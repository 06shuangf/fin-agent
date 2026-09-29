# -*- coding: utf-8 -*-
"""知识引擎统一入口:RAG 检索 + 合规规则扫描。"""
from __future__ import annotations

from ..config import AgentConfig
from .kb import KnowledgeEngine
from .rules import COMPLIANCE_RULES, QUALITY_GATE, QUALITY_RULES

__all__ = ["KnowledgeEngine", "COMPLIANCE_RULES", "QUALITY_RULES", "QUALITY_GATE"]


def build_engine(cfg: AgentConfig) -> KnowledgeEngine:
    return KnowledgeEngine(top_k=cfg.rag_top_k)
