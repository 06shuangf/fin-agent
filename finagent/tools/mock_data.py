# -*- coding: utf-8 -*-
"""模拟金融数据源(确定性伪随机,保证评测可复现)。

真实生产环境此处替换为 Wind/聚宽/Tushare 等行情与财务 API。
工具层只依赖这里的统一接口,切换数据源不动工具代码。
"""
from __future__ import annotations

import hashlib
import math
from typing import Any

# 种子公司池:覆盖不同行业,用于构造有区分度的数据
UNIVERSE: dict[str, dict[str, Any]] = {
    "600519": {"name": "贵州茅台", "industry": "白酒", "price": 1520.0, "pe": 22.5, "pb": 7.8,
               "market_cap": 1.9e12, "dividend_yield": 3.1},
    "000858": {"name": "五粮液", "industry": "白酒", "price": 128.0, "pe": 15.2, "pb": 3.6,
               "market_cap": 4.9e11, "dividend_yield": 4.2},
    "601318": {"name": "中国平安", "industry": "保险", "price": 52.0, "pe": 9.1, "pb": 1.05,
               "market_cap": 9.5e11, "dividend_yield": 5.0},
    "600036": {"name": "招商银行", "industry": "银行", "price": 35.0, "pe": 5.8, "pb": 0.88,
               "market_cap": 8.8e11, "dividend_yield": 5.3},
    "300750": {"name": "宁德时代", "industry": "锂电", "price": 185.0, "pe": 18.0, "pb": 3.2,
               "market_cap": 8.1e11, "dividend_yield": 0.6},
    "601012": {"name": "隆基绿能", "industry": "光伏", "price": 14.2, "pe": None, "pb": 1.9,
               "market_cap": 1.08e11, "dividend_yield": 0.0},       # 亏损 → pe=None
    "002594": {"name": "比亚迪", "industry": "汽车", "price": 245.0, "pe": 20.1, "pb": 4.1,
               "market_cap": 7.1e11, "dividend_yield": 1.2},
    "688981": {"name": "中芯国际", "industry": "半导体", "price": 52.8, "pe": 88.0, "pb": 4.9,
               "market_cap": 4.2e11, "dividend_yield": 0.3},
}


def _seeded(ticker: str, salt: str) -> float:
    """确定性伪随机:同 ticker+salt 永远同值 → 评测可复现。"""
    h = hashlib.md5(f"{ticker}:{salt}".encode()).digest()
    return (int.from_bytes(h[:4], "big") % 10000) / 10000.0  # [0,1)


class MarketData:
    """统一数据接口(生产实现替换此类)。"""

    # ---- 行情 ----
    def quote(self, ticker: str) -> dict[str, Any]:
        base = UNIVERSE.get(ticker)
        if not base:
            return {"error": f"未知代码 {ticker}", "known": list(UNIVERSE)}
        r = _seeded(ticker, "chg")
        return {
            "ticker": ticker, "name": base["name"], "industry": base["industry"],
            "price": round(base["price"] * (0.96 + 0.08 * r), 2),
            "change_pct": round((r - 0.5) * 6, 2),
            "pe_ttm": base["pe"], "pb": base["pb"],
            "market_cap_cny": base["market_cap"],
            "dividend_yield_pct": base["dividend_yield"],
            "as_of": "2026-09-21",
        }

    def peers(self, ticker: str) -> dict[str, Any]:
        base = UNIVERSE.get(ticker)
        if not base:
            return {"error": f"未知代码 {ticker}"}
        same = [t for t, v in UNIVERSE.items()
                if v["industry"] == base["industry"] and t != ticker]
        rows = []
        for t in same:
            v = UNIVERSE[t]
            rows.append({"ticker": t, "name": v["name"],
                         "pe_ttm": v["pe"], "pb": v["pb"],
                         "dividend_yield_pct": v["dividend_yield"]})
        pes = [r["pe_ttm"] for r in rows if r["pe_ttm"]]
        pbs = [r["pb"] for r in rows if r["pb"]]
        return {
            "industry": base["industry"],
            "peers": rows,
            "industry_avg_pe": round(sum(pes) / len(pes), 2) if pes else None,
            "industry_avg_pb": round(sum(pbs) / len(pbs), 2) if pbs else None,
            "as_of": "2026-09-21",
        }

    def price_history(self, ticker: str, days: int = 120) -> list[dict]:
        q = self.quote(ticker)
        if "error" in q:
            return []
        out = []
        p = q["price"]
        for i in range(days, 0, -1):
            r = _seeded(ticker, f"d{i}")
            drift = (r - 0.5) * 0.03
            p = max(0.5, p * (1 - drift))
            out.append({"days_ago": i, "close": round(p, 2)})
        out.reverse()
        return out

    # ---- 财务 ----
    def fundamentals(self, ticker: str) -> dict[str, Any]:
        base = UNIVERSE.get(ticker)
        if not base:
            return {"error": f"未知代码 {ticker}"}
        r1 = _seeded(ticker, "fin1")
        return {
            "ticker": ticker, "name": base["name"],
            "revenue_cny": round(5e10 * (0.5 + r1 * 3), 0),
            "revenue_yoy_pct": round((r1 - 0.4) * 40, 1),
            "gross_margin_pct": round(25 + r1 * 45, 1),
            "net_margin_pct": round(6 + r1 * 22, 1),
            "roe_pct": round(4 + r1 * 26, 1),
            "debt_ratio_pct": round(28 + r1 * 42, 1),
            "current_ratio": round(0.8 + r1 * 2.2, 2),
            "ocf_to_net_profit": round(0.4 + r1 * 1.2, 2),
            "goodwill_to_asset_pct": round(r1 * 18, 1),
            "top1_customer_pct": round(8 + r1 * 55, 1),
            "major_holder_pledge_pct": round(r1 * 65, 1),
            "report_period": "2026H1",
        }

    def news(self, ticker: str, limit: int = 5) -> list[dict]:
        base = UNIVERSE.get(ticker)
        if not base:
            return []
        pool = [
            {"date": "2026-09-15", "title": f"{base['name']}发布2026年半年报,营收同比变动符合预期",
             "sentiment": "neutral"},
            {"date": "2026-09-10", "title": f"{base['industry']}行业需求侧出现改善信号,机构调研频次上升",
             "sentiment": "positive"},
            {"date": "2026-09-02", "title": f"{base['name']}宣布新的产能扩张计划,资本开支加大",
             "sentiment": "neutral"},
            {"date": "2026-08-25", "title": f"券商研报对{base['industry']}板块观点出现分歧",
             "sentiment": "mixed"},
            {"date": "2026-08-18", "title": f"{base['name']}股东质押比例引起市场关注",
             "sentiment": "negative"},
        ][:limit]
        return pool
