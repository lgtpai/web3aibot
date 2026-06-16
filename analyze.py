"""
analyze.py — 猎狗AI数据层

逻辑:
  1. fetch_live_price()  拉取代币实时价格 (本地 API → Binance fallback)
  2. get_token_analysis():
       - 支撑位: 推送记录倒序扫，第一条 price < 当前价 的点位
       - 压力位: 推送记录倒序扫，第一条 price > 当前价 的点位
       - 连推方向: 最新推送序列连涨/连跌次数
  3. get_market_prediction(): 大盘体制 + BTC/ETH 推送方向
"""

from __future__ import annotations
import json
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

# ── 路径 ─────────────────────────────────────────────────────────────────────
BASE         = Path(__file__).resolve().parent.parent.parent   # crypto_quant/
DB_PATH      = BASE / "data" / "lgai.db"
REGIME_PATH  = BASE / "data" / "regime_monitor" / "state.json"
LEADERS_PATH = BASE / "data" / "leaders_config.json"

MIN_PUSHES_FOR_SIGNAL = 2


# ══════════════════════════════════════════════════════════════════════════════
# 实时价格
# ══════════════════════════════════════════════════════════════════════════════

def fetch_live_price(token: str) -> Optional[float]:
    """
    获取代币当前实时价格.
    优先调本地 serve_v3 API (已有缓存), 失败则直接查 Binance 公开接口.
    """
    tok = token.strip().upper()

    # ① 本地 serve_v3 (lgai_live_prices)
    try:
        url = f"http://localhost:8899/api/lgai/live_prices?tokens={tok}"
        with urllib.request.urlopen(url, timeout=3) as r:
            d = json.loads(r.read())
            px = d.get("prices", {}).get(tok)
            if px is not None:
                return float(px)
    except Exception:
        pass

    # ② Binance 公开接口 fallback
    for symbol in (f"{tok}USDT", f"{tok}USDC"):
        try:
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            with urllib.request.urlopen(url, timeout=5) as r:
                d = json.loads(r.read())
                return float(d["price"])
        except Exception:
            continue

    return None


# ══════════════════════════════════════════════════════════════════════════════
# 体制 & 龙头
# ══════════════════════════════════════════════════════════════════════════════

def get_regime() -> dict:
    """
    读取大盘体制.
    btc_state / eth_state 优先从 serve_v3 /api/lgai 实时计算, 避免 state.json 陈旧.
    """
    # 基础字段从 state.json 读
    base: dict = {}
    try:
        if REGIME_PATH.exists():
            d = json.loads(REGIME_PATH.read_text())
            regime = int(d.get("regime", 0))
            base = {
                "regime": regime,
                "regime_label": {1: "🟢 牛市", -1: "🔴 熊市", 0: "⚪ 震荡"}.get(regime, "⚪ 震荡"),
                "regime_label_en": {1: "🟢 Bull", -1: "🔴 Bear", 0: "⚪ Neutral"}.get(regime, "⚪ Neutral"),
                "breadth": d.get("breadth"),
                "btc_state": d.get("btc_state"),
                "eth_state": d.get("eth_state"),
                "alt_breadth": d.get("alt_breadth"),
                "updated_at": d.get("ts") or d.get("updated_at"),
            }
    except Exception:
        pass

    if not base:
        base = {"regime": 0, "regime_label": "⚪ 震荡", "regime_label_en": "⚪ Neutral", "breadth": None,
                "btc_state": None, "eth_state": None, "alt_breadth": None, "updated_at": None}

    # 实时覆盖 btc_state / eth_state (serve_v3 每次调 lgai_regime.compute())
    try:
        url = "http://localhost:8899/api/lgai?symbols=BTC/USDT,ETH/USDT"
        with urllib.request.urlopen(url, timeout=3) as r:
            live = json.loads(r.read())
        syms = live.get("symbols") or live
        def _state_int(tok: str) -> int:
            s = (syms.get(f"{tok}/USDT") or {}).get("state", "")
            return 1 if s == "GREEN" else (-1 if s == "RED" else 0)
        base["btc_state"] = _state_int("BTC")
        base["eth_state"] = _state_int("ETH")
        # 实时龙头宽度 (bull/total 比例, 替换 stale state.json breadth)
        lb = live.get("leader_breadth") or {}
        lb_bull = lb.get("bull", 0)
        lb_total = lb.get("total", 0)
        if lb_total > 0:
            base["breadth"] = round((lb_bull / lb_total) - 0.5, 4)  # 转成 [-0.5, 0.5] 区间
            base["alt_breadth"] = base["breadth"]  # 同源
        # 也覆盖 regime (market_state 字段)
        ms = live.get("market_state") or {}
        if ms.get("state") == "BULL":
            base["regime"] = 1
            base["regime_label"] = "🟢 牛市"
            base["regime_label_en"] = "🟢 Bull"
        elif ms.get("state") == "BEAR":
            base["regime"] = -1
            base["regime_label"] = "🔴 熊市"
            base["regime_label_en"] = "🔴 Bear"
        # NEUTRAL / MIXED → 保留 state.json regime
    except Exception:
        pass  # 降级到 state.json 值

    return base


