# AutoJS 手机控制方案

## 概述

通过 AutoJS 实现无需 ROOT 的手机自动化控制：

```
服务器 (Python)          手机 (AutoJS)
      │                        │
      │  ──── HTTP 轮询 ────▶  │  获取指令
      │                        │
      │                        │  AccessibilityService
      │                        │       ↓
      │                        │  执行 click/swipe/input
      │                        │
      ◀ ──── 上报结果 ─────────┘
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `scripts/autojs/autojs_polling.js` | AutoJS 脚本，放在手机上运行 |
| `scripts/autojs/autojs_server.js` | 备选方案（需要插件） |
| `app/services/autojs_device_client.py` | Python 设备客户端 |
| `app/services/autojs_router.py` | FastAPI 路由 |

## 步骤 1: 手机安装 AutoJS

1. 下载 AutoJS
   - 酷安：https://www.coolapk.com/apk/com.tencent.autojs6
   - Google Play：搜索 AutoJS

2. 安装后开启权限
   - 设置 → 无障碍 → 已下载的APP → AutoJS → 开启

## 步骤 2: 配置脚本

编辑 `scripts/autojs/autojs_polling.js`，修改服务器地址：

```javascript
let CONFIG = {
    // 修改为你的服务器地址（服务器运行机器的 IP）
    serverUrl: "http://192.168.x.x:8000/api/agent/device",
    pollInterval: 1000,      // 轮询间隔（毫秒）
    debugMode: true
};
```

## 步骤 3: 传输脚本到手机

方式 A: 通过 ADB push
```bash
adb push scripts/autojs/autojs_polling.js /sdcard/
```

方式 B: 通过局域网共享
- 把脚本放到电脑的共享文件夹
- 手机浏览器访问电脑 IP 下载

## 步骤 4: 运行脚本

1. 手机打开 AutoJS APP
2. 点击右上角"运行"按钮
3. 选择 `autojs_polling.js` 脚本
4. 脚本会在后台运行，定期从服务器获取指令

## 步骤 5: 注册设备

脚本运行后，需要注册设备到服务器：

```bash
curl -X POST "http://服务器IP:8000/api/agent/device/register" \
  -H "Content-Type: application/json" \
  -d '{"device_id": "我的手机", "device_name": "红米手机"}'
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/agent/device/register` | POST | 注册设备 |
| `/api/agent/device/unregister` | POST | 注销设备 |
| `/api/agent/device/command` | GET | 获取命令（AutoJS 调用） |
| `/api/agent/device/result` | POST | 上报结果（AutoJS 调用） |
| `/api/agent/device/status` | GET | 设备状态 |
| `/api/agent/device/devices` | GET | 设备列表 |
| `/api/agent/device/send` | POST | 发送命令（同步） |
| `/api/agent/device/click` | POST | 点击 |
| `/api/agent/device/swipe` | POST | 滑动 |
| `/api/agent/device/input` | POST | 输入 |
| `/api/agent/device/back` | POST | 返回键 |
| `/api/agent/device/home` | POST | Home 键 |
| `/api/agent/device/screenshot` | POST | 截图 |
| `/api/agent/device/find` | POST | 查找元素 |

## 使用示例

### Python 中使用

```python
from app.services.autojs_device_client import (
    device_click,
    device_swipe,
    device_input,
    AutoJSDeviceClient,
    get_command_server
)

# 注册设备
device = AutoJSDeviceClient("my_phone")
server = get_command_server()
server.register_device("my_phone", device)

# 发送命令
await device_click(540, 1200)  # 点击屏幕中央
await device_swipe(540, 1800, 540, 600)  # 向上滑动
await device_input("你好")  # 输入文本
```

### curl 测试

```bash
# 点击
curl -X POST "http://localhost:8000/api/agent/device/click?device_id=my_phone&x=540&y=1200"

# 滑动
curl -X POST "http://localhost:8000/api/agent/device/swipe?device_id=my_phone&x1=540&y1=1800&x2=540&y2=600"

# 查找并点击
curl -X POST "http://localhost:8000/api/agent/device/find?device_id=my_phone&text=消息"

# 截图
curl -X POST "http://localhost:8000/api/agent/device/screenshot?device_id=my_phone"
```

## 支持的指令

| 指令 | 参数 | 说明 |
|------|------|------|
| `click` / `tap` | x, y | 点击坐标 |
| `swipe` | x1, y1, x2, y2, duration | 滑动 |
| `input` | text | 输入文本 |
| `back` | - | 返回键 |
| `home` | - | Home 键 |
| `screenshot` | - | 截图 |
| `getText` | - | 获取界面文本 |
| `find` | text | 查找并点击元素 |

## 注意事项

1. **服务器地址**: 确保手机能访问到服务器地址
2. **网络**: 手机和服务器需要在同一网络，或服务器有公网 IP
3. **权限**: AutoJS 需要辅助功能权限才能正常工作
4. **屏幕**: 手机屏幕不能锁屏，AutoJS 需要保持后台运行

## 故障排查

### 问题: 设备一直显示未连接

1. 检查 AutoJS 脚本是否正在运行
2. 检查 serverUrl 是否配置正确
3. 检查手机网络是否能访问服务器

### 问题: 命令执行成功但没反应

1. 检查辅助功能权限是否开启
2. 检查手机是否在目标 APP 页面

### 问题: 找不到元素

1. 使用 `getText` 获取当前界面文本
2. 使用 `screenshot` 截图确认界面状态
