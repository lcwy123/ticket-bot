"""
AutoJS 设备客户端 - 与手机上的 AutoJS 脚本通信
通过 HTTP 轮询模式，让服务器可以控制手机执行操作

使用方式：
1. 手机安装 AutoJS，安装 autojs_polling.js 脚本
2. 开启辅助功能权限
3. 运行脚本
4. 服务器通过此类发送指令
"""
import asyncio
import httpx
import time
import uuid
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from loguru import logger
from enum import Enum

from app.config import get_settings

settings = get_settings()


class DeviceStatus(Enum):
    """设备状态"""
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class DeviceCommand:
    """设备命令"""
    id: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    result: Optional[Dict] = None
    status: str = "pending"  # pending, executed, failed


class AutoJSDeviceClient:
    """
    AutoJS 设备客户端

    工作原理：
    1. 手机上运行 AutoJS 脚本，脚本定期从服务器获取指令
    2. 服务器通过此类存储指令，AutoJS 轮询获取并执行
    3. 执行结果由 AutoJS 上报到服务器
    """

    def __init__(
        self,
        device_id: str,
        server_url: str = None,
        poll_interval: float = 1.0
    ):
        """
        Args:
            device_id: 设备标识
            server_url: 服务器 URL（AutoJS 脚本会访问此地址）
            poll_interval: 轮询间隔
        """
        self.device_id = device_id
        self.server_url = server_url or f"http://localhost:8000/api/agent/device/{device_id}"
        self.poll_interval = poll_interval
        self.status = DeviceStatus.DISCONNECTED
        self.last_seen: float = 0
        self.pending_commands: Dict[str, DeviceCommand] = {}
        self.command_history: List[DeviceCommand] = []

    async def send_command(
        self,
        action: str,
        params: Dict[str, Any] = None,
        timeout: float = 30.0
    ) -> Dict:
        """
        发送命令到设备

        Args:
            action: 命令动作 (click, swipe, input, back, home, screenshot, getText, find)
            params: 命令参数
            timeout: 超时时间（秒）

        Returns:
            执行结果
        """
        cmd_id = str(uuid.uuid4())[:8]
        command = DeviceCommand(
            id=cmd_id,
            action=action,
            params=params or {}
        )

        # 存储命令
        self.pending_commands[cmd_id] = command
        self.command_history.append(command)

        # 限制历史记录大小
        if len(self.command_history) > 100:
            self.command_history = self.command_history[-100:]

        logger.info(f"[{self.device_id}] 发送命令: {action} {params}")

        # 等待命令执行结果
        start_time = time.time()
        while time.time() - start_time < timeout:
            if command.status != "pending":
                logger.info(f"[{self.device_id}] 命令完成: {command.status}, result: {command.result}")
                return command.result or {"success": False, "error": "no result"}

            await asyncio.sleep(0.1)

        # 超时
        command.status = "failed"
        command.result = {"success": False, "error": "timeout"}
        return {"success": False, "error": "timeout"}