def get_leaders() -> set:
    try:
        if LEADERS_PATH.exists():
            return set(json.loads(LEADERS_PATH.read_text()).get("tokens", []))
    except Exception:
        pass
    return {"XMR","TAO","SOL","ETH","BTC","HYPE","INJ",
            "SUI","AAVE","LINK","BNB","XRP","TON","AVAX"}


# ══════════════════════════════════════════════════════════════════════════════
# 核心分析
# ══════════════════════════════════════════════════════════════════════════════

def get_token_analysis(token: str, live_price: Optional[float] = None) -> dict:
    """
    返回指定 token 的行情分析.

    支撑位: 推送记录倒序扫，遇到的第一条 price < 当前实时价 的点位
    压力位: 推送记录倒序扫，遇到的第一条 price > 当前实时价 的点位

    live_price 可由外部传入(测试/回测用), 否则自动拉取实时价.
    """
    tok = token.strip().upper()
    result: dict = {
        "token": tok,
        "found": False,
        "live_price": None,           # 当前实时价
        "live_price_source": None,    # "api" / "binance" / "latest_push"
        "push_count": 0,
        "latest_push": None,          # 最新推送价
        "latest_push_time": None,
        "support": None,              # 第一条低于当前价的推送
        "support_time": None,
        "resistance": None,           # 第一条高于当前价的推送
        "resistance_time": None,
        "run": 0,
        "direction": "中性",
        "direction_emoji": "⚪",
        "is_leader": tok in get_leaders(),
        "pushes": [],                 # 最近20条推送(详情用)
    }

    if not DB_PATH.exists():
        return result

    # ── 拉取全部推送 (按时间倒序, 去重) ─────────────────────────────────────
    try:
        con = sqlite3.connect(str(DB_PATH))
        rows = con.execute(
            "SELECT price, time FROM newcoins "
            "WHERE token=? AND price>0 "
            "GROUP BY time "          # 同一时间戳只取一条
            "ORDER BY time DESC",
            [tok]
        ).fetchall()
        con.close()
        # Python 层再按 (price, time) 去重，防止数据库数据异常
        seen: set = set()
        deduped = []
        for r in rows:
            key = (round(float(r[0]), 4), str(r[1]))
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        rows = deduped
    except Exception:
        return result

    if not rows:
        return result

    prices = [float(r[0]) for r in rows]
    times  = [r[1] for r in rows]

    result["found"] = True
    result["push_count"] = len(prices)
    result["latest_push"] = round(prices[0], 8)
    result["latest_push_time"] = times[0]
    result["pushes"] = [
        {"price": round(float(r[0]), 8), "time": r[1]} for r in rows[:20]
    ]

    # ── 实时价格 ──────────────────────────────────────────────────────────────
    if live_price is not None:
        cur = float(live_price)
        result["live_price_source"] = "provided"
    else:
        cur = fetch_live_price(tok)
        if cur is not None:
            result["live_price_source"] = "api"
        else:
            # fallback: 用最新推送价
            cur = prices[0]
            result["live_price_source"] = "latest_push"

    result["live_price"] = round(cur, 8)

    # ── 支撑位 & 压力位 ───────────────────────────────────────────────────────
    # 推送按时间倒序, 遇到第一条低于当前价 = 支撑, 第一条高于当前价 = 压力
    support = resistance = None
    support_time = resistance_time = None

    for p, t in zip(prices, times):
        if support is None and p < cur:
            support = round(p, 8)
            support_time = t
        if resistance is None and p > cur:
            resistance = round(p, 8)
            resistance_time = t
        if support is not None and resistance is not None:
            break

    result["support"] = support
    result["support_time"] = support_time
    result["resistance"] = resistance
    result["resistance_time"] = resistance_time

    # ── 连推方向 ──────────────────────────────────────────────────────────────
    if len(prices) >= MIN_PUSHES_FOR_SIGNAL:
        d = 1 if prices[0] >= prices[1] else -1
        run = 1
        for i in range(1, len(prices) - 1):
            nd = 1 if prices[i] >= prices[i + 1] else -1
            if nd == d:
                run += 1
            else:
                break
        result["run"] = run * d
        result["direction"] = "多" if d == 1 else "空"
        result["direction_emoji"] = "🟢" if d == 1 else "🔴"

    return result


