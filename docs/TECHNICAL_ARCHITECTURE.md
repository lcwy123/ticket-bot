# 闲鱼AI助手 - 技术架构文档

## 项目概述

闲鱼AI助手是一个基于 Android 真机控制的自动化客服/票务系统，通过多模态大模型实现手机 APP 的智能操控。

**核心目标**: 让 AI 能够像人一样操作手机 APP（闲鱼），自动处理消息、订单、咨询等业务。

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         服务器端 (Server)                            │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐   ┌──────────────┐   ┌────────────────────────┐   │
│  │   FastAPI   │   │ TaskPlanner  │   │  NotificationListener   │   │
│  │   Web API   │◀──│   任务规划   │◀──│     通知驱动            │   │
│  └──────┬──────┘   └──────┬───────┘   └───────────┬────────────┘   │
│         │                  │                        │                 │
│         │         ┌────────▼────────┐               │                 │
│         │         │  Enhanced      │               │                 │
│         │         │  MobileAgent   │               │                 │
│         │         └───────┬────────┘               │                 │
│         │                 │                        │                 │
│  ┌──────▼─────────────────▼────────────────────────▼──────┐          │
│  │                    XianyuAppClient                    │          │
│  │                   (ADB 命令封装)                       │          │
│  └──────────────────────────┬───────────────────────────┘          │
│                             │ ADB                                     │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         Android 设备                                 │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    闲鱼 APP (闲鱼)                          │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 核心模块

### 1. XianyuAppClient - 设备控制层

**文件**: `app/services/xianyu_app_client.py`

负责与 Android 设备通信，封装 ADB 命令。

#### 核心功能

| 功能 | ADB 命令 | 说明 |
|------|----------|------|
| 截图 | `screencap -p` | 获取屏幕截图 |
| UI 结构 | `uiautomator dump` | 获取界面 XML 层次结构 |
| 启动 APP | `am start` | 启动指定应用 |
| 点击 | `input tap` | 点击屏幕坐标 (需 ROOT) |
| 滑动 | `input swipe` | 滑动屏幕 (需 ROOT) |
| 输入文本 | `input text` | 输入文本 (需 ROOT) |
| 按键 | `input keyevent` | 按 Home/Back 键 |

#### 类设计

```
ADBDevice
├── 封装单个 ADB 命令
├── screenshot() → bytes
├── click(x, y) → bool
├── swipe(x1, y1, x2, y2) → bool
├── input_text(text) → bool
├── dump_ui_xml() → str
└── start_app(package) → bool

XianyuAppClient
├── 业务层封装
├── connect() → 连接设备
├── ensure_app_running() → 确保闲鱼在前台
├── get_conversations() → 获取会话列表
├── read_messages(conv_name) → 读取消息
├── send_message(conv_name, text) → 发送消息
└── screenshot() → bytes
```

#### 权限说明

| 命令 | 需要权限 | 解决方案 |
|------|----------|----------|
| screencap | 无 | 正常工作 |
| uiautomator dump | 无 | 正常工作 |
| am start | 无 | 正常工作 |
| input tap/swipe/text | INJECT_EVENTS | **需要 ROOT** |

---

### 2. EnhancedMobileAgent - 智能代理层

**文件**: `app/services/mobile_agent.py`

基于多模态大模型的智能手机操作代理。

#### 工作流程

```
┌──────────────────────────────────────────────────────┐
│                    MobileAgent                        │
├──────────────────────────────────────────────────────┤
│                                                       │
│  1. screenshot()      截取当前屏幕                     │
│         │                                           │
│         ▼                                           │
│  2. analyze_screen()  发送给 Vision Model            │
│         │                                           │
│         ▼                                           │
│  3. LLM 决策        返回 Operation (click/swipe/...) │
│         │                                           │
│         ▼                                           │
│  4. execute_operation() 执行操作                      │
│         │                                           │
│         ▼                                           │
│  5. 判断是否完成   done? → 结束 : 回到步骤1          │
│                                                       │
└──────────────────────────────────────────────────────┘
```

