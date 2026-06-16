# LGAI Pharos Skill

## Description

This skill lets you query the 猎狗AI (LGAI) market prediction service running on the Pharos blockchain ecosystem. Use it to check crypto token price direction, support levels, resistance levels, market regime, bullish or bearish trend, bull or bear signal, push direction, query BTC ETH SOL prediction, check LGAI market forecast, ask for support and resistance prices, or unlock detailed analysis via x402 micropayment on Pharos testnet. Do not attempt tasks outside of LGAI market queries, token price analysis, or Pharos x402 payment flows.

## Network

Read network config from `assets/networks.json`. Default: `pharos-testnet` (chain ID 688689).

## Write Operation Pre-checks

Before any x402 payment (USDC transfer on Pharos), always:
1. Confirm the user's wallet address and that `$PRIVATE_KEY` is set
2. Check USDC balance: `cast call <usdcAddress> "balanceOf(address)(uint256)" <wallet> --rpc-url <rpc>`
3. If balance < payment amount, tell the user to get testnet USDC from the faucet

## Capability Index

| User Need | Tool | Reference |
|---|---|---|
| Check token direction / bull or bear / multi or kong | `curl` free API | → `references/lgai.md#free-token-query` |
| Get support level / resistance level / price target | `curl` paid API with x402 | → `references/lgai.md#paid-token-detail` |
| Query market regime / overall market trend / LGAI prediction / big picture | `curl` free market API | → `references/lgai.md#free-market-query` |
| Get detailed market analysis / breadth / BTC ETH state | `curl` paid market API with x402 | → `references/lgai.md#paid-market-detail` |
| Pay for LGAI detail / unlock analysis / x402 payment | `cast send` USDC on Pharos | → `references/lgai.md#x402-payment-flow` |
| Check USDC balance / wallet balance on Pharos | `cast call` balanceOf | → `references/lgai.md#check-balance` |
| Get testnet USDC / fund wallet / faucet | browser link | → `references/lgai.md#faucet` |