# ══════════════════════════════════════════════════════════════════════════════
# 推送密度指标 (基于回测结论)
# ══════════════════════════════════════════════════════════════════════════════
# 历史五分位边界 (backtest_push_density 结论):
#   Q1(<12): 低密度，7日+2.49%，60%胜率
#   Q2(12-22): 略低，7日+1.93%
#   Q3(22-38): 中等，最差 -0.04%
#   Q4(38-56): 偏高，7日-0.95%
#   Q5(>56):  极高，7日+1.55%
# 加速度信号: MA7周环比骤降(>10) → 7日+5.25%（最强）

_PUSH_Q_BOUNDS = [0, 12, 22, 38, 56, 9999]
_PUSH_Q_LABELS = ["Q1低密度", "Q2", "Q3中等", "Q4偏高", "Q5极高"]
_PUSH_Q_SIGNAL = {
    "Q1低密度": ("🟢", "低密度蓄力期，历史7日+2.5%"),
    "Q2":       ("🟡", "偏低密度，历史7日+1.9%"),
    "Q3中等":   ("⚪", "中等密度分化期，历史7日持平"),
    "Q4偏高":   ("🔴", "中高密度，历史7日-1.0%，谨慎"),
    "Q5极高":   ("🟢", "极高密度动能期，历史7日+1.5%"),
}
_PUSH_Q_SIGNAL_EN = {
    "Q1低密度": "Low density buildup, hist. 7d +2.5%",
    "Q2":       "Below-avg density, hist. 7d +1.9%",
    "Q3中等":   "Mid density diverging, hist. 7d flat",
    "Q4偏高":   "Above-avg density, hist. 7d -1.0%, caution",
    "Q5极高":   "High density momentum, hist. 7d +1.5%",
}

