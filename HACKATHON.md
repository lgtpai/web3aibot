# LGAI Pharos Skill — Hackathon Submission

**Project:** LGAI Pharos — On-Chain Crypto Market Intelligence Skill  
**Track:** Skill & Agent Hackathon on Pharos  
**Repository:** https://github.com/lgtpai/web3aibot  
**Live Endpoint:** `http://<your-host>:8402`

---

## 1. Originality & Creative Idea

LGAI Pharos bridges **real quantitative trading signals** with **blockchain micropayments** in a single composable skill. Most DeFi tools show price feeds or generic indicators — LGAI goes further by exposing proprietary push-signal analytics: consecutive bull/bear streak detection, support/resistance levels derived from actual signal history, and a multi-layer market regime model (breadth × BTC state × ETH state × altcoin width).

The core insight is that **information asymmetry has monetary value**. Rather than a subscription wall or API key, access is gated by a native x402 PHRS micropayment — so the skill itself earns on every meaningful query. This turns a data product into a self-sustaining on-chain economy.

Key differentiators:
- Signal source is a live, battle-tested quantitative system (500+ days of push history across 300+ tokens)
- Tiered access model: free direction signal → paid support/resistance/entry advice, all in one skill
- Fully bilingual UI (EN/ZH) with zero hard-coded strings — ready for global users

---

## 2. Technical Quality & Completeness

### Architecture

```
Free tier                          Paid tier (x402 · PHRS native)
──────────────────────             ──────────────────────────────────
GET /predict/{token}        →      GET /predict/{token}/detail
  Bull/Bear · Live price             Support · Resistance · Entry advice

GET /market                 →      GET /market/detail
  Regime direction                   Breadth · BTC/ETH state · Overall signal
```

### Stack

| Layer | Technology |
|-------|-----------|
| Skill server | FastAPI + Uvicorn (Python) |
| Payment middleware | Custom x402 module — verify → serve → settle |
| Subscription DB | SQLite (per-wallet, per-plan, on-chain tx hash recorded) |
| Signal data | SQLite (`lgai.db`) — 500+ days, 300+ tokens |
| Frontend | Vanilla JS + CSS (single-file, no framework dependency) |
| Chain | Pharos Atlantic testnet (Chain ID 688689, PHRS native token) |
| Deployment | macOS launchd / Linux systemd compatible |

### Completeness checklist

- [x] x402 payment flow: 402 challenge → wallet signs → verify with Pharos facilitator → settle
- [x] Subscription plans: per-query / weekly / monthly / quarterly / semi-annual / annual
- [x] Wallet connect (MetaMask / EIP-1193 compatible)
- [x] Consumption history with on-chain TX hash links to pharosscan.xyz
- [x] Token autocomplete (300+ symbols)
- [x] Health endpoint + `.well-known/x402` + `.well-known/mcp.json` (agent-discoverable)
- [x] Dev mode (`LGAI_DEV_MODE=true`) for local testing without real payment
- [x] Full bilingual support (EN default, ZH toggle) — zero Chinese in EN mode

---

## 3. Real-World AI Agent Use Cases

### Use Case A — Trading Assistant Agent

An AI agent (e.g. Claude, GPT) calls `GET /predict/BTC` to get a free bull/bear direction, then pays 0.18 PHRS to call `GET /predict/BTC/detail` and receives structured entry advice, support/resistance levels, and signal confidence. The agent then composes a trade recommendation with specific price levels — no manual chart reading required.

```
Agent:  GET /predict/ETH          →  { direction: "Bull", run: +3 }
Agent:  pays 0.18 PHRS via x402
Agent:  GET /predict/ETH/detail   →  { support: $2,410, resistance: $2,680,
                                        entry_advice: "Long near $2,410",
                                        signals: ["✅ +3 bull streak", "✅ Bull regime"] }
Agent:  outputs structured trade plan to user
```

### Use Case B — Market Regime Monitor

An agent queries `GET /market/detail` (paid) each morning to get the overall regime signal, breadth score, BTC/ETH state, and altcoin width. It synthesizes an `overall` verdict (e.g. "🟢 Bull confluence — high-confidence long on leaders") and routes downstream agents accordingly: long-leader agent activates in bull regime, cash agent activates in bear.

### Use Case C — Portfolio Risk Scanner

An agent loops over a user's held tokens, calls `/predict/{token}` for each (free), flags any with `run <= -3` (strong bear streak), and pays for `/predict/{token}/detail` only on flagged tokens to get precise exit levels. Minimal PHRS spend, maximum signal coverage.

