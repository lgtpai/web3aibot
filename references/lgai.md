# LGAI Market Prediction — Operation Instructions

This file teaches Claude how to query the 猎狗AI prediction service and handle
x402 micropayments on the Pharos testnet for unlocking detailed analysis.

> **Service URL**: `http://localhost:8402`
> **Network config**: read `rpcUrl`, `chainId`, `usdcAddress` from `assets/networks.json` → `pharos-testnet`
> **Private Key**: all write operations use `--private-key $PRIVATE_KEY`

---

## Free Token Query

Query a token's bull/bear direction for free. No payment required.

### Command Template

```bash
curl -s http://localhost:8402/predict/<TOKEN>
```

### Parameters

| Parameter | Type | Required | Description |
|---|---|---|---|
| `<TOKEN>` | string | Yes | Token symbol, uppercase. e.g. `BTC`, `ETH`, `SOL`, `XRP` |

### Output Parsing

| Field | Description |
|---|---|
| `direction` | `多` (long/bull) or `空` (short/bear) or `中性` (neutral) |
| `direction_emoji` | 🟢 bull / 🔴 bear / ⚪ neutral |
| `run` | Consecutive push count: positive = bullish streak, negative = bearish streak |
| `run_label` | Human label e.g. "强多头 +3连涨" (strong bull +3 consecutive) |
| `latest_push` | Most recent signal price |
| `found` | `false` means no push data for this token yet |
| `upgrade_hint` | How to unlock support/resistance via paid endpoint |

### Error Handling

| Error | Cause | Fix |
|---|---|---|
| `connection refused` | LGAI server not running | Run `bash skills/lgai_pharos/start.sh` to start the service |
| `found: false` | Token has no push history | Try a major token: BTC, ETH, SOL, XRP, BNB |
| Empty response | Server starting up | Wait 3 seconds and retry |

> **Agent Guidelines:**
> 1. Run the curl command
> 2. Parse `direction_emoji`, `direction`, `run_label`, `latest_push` from JSON
> 3. Show the user: "{TOKEN} 当前方向: {emoji} {direction} ({run_label}) · 最新推送价 {price}"
> 4. Tell the user: "支撑位/压力位详情需支付 0.1 USDC，输入「查询 {TOKEN} 详情」解锁"

---

## Paid Token Detail

Get support level, resistance level, entry advice and trend strength.
**Cost: 0.1 USDC on Pharos testnet** via x402.

### Step 1 — Attempt the Request

```bash
curl -s -w "\n%{http_code}" http://localhost:8402/predict/<TOKEN>/detail
```

- If HTTP status is `200` → payment already attached or dev mode, show results directly
- If HTTP status is `402` → payment required, proceed to x402 payment flow (see below)

### Step 2 — If 402: Execute x402 Payment Flow

See section `#x402-payment-flow` below. After payment, re-run:

```bash
curl -s \
  -H "X-PAYMENT: <base64_payment_proof>" \
  http://localhost:8402/predict/<TOKEN>/detail
```

### Output Parsing (200 response)

| Field | Description |
|---|---|
| `live_price` | Current real-time price fetched at query time |
| `support` | Most recent push price **below** current price (support level) |
| `support_time` | Timestamp of that push event |
| `resistance` | Most recent push price **above** current price (resistance level) |
| `resistance_time` | Timestamp of that push event |
| `direction` / `run` | Trend direction and streak count |
| `signals` | List of signal confirmations e.g. "✅ 大盘牛市体制，多头方向共振" |
| `entry_advice` | Entry suggestion (for reference only, not financial advice) |
| `market_regime_label` | Overall market regime: 🟢 牛市 / 🔴 熊市 / ⚪ 震荡 |
| `recent_pushes` | Last 5 push records with price + timestamp |

### Display Format

Show the user:

```
{TOKEN} 实时价: {live_price}
━━━━━━━━━━━━━━━━━━━━
支撑位: {support} ({support_time} 推送)
压力位: {resistance} ({resistance_time} 推送)
━━━━━━━━━━━━━━━━━━━━
方向: {direction_emoji} {direction} · {run_label}
大盘: {market_regime_label}
信号: {signals joined by newline}
建议: {entry_advice}
⚠️ 仅供参考，不构成投资建议
```

> **Agent Guidelines:**
> 1. First attempt without payment header
> 2. If 402 returned, run the x402 payment flow
> 3. After payment, re-send request with `X-PAYMENT` header
> 4. Parse and display results in the format above
> 5. Include disclaimer at the end

---

## Free Market Query

Get overall market bull/bear regime for free.

### Command Template

```bash
curl -s http://localhost:8402/market
```

### Output Parsing

| Field | Description |
|---|---|
| `direction` | `多` / `空` / `中性` |
| `direction_emoji` | 🟢 / 🔴 / ⚪ |
| `regime_label` | `🟢 牛市` / `🔴 熊市` / `⚪ 震荡` |
| `message` | Human-readable summary |

> **Agent Guidelines:**
> 1. Run curl command
> 2. Show `message` field directly to user
> 3. Offer: "输入「大盘详情」解锁 BTC/ETH 状态、市场宽度等详细数据（0.1 USDC）"

---

## Paid Market Detail

Get full market breakdown: BTC/ETH states, market breadth, altcoin regime.
**Cost: 0.1 USDC** via x402.

### Step 1 — Attempt the Request

```bash
curl -s -w "\n%{http_code}" http://localhost:8402/market/detail
```