class DeviceCommandServer:
    """
    设备命令服务器

    AutoJS 设备通过 HTTP 轮询获取命令并上报结果
    """

    def __init__(self):
        self.devices: Dict[str, AutoJSDeviceClient] = {}

    def register_device(self, device_id: str, device: AutoJSDeviceClient):
        """注册设备"""
        self.devices[device_id] = device
        device.status = DeviceStatus.CONNECTED
        device.last_seen = time.time()
        logger.info(f"设备已注册: {device_id}")

    def get_command(self, device_id: str, last_id: str = None) -> Optional[Dict]:
        """
        获取待执行命令（供 AutoJS 轮询调用）

        Args:
            device_id: 设备ID
            last_id: 上次执行的命令ID

        Returns:
            命令字典，如果没有新命令返回 None
        """
        device = self.devices.get(device_id)
        if not device:
            return None

        device.last_seen = time.time()

        # 查找最新待执行的命令
        for cmd in sorted(device.pending_commands.values(), key=lambda c: c.timestamp):
            if cmd.status == "pending":
                return {
                    "id": cmd.id,
                    "action": cmd.action,
                    "x": cmd.params.get("x"),
                    "y": cmd.params.get("y"),
                    "x1": cmd.params.get("x1"),
                    "y1": cmd.params.get("y1"),
                    "x2": cmd.params.get("x2"),
                    "y2": cmd.params.get("y2"),
                    "text": cmd.params.get("text"),
                    "duration": cmd.params.get("duration", 500),
                    "app": cmd.params.get("app"),
                }

        return None

    def report_result(self, device_id: str, command_id: str, result: Dict):
        """
        上报命令执行结果

        Args:
            device_id: 设备ID
            command_id: 命令ID
            result: 执行结果
        """
        device = self.devices.get(device_id)
        if not device:
            logger.warning(f"未知设备 {device_id} 上报结果")
            return

        cmd = device.pending_commands.get(command_id)
        if cmd:
            cmd.result = result
            cmd.status = "success" if result.get("success") else "failed"
            logger.info(f"[{device_id}] 命令 {command_id} 执行{cmd.status}: {result}")

    def unregister_device(self, device_id: str):
        """注销设备"""
        if device_id in self.devices:
            self.devices[device_id].status = DeviceStatus.DISCONNECTED
            del self.devices[device_id]
            logger.info(f"设备已注销: {device_id}")


# 全局命令服务器实例
_command_server: Optional[DeviceCommandServer] = None


def get_command_server() -> DeviceCommandServer:
    """获取命令服务器实例"""
    global _command_server
    if _command_server is None:
        _command_server = DeviceCommandServer()
    return _command_server


# 便捷函数
async def device_click(x: int, y: int, device_id: str = "default") -> Dict:
    """点击"""
    server = get_command_server()
    if device_id not in server.devices:
        return {"success": False, "error": "设备未连接"}
    return await server.devices[device_id].send_command("click", {"x": x, "y": y})


async def device_swipe(
    x1: int, y1: int, x2: int, y2: int,
    duration: int = 500,
    device_id: str = "default"
) -> Dict:
    """滑动"""
    server = get_command_server()
    if device_id not in server.devices:
        return {"success": False, "error": "设备未连接"}
    return await server.devices[device_id].send_command("swipe", {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration
    })


async def device_input(text: str, device_id: str = "default") -> Dict:
    """输入文本"""
    server = get_command_server()
    if device_id not in server.devices:
        return {"success": False, "error": "设备未连接"}
    return await server.devices[device_id].send_command("input", {"text": text})


async def device_back(device_id: str = "default") -> Dict:
    """按返回键"""
    server = get_command_server()
    if device_id not in server.devices:
        return {"success": False, "error": "设备未连接"}
    return await server.devices[device_id].send_command("back")


async def device_home(device_id: str = "default") -> Dict:
    """按 Home 键"""
    server = get_command_server()
    if device_id not in server.devices:
        return {"success": False, "error": "设备未连接"}
    return await server.devices[device_id].send_command("home")


async def device_screenshot(device_id: str = "default") -> Dict:
    """截图"""
    server = get_command_server()
    if device_id not in server.devices:
        return {"success": False, "error": "设备未连接"}
    return await server.devices[device_id].send_command("screenshot")


async def device_get_text(device_id: str = "default") -> Dict:
    """获取界面文本"""
    server = get_command_server()
    if device_id not in server.devices:
        return {"success": False, "error": "设备未连接"}
    return await server.devices[device_id].send_command("getText")


async def device_find(text: str, device_id: str = "default") -> Dict:
    """查找并点击元素"""
    server = get_command_server()
    if device_id not in server.devices:
        return {"success": False, "error": "设备未连接"}
    return await server.devices[device_id].send_command("find", {"text": text})
