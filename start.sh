#!/bin/bash
# start.sh — 启动 LGAI Pharos Skill 服务
# 用法: bash skills/lgai_pharos/start.sh

set -e
SKILL_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SKILL_DIR/../.." && pwd)"
ENV_FILE="$SKILL_DIR/.env"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

echo "=== LGAI Pharos Skill 启动 ==="

# ── Python 解释器 ────────────────────────────────────────────────────────────
PYTHON=""
for p in \
  "$PROJECT_DIR/.venv/bin/python" \
  "$PROJECT_DIR/.venv/bin/python3" \
  "$(which python3)" \
  "$(which python)"; do
  if [ -n "$p" ] && "$p" --version &>/dev/null; then
    PYTHON="$p"
    break
  fi
done
[ -z "$PYTHON" ] && { echo "[错误] 找不到 Python"; exit 1; }
echo "[✓] Python: $($PYTHON --version)"

# ── 安装缺失依赖 ─────────────────────────────────────────────────────────────
echo "[...] 检查依赖..."
$PYTHON -c "import fastapi, uvicorn" 2>/dev/null || {
  echo "[...] 安装 fastapi uvicorn..."
  PIP="$(dirname $PYTHON)/pip"
  [ -f "$PIP" ] || PIP="$(which pip3)"
  $PIP install fastapi uvicorn httpx eth-account -q
}
$PYTHON -c "import httpx" 2>/dev/null || {
  PIP="$(dirname $PYTHON)/pip"
  [ -f "$PIP" ] || PIP="$(which pip3)"
  $PIP install httpx eth-account -q
}
echo "[✓] 依赖 OK"

# ── 生成测试网钱包 (仅首次) ──────────────────────────────────────────────────
if [ ! -f "$ENV_FILE" ] || ! grep -q "LGAI_RECIPIENT_ADDRESS=0x[0-9a-fA-F]" "$ENV_FILE" 2>/dev/null; then
  echo "[...] 生成 Pharos 测试网钱包..."
  WALLET_OUT=$($PYTHON -c "
from eth_account import Account
a = Account.create()
print('ADDR=' + a.address)
print('PK=' + a.key.hex())
" 2>/dev/null) || {
    # eth_account 未装，生成随机占位地址
    WALLET_OUT="ADDR=0x0000000000000000000000000000000000000001
PK=0x0000000000000000000000000000000000000000000000000000000000000001"
    echo "[警告] eth_account 未安装，使用占位地址。请手动填入真实地址到 .env"
  }
  ADDR=$(echo "$WALLET_OUT" | grep ADDR | cut -d= -f2)
  PK=$(echo "$WALLET_OUT" | grep PK | cut -d= -f2)

  cat > "$ENV_FILE" <<EOF
# LGAI Pharos Skill 配置
# Pharos Atlantic 测试网 (chain ID 688689)

LGAI_RECIPIENT_ADDRESS=$ADDR
LGAI_PRIVATE_KEY=$PK
PHAROS_CHAIN_ID=688689
PHAROS_USDC_ADDRESS=0xE0BE08c77f415F577A1B3A9aD7a1Df1479564ec8
PHAROS_FACILITATOR_URL=https://x402.pharos.xyz/facilitator
LGAI_SKILL_BASE_URL=http://localhost:8402
LGAI_PRICE_USDC=100000
LGAI_DEV_MODE=true
EOF
  chmod 600 "$ENV_FILE"
  echo ""
  echo "┌─────────────────────────────────────────────────────┐"
  echo "│  新测试网钱包已生成                                     │"
  echo "│  地址: $ADDR  │"
  echo "│                                                     │"
  echo "│  请去水龙头领取测试 PHRS 和 USDC:                       │"
  echo "│  https://faucet.pharos.xyz                          │"
  echo "└─────────────────────────────────────────────────────┘"
  echo ""
else
  ADDR=$(grep LGAI_RECIPIENT_ADDRESS "$ENV_FILE" | cut -d= -f2)
  echo "[✓] 使用已有钱包: $ADDR"
fi

# ── 从 .env 加载环境变量 ──────────────────────────────────────────────────────
set -a
source "$ENV_FILE"
set +a

# 同时导出 PRIVATE_KEY 供 cast 使用
export PRIVATE_KEY="$LGAI_PRIVATE_KEY"

# ── 停止旧实例 ────────────────────────────────────────────────────────────────
OLD_PID=$(lsof -ti:8402 2>/dev/null || true)
[ -n "$OLD_PID" ] && { echo "[...] 停止旧服务 (PID $OLD_PID)"; kill "$OLD_PID" 2>/dev/null; sleep 1; }

# ── 启动服务 ──────────────────────────────────────────────────────────────────
echo "[...] 启动 LGAI Skill 服务 (port 8402)..."
cd "$SKILL_DIR"
nohup $PYTHON -m uvicorn server:app \
  --host 0.0.0.0 --port 8402 --no-access-log \
  > "$LOG_DIR/lgai_skill.log" 2>&1 &
SVC_PID=$!
echo "$SVC_PID" > "$SKILL_DIR/.service.pid"

# ── 等待就绪 ──────────────────────────────────────────────────────────────────
echo -n "[...] 等待服务就绪"
for i in $(seq 1 15); do
  sleep 1
  if curl -sf http://localhost:8402/health &>/dev/null; then
    echo " ✓"
    break
  fi
  echo -n "."
done

if ! curl -sf http://localhost:8402/health &>/dev/null; then
  echo ""
  echo "[错误] 服务未能启动，查看日志:"
  tail -20 "$LOG_DIR/lgai_skill.log"
  exit 1
fi

# ── 冒烟测试 ──────────────────────────────────────────────────────────────────
echo ""
echo "=== 冒烟测试 ==="
echo ""
echo "--- BTC 免费方向查询 ---"
curl -s http://localhost:8402/predict/BTC | python3 -m json.tool 2>/dev/null
echo ""
echo "--- 大盘体制 ---"
curl -s http://localhost:8402/market | python3 -m json.tool 2>/dev/null
echo ""
echo "--- BTC 详情 (402 挑战) ---"
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8402/predict/BTC/detail)
echo "HTTP $STATUS (期望 402 — 需要付款)"
[ "$STATUS" = "402" ] && echo "[✓] x402 付款流程正常"
echo ""

# ── 打印 PRIVATE_KEY 供 cast 使用 ────────────────────────────────────────────
echo "=== 部署完成 ==="
echo ""
echo "服务地址:    http://localhost:8402"
echo "发现端点:    http://localhost:8402/.well-known/mcp.json"
echo "收款地址:    $ADDR"
echo "日志:        tail -f $LOG_DIR/lgai_skill.log"
echo ""
echo "Claude Code 使用方式:"
echo "  cd $SKILL_DIR"
echo "  export PRIVATE_KEY=$LGAI_PRIVATE_KEY"
echo "  claude"
echo ""
echo "测试提示词:"
echo "  查询 BTC 行情预测"
echo "  查询 ETH 的支撑位和压力位"
echo "  大盘现在什么趋势"
echo "  查询 SOL 详情 (会触发 x402 支付流程)"
