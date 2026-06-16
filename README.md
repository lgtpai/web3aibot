# 猎狗AI Pharos Skill 🐕

> Web3 AI 行情预测技能 —— 基于 Pharos 测试网 x402 微支付，提供加密货币多空方向、支撑压力位、大盘体制分析。

[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code-Skill-yellow)](https://code.claude.com)
[![Pharos Testnet](https://img.shields.io/badge/Pharos-Testnet-blue)](https://pharos.network)

## 功能

| 功能 | 是否免费 |
|------|---------|
| 币种多空方向 / 推送价格 | ✅ 免费 |
| 大盘体制 (牛/熊/震荡) | ✅ 免费 |
| 支撑位 / 压力位 / 入场建议 | 💰 按次付费 (PHRS) |
| 大盘详细分析 / 市场宽度 | 💰 按次付费 (PHRS) |

支付使用 Pharos 测试网原生代币 PHRS，通过 [x402 协议](https://x402.org) 完成链上微支付。

## 在线体验

访问 Web 界面：连接 MetaMask → 选套餐 → 支付 → 解锁分析

需要 Pharos 测试网（Chain ID: 688689），可在水龙头领取测试 PHRS：
https://faucet.pharos.network

## Claude Code 安装

```bash
claude mcp add https://raw.githubusercontent.com/lgtpai/web3aibot/main/well-known/mcp.json
```

或直接克隆后本地安装：

```bash
git clone https://github.com/lgtpai/web3aibot.git
cd web3aibot
pip install -r requirements.txt
```

## 自部署

### 1. 环境配置

```bash
cp .env.example .env
# 编辑 .env，填写以下必填项：
# LGAI_RECIPIENT_ADDRESS=0xYOUR_WALLET   # 收款钱包地址
# LGAI_SECRET=your_random_secret         # 用于生成 session token
```

### 2. 实现数据层

`analyze.py` 是数据接口层，当前为 stub（返回空数据）。
你需要替换为连接你自己数据源的实现：

```python
# analyze.py
def get_token_analysis(token: str) -> dict:
    # 返回代币分析结果
    # 必须字段见 analyze.py 中的文档注释
    ...
```

### 3. 启动服务

```bash
# 开发模式
uvicorn server:app --host 0.0.0.0 --port 8402

# macOS 后台服务（launchd）
cp com.lgai.skill.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.lgai.skill.plist
```

### 4. 访问 Web 界面

打开 http://localhost:8402

## 订阅套餐

| 套餐 | 价格 | 有效期 |
|------|------|--------|
| 按次解锁 | 0.18 PHRS | 每次独立，90天内有效 |
| 周卡 | 0.68 PHRS | 7天 |
| 月卡 | 1.18 PHRS | 30天 |
| 季卡 | 2.88 PHRS | 90天 |
| 半年卡 | 4.98 PHRS | 180天 |
| 年卡 | 8.88 PHRS | 365天 |

## 技术架构

```
用户浏览器
  └─ static/index.html (MetaMask + PHRS 支付)
       └─ FastAPI server (port 8402)
            ├─ /predict/{token}        免费接口
            ├─ /predict/{token}/detail 付费接口 (x402)
            ├─ /market                 免费接口
            ├─ /market/detail          付费接口 (x402)
            ├─ /api/subscribe          订阅注册
            ├─ /api/subscription/{w}   订阅查询
            ├─ /api/history/{w}        消费记录
            └─ /api/tokens             联想候选
```

## 许可

MIT License — 欢迎 fork 后接入你自己的数据源。

---

**猎狗AI** · [GitHub](https://github.com/lgtpai) · Pharos Testnet
