# 闲鱼APP模式

## 概述

由于网页版闲鱼存在功能限制（动态DOM、无法接收实时推送、频繁验证码），项目支持通过**Android真机 + APP客户端**的方式来监听和回复消息。

## 架构

```
┌─────────────────────────────────────────┐
│           阿里云 Linux Server             │
│                                          │
│  ┌──────────────────────────────────┐   │
│  │  Python 控制层                     │   │
│  │  - uiautomator2 (ATX客户端)       │   │
│  │  - message_listener.py           │   │
│  └──────────────────────────────────┘   │
│                    │                     │
│                    │ ADB (通过网络)      │
│                    │                     │
│  ┌──────────────────────────────────┐   │
│  │   Android真机                     │   │
│  │  ┌──────────────────────────┐   │   │
│  │  │      闲鱼 APP             │   │   │
│  │  │   + ATX_agent (常驻)      │   │   │
│  │  │   + frpc (内网穿透)       │   │   │
│  │  └──────────────────────────┘   │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

## 环境要求

### 服务器端
- Linux服务器（阿里云）
- Python 3.8+
- ADB (Android Debug Bridge)

### 手机端
- Android 7.0+
- 已获取ROOT权限（或安装ATX-agent）
- 闲鱼APP已登录

## 安装步骤

### 1. 服务器端安装

```bash
# 安装ADB
sudo apt-get install android-tools-adb

# 安装python-uiautomator2
pip install uiautomator2

# 运行内网穿透设置脚本
sudo bash scripts/setup_xianyu_tunnel.sh
```

### 2. 手机端设置

#### 方案A: 使用FRP内网穿透（推荐）

1. 在手机上安装FRP客户端
   - 推荐使用 [HBTaleb/frp](https://github.com/HBTaleb/frp) 或 Termux

2. 配置FRP客户端 (`frpc.ini`):
```ini
[common]
server_addr = 你的服务器IP
server_port = 7000
token = 你的token

[adb]
type = tcp
local_ip = 127.0.0.1
local_port = 5555
remote_port = 5555
```

3. 启动FRP客户端并确保连接成功

#### 方案B: 使用阿里云APP的SSH反向隧道

如果手机使用阿里云APP连接服务器，可以使用SSH反向隧道：
```bash
# 在手机端（通过阿里云APP的终端）
ssh -R 5555:localhost:5555 user@服务器IP
```

### 3. 测试连接

```bash
# 测试APP客户端
python scripts/test_xianyu_app_client.py

# 如果连接成功，应该能看到设备信息
```

### 4. 配置项目

在 `.env` 文件中添加：

```bash
# 启用APP模式
USE_APP_MODE=true

# 设备地址（留空则自动发现）
XIANYU_DEVICE_ADDR=

# 消息轮询间隔(秒)
XIANYU_POLL_INTERVAL=30
```

## 使用方法

### 启动服务

```bash
# 启动主服务
python -m app.main
```

服务启动时会自动检测 `USE_APP_MODE` 配置：
- `USE_APP_MODE=true`: 使用APP模式
- `USE_APP_MODE=false` 或 未设置: 使用浏览器模式

### 查看日志

```bash
# 查看监听日志
tail -f logs/xianyu_listener.log
```

## 故障排查

### 问题1: 设备未发现
```
RuntimeError: No Android device found
```
解决：
1. 检查手机是否已连接 `adb devices`
2. 检查FRP是否正常运行
3. 检查防火墙是否开放了5555端口

### 问题2: ATX连接失败
```
ConnectionError: Cannot connect to ATX agent
```
解决：
1. 在手机上安装ATX-agent: `adb install atx-agent.apk`
2. 启动ATX-agent: `adb shell am start -n com.github.uiautomator/.Server`

### 问题3: 闲鱼APP UI元素定位失败

APP版本更新后UI可能变化，需要更新定位逻辑：
1. 截图分析UI结构: `adb exec-out uiautomator dump /dev/stdin`
2. 根据实际UI调整 `xianyu_app_client.py` 中的选择器

## 性能对比

| 模式 | 资源占用 | 稳定性 | 实时性 |
|------|----------|--------|--------|
| 浏览器模式 | 中 | 中 | 30秒轮询 |
| APP模式 | 低 | 高 | 5-10秒轮询 |

## 注意事项

1. **手机保持亮屏**: 设置手机不息屏，避免APP进入后台
2. **网络稳定**: 确保手机网络稳定，断线会影响消息接收
3. **闲鱼更新**: 闲鱼APP更新后可能需要更新UI定位代码
4. **验证码**: 闲鱼可能弹出验证码，需要人工处理
