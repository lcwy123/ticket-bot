# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

**闲鱼AI助手** — 电影票代购服务，主要功能：

- **电影票代购**：搜索猫眼、时光网等平台票价，自动发布到闲鱼
- **飞书客服**：通过飞书聊天机器人为用户提供AI客服对话
- **电影监控**：定时检查新上映电影并自动上架、更新价格
- **消息处理**：支持闲鱼消息同步到飞书通知

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 安装浏览器驱动（浏览器模式需要）
python scripts/install_browser.py

# 启动应用
python -m app.main
# 或开发模式（热重载）
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 运行测试
pytest tests/ -v
pytest tests/test_customer_service.py::test_customer_service_chat -v  # 单个测试

# 测试 ADB 设备连接
python scripts/test_adb_device.py

# 模块集成测试
python scripts/test_modules.py
```

## 启动生命周期（`app/main.py`）

应用启动时按顺序初始化以下组件（均在 `lifespan` 中）：

1. **APScheduler** — 启动电影监控定时任务
2. **XianyuAppClient** — 连接 Android 设备（需配置 `xianyu_device_addr` 或 `use_app_mode=true`）
3. **EnhancedMobileAgent** — 多模态大模型驱动的手机操作代理
4. **TaskPlanner** — 任务规划器，将复杂任务拆解为可执行步骤
5. **LarkService** — 飞书消息推送
6. **NotificationHandler** → **NotificationListener** — 通知驱动的事件处理链
7. **XianyuMessageListener** — 闲鱼消息轮询（后台异步任务）
8. **ADBNotificationWatcher** — ADB 通知监控（仅 APP 模式）
9. **Lark WebSocket Client** — 飞书长连接（需配置 `lark_agent_app_id`）

关闭时反向清理：停止消息监听 → 停止调度器 → 停止飞书客户端 → 断开设备连接

### API 路由总览

| 路由前缀 | 模块 | 用途 |
|----------|------|------|
| `/` | `main.py` | 根路径（状态）、`/health`（健康检查） |
| `/api/agent/*` | `main.py` | Agent 状态、任务执行、计划管理 |
| `/api/customer-service/*` | `customer_service/` | 客服对话、飞书 Webhook、会话管理 |
| `/api/ticket/*` | `ticket/` | 票务搜索、报价、订单 |
| `/api/monitor/*` | `monitor/` | 电影监控手动触发、数据查询 |
| `/api/agent/device/*` | `autojs_router.py` | AutoJS 设备注册、命令、WebSocket |
| `/api/notifications/*` | `notification_driver.py` | 通知 Webhook、历史、状态 |
| `/lark/*` | `lark_agent/` | 飞书 Agent Webhook（手机控制） |
| `/admin/ticket` | `main.py` | 票务管理 HTML 页面（`app/templates/ticket_admin.html`） |

## 手机设备控制架构

### 两条控制链路

**链路 1: ADB 模式** (`use_app_mode=true`)
```
XianyuAppClient (ADB命令封装)
  → EnhancedMobileAgent (多模态大模型决策)
    → TaskPlanner (任务规划 + 步骤调度)
      → NotificationListener (事件驱动入口)
```

**链路 2: AutoJS 模式** (无 ROOT 方案)
```
AutoJS 脚本（运行在手机上）
  → HTTP 轮询 / WebSocket 获取指令
    → autojs_router.py (FastAPI 路由)
      → AutoJSDeviceClient (命令队列管理)
```

### MobileAgent 核心流程

```
截图 → Vision Model 分析 → JSON 操作指令 → 执行操作 → 判断完成 → 循环
```

LLM 输出格式：`{action, x, y, reason, confidence, alternatives}`

自我纠错：confidence < 0.7 时尝试备用方案；操作失败后自动重试；遇到验证码立即停止。

### 通知驱动工作流

```
Webhook/ADB通知 → NotificationFilter(过滤广告) → classify(分类)
  → NotificationHandler → TaskPlanner.parse_task() → execute_plan()
    → MobileAgent.run() → 飞书通知人工确认(失败时)
```

通知类型：`xianyu_message`, `xianyu_order`, `xianyu_system`

### AutoJS WebSocket 消息闭环（含 Agent 自动回复）

手机通过 WebSocket (`/api/agent/device/ws/{device_id}`) 连接后，实现完整的消息收发闭环：

```
手机通知 → 打开闲鱼 → 无障碍控件树导航 → 提取消息 → WebSocket 上传(type="message")
  → autojs_router.py → OpenClaw Agent (AI+工具+记忆) → 生成回复
    → manager.send_command(device_id, {"action":"reply","text":"..."})
      → 手机等待回复(≤30s) → sendReply() 自动输入+发送 → 用户收到回复
```

关键组件：
- `app/services/openclaw_client.py` — OpenClaw Gateway 桥接客户端
- `app/services/autojs_router.py` — WebSocket 消息处理器（消息转发 + 回复回传）
- `scripts/autojs/autojs_websocket.js` — 手机端完整脚本（WebSocket 长连接、通知监听、导航、消息提取、回复发送，主用）
- `scripts/autojs/autojs_polling.js` — HTTP 轮询模式（备选方案）
- `scripts/autojs/autojs_message_monitor.js` — 消息监控专用脚本
- `scripts/autojs/autojs_server.js` — HTTP Server 模式
- `scripts/autojs/autojs_test.js` — 测试脚本

手机端 `sendReply()` 流程：点击输入框 → setClip()+ACTION_PASTE 粘贴 → 查找/点击发送按钮

详见 `docs/AUTOJS_SETUP.md`

## 飞书客服对话架构

### 核心模块：`app/modules/customer_service/`

```
service.py          # CustomerService 核心类
message_listener.py  # XianyuMessageListener 闲鱼消息轮询
router.py           # FastAPI 路由（/api/customer-service/*）
```

### 消息流程

1. **消息来源**（三个入口）：
   - `MessageSource.XIANYU` — 闲鱼平台用户消息
   - `MessageSource.LARK` — 飞书机器人接收的消息
   - `MessageSource.SYSTEM` — 系统内部消息

2. **消息处理流程**：
   ```
   闲鱼消息(手机WebSocket) → OpenClaw Agent(实时回复) → 手机自动发送
                           → Redis队列(备份) → CustomerService.chat() → 飞书通知
   飞书消息 → Redis队列 → CustomerService.chat() → 回复到飞书
   ```

3. **AI对话核心**（`CustomerService`）：
   - `chat()` — 基础对话，使用 Anthropic/MiniMax API
   - `chat_with_context()` — 带用户上下文的对话（用户名、订单、偏好）
   - `queue_message()` — 消息入队（Redis）
   - `process_message_queue()` — 后台消费队列
   
   注意：闲鱼消息的**实时回复**由 `openclaw_client.py` → OpenClaw Agent 处理，
   `CustomerService` 的 Redis 队列仅作为备份和飞书通知通道。

4. **会话管理**（全量存储在 Redis）：
   - `xianyu:chat:session:{user_id}` — 用户的会话ID集合
   - `xianyu:chat:conversation:{session_id}` — 会话历史（24h过期）
   - `xianyu:chat:message_queue` — 消息队列

### 飞书Webhook路由

`POST /api/customer-service/webhook/lark` 处理飞书事件：

- 接收 `im.message.receive_v1` 事件
- 验证签名（`x-lark-signature`）
- 解析消息内容，提取 `open_id` 和文本
- 消息入队，触发后台 `process_message_queue()`

### 关键设计

1. **多消息源统一处理**：闲鱼/飞书消息统一入队，异步处理
2. **Redis 持久化会话**：支持多会话、上下文记忆
3. **AI 回复同步通知**：闲鱼消息处理后推送到飞书通知
4. **下单意图识别**：`identify_order_intent()` 从自然语言识别买票意图
5. **实体抽取**：`extract_order_entities()` 从消息提取电影名、数量、时间、城市

## 相关服务和设备控制文件

- `app/services/xianyu_app_client.py` — ADB 设备控制
- `app/services/xianyu_browser.py` — 闲鱼 Playwright 无头浏览器（浏览器模式，`use_app_mode=false`）
- `app/services/browser/anti_detect.py` — 浏览器反检测（配合 `xianyu_browser.py`）
- `app/services/autojs_device_client.py` — AutoJS 设备通信与命令队列
- `app/services/autojs_router.py` — AutoJS API 路由（含 WebSocket 消息转发 + Agent 回复回传）
- `app/services/openclaw_client.py` — OpenClaw Gateway 桥接客户端（Agent 调用）
- `app/services/notification_driver.py` — `NotificationListener`（Webhook 接收 + 签名验证）、`ADBNotificationWatcher`（ADB 轮询）、`create_notification_endpoints()`（注册 `/api/notifications/*` 路由）
- `app/services/lark_service.py` — 飞书开放 API（发消息、获取用户信息）
- `app/services/lark_websocket_client.py` — 飞书 WebSocket 长连接客户端
- `app/services/lark_mobile_agent.py` — 飞书手机控制 Agent
- `app/modules/lark_agent/router.py` — 飞书 Agent Webhook（手机控制专用）

## 票务模块架构（`app/modules/ticket/`）

- `service.py` — `TicketService` 搜索多平台、创建代购订单
- `price_service.py` — 官方票价查询
- `pricing_engine.py` — 智能报价（成本 + 利润计算）
- `channel_service.py` — 渠道成本管理
- `order_service.py` — 订单生命周期
- `models.py` — Pydantic数据模型
- `router.py` — 票务API路由

## 监控模块架构（`app/modules/monitor/`）

- `service.py` — `MonitorService` + `MovieDataService`（豆瓣/猫眼API）+ `XianyuListingService`
- `scheduler.py` — APScheduler定时任务（每天9点查新片、每30分钟查价格）
- `router.py` — 手动触发接口

## OpenClaw Agent 集成

本项目的闲鱼消息 Agent 由 [OpenClaw](https://docs.openclaw.ai) 框架驱动，而非直接调用 Anthropic API。

### 架构

```
ticket-bot (Python)                    OpenClaw (Node.js)
─────────────────                      ─────────────────
openclaw_client.py  ──CLI subprocess──→ openclaw gateway call agent
  (WebSocket RPC)                      → gateway (ws://127.0.0.1:18789)
                                       → projector agent
                                         → AI model + tools + memory
```

### OpenClaw Gateway

- 地址：`ws://127.0.0.1:18789` (loopback)
- 启动方式：`systemctl --user start openclaw-gateway`（已安装为 systemd daemon）
- 配置文件：`~/.openclaw/openclaw.json`
- Agent ID：`projector`
- Model：`minimax/MiniMax-M2.7-highspeed`（通过 Anthropic Messages API 兼容层）
- 用 `openclaw doctor` 诊断，`openclaw gateway call health` 检查健康状态

### 桥接客户端 (`app/services/openclaw_client.py`)

通过子进程调用 `openclaw gateway call agent` CLI，传递参数：
- `sessionKey: "agent:projector:xianyu:{user_id}"` — 保证每用户会话连续性
- `deliver: false` — Agent 不通过 channel 投递回复，由 ticket-bot 自行处理
- `thinking: low` — 降低延迟
- `idempotencyKey` — 幂等键（每消息 UUID）
- 超时 65 秒，超时或错误返回 `None`

回复提取路径：`result.payloads[0].text`

### 与 CustomerService 的关系

`openclaw_client.py` 处理闲鱼消息的**实时回复**回路。`CustomerService` 保留给：
- 飞书/Lark 聊天路径
- Redis 消息备份和飞书通知
- 消息队列消费（在 `autojs_router.py` 中仍会调用作为备份）

### Device 授权

OpenClaw Gateway 使用 device pairing 授权。若 CLI 报 "scope upgrade pending approval"，
检查 `~/.openclaw/devices/paired.json` 和 `pending.json`，确保设备 `approvedScopes` 包含
`operator.write`（调用 `agent` RPC 方法需要）。

## 配置（`app/config.py`）

`.env` 文件自动加载，所有配置项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `anthropic_api_key` | MiniMax API Key（兼容 Anthropic SDK） | - |
| `anthropic_base_url` | API 地址 | `https://api.minimaxi.com/anthropic` |
| `anthropic_model` | 模型名称 | `MiniMax-M2.7` |
| `anthropic_max_tokens` | 最大输出 token | `1024` |
| `lark_app_id / lark_app_secret` | 飞书应用凭证（客服机器人） | - |
| `lark_agent_app_id / lark_agent_app_secret` | 飞书应用凭证（手机控制专用） | - |
| `redis_url` | Redis 连接 | `redis://localhost:6379/0` |
| `database_url` | PostgreSQL 连接 | `postgresql+asyncpg://...` |
| `use_app_mode` | True=APP 模式，False=浏览器模式 | `false` |
| `xianyu_device_addr` | ADB 设备地址（如 `192.168.1.101:5555`） | - |
| `xianyu_poll_interval` | 消息轮询间隔（秒） | `30` |
| `webhook_secret` | Webhook 签名密钥 | - |
| `service_fee_rate` | 代购手续费率 | `0.05`（5%） |
| `min_service_fee` | 最低代购费（元） | `2.0` |
注意：
- `OPENCLAW_AGENT_ID` 不在 `config.py` 的 `Settings` 类中，由 `openclaw_client.py` 通过 `os.getenv("OPENCLAW_AGENT_ID", "projector")` 直接读取。
- `.env.example` 使用了旧字段名（`CLAUDE_API_KEY`、`CLAUDE_MODEL`、`CLAUDE_MAX_TOKENS`），但 `config.py` 的 Settings 类读取的是 `ANTHROPIC_API_KEY`、`ANTHROPIC_MODEL`、`ANTHROPIC_MAX_TOKENS`。创建 `.env` 时请使用 `config.py` 中的实际字段名。

## 参考文档

- `docs/TECHNICAL_ARCHITECTURE.md` — 完整技术架构
- `docs/AUTOJS_SETUP.md` — AutoJS 手机控制配置指南
- `docs/APP_MODE.md` — APP 模式说明
- `docs/MOBILE_AGENT.md` — MobileAgent 详细文档