---

## 4. Skill Reusability & Composability

The skill exposes standard discoverable endpoints:

```
GET /.well-known/x402       →  payment requirements (amount, token, chain)
GET /.well-known/mcp.json   →  MCP-compatible tool manifest
GET /.well-known/agent-card.json  →  agent metadata
```

Any agent framework that supports x402 (or can be extended to) can consume this skill without modification. The free endpoints are fully open — agents can probe before committing payment.

**Composability patterns:**
- Chain with an execution skill: LGAI provides the signal, a trade-execution skill acts on it
- Chain with a notification skill: LGAI detects regime shift, Telegram/email skill fires the alert
- Use as a routing oracle: upstream agent asks LGAI for regime, downstream agents branch on the result
- Embed in a daily briefing agent: call `/market` (free) every morning, pay for `/market/detail` only when regime changes

The subscription model means a long-running agent can buy a monthly plan once and call detail endpoints freely within that window — no per-call payment overhead.

---

## 5. Successful Deployment on Pharos

- **Chain:** Pharos Atlantic testnet (Chain ID 688689)
- **Native token:** PHRS for all payments
- **Facilitator:** `https://x402.pharos.xyz/facilitator` — verify and settle calls integrated
- **Explorer:** All TX hashes recorded and linked to `https://pharosscan.xyz/tx/{hash}`
- **Wallet support:** MetaMask and any EIP-1193 provider; `eth_requestAccounts` + `eth_sendTransaction`
- **Payment amounts:** 0.18 PHRS (per query) up to 888 PHRS (annual plan), all in native PHRS wei

The server validates every paid request against the Pharos facilitator before serving data, and marks per-query subscriptions as consumed atomically to prevent double-use.

---

## 6. User Experience & Documentation

### Frontend UX

- Clean single-page UI, loads in < 1 second (no framework, no CDN dependency)
- Token search with autocomplete across 300+ symbols
- Free result visible immediately; paid content previewed blurred with clear unlock CTA
- Wallet status, remaining queries, and subscription expiry shown after connect
- Consumption history table with TX hash links for self-auditing
- Full EN/ZH language switch — all dynamic content translated server-side via `_en` fields

### Documentation

| Document | Contents |
|----------|----------|
| `README.md` | Bilingual quickstart, architecture, API examples, env vars |
| `SKILL.md` | Agent-facing skill description and endpoint reference |
| `references/lgai.md` | Deep operational manual for integrating agents |
| `/docs` (Swagger) | Auto-generated interactive API docs at `http://host:8402/docs` |

### Developer Experience

```bash
# Zero-config local dev
LGAI_DEV_MODE=true uvicorn server:app --port 8402
# X-PAYMENT: any value passes in dev mode
curl -H "X-PAYMENT: dGVzdA==" http://localhost:8402/predict/BTC/detail
```

---

## 7. Alignment with Pharos AI Agent & On-Chain Economy Vision

Pharos is building the infrastructure for an **AI-native on-chain economy** — where agents earn, spend, and compose autonomously. LGAI Pharos is a direct instantiation of this vision:

| Pharos Vision | LGAI Implementation |
|---------------|---------------------|
| Skills as economic primitives | Every detail query earns PHRS for the operator |
| Agents paying agents | x402 allows AI agents to pay autonomously without human approval |
| On-chain verification | All payments verified via Pharos facilitator; TX hashes on-chain |
| Composable agent ecosystem | Free tier for discovery, paid tier for depth — naturally composable |
| Open agent discovery | `.well-known/mcp.json` + `agent-card.json` make the skill self-describing |

The skill is not a demo — it runs on real signal data from a production quantitative trading system with years of history, making it immediately useful to agents operating in live crypto markets.

---

## Phase Notes

**Phase 1 (Skill Quality):** The skill module is complete, documented, and deployable standalone. The x402 payment flow, subscription system, free/paid tier split, and agent-discovery endpoints are all production-ready.

**Phase 2 (Full Agent):** The natural Phase 2 extension is an autonomous trading agent that: (1) queries LGAI for signals, (2) pays for detail on high-conviction setups, (3) executes trades on Pharos DEX, and (4) reports PnL on-chain — closing the full loop of an AI agent earning and spending PHRS autonomously.

---

*Built by LGAI · Pharos Atlantic Testnet · Chain ID 688689*
