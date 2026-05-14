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

# 安装浏览器驱动
python scripts/install_browser.py

# 启动应用
python -m app.main
# 或
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 运行测试
pytest tests/ -v
pytest tests/test_customer_service.py::test_customer_service_chat -v  # 单个测试
```

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

### System Prompt

```
你是一个闲鱼平台的AI客服助手，专门帮助用户解答关于电影票购买的问题。
可以帮用户：解答价格咨询、推荐热门电影、说明购票流程、处理售后问题
```

### 相关服务

- **`app/services/lark_service.py`** — 飞书开放API（发消息、获取用户信息）
- **`app/modules/lark_agent/router.py`** — 飞书Agent Webhook（手机控制专用）
- **`app/services/notification_driver.py`** — Webhook端点 + ADB通知监控

## 票务模块架构（`app/modules/ticket/`）

- `service.py` — `TicketService` 搜索多平台、创建代购订单
- `price_service.py` — 官方票价查询
- `pricing_engine.py` — 智能报价（成本 + 利润计算）
- `channel_service.py` — 渠道成本管理
- `order_service.py` — 订单生命周期
- `router.py` — 票务API路由

## 监控模块架构（`app/modules/monitor/`）

- `service.py` — `MonitorService` + `MovieDataService`（豆瓣/猫眼API）+ `XianyuListingService`
- `scheduler.py` — APScheduler定时任务（每天9点查新片、每30分钟查价格）
- `router.py` — 手动触发接口

## 配置（`app/config.py`）

| 配置项 | 说明 |
|--------|------|
| `anthropic_api_key/base_url/model` | AI模型配置（MiniMax） |
| `lark_app_id/secret` | 飞书应用凭证 |
| `redis_url` | Redis连接 |
| `service_fee_rate` | 代购手续费率（默认5%） |
| `min_service_fee` | 最低代购费（默认2元） |
| `use_app_mode` | True=APP模式，False=浏览器模式 |