- `200` → show results
- `402` → go to x402 payment flow, then re-request with `X-PAYMENT` header

### Output Parsing (200)

| Field | Description |
|---|---|
| `regime_label` | Overall regime |
| `btc_state_label` | BTC bulldozer trend |
| `eth_state_label` | ETH bulldozer trend |
| `btc_run_label` | BTC consecutive push direction |
| `eth_run_label` | ETH consecutive push direction |
| `breadth` | Market breadth ratio (0–1). ≥0.7 = strong bull, ≤0.3 = bear |
| `alt_breadth` | Altcoin breadth ratio |
| `interpretations` | List of signal bullets |
| `overall` | Single-line comprehensive conclusion |

> **Agent Guidelines:**
> Same as paid token detail. After payment, display `overall` prominently,
> then list `interpretations` as bullet points.

---

## x402 Payment Flow

Used when a paid endpoint returns HTTP 402. Sends 0.1 USDC on Pharos testnet
and constructs the `X-PAYMENT` header.

### Pre-checks

```bash
# 1. Confirm PRIVATE_KEY is set
echo "Wallet: $(cast wallet address --private-key $PRIVATE_KEY 2>/dev/null)"

# 2. Check USDC balance (must be ≥ 100000, i.e. 0.1 USDC with 6 decimals)
cast call 0xE0BE08c77f415F577A1B3A9aD7a1Df1479564ec8 \
  "balanceOf(address)(uint256)" \
  $(cast wallet address --private-key $PRIVATE_KEY) \
  --rpc-url https://atlantic.dplabs-internal.com
```

If balance < 100000 → send user to faucet (see `#faucet`).

### Step 1 — Parse Payment Requirements from 402 Response

The 402 body contains:
```json
{
  "accepts": [{
    "payTo": "<RECIPIENT_ADDRESS>",
    "maxAmountRequired": "100000",
    "asset": "0xE0BE08c77f415F577A1B3A9aD7a1Df1479564ec8"
  }]
}
```

Extract `payTo` (recipient address) from `accepts[0].payTo`.

### Step 2 — Send USDC Transfer

```bash
cast send 0xE0BE08c77f415F577A1B3A9aD7a1Df1479564ec8 \
  "transfer(address,uint256)(bool)" \
  <payTo_address> \
  100000 \
  --private-key $PRIVATE_KEY \
  --rpc-url https://atlantic.dplabs-internal.com
```

| Parameter | Value |
|---|---|
| Contract | `0xE0BE08c77f415F577A1B3A9aD7a1Df1479564ec8` (test USDC) |
| `<payTo_address>` | From 402 response `accepts[0].payTo` |
| Amount | `100000` (0.1 USDC, 6 decimals) |

### Step 3 — Build Payment Proof Header

After the transfer succeeds, get the transaction hash from `cast send` output field `transactionHash`.

Build the payment proof JSON:
```json
{
  "x402Version": 1,
  "scheme": "exact",
  "network": "pharos-688689",
  "payload": {
    "txHash": "<transactionHash>",
    "from": "<your_wallet_address>"
  }
}
```

Base64-encode it:
```bash
echo -n '{"x402Version":1,"scheme":"exact","network":"pharos-688689","payload":{"txHash":"<txHash>","from":"<wallet>"}}' | base64
```

### Step 4 — Re-request with Payment Header

```bash
curl -s \
  -H "X-PAYMENT: <base64_string>" \
  http://localhost:8402/predict/<TOKEN>/detail
```

### Error Handling

| Error | Cause | Fix |
|---|---|---|
| `execution reverted` on cast send | USDC balance too low | Go to faucet |
| `missing X-PAYMENT header` in response | Base64 encoding issue | Ensure no newlines in base64 string (use `base64 -w 0` on Linux) |
| `payment invalid` from facilitator | Tx not confirmed yet | Wait 3 seconds and retry the detail request |
| `wrong network` | PRIVATE_KEY on wrong chain | Confirm RPC is `https://atlantic.dplabs-internal.com` (chain 688689) |

> **Agent Guidelines:**
> 1. Always run pre-checks first
> 2. Parse `payTo` from 402 body — never hardcode the recipient
> 3. After `cast send`, wait 3 seconds for confirmation before re-requesting
> 4. If facilitator still returns error after 10s, inform user and suggest retry

---

## Check Balance

Check USDC balance on Pharos testnet.

```bash
# PHRS native balance
cast balance $(cast wallet address --private-key $PRIVATE_KEY) \
  --rpc-url https://atlantic.dplabs-internal.com --ether

# USDC token balance (6 decimals, divide by 1000000 for display)
cast call 0xE0BE08c77f415F577A1B3A9aD7a1Df1479564ec8 \
  "balanceOf(address)(uint256)" \
  $(cast wallet address --private-key $PRIVATE_KEY) \
  --rpc-url https://atlantic.dplabs-internal.com
```

> **Agent Guidelines:** Divide USDC result by 1000000 for display. Show as "X.XX USDC".

---

## Faucet

If the user needs testnet USDC or PHRS:

- Pharos testnet faucet: **https://faucet.pharos.xyz**
- User needs their wallet address (run `cast wallet address --private-key $PRIVATE_KEY`)
- After getting PHRS, they may need to swap for test USDC at the testnet DEX

> **Agent Guidelines:** Show the faucet URL and the user's wallet address.
> Remind them USDC contract is `0xE0BE08c77f415F577A1B3A9aD7a1Df1479564ec8` on chain 688689.
