"""
x402.py — Pharos x402 支付协议实现
规范参考: https://docs.pharos.xyz/developer-guide/x402
         https://github.com/PharosNetwork/examples/tree/main/skills/x402-pharos

流程:
  1. 客户端请求付费端点 → 服务端返回 HTTP 402 + payment_requirements JSON
  2. 客户端链上支付 (Pharos Atlantic 测试网, test USDC)
  3. 客户端在 X-PAYMENT 头携带 base64(payment_proof_json) 重新请求
  4. 服务端向 Facilitator 验证 → 通过则返回数据

Pharos Atlantic 测试网:
  chain_id  : 688689
  PHRS      : 原生代币, 18位小数 (like ETH)
  facilitator: https://x402.pharos.xyz/facilitator  (配置 FACILITATOR_URL 覆盖)
"""

from __future__ import annotations
import base64
import json
import os
import time
import httpx
from typing import Optional
from fastapi import Request, Response
from fastapi.responses import JSONResponse

# ── 配置 (可通过环境变量覆盖) ─────────────────────────────────────────────────
CHAIN_ID         = int(os.getenv("PHAROS_CHAIN_ID", "688689"))
# 原生代币 PHRS 用零地址表示 (18位小数)
NATIVE_TOKEN     = "0x0000000000000000000000000000000000000000"
RECIPIENT        = os.getenv("LGAI_RECIPIENT_ADDRESS", "")   # 你的收款地址
FACILITATOR_URL  = os.getenv("PHAROS_FACILITATOR_URL",
                              "https://x402.pharos.xyz/facilitator")
SKILL_BASE_URL   = os.getenv("LGAI_SKILL_BASE_URL",
                              "http://localhost:8402")

# 价格 (PHRS, 18位小数): 0.18 PHRS = 180_000_000_000_000_000
PRICE_DETAIL     = int(os.getenv("LGAI_PRICE_PHRS", "180000000000000000"))   # 0.18 PHRS
PRICE_MARKET     = int(os.getenv("LGAI_PRICE_MARKET_PHRS", "180000000000000000"))  # 0.18 PHRS

# 向后兼容别名
USDC_ADDRESS = NATIVE_TOKEN

X402_VERSION     = 1
PAYMENT_TIMEOUT  = 300   # 支付有效期(秒)


def payment_requirements(resource_url: str, description: str,
                          amount: int = PRICE_DETAIL) -> dict:
    """生成 x402 支付要求 JSON (符合 x402 v1 规范)."""
    return {
        "x402Version": X402_VERSION,
        "accepts": [
            {
                "scheme": "exact",
                "network": f"pharos-{CHAIN_ID}",
                "maxAmountRequired": str(amount),
                "resource": resource_url,
                "description": description,
                "mimeType": "application/json",
                "payTo": RECIPIENT,
                "maxTimeoutSeconds": PAYMENT_TIMEOUT,
                "asset": NATIVE_TOKEN,
                "extra": {
                    "name": "PHRS",
                    "version": "1",
                    "decimals": 18
                }
            }
        ],
        "error": "Payment required. Send X-PAYMENT header with valid proof."
    }


def payment_required_response(request: Request, description: str,
                               amount: int = PRICE_DETAIL) -> JSONResponse:
    """返回 HTTP 402 响应."""
    resource_url = str(request.url)
    reqs = payment_requirements(resource_url, description, amount)
    return JSONResponse(
        status_code=402,
        content=reqs,
        headers={
            "X-PAYMENT-REQUIRED": "true",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Expose-Headers": "X-PAYMENT-REQUIRED",
        }
    )


async def verify_payment(request: Request) -> tuple[bool, Optional[str]]:
    """
    验证请求中的 X-PAYMENT 头.
    返回 (verified: bool, error_msg: str | None)

    X-PAYMENT 格式: base64(JSON{
        "x402Version": 1,
        "scheme": "exact",
        "network": "pharos-688689",
        "payload": {
            "signature": "0x...",
            "authorization": { ... }
        }
    })
    """
    payment_header = request.headers.get("X-PAYMENT") or request.headers.get("x-payment")
    if not payment_header:
        return False, "missing X-PAYMENT header"

    # 解码支付证明
    try:
        payment_bytes = base64.b64decode(payment_header + "==")  # 补充padding
        payment_proof = json.loads(payment_bytes)
    except Exception as e:
        return False, f"invalid X-PAYMENT encoding: {e}"

    # 检查版本
    if payment_proof.get("x402Version") != X402_VERSION:
        return False, f"unsupported x402Version: {payment_proof.get('x402Version')}"

    # 本地快速检查 network
    network = payment_proof.get("network", "")
    if not network.startswith("pharos"):
        return False, f"wrong network: {network}, expected pharos-{CHAIN_ID}"

    # 向 Facilitator 验证
    if not RECIPIENT:
        # 未配置收款地址时, 测试模式直接通过 (仅开发用)
        return True, None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{FACILITATOR_URL}/verify",
                json={
                    "x402Version": X402_VERSION,
                    "paymentPayload": payment_proof,
                    "paymentRequirements": payment_requirements(
                        str(request.url),
                        "detail query",
                        PRICE_DETAIL
                    )["accepts"][0]
                }
            )
            if resp.status_code == 200:
                result = resp.json()
                if result.get("isValid"):
                    return True, None
                return False, result.get("invalidReason", "payment invalid")
            return False, f"facilitator error: {resp.status_code}"
    except httpx.TimeoutException:
        return False, "facilitator timeout"
    except httpx.ConnectError:
        # facilitator 不可达: 测试环境降级(生产中应拒绝)
        if os.getenv("LGAI_DEV_MODE", "false").lower() == "true":
            return True, None
        return False, "facilitator unreachable"
    except Exception as e:
        return False, f"verification error: {e}"


async def settle_payment(request: Request) -> None:
    """可选: 通知 facilitator 结算 (settle). 失败不影响主流程."""
    payment_header = request.headers.get("X-PAYMENT") or request.headers.get("x-payment")
    if not payment_header or not RECIPIENT:
        return
    try:
        payment_bytes = base64.b64decode(payment_header + "==")
        payment_proof = json.loads(payment_bytes)
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(
                f"{FACILITATOR_URL}/settle",
                json={
                    "x402Version": X402_VERSION,
                    "paymentPayload": payment_proof,
                    "paymentRequirements": payment_requirements(
                        str(request.url),
                        "detail query",
                        PRICE_DETAIL
                    )["accepts"][0]
                }
            )
    except Exception:
        pass  # settle 失败静默处理
