# Mobile Agent 使用文档

## 概述

Mobile Agent 是一个基于多模态大模型的智能手机操作助手。它能够：

1. **视觉理解** - 分析当前屏幕截图，理解界面内容
2. **智能决策** - 根据任务目标决定下一步操作
3. **自动执行** - 点击、滑动、输入等操作
4. **自适应** - 不依赖硬编码UI选择器，能适应APP更新

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                    Mobile Agent                         │
├─────────────────────────────────────────────────────────┤
│  1. Screenshot  →  截图当前屏幕                         │
│  2. Vision Model → 发送给多模态大模型分析               │
│  3. Parse       →  解析操作决策(click/swipe/input)    │
│  4. Execute     →  执行操作                            │
│  5. Loop        →  重复直到完成                        │
└─────────────────────────────────────────────────────────┘
```

## 使用方式

### 1. 基本用法

```python
from app.services.mobile_agent import MobileAgent, execute_task
from app.services.xianyu_app_client import XianyuAppClient

# 连接设备
client = XianyuAppClient()
client.connect()

# 执行任务
result = await execute_task(
    device_client=client,
    task="打开闲鱼APP，点击消息tab，查看最新消息",
    max_steps=15
)

print(result)
# {'success': True, 'steps': 5, 'reason': '已完成查看消息'}
```

### 2. 直接使用Agent类

```python
agent = MobileAgent(device_client=client)

# 单次执行
screen = agent.screenshot()  # 截图
operation = agent.analyze_screen(screen, task="查看消息")  # 分析
agent.execute_operation(operation)  # 执行

# 完整运行
result = agent.run("打开闲鱼查看最新消息")
```

### 3. 内置任务预设

```python
from app.services.mobile_agent import TASK_PRESETS

# 查看可用预设
print(TASK_PRESETS.keys())
# ['查看消息', '回复消息', '发布商品', '查看订单']

# 使用预设
result = await execute_task(client, TASK_PRESETS["查看消息"])
```

## 支持的操作

| 操作 | 说明 | 参数 |
|------|------|------|
| `click x y` | 点击坐标 | x,y: 0-1000比例 |
| `swipe direction` | 滑动 | direction: up/down/left/right |
| `input text` | 输入文本 | text: 要输入的文字 |
| `wait seconds` | 等待 | seconds: 秒数 |
| `done` | 任务完成 | - |
| `error` | 操作错误 | - |

## 注意事项

1. **坐标系统** - 使用0-1000比例坐标系，自动适配不同分辨率
2. **操作限制** - 默认最多20步，可通过max_steps调整
3. **等待时间** - 每次操作后等待1秒让UI更新
4. **API依赖** - 需要配置多模态大模型API

## 配置

在 `.env` 中确保有：

```bash
ANTHROPIC_API_KEY=your_api_key
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic
ANTHROPIC_MODEL=your_model_name
```

## 示例场景

### 场景1: 自动回复买家消息

```python
task = """打开闲鱼APP的消息列表，找到最新的买家对话，
读取买家的问题，然后发送回复: 您好，您的订单已确认，我们会尽快处理。"""

result = await execute_task(client, task)
```

### 场景2: 自动发布商品

```python
task = """打开闲鱼APP，点击发布按钮，填写电影票信息:
- 标题: 代购哪吒之魔童闹海电影票
- 价格: 35元
- 描述: 代购电影票，影院取票"""

result = await execute_task(client, task)
```

### 场景3: 查询订单

```python
task = """打开闲鱼APP，进入我的页面，点击我的订单，
查看所有订单状态"""

result = await execute_task(client, task)
```

## 未来扩展

1. **记忆模块** - 跨任务记忆界面状态
2. **自我纠错** - 操作失败时尝试替代方案
3. **多模态反馈** - 不仅执行操作，还能总结屏幕内容回复用户
4. **异常处理** - 更好的验证码检测和应对