def get_push_density_signal() -> dict:
    """当前推送密度信号."""
    try:
        con = sqlite3.connect(str(DB_PATH))
        # 最近7天每日推送数
        rows = con.execute(
            "SELECT date(time) as d, COUNT(*) as n FROM newcoins "
            "WHERE time >= date('now', '-14 days') AND price > 0 "
            "GROUP BY d ORDER BY d DESC LIMIT 14"
        ).fetchall()
        con.close()
    except Exception:
        return {"ma7": None, "quintile": None, "signal": "数据不可用", "signal_en": "Data unavailable", "accel": None}

    if not rows:
        return {"ma7": None, "quintile": None, "signal": "数据不足", "signal_en": "Insufficient data", "accel": None}

    daily = {r[0]: r[1] for r in rows}
    vals = list(daily.values())
    ma7  = round(sum(vals[:7]) / min(7, len(vals[:7])), 1)
    ma7_prev = round(sum(vals[7:14]) / min(7, len(vals[7:14])), 1) if len(vals) >= 8 else ma7
    accel = round(ma7 - ma7_prev, 1)

    # 分位
    q_label = _PUSH_Q_LABELS[-1]
    for i, bound in enumerate(_PUSH_Q_BOUNDS[1:]):
        if ma7 < bound:
            q_label = _PUSH_Q_LABELS[i]
            break

    emoji, desc = _PUSH_Q_SIGNAL[q_label]
    desc_en = _PUSH_Q_SIGNAL_EN[q_label]

    # 加速度叠加
    accel_note = ""
    accel_note_en = ""
    if accel <= -10:
        accel_note = " ⚡急剧减速，历史最强买点(7日+5.25%)"
        accel_note_en = " ⚡Sharp decel, strongest buy signal (7d +5.25%)"
    elif accel >= 10:
        accel_note = " 🚀急剧加速，历史7日+1.85%"
        accel_note_en = " 🚀Sharp accel, hist. 7d +1.85%"
    elif accel <= -3:
        accel_note = " ↘减速中"
        accel_note_en = " ↘Decelerating"
    elif accel >= 3:
        accel_note = " ↗加速中"
        accel_note_en = " ↗Accelerating"

    return {
        "ma7": ma7,
        "quintile": q_label,
        "accel": accel,
        "emoji": emoji,
        "signal": f"{emoji} {desc}{accel_note}",
        "signal_en": f"{emoji} {desc_en}{accel_note_en}",
        "today_pushes": vals[0] if vals else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 回调信号密度指标 (基于回测结论)
# ══════════════════════════════════════════════════════════════════════════════
# 回测结论:
#   7日内 back≥3次 → 7日+0.91%，胜率59%
#   back≥1 且 push_ma7<20 → 7日+1.05%，胜率61%（最强联合信号）
#   中等月(4-8次/月) → 月收益-4.62%（最危险）

def get_back_density_signal() -> dict:
    """最近7/30天回调信号密度."""
    try:
        con = sqlite3.connect(str(DB_PATH))
        rows_7 = con.execute(
            "SELECT COUNT(*) FROM back WHERE time >= datetime('now', '-7 days')"
        ).fetchone()[0]
        rows_30 = con.execute(
            "SELECT COUNT(*) FROM back WHERE time >= datetime('now', '-30 days')"
        ).fetchone()[0]
        con.close()
    except Exception:
        return {"back_7d": None, "back_30d": None, "signal": "back表不存在"}

    # 7日信号解读
    if rows_7 >= 3:
        b7_note = f"🟢 7日{rows_7}次回调，密集期历史胜率59%"
        b7_note_en = f"🟢 {rows_7} pullbacks in 7d — dense period, hist. win rate 59%"
    elif rows_7 == 0:
        b7_note = "⚪ 7日无回调信号"
        b7_note_en = "⚪ No pullback signals in 7d"
    else:
        b7_note = f"🟡 7日{rows_7}次回调，密度一般"
        b7_note_en = f"🟡 {rows_7} pullback(s) in 7d — average density"

    # 月度解读
    if rows_30 <= 3:
        m_note = "🟢 本月稀疏(≤3次)，历史最强月份"
        m_note_en = "🟢 Sparse month (≤3), historically strongest period"
    elif rows_30 <= 8:
        m_note = "🔴 本月中等(4-8次)，历史最弱月份，谨慎"
        m_note_en = "🔴 Mid-density month (4-8), historically weakest — caution"
    else:
        m_note = f"🟡 本月密集({rows_30}次)，历史胜率57%"
        m_note_en = f"🟡 Dense month ({rows_30}), hist. win rate 57%"

    return {
        "back_7d": rows_7,
        "back_30d": rows_30,
        "back_7d_note": b7_note,
        "back_7d_note_en": b7_note_en,
        "back_30d_note_en": m_note_en,
        "back_30d_note": m_note,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 大盘预测
# ══════════════════════════════════════════════════════════════════════════════

def get_market_prediction() -> dict:
    regime = get_regime()
    r = regime["regime"]
    direction = {1: "多", -1: "空"}.get(r, "中性")
    emoji     = {1: "🟢", -1: "🔴"}.get(r, "⚪")

    btc = get_token_analysis("BTC")
    eth = get_token_analysis("ETH")
    density = get_push_density_signal()
    back    = get_back_density_signal()

    # 联合信号: back近7日≥1 且 推送低密度
    joint_signal = (
        (back.get("back_7d") or 0) >= 1 and
        (density.get("ma7") or 99) < 20
    )

    return {
        "direction": direction,
        "direction_emoji": emoji,
        "regime": r,
        "regime_label": regime["regime_label"],
        "regime_label_en": regime.get("regime_label_en", "⚪ Neutral"),
        "breadth": regime["breadth"],
        "btc_state": regime["btc_state"],
        "eth_state": regime["eth_state"],
        "alt_breadth": regime["alt_breadth"],
        "btc_run": btc["run"],
        "eth_run": eth["run"],
        "updated_at": regime["updated_at"],
        # 密度指标
        "push_density": density,
        "back_density": back,
        "joint_signal": joint_signal,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 格式化
# ══════════════════════════════════════════════════════════════════════════════

def fmt_price(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v >= 1000:
        return f"${v:,.2f}"
    if v >= 1:
        return f"${v:.4f}"
    return f"${v:.6f}"


def trend_label(run: int) -> str:
    if run >= 3:   return f"强多头 +{run}连涨"
    if run == 2:   return f"多头确认 +{run}连涨"
    if run == 1:   return "多头初现 +1连涨"
    if run == -1:  return "空头初现 -1连跌"
    if run == -2:  return f"空头确认 {run}连跌"
    if run <= -3:  return f"强空头 {run}连跌"
    return "无明确趋势"


def trend_label_en(run: int) -> str:
    if run >= 3:   return f"Strong Bull +{run} streak"
    if run == 2:   return f"Bull Confirmed +{run} streak"
    if run == 1:   return "Bull Emerging +1 streak"
    if run == -1:  return "Bear Emerging -1 streak"
    if run == -2:  return f"Bear Confirmed {run} streak"
    if run <= -3:  return f"Strong Bear {run} streak"
    return "No clear trend"
