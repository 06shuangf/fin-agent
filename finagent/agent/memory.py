# -*- coding: utf-8 -*-
"""记忆系统:Memory。

短期记忆 = 当前任务的对话历史(含工具结果),由 Runner 维护。
长期记忆 = 跨任务沉淀的"研究结论",按股票代码归档,新任务自动注入相关记忆。
这是 Agent 从"每次从零开始"进化到"越用越聪明"的机制。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

_TICKER_RE = re.compile(r"\b([0-9]{6})\b|\b(SH[0-9]{6}|SZ[0-9]{6}|BK[0-9]{4})\b", re.IGNORECASE)


class Memory:
    """文件持久化的长期记忆,按 ticker 组织。"""

    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)

    # ---- 写 ----
    def remember(self, ticker: str, task_type: str, conclusion: str,
                 source: str = "agent") -> str:
        entry = {
            "id": f"m{int(time.time()*1000)%10**10:010d}",
            "ticker": ticker,
            "task_type": task_type,        # e.g. deep_research / valuation
            "conclusion": conclusion,      # 一句话沉淀结论
            "source": source,
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        path = self._path(ticker)
        data = self._load(ticker)
        data.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return entry["id"]

    # ---- 读 ----
    def recall(self, ticker: str, limit: int = 3) -> list[dict]:
        return self._load(ticker)[-limit:]

    def recall_for_task(self, task: str, limit_per_ticker: int = 2) -> list[dict]:
        """从任务文本中识别股票代码,召回相关历史结论。"""
        out: list[dict] = []
        seen = set()
        for m in _TICKER_RE.finditer(task):
            t = m.group(0).upper()
            if t in seen:
                continue
            seen.add(t)
            out.extend(self.recall(t, limit_per_ticker))
        return out

    # ---- 内部 ----
    def _path(self, ticker: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9]", "_", ticker)
        return os.path.join(self.root, f"{safe}.json")

    def _load(self, ticker: str) -> list[dict]:
        path = self._path(ticker)
        if not os.path.exists(path):
            return []
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return []
