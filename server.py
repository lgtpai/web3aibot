"""
server.py — 猎狗AI Pharos Skill 主服务
Port: 8402 (与主面板 :8899 独立)

启动:
    cd skills/lgai_pharos
    LGAI_RECIPIENT_ADDRESS=0xYOUR_ADDR uvicorn server:app --host 0.0.0.0 --port 8402

端点:
  免费 (无需支付):
    GET /predict/{token}       → 多空方向
    GET /market                → 大盘多空方向
    GET /.well-known/agent-card.json
    GET /.well-known/mcp.json
    GET /.well-known/x402
    GET /health

  付费 (x402, 0.1 USDC Pharos测试网):
    GET /predict/{token}/detail → 支撑位/压力位/趋势/入场建议
    GET /market/detail          → 大盘详情 breadth/BTC/ETH/alt
"""

from __future__ import annotations
import json
import sqlite3
import time
import hashlib
import secrets
import os
from pathlib import Path

# 加载 .env（优先级低于已有环境变量）
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            import os as _os
            _os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from analyze import (
    get_token_analysis, get_market_prediction, get_regime,
    fmt_price, trend_label
)
from x402 import (
    payment_required_response, verify_payment, settle_payment,
    payment_requirements, PRICE_DETAIL, PRICE_MARKET,
    CHAIN_ID, USDC_ADDRESS, RECIPIENT, SKILL_BASE_URL
)

SKILL_DIR = Path(__file__).parent
WELL_KNOWN_DIR = SKILL_DIR / "well-known"
STATIC_DIR = SKILL_DIR / "static"
PROJECT_DIR = SKILL_DIR.parent.parent
SUB_DB_PATH = PROJECT_DIR / "data" / "lgai_subscriptions.db"

# ── 订阅计划 (USDC 6位精度) ───────────────────────────────────────────────────
# 金额单位: PHRS wei (18位小数), price 字段是展示用字符串
PLANS = {
    "per_query": {"wei":   180_000_000_000_000_000, "seconds": 3600,        "label": "按次",   "price": "0.18", "discount": ""},
    "weekly":    {"wei":  23_000_000_000_000_000_000, "seconds": 7*86400,   "label": "周卡",   "price": "23",   "discount": "无折扣"},
    "monthly":   {"wei":  93_000_000_000_000_000_000, "seconds": 30*86400,  "label": "月卡",   "price": "93",   "discount": "95折"},
    "quarterly": {"wei": 260_000_000_000_000_000_000, "seconds": 90*86400,  "label": "季卡",   "price": "260",  "discount": "88折"},
    "biannual":  {"wei": 508_000_000_000_000_000_000, "seconds": 180*86400, "label": "半年卡", "price": "508",  "discount": "86折"},
    "annual":    {"wei": 888_000_000_000_000_000_000, "seconds": 365*86400, "label": "年卡",   "price": "888",  "discount": "75折"},
}

# ── 订阅会话 secret (进程级, 重启后旧 token 失效) ──────────────────────────────
_SESSION_SECRET = os.environ.get("LGAI_SESSION_SECRET") or secrets.token_hex(32)


