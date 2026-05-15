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

### AutoJS WebSocket 消息转发

手机通过 WebSocket (`/api/agent/device/ws/{device_id}`) 连接后，可将闲鱼消息实时转发到客服队列：
```
手机 WebSocket → 收到 type="message" → ChatMessage → CustomerService.queue_message()
```

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
   用户消息 → 消息队列(Redis) → AI处理 → 回复 → 存储会话历史
                                    ↓
                           闲鱼消息 → 飞书通知(LarkService)
   ```

3. **AI对话核心**（`CustomerService`）：
   - `chat()` — 基础对话，使用 Anthropic/MiniMax API
   - `chat_with_context()` — 带用户上下文的对话（用户名、订单、偏好）
   - `queue_message()` — 消息入队
   - `process_message_queue()` — 后台消费队列

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
- `app/services/autojs_device_client.py` — AutoJS 设备通信与命令队列
- `app/services/autojs_router.py` — AutoJS API 路由（含 WebSocket 消息转发）
- `app/services/lark_service.py` — 飞书开放 API（发消息、获取用户信息）
- `app/services/lark_websocket_client.py` — 飞书 WebSocket 长连接客户端
- `app/services/lark_mobile_agent.py` — 飞书手机控制 Agent
- `app/modules/lark_agent/router.py` — 飞书 Agent Webhook（手机控制专用）
- `app/services/browser/anti_detect.py` — 浏览器反检测（浏览器模式）

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

注意：`.env.example` 使用旧字段名 `CLAUDE_API_KEY`，实际配置读取的是 `ANTHROPIC_API_KEY`。

## 参考文档

- `docs/TECHNICAL_ARCHITECTURE.md` — 完整技术架构
- `docs/AUTOJS_SETUP.md` — AutoJS 手机控制配置指南
- `docs/APP_MODE.md` — APP 模式说明
- `docs/MOBILE_AGENT.md` — MobileAgent 详细文档
