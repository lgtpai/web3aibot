"""
analyze.py — 猎狗AI数据接口层（公开 stub 版本）

本文件定义了 server.py 所需的接口契约。
自部署时请替换为连接你自己数据源的实现。
"""

from __future__ import annotations


def get_token_analysis(token: str) -> dict:
    """返回指定代币分析结果（stub，请替换为真实数据逻辑）。"""
    return {
        "found": False,
        "token": token,
        "direction": "震荡",
        "direction_emoji": "➡️",
        "run_label": "",
        "latest_price": None,
        "latest_push": None,
        "push_count": 0,
        "is_leader": False,
        "reversal_pct": None,
        "support": None,
        "support_time": None,
        "resistance": None,
        "resistance_time": None,
        "range_pct": "—",
        "market_regime_label": "—",
        "signals": [],
        "message": "请实现 analyze.py 中的数据逻辑",
    }


def get_market_prediction() -> dict:
    """返回大盘总览（stub）。"""
    return {
        "direction": "震荡",
        "direction_emoji": "➡️",
        "regime_label": "震荡",
        "regime": "neutral",
        "breadth": None,
        "btc_state_label": "—",
        "eth_state_label": "—",
        "overall": "请实现 analyze.py 中的数据逻辑",
        "interpretations": [],
    }


def get_regime() -> dict:
    return {"regime": "neutral", "regime_label": "震荡"}


def fmt_price(price) -> str:
    if price is None:
        return "—"
    p = float(price)
    if p >= 10000:
        return f"${p:,.2f}"
    if p >= 1:
        return f"${p:.4f}"
    return f"${p:.6f}"


def trend_label(n: int) -> str:
    if n >= 3:
        return f"连涨{n}次"
    if n <= -3:
        return f"连跌{abs(n)}次"
    return ""