def _init_sub_db() -> None:
    """初始化订阅数据库."""
    SUB_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(SUB_DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wallet TEXT NOT NULL,
            plan TEXT NOT NULL,
            expires_at INTEGER NOT NULL,
            tx_hash TEXT,
            created_at INTEGER NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        )
    """)
    # 迁移: 旧表无 used 列时补加
    try:
        con.execute("ALTER TABLE subscriptions ADD COLUMN used INTEGER NOT NULL DEFAULT 0")
    except Exception:
        pass
    con.commit()
    con.close()


def _get_active_sub(wallet: str) -> dict | None:
    """返回钱包的最新有效订阅, 无则 None.
    per_query 计划额外要求 used=0 (未消耗).
    """
    now = int(time.time())
    try:
        con = sqlite3.connect(str(SUB_DB_PATH))
        row = con.execute(
            "SELECT plan, expires_at FROM subscriptions"
            " WHERE wallet=? AND expires_at>?"
            "   AND (plan != 'per_query' OR used=0)"
            " ORDER BY expires_at DESC LIMIT 1",
            [wallet.lower(), now]
        ).fetchone()
        con.close()
        if row:
            return {"plan": row[0], "expires_at": row[1]}
    except Exception:
        pass
    return None


def _make_token(wallet: str, expires_at: int) -> str:
    data = f"{wallet.lower()}:{expires_at}:{_SESSION_SECRET}"
    return hashlib.sha256(data.encode()).hexdigest()[:40]


def _verify_token(wallet: str, token: str) -> bool:
    """验证 session token.
    per_query 计划要求 used=0; 其他计划只要 expires_at 未过期即可.
    """
    now = int(time.time())
    try:
        con = sqlite3.connect(str(SUB_DB_PATH))
        rows = con.execute(
            "SELECT expires_at FROM subscriptions"
            " WHERE wallet=? AND expires_at>?"
            "   AND (plan != 'per_query' OR used=0)"
            " ORDER BY expires_at DESC LIMIT 10",
            [wallet.lower(), now]
        ).fetchall()
        con.close()
        for (exp,) in rows:
            if token == _make_token(wallet, exp):
                return True
    except Exception:
        pass
    return False


def _consume_per_query(wallet: str, token: str) -> None:
    """将 per_query 订阅标记为已使用 (used=1), 使 token 立即失效."""
    now = int(time.time())
    try:
        con = sqlite3.connect(str(SUB_DB_PATH))
        rows = con.execute(
            "SELECT id, expires_at FROM subscriptions"
            " WHERE wallet=? AND plan='per_query' AND used=0 AND expires_at>?"
            " ORDER BY expires_at DESC LIMIT 10",
            [wallet.lower(), now]
        ).fetchall()
        for row_id, exp in rows:
            if token == _make_token(wallet, exp):
                con.execute("UPDATE subscriptions SET used=1 WHERE id=?", [row_id])
                con.commit()
                break
        con.close()
    except Exception:
        pass


async def _check_access(request: Request) -> tuple[bool, str | None, bool, str, str]:
    """验证访问权限.
    Returns (verified, error_msg, is_session_token, wallet, session_token).
    先检查订阅 session token, 再回退到 x402.
    """
    wallet = request.headers.get("X-Wallet-Address", "").lower().strip()
    token = request.headers.get("X-Session-Token", "").strip()
    if wallet and token and _verify_token(wallet, token):
        return True, None, True, wallet, token
    verified, err = await verify_payment(request)
    return verified, err, False, wallet, token


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="猎狗AI行情技能",
    description="Pharos x402 — 加密行情预测 · 支撑压力位 · 多空方向",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-PAYMENT-REQUIRED", "X-PAYMENT-RESPONSE"],
)

# 静态文件 & 初始化
STATIC_DIR.mkdir(exist_ok=True)
_init_sub_db()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ══════════════════════════════════════════════════════════════════════════════
# 健康 & 发现端点
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {"status": "ok", "skill": "lgai-pharos", "version": "1.0.0"}


@app.get("/api/history/{wallet}")
def api_history(wallet: str, limit: int = 50):
    """返回钱包的消费历史（购买 + 使用记录）。"""
    w = wallet.lower().strip()
    try:
        con = sqlite3.connect(str(SUB_DB_PATH))
        rows = con.execute(
            "SELECT id, plan, expires_at, tx_hash, created_at, used"
            " FROM subscriptions WHERE wallet=?"
            " ORDER BY created_at DESC LIMIT ?",
            [w, limit]
        ).fetchall()
        con.close()
        records = []
        for row_id, plan, expires_at, tx_hash, created_at, used in rows:
            plan_info = PLANS.get(plan, {})
            records.append({
                "id": row_id,
                "plan": plan,
                "plan_label": plan_info.get("label", plan),
                "price": plan_info.get("price", "?"),
                "created_at": created_at,
                "created_readable": time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at)),
                "expires_at": expires_at,
                "expires_readable": time.strftime("%Y-%m-%d %H:%M", time.localtime(expires_at)),
                "tx_hash": tx_hash or "",
                "used": used,
                # per_query: used=1 表示已消费；其他: 看 expires_at
                "status": (
                    "已使用" if plan == "per_query" and used == 1
                    else "待使用" if plan == "per_query" and used == 0
                    else "已过期" if expires_at < int(time.time())
                    else "有效"
                ),
            })
        return JSONResponse({"ok": True, "records": records})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "records": []})


@app.get("/api/tokens")
def api_tokens():
    """返回所有有记录的币种符号列表，供前端联想。"""
    try:
        from analyze import DB_PATH
        con = sqlite3.connect(str(DB_PATH))
        rows = con.execute(
            "SELECT DISTINCT token FROM newcoins WHERE price>0 ORDER BY token"
        ).fetchall()
        con.close()
        return JSONResponse({"tokens": [r[0] for r in rows]})
    except Exception as e:
        return JSONResponse({"tokens": [], "error": str(e)})


@app.get("/.well-known/agent-card.json")
def agent_card():
    f = WELL_KNOWN_DIR / "agent-card.json"
    return JSONResponse(json.loads(f.read_text()))


@app.get("/.well-known/mcp.json")
def mcp_manifest():
    f = WELL_KNOWN_DIR / "mcp.json"
    return JSONResponse(json.loads(f.read_text()))


@app.get("/.well-known/x402")
def x402_discovery():
    """列出所有付费资源及定价 (x402 发现端点)."""
    return JSONResponse({
        "x402Version": 1,
        "resources": [
            {
                "path": "/predict/{token}/detail",
                "description": "币种详细分析: 支撑位/压力位/趋势/入场建议",
                "mimeType": "application/json",
                "pricing": payment_requirements(
                    f"{SKILL_BASE_URL}/predict/TOKEN/detail",
                    "详细行情分析",
                    PRICE_DETAIL
                )["accepts"][0]
            },
            {
                "path": "/market/detail",
                "description": "大盘详细预测: BTC/ETH状态/宽度/山寨体制",
                "mimeType": "application/json",
                "pricing": payment_requirements(
                    f"{SKILL_BASE_URL}/market/detail",
                    "大盘详细预测",
                    PRICE_MARKET
                )["accepts"][0]
            }
        ]
    })


# ── 仪表盘 ────────────────────────────────────────────────────────────────────

@app.get("/")
def dashboard():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return FileResponse(str(html_path))
    return JSONResponse({"error": "Dashboard not found"}, status_code=404)


# ══════════════════════════════════════════════════════════════════════════════
# 订阅 API
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/plans")
def api_plans():
    """返回所有订阅计划及收款地址."""
    return JSONResponse({
        "plans": {k: {**v, "display": f"{v['price']} PHRS"} for k, v in PLANS.items()},
        "recipient": RECIPIENT,
        "token": "PHRS",
        "token_decimals": 18,
        "chain_id": CHAIN_ID,
        "rpc_url": "https://atlantic.dplabs-internal.com",
    })


@app.post("/api/subscribe")
async def api_subscribe(request: Request):
    """记录订阅付款, 返回 session_token.
    per_query 支持 quantity 批量购买多次查询.
    """
    body = await request.json()
    wallet = str(body.get("wallet", "")).lower().strip()
    plan = str(body.get("plan", "")).strip()
    tx_hash = str(body.get("tx_hash", "")).strip()
    quantity = max(1, min(50, int(body.get("quantity", 1))))

    if not wallet or not plan:
        return JSONResponse({"ok": False, "error": "wallet 和 plan 必填"}, status_code=400)
    if plan not in PLANS:
        return JSONResponse({"ok": False, "error": f"未知计划: {plan}"}, status_code=400)

    plan_info = PLANS[plan]
    now = int(time.time())
    # per_query: 每批次统一 expires_at = 现在 + 7天（给充足时间用完），gate 是 used=0
    # 其他计划: expires_at = 订阅时长
    if plan == "per_query":
        expires_at = now + 90 * 86400  # 点数90天内有效，gate 是 used=0
    else:
        expires_at = now + plan_info["seconds"]
        quantity = 1  # 非按次计划忽略 quantity

    con = sqlite3.connect(str(SUB_DB_PATH))
    for _ in range(quantity):
        con.execute(
            "INSERT INTO subscriptions (wallet, plan, expires_at, tx_hash, created_at, used) VALUES (?,?,?,?,?,0)",
            [wallet, plan, expires_at, tx_hash or None, now]
        )
    con.commit()
    con.close()

    session_token = _make_token(wallet, expires_at)

    resp: dict = {
        "ok": True,
        "plan": plan,
        "plan_label": plan_info["label"],
        "session_token": session_token,
        "wallet": wallet,
    }
    if plan == "per_query":
        resp["remaining_queries"] = quantity
        resp["quantity"] = quantity
    else:
        resp["expires_at"] = expires_at
        resp["expires_readable"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(expires_at))
    return JSONResponse(resp)


@app.get("/api/subscription/{wallet}")
def api_subscription(wallet: str, token: str = ""):
    """查询钱包订阅状态, 可选 token 验证.
    per_query 计划返回 remaining_queries (未使用次数).
    """
    w = wallet.lower().strip()
    now = int(time.time())
    sub = _get_active_sub(w)
    con = sqlite3.connect(str(SUB_DB_PATH))

    if not sub:
        # 检查 per_query 剩余次数
        row = con.execute(
            "SELECT expires_at FROM subscriptions"
            " WHERE wallet=? AND plan='per_query' AND used=0 AND expires_at>?"
            " ORDER BY expires_at DESC LIMIT 1",
            [w, now]
        ).fetchone()
        remaining = con.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE wallet=? AND plan='per_query' AND used=0 AND expires_at>?",
            [w, now]
        ).fetchone()[0]
        con.close()
        if remaining > 0 and row:
            # 直接返回重建的 session_token，让任何设备连接钱包后都能直接使用
            session_token = _make_token(w, row[0])
            return JSONResponse({
                "active": True,
                "plan": "per_query",
                "plan_label": PLANS["per_query"]["label"],
                "remaining_queries": remaining,
                "session_token": session_token,
                "token_valid": True,
            })
        return JSONResponse({"active": False})

    # 有活跃订阅：重建 session_token
    session_token = _make_token(w, sub["expires_at"])
    resp: dict = {
        "active": True,
        "plan": sub["plan"],
        "plan_label": PLANS.get(sub["plan"], {}).get("label", sub["plan"]),
        "session_token": session_token,
        "token_valid": True,
    }
    if sub["plan"] == "per_query":
        remaining = con.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE wallet=? AND plan='per_query' AND used=0 AND expires_at>?",
            [w, now]
        ).fetchone()[0]
        resp["remaining_queries"] = remaining
    else:
        resp["expires_at"] = sub["expires_at"]
        resp["expires_readable"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(sub["expires_at"]))
    con.close()
    return JSONResponse(resp)


# ══════════════════════════════════════════════════════════════════════════════
# 免费端点
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/predict/{token}")
def predict_token_free(token: str):
    """
    【免费】币种多空方向查询
    返回: token, direction, direction_emoji, run, latest_price, is_leader
    付费解锁: /predict/{token}/detail
    """
    tok = token.strip().upper()
    d = get_token_analysis(tok)

    if not d["found"]:
        return JSONResponse({
            "token": tok,
            "found": False,
            "message": f"暂无 {tok} 的推送数据，请确认币种符号是否正确。",
            "upgrade_url": f"/predict/{tok}/detail"
        })

    return JSONResponse({
        "token": tok,
        "found": True,
        "direction": d["direction"],
        "direction_emoji": d["direction_emoji"],
        "run": d["run"],
        "run_label": trend_label(d["run"]),
        "latest_price": d["live_price"],
        "latest_push": d["latest_push"],
        "is_leader": d["is_leader"],
        "push_count": d["push_count"],
        "message": (
            f"{tok} 当前方向: {d['direction_emoji']} {d['direction']} "
            f"({trend_label(d['run'])}) · 实时价 {fmt_price(d['live_price'])} · 最新推送 {fmt_price(d['latest_push'])}"
        ),
        "upgrade_hint": "支撑位/压力位/入场建议请 POST /predict/{}/detail (需 x402 支付 0.1 USDC)".format(tok)
    })


@app.get("/market")
def market_free():
    """
    【免费】大盘多空方向 (LGAI 推土机体制)
    详情请访问 /market/detail (付费)
    """
    m = get_market_prediction()
    return JSONResponse({
        "direction": m["direction"],
        "direction_emoji": m["direction_emoji"],
        "regime_label": m["regime_label"],
        "message": (
            f"大盘当前体制: {m['direction_emoji']} {m['regime_label']} · "
            f"BTC推送 {'+' if m['btc_run'] > 0 else ''}{m['btc_run']}连"
            if m["btc_run"] != 0 else
            f"大盘当前体制: {m['direction_emoji']} {m['regime_label']}"
        ),
        "upgrade_hint": "详细分析(BTC/ETH状态/宽度/山寨体制)请访问 /market/detail (x402 支付 0.1 USDC)"
    })


# ══════════════════════════════════════════════════════════════════════════════
# 付费端点 (x402)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/predict/{token}/detail")
async def predict_token_detail(token: str, request: Request):
    """
    【付费 0.1 USDC / x402】币种详细分析
    - 支撑位 (最近推送最低价)
    - 压力位 (最近推送最高价)
    - 趋势强度 & 连推次数
    - 龙头身份判断
    - 入场建议 (仅参考, 非投资建议)
    """
    tok = token.strip().upper()

    # ── 验证 (订阅 session token 或 x402) ────────────────────────────────────
    verified, err, is_session, s_wallet, s_token = await _check_access(request)
    if not verified:
        return payment_required_response(
            request,
            f"{tok} 详细行情分析 (支撑/压力/趋势/建议)",
            PRICE_DETAIL
        )

    # ── 分析 ──────────────────────────────────────────────────────────────────
    d = get_token_analysis(tok)
    regime = get_regime()

    if not d["found"]:
        if not is_session:
            await settle_payment(request)
        else:
            _consume_per_query(s_wallet, s_token)
        return JSONResponse({
            "token": tok,
            "found": False,
            "message": f"暂无 {tok} 的推送数据，请确认币种符号是否正确。"
        })

    # 入场建议逻辑
    run = d["run"]
    market_regime = regime["regime"]
    advice_parts = []

    if run >= 2:
        advice_parts.append(f"✅ 连涨 +{run} 次，多头信号有效")
        if market_regime == 1:
            advice_parts.append("✅ 大盘牛市体制，多头方向共振")
            entry_advice = f"可考虑在支撑位 {fmt_price(d['support'])} 附近做多"
        elif market_regime == -1:
            advice_parts.append("⚠️ 大盘熊市体制，逆势做多需谨慎")
            entry_advice = "建议等待大盘体制转正后再介入"
        else:
            entry_advice = f"支撑位(前次推送) {fmt_price(d['support'])} 做多，目标压力位(最近高点) {fmt_price(d['resistance'])}"
    elif run <= -2:
        advice_parts.append(f"✅ 连跌 {run} 次，空头信号有效")
        if market_regime == 1:
            advice_parts.append("⚠️ 大盘牛市体制，做空风险较高")
            entry_advice = "牛市体制不建议做空，等待反弹后顺势做多"
        elif market_regime == -1:
            advice_parts.append("✅ 大盘熊市体制，空头方向共振")
            entry_advice = f"可考虑在压力位(最近高点) {fmt_price(d['resistance'])} 附近做空，支撑位(前次推送) {fmt_price(d['support'])} 止损参考"
        else:
            entry_advice = f"压力位 {fmt_price(d['resistance'])} 做空，止损参考支撑位 {fmt_price(d['support'])}"
    else:
        entry_advice = "信号不足（连推 <2次），建议观望等待趋势确认"

    # 支撑压力区间
    if d["support"] and d["resistance"] and d["support"] > 0:
        range_pct = round((d["resistance"] / d["support"] - 1) * 100, 2)
        range_str = f"区间幅度 {range_pct}%"
    else:
        range_str = ""

    result = {
        "token": tok,
        "found": True,
        "is_leader": d["is_leader"],

        # 核心数据
        "live_price": d["live_price"],
        "live_price_fmt": fmt_price(d["live_price"]),
        "latest_push": d["latest_push"],
        "latest_push_time": d["latest_push_time"],

        # 支撑压力
        "support": d["support"],
        "support_fmt": fmt_price(d["support"]),
        "support_time": d.get("support_time"),
        "resistance": d["resistance"],
        "resistance_fmt": fmt_price(d["resistance"]) if d["resistance"] else "—(当前处于历史推送高位)",
        "resistance_time": d.get("resistance_time"),
        "range_pct": range_str,

        # 趋势
        "direction": d["direction"],
        "direction_emoji": d["direction_emoji"],
        "run": run,
        "run_label": trend_label(run),
        "push_count": d["push_count"],

        # 大盘背景
        "market_regime": market_regime,
        "market_regime_label": regime["regime_label"],

        # 建议 (仅供参考)
        "signals": advice_parts,
        "entry_advice": entry_advice,
        "disclaimer": "以上分析基于推送数据统计，仅供参考，不构成投资建议。",

        # 近期推送 (最新5条)
        "recent_pushes": d["pushes"][:5],
    }

    if not is_session:
        await settle_payment(request)
    else:
        _consume_per_query(s_wallet, s_token)
    return JSONResponse(result)


@app.get("/market/detail")
async def market_detail(request: Request):
    """
    【付费 0.1 USDC / x402】大盘详细预测
    - 推土机体制 (regime)
    - BTC / ETH 链上状态
    - 市场宽度 (breadth)
    - 山寨宽度 (alt_breadth)
    - BTC + ETH 推送连推方向
    - 综合建议
    """
    # ── 验证 (订阅 session token 或 x402) ────────────────────────────────────
    verified, err, is_session, s_wallet, s_token = await _check_access(request)
    if not verified:
        return payment_required_response(
            request,
            "大盘详细预测 (BTC/ETH状态/宽度/山寨体制)",
            PRICE_MARKET
        )

    # ── 分析 ──────────────────────────────────────────────────────────────────
    m = get_market_prediction()

    # 综合解读
    regime = m["regime"]
    interpretations = []

    if m["breadth"] is not None:
        b = m["breadth"]
        # breadth 在 [-0.5, 0.5] 区间: 0=五五开, >0=多头占优, <0=空头占优
        if b >= 0.2:
            interpretations.append(f"📊 市场宽度 {b:+.1%} — 多数币种走强，趋势健康")
        elif b <= -0.2:
            interpretations.append(f"📊 市场宽度 {b:+.1%} — 空头占优，谨慎追多")
        else:
            interpretations.append(f"📊 市场宽度 {b:+.1%} — 多空分化，关注龙头方向")

    if m["btc_state"] == 1:
        interpretations.append("₿ BTC 推土机多头，主流多头确认")
    elif m["btc_state"] == -1:
        interpretations.append("₿ BTC 推土机空头，市场承压")

    if m["eth_state"] == 1:
        interpretations.append("Ξ ETH 推土机多头，山寨联动向好")
    elif m["eth_state"] == -1:
        interpretations.append("Ξ ETH 推土机空头，山寨承压")

    if m["alt_breadth"] is not None:
        ab = m["alt_breadth"]
        if ab >= 0.2:
            interpretations.append(f"🪙 山寨宽度 {ab:+.1%} — 山寨行情活跃，联动向好")
        elif ab <= -0.2:
            interpretations.append(f"🪙 山寨宽度 {ab:+.1%} — 山寨普遍承压")
        else:
            interpretations.append(f"🪙 山寨宽度 {ab:+.1%} — 山寨分化，跟随龙头")

    btc_run = m["btc_run"]
    eth_run = m["eth_run"]
    if btc_run >= 2:
        interpretations.append(f"🐂 BTC 连涨 +{btc_run} 次，短期多头动能强")
    elif btc_run <= -2:
        interpretations.append(f"🐻 BTC 连跌 {btc_run} 次，短期空头压力大")

    # ── 推送密度信号 (回测结论) ──────────────────────────────────────────────
    density = m.get("push_density") or {}
    back    = m.get("back_density") or {}
    joint   = m.get("joint_signal", False)

    if density.get("signal"):
        interpretations.append(f"📶 推送密度 MA7={density.get('ma7','?')}次/天 · {density['signal']}")

    if back.get("back_7d_note"):
        interpretations.append(f"🔔 {back['back_7d_note']}")
    if back.get("back_30d_note"):
        interpretations.append(f"📅 {back['back_30d_note']}")

    if joint:
        interpretations.append("⚡ 联合信号触发: 回调信号 + 推送低密度 → 历史7日胜率61%")

    # 综合建议 (加入密度权重)
    density_q = density.get("quintile", "")
    density_accel = density.get("accel", 0) or 0
    back_7d = back.get("back_7d", 0) or 0

    if joint:
        overall = "⚡ 强买点共振 — 回调信号 + 低密度蓄力，历史最强组合，胜率61%"
    elif regime == 1 and (m["btc_state"] == 1 or btc_run >= 2):
        if density_q in ("Q1低密度", "Q2") or density_accel <= -10:
            overall = "🟢 多头共振 + 密度低位 — 三重共振，高置信做多龙头"
        else:
            overall = "🟢 多头共振 — 推土机多头 + BTC走强，适合做多龙头币"
    elif regime == -1 and (m["btc_state"] == -1 or btc_run <= -2):
        overall = "🔴 空头共振 — 推土机熊市 + BTC走弱，谨慎做多，山寨避险"
    elif density_q == "Q4偏高" and back_7d <= 1:
        overall = "🟡 密度偏高分化期 — 历史7日收益-1%，轻仓观望等低密度或急剧减速"
    elif regime == 1:
        overall = "🟡 牛市体制但信号分化 — 以龙头多头机会为主，控制仓位"
    elif regime == -1:
        overall = "🟡 熊市体制但信号分化 — 减少多头暴露，等待趋势明朗"
    else:
        overall = "⚪ 震荡格局 — 方向不明，轻仓或观望为宜"

    result = {
        "direction": m["direction"],
        "direction_emoji": m["direction_emoji"],
        "regime": regime,
        "regime_label": m["regime_label"],

        # 宽度指标
        "breadth": m["breadth"],
        "alt_breadth": m["alt_breadth"],

        # BTC/ETH 状态
        "btc_state": m["btc_state"],
        "btc_state_label": {1: "🟢 推土机多头", -1: "🔴 推土机空头", 0: "⚪ 中性"}.get(m["btc_state"] or 0, "—"),
        "eth_state": m["eth_state"],
        "eth_state_label": {1: "🟢 推土机多头", -1: "🔴 推土机空头", 0: "⚪ 中性"}.get(m["eth_state"] or 0, "—"),

        # 推送连推
        "btc_run": btc_run,
        "btc_run_label": trend_label(btc_run),
        "eth_run": eth_run,
        "eth_run_label": trend_label(eth_run),

        # 密度指标
        "push_density_ma7": density.get("ma7"),
        "push_density_quintile": density.get("quintile"),
        "push_density_accel": density.get("accel"),
        "back_7d": back.get("back_7d"),
        "back_30d": back.get("back_30d"),
        "joint_signal": joint,

        # 解读 & 建议
        "interpretations": interpretations,
        "overall": overall,
        "disclaimer": "以上分析基于推土机体制 + 猎狗推送数据，仅供参考，不构成投资建议。",

        "updated_at": m["updated_at"],
    }

    if not is_session:
        await settle_payment(request)
    else:
        _consume_per_query(s_wallet, s_token)
    return JSONResponse(result)


# ══════════════════════════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    import os
    uvicorn.run("server:app", host="0.0.0.0", port=8402, reload=False)
