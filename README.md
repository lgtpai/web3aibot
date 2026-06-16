# LGAI Pharos Skill — Market Prediction + x402 Payment

A market prediction skill on the [Pharos](https://docs.pharos.xyz) blockchain. Free queries return bull/bear direction; x402 micropayments unlock detailed analysis with support/resistance levels.

## Architecture

```
Free                              Paid (PHRS native token / x402)
─────────────────────             ──────────────────────────────────────
GET /predict/{token}       →      GET /predict/{token}/detail
  Direction · Latest price          Support · Resistance · Trend · Entry

GET /market                →      GET /market/detail
  Market regime                     Breadth / BTC / ETH / altcoin state
```

## Data Sources

| Data | Source |
|------|--------|
| Support level | `data/lgai.db` — lowest push price in recent signals |
| Resistance level | `data/lgai.db` — highest push price in recent signals |
| Direction (bull/bear) | Consecutive push direction: up/down vs previous |
| Market regime | `data/regime_monitor/state.json` (regime field) |
| Leader list | `data/leaders_config.json` |

## Pharos Testnet Config

| Parameter | Value |
|-----------|-------|
| Chain ID | 688689 (Pharos Atlantic) |
| Native token | PHRS |
| Explorer | https://pharosscan.xyz |
| Faucet | https://faucet.pharos.xyz |

## Quick Start

### 1. Install Dependencies

```bash
cd crypto_quant
.venv/bin/pip install httpx --break-system-packages
```

### 2. Dev Mode (no real payment)

```bash
cd skills/lgai_pharos
LGAI_DEV_MODE=true .venv/bin/python -m uvicorn server:app --port 8402
```

Visit http://localhost:8402 for the web UI, or http://localhost:8402/docs for Swagger.

### 3. Production (real x402 payment)

```bash
# Set your Pharos wallet address in the plist
nano com.lgai.skill.plist   # edit LGAI_RECIPIENT_ADDRESS

# Install launchd autostart
cp com.lgai.skill.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.lgai.skill.plist
```

### 4. Test Endpoints

```bash
# Free: BTC direction
curl http://localhost:8402/predict/BTC

# Free: market regime
curl http://localhost:8402/market

# Paid: returns 402 + payment info
curl http://localhost:8402/predict/BTC/detail

# Discovery
curl http://localhost:8402/.well-known/x402
curl http://localhost:8402/.well-known/mcp.json

# Dev mode paid test (X-PAYMENT any value passes)
curl -H "X-PAYMENT: dGVzdA==" http://localhost:8402/predict/BTC/detail
```

## x402 Payment Flow

```
Client                          LGAI Skill Server           Pharos Facilitator
  │                                   │                             │
  │── GET /predict/BTC/detail ───────→│                             │
  │                                   │── no X-PAYMENT ──→ 402     │
  │←── 402 + payment_requirements ───│                             │
  │                                   │                             │
  │── on-chain PHRS transfer ─────────────────────────────→ broadcast
  │                                   │                             │
  │── GET /predict/BTC/detail ───────→│                             │
  │   X-PAYMENT: base64(proof_json)   │                             │
  │                                   │── POST /verify ────────────→│
  │                                   │←── {isValid: true} ─────────│
  │←── 200 + detailed analysis JSON ─│                             │
  │                                   │── POST /settle ────────────→│
```

## Response Examples

### Free `/predict/BTC`
```json
{
  "token": "BTC",
  "direction": "多",
  "direction_emoji": "🟢",
  "run": 3,
  "run_label": "Strong Bull +3",
  "latest_price": 68420.5,
  "is_leader": true,
  "message": "BTC direction: 🟢 Bull (Strong +3) · Latest $68,420.50"
}
```

### Paid `/predict/BTC/detail`
```json
{
  "token": "BTC",
  "support": 65200.0,
  "support_fmt": "$65,200.00",
  "resistance": 71500.0,
  "resistance_fmt": "$71,500.00",
  "range_pct": "Range 9.66%",
  "direction": "多",
  "run": 3,
  "market_regime": 1,
  "market_regime_label": "🟢 Bull",
  "signals": ["✅ +3 consecutive bull signals", "✅ Market in bull regime"],
  "entry_advice": "Consider long near support $65,200.00",
  "recent_pushes": [...]
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LGAI_RECIPIENT_ADDRESS` | (required) | Your Pharos wallet address to receive payments |
| `PHAROS_CHAIN_ID` | 688689 | Pharos Atlantic testnet |
| `LGAI_SKILL_BASE_URL` | http://localhost:8402 | Public URL of the skill |
| `LGAI_DEV_MODE` | false | `true` = skip payment verification (dev only) |

---

# 猎狗AI Pharos 技能 — 行情预测 + x402 支付

基于 [Pharos](https://docs.pharos.xyz) 公链的行情预测技能，支持免费查询多空方向，x402 微支付解锁详细分析。

## 架构

```
免费                          付费 (PHRS 原生代币 / x402)
─────────────────────         ──────────────────────────────────────
GET /predict/{token}    →     GET /predict/{token}/detail
  多空方向 · 最新价             支撑位 · 压力位 · 趋势强度 · 入场建议

GET /market             →     GET /market/detail
  大盘体制方向                  宽度/BTC/ETH状态/山寨体制/综合建议
```

## 快速启动

```bash
# 安装依赖
cd crypto_quant && .venv/bin/pip install httpx --break-system-packages

# 开发模式 (无需真实支付)
cd skills/lgai_pharos
LGAI_DEV_MODE=true .venv/bin/python -m uvicorn server:app --port 8402
```

访问 http://localhost:8402 查看面板（默认英文，右上角切换中文）。

## Pharos 测试网

| 参数 | 值 |
|------|----|
| Chain ID | 688689 (Pharos Atlantic) |
| 原生代币 | PHRS |
| 浏览器 | https://pharosscan.xyz |
| 水龙头 | https://faucet.pharos.xyz |

## 订阅套餐

| 套餐 | 价格 | 有效期 |
|------|------|--------|
| 按次解锁 | 0.18 PHRS/次 | 90天 |
| 周卡 | 0.50 PHRS | 7天 |
| 月卡 | 1.80 PHRS | 30天 |
| 季卡 | 4.00 PHRS | 90天 |

## 环境变量

| 变量 | 说明 |
|------|------|
| `LGAI_RECIPIENT_ADDRESS` | **必填** 收款钱包地址 |
| `LGAI_DEV_MODE` | `true` = 跳过支付验证（仅开发用） |