#### 核心组件

| 组件 | 说明 |
|------|------|
| `ScreenInfo` | 屏幕截图 + UI XML + 尺寸 |
| `Operation` | 操作指令 (click/swipe/input/done/error) |
| `TaskContext` | 任务上下文 (ID、目标、步骤、变量) |
| `OperationRecord` | 操作记录 (每步的结果和截图) |

#### LLM 决策

系统提示词指导模型输出 JSON 格式的操作指令：

```json
{
    "action": "click",
    "x": 500,
    "y": 300,
    "reason": "点击消息入口进入聊天列表",
    "confidence": 0.95,
    "alternatives": [...]
}
```

#### 自我纠错机制

1. **低置信度重试**: confidence < 0.7 时尝试 alternatives
2. **操作失败重试**: 最多重试 2 次
3. **阻塞检测**: 检测到验证码/权限问题立即停止

---

### 3. TaskPlanner - 任务规划层

**文件**: `app/services/task_planner.py`

将复杂任务拆解为可执行步骤。

#### 步骤类型

| 类型 | 说明 |
|------|------|
| `AGENT_TASK` | 调用 MobileAgent 执行任务 |
| `ACTION` | 直接执行动作 |
| `CONDITION` | 条件判断 |
| `LOOP` | 循环执行 |
| `PARALLEL` | 并行执行 |
| `NOTIFY` | 发送通知 |

#### 内置任务模板

**模板 1: 回复所有买家消息**
```
Plan:
  [1] AGENT_TASK: 打开闲鱼APP，进入消息列表
  [2] LOOP: 遍历每个会话
        ├─ [2.1] AGENT_TASK: 读取买家消息
        ├─ [2.2] CONDITION: 是否是订单咨询
        └─ [2.3] AGENT_TASK: 生成并发送回复
```

**模板 2: 处理新订单咨询**
```
Plan:
  [1] AGENT_TASK: 读取最新消息，判断意图
  [2] CONDITION: 是否是订单
  [3] AGENT_TASK: 提取电影信息，查询价格
  [4] NOTIFY: 通知人工确认
```

**模板 3: 主动营销**
```
Plan:
  [1] AGENT_TASK: 筛选最近30天活跃买家
  [2] LOOP: 向每个买家发送优惠信息
```

#### 变量存储

步骤间通过 `context.variables` 共享数据：

```python
planner.variables = {
    "current_message": "你好，我想买票",
    "current_sender": "买家昵称",
    "intent": "order",
    "loop_items": ["买家A", "买家B", ...]
}
```

---

### 4. NotificationDriver - 事件驱动层

**文件**: `app/services/notification_driver.py`

实现事件驱动的通知监听和处理。

#### 触发方式

| 方式 | 说明 |
|------|------|
| Webhook | 外部 APP 推送通知到 `/api/notifications/webhook` |
| ADB 轮询 | 通过 `dumpsys notification` 监控 (需权限) |

#### 通知类型

| 类型 | 说明 |
|------|------|
| `xianyu_message` | 闲鱼新消息 |
| `xianyu_order` | 闲鱼订单 |
| `xianyu_system` | 闲鱼系统通知 |

#### 处理流程

```
收到通知
    │
    ▼
┌─────────────────┐
│ NotificationFilter │ → 过滤广告/推送
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ classify()      │ → 分类为 message/order/system
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ TaskPlanner     │
│ parse_task()   │ → 根据模板生成执行计划
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ execute_plan()  │ → 执行计划
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ MobileAgent     │ → 调用 Agent 执行
└─────────────────┘
```

#### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/notifications/webhook` | POST | 接收通知 |
| `/api/notifications/history` | GET | 获取历史 |
| `/api/notifications/status` | GET | 监听状态 |
| `/api/notifications/enable` | POST | 启用监听 |
| `/api/notifications/disable` | POST | 禁用监听 |

---

### 5. 业务模块

#### 客服模块 (customer_service)

**文件**: `app/modules/customer_service/`

| 文件 | 职责 |
|------|------|
| `message_listener.py` | 消息监听（轮询/Webhook） |
| `service.py` | 意图识别、实体提取 |
| `router.py` | API 路由 |

#### 票务模块 (ticket)

**文件**: `app/modules/ticket/`

| 文件 | 职责 |
|------|------|
| `service.py` | 票务主服务 |
| `pricing_engine.py` | 价格计算引擎 |
| `order_service.py` | 订单管理 |
| `channel_service.py` | 渠道管理（猫眼、淘宝） |

#### 监控模块 (monitor)

**文件**: `app/modules/monitor/`

| 文件 | 职责 |
|------|------|
| `service.py` | 电影票价格监控 |
| `scheduler.py` | 定时任务调度 |
| `router.py` | API 路由 |

---

## API 概览

### Agent API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/agent/status` | GET | 获取 Agent 状态 |
| `/api/agent/task` | POST | 执行单个任务 |
| `/api/agent/plan/status` | GET | 获取当前计划状态 |
| `/api/agent/plan/execute` | POST | 解析并执行计划 |

### 业务 API

| 端点 | 前缀 | 说明 |
|------|------|------|
| `/api/customer-service/*` | 客服 | 消息处理、登录 |
| `/api/ticket/*` | 票务 | 订单、价格查询 |
| `/api/monitor/*` | 监控 | 电影票监控 |

---

## 配置说明

### 环境变量 (.env)

```env
# 应用
APP_NAME=闲鱼AI助手
DEBUG=false

# 数据库
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/db
REDIS_URL=redis://host:6379/0

# MiniMax API (多模态大模型)
ANTHROPIC_API_KEY=your_api_key
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_MODEL=MiniMax-M2.7

# 飞书
LARK_APP_ID=your_app_id
LARK_APP_SECRET=your_app_secret

# 设备 (ADB 模式)
USE_APP_MODE=true
XIANYU_DEVICE_ADDR=192.168.31.101:5555

# Webhook
WEBHOOK_SECRET=your_secret
```

---

## 依赖项

| 依赖 | 版本 | 用途 |
|------|------|------|
| FastAPI | - | Web 框架 |
| APScheduler | - | 定时任务 |
| uiautomator2 | - | 设备控制 (备选) |
| loguru | - | 日志 |
| httpx | - | HTTP 客户端 |
| PIL | - | 图像处理 |

---

## 待完成功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 点击/滑动控制 | 需 ROOT | Android 14 限制 INJECT_EVENTS |
| 通知监听 APP | 待开发 | NotificationListenerService APK |
| 验证码处理 | 待实现 | 人工介入流程 |

---

## 目录结构

```
app/
├── __init__.py
├── main.py                 # FastAPI 入口
├── config.py              # 配置管理
├── services/
│   ├── __init__.py
│   ├── xianyu_app_client.py    # ADB 设备控制
│   ├── mobile_agent.py         # 增强版 MobileAgent
│   ├── task_planner.py         # 任务规划器
│   ├── notification_driver.py   # 通知驱动
│   ├── lark_service.py         # 飞书集成
│   └── browser/
│       └── anti_detect.py      # 浏览器反检测
├── modules/
│   ├── customer_service/
│   │   ├── message_listener.py
│   │   ├── service.py
│   │   └── router.py
│   ├── ticket/
│   │   ├── service.py
│   │   ├── pricing_engine.py
│   │   ├── order_service.py
│   │   └── router.py
│   └── monitor/
│       ├── service.py
│       ├── scheduler.py
│       └── router.py
└── templates/
    └── ticket_admin.html

scripts/
├── test_adb_device.py     # ADB 设备测试
└── test_modules.py        # 模块集成测试

docs/
├── APP_MODE.md            # APP 模式文档
├── MOBILE_AGENT.md        # MobileAgent 文档
└── TECHNICAL_ARCHITECTURE.md  # 本文档
```
