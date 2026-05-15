"""
AutoJS 设备 API 路由
处理 AutoJS 设备的注册、命令获取和结果上报
"""
from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime
import asyncio
import json
from loguru import logger

from app.services.autojs_device_client import (
    get_command_server,
    DeviceCommandServer,
    AutoJSDeviceClient
)


# WebSocket 连接管理器
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, device_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[device_id] = websocket

    def disconnect(self, device_id: str):
        if device_id in self.active_connections:
            del self.active_connections[device_id]

    async def send_command(self, device_id: str, command: Dict):
        if device_id in self.active_connections:
            await self.active_connections[device_id].send_json({
                "type": "command",
                **command
            })
            return True
        return False

    def is_connected(self, device_id: str) -> bool:
        return device_id in self.active_connections


manager = ConnectionManager()


router = APIRouter(prefix="/api/agent/device", tags=["AutoJS设备"])


class DeviceRegisterRequest(BaseModel):
    """设备注册请求"""
    device_id: str
    device_name: str
    device_info: Dict[str, Any] = {}


class CommandResultRequest(BaseModel):
    """命令结果上报"""
    command_id: str
    result: Dict[str, Any]
    timestamp: Optional[float] = None


@router.post("/register")
async def register_device(request: DeviceRegisterRequest):
    """注册设备"""
    server = get_command_server()

    device = AutoJSDeviceClient(
        device_id=request.device_id,
        server_url=""  # AutoJS 会轮询这个服务器
    )

    server.register_device(request.device_id, device)

    return {
        "success": True,
        "device_id": request.device_id,
        "message": "设备注册成功"
    }


@router.post("/unregister")
async def unregister_device(device_id: str):
    """注销设备"""
    server = get_command_server()
    server.unregister_device(device_id)

    return {
        "success": True,
        "message": "设备已注销"
    }


@router.get("/command")
async def get_command(
    device_id: str = Query(..., description="设备ID"),
    last_id: Optional[str] = Query(None, description="上次执行的命令ID")
):
    """
    获取待执行的命令

    AutoJS 设备定期调用此接口获取需要执行的命令
    自动注册未注册的设备
    """
    server = get_command_server()

    # 自动注册设备（如果不存在）
    if device_id not in server.devices:
        device = AutoJSDeviceClient(device_id=device_id)
        server.register_device(device_id, device)
        logger.info(f"设备自动注册: {device_id}")

    command = server.get_command(device_id, last_id)

    if command is None:
        return {
            "has_command": False,
            "command": None
        }

    return {
        "has_command": True,
        "command": command
    }


class ReportResultRequest(BaseModel):
    command_id: str
    result: Dict[str, Any]
    timestamp: Optional[float] = None


@router.post("/result")
async def report_result(
    device_id: str = Query(..., description="设备ID"),
    request: ReportResultRequest = None
):
    """
    上报命令执行结果

    AutoJS 执行完命令后调用此接口上报结果
    """
    server = get_command_server()

    if request:
        server.report_result(device_id, request.command_id, request.result)

    return {
        "success": True,
        "message": "结果已接收"
    }


@router.get("/status")
async def get_device_status(device_id: str = Query(..., description="设备ID")):
    """获取设备状态"""
    server = get_command_server()

    device = server.devices.get(device_id)
    if not device:
        return {
            "connected": False,
            "device_id": device_id
        }

    return {
        "connected": True,
        "device_id": device_id,
        "status": device.status.value,
        "last_seen": datetime.fromtimestamp(device.last_seen).isoformat() if device.last_seen else None,
        "pending_commands": len([c for c in device.pending_commands.values() if c.status == "pending"]),
        "total_commands": len(device.command_history)
    }


@router.get("/devices")
async def list_devices():
    """列出所有已连接设备"""
    server = get_command_server()

    devices = []
    for device_id, device in server.devices.items():
        devices.append({
            "device_id": device_id,
            "status": device.status.value,
            "last_seen": datetime.fromtimestamp(device.last_seen).isoformat() if device.last_seen else None
        })

    return {
        "total": len(devices),
        "devices": devices
    }


async def queue_command(device_id: str, action: str, params: Dict[str, Any]):
    """将命令加入设备队列（供轮询方式使用）"""
    import uuid
    from app.services.autojs_device_client import get_command_server, DeviceCommand

    server = get_command_server()
    device = server.devices.get(device_id)

    if not device:
        raise HTTPException(status_code=404, detail="设备未连接")

    cmd_id = str(uuid.uuid4())[:8]
    command = DeviceCommand(
        id=cmd_id,
        action=action,
        params=params
    )

    device.pending_commands[cmd_id] = command
    logger.info(f"命令已加入队列: {device_id} - {action} ({cmd_id})")

    return {
        "success": True,
        "command_id": cmd_id,
        "message": "命令已加入队列"
    }


# 直接命令接口（服务器主动发送命令）
class SendCommandRequest(BaseModel):
    device_id: str
    action: str
    params: Optional[Dict[str, Any]] = {}


@router.post("/send")
async def send_command(request: SendCommandRequest):
    """
    发送命令到设备（同步方式）

    调用后会等待命令执行完成并返回结果
    """
    import asyncio
    from app.services.autojs_device_client import get_command_server

    server = get_command_server()

    device_id = request.device_id
    action = request.action
    params = request.params

    device = server.devices.get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="设备未连接")

    result = await device.send_command(action, params or {})

    return {
        "success": result.get("success", False),
        "action": action,
        "result": result
    }


@router.post("/click")
async def click(
    device_id: str = Query(..., description="设备ID"),
    x: int = Query(..., description="X坐标"),
    y: int = Query(..., description="Y坐标")
):
    """点击指定坐标"""
    return await queue_command(device_id, "click", {"x": x, "y": y})


@router.post("/swipe")
async def swipe(
    device_id: str = Query(..., description="设备ID"),
    x1: int = Query(..., description="起点X"),
    y1: int = Query(..., description="起点Y"),
    x2: int = Query(..., description="终点X"),
    y2: int = Query(..., description="终点Y"),
    duration: int = Query(500, description="持续时间(ms)")
):
    """滑动"""
    return await queue_command(device_id, "swipe", {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration": duration
    })


@router.post("/input")
async def input_text(
    device_id: str = Query(..., description="设备ID"),
    text: str = Query(..., description="输入文本")
):
    """输入文本"""
    return await queue_command(device_id, "input", {"text": text})


@router.post("/back")
async def press_back(device_id: str = Query(..., description="设备ID")):
    """按返回键"""
    return await queue_command(device_id, "back", {})


@router.post("/home")
async def press_home(device_id: str = Query(..., description="设备ID")):
    """按 Home 键"""
    return await queue_command(device_id, "home", {})


@router.post("/screenshot")
async def screenshot(device_id: str = Query(..., description="设备ID")):
    """截图"""
    return await queue_command(device_id, "screenshot", {})


@router.post("/find")
async def find_and_click(
    device_id: str = Query(..., description="设备ID"),
    text: str = Query(..., description="要查找的文本")
):
    """查找并点击包含指定文本的元素"""
    return await queue_command(device_id, "find", {"text": text})


@router.post("/launch")
async def launch_app(
    device_id: str = Query(..., description="设备ID"),
    app: str = Query(..., description="APP名称")
):
    """启动APP"""
    return await queue_command(device_id, "launch", {"app": app})


# ========== WebSocket 接口 ==========
@router.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    """
    WebSocket 长连接端点

    手机通过 WebSocket 连接服务器，接收指令并上报结果
    """
    await manager.connect(device_id, websocket)
    logger.info(f"WebSocket 连接已建立: {device_id}")

    # 立即发送连接确认，让手机知道连接成功
    try:
        await websocket.send_json({"type": "connected", "device_id": device_id})
        logger.info(f"连接确认已发送: {device_id}")
    except Exception as e:
        logger.error(f"发送连接确认失败: {e}")

    # 注册设备
    server = get_command_server()
    device = AutoJSDeviceClient(device_id=device_id)
    server.register_device(device_id, device)

    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()

            try:
                msg = json.loads(data)
                msg_type = msg.get("type")

                if msg_type == "register":
                    # 设备注册
                    device_name = msg.get("device_name", "Unknown")
                    logger.info(f"WebSocket 设备注册: {device_id} ({device_name})")
                    await websocket.send_json({
                        "type": "registered",
                        "device_id": device_id
                    })

                elif msg_type == "result":
                    # 上报命令结果
                    command_id = msg.get("command_id")
                    result = msg.get("result", {})
                    server.report_result(device_id, command_id, result)
                    logger.info(f"收到结果: {command_id} -> {result}")

                elif msg_type == "pong":
                    # 心跳回复
                    logger.debug(f"收到 pong from {device_id}")

                elif msg_type == "message":
                    # 手机端转发闲鱼消息
                    user_id = msg.get("user_id", "unknown")
                    content = msg.get("content", "")
                    source = msg.get("source", "xianyu_app")
                    timestamp = msg.get("timestamp", asyncio.get_event_loop().time())
                    logger.info(f"收到手机消息: {user_id} -> {content[:30]}...")

                    # 转发到客服队列
                    from app.modules.customer_service.service import CustomerService, MessageSource, ChatMessage
                    service = CustomerService()
                    chat_msg = ChatMessage(
                        source=MessageSource.XIANYU,
                        user_id=user_id,
                        content=content,
                        session_id="",
                        timestamp=timestamp,
                        metadata={"device_id": device_id, "from_phone": True, "source": source}
                    )

                    await service.queue_message(chat_msg)

                    # 触发后台处理
                    asyncio.create_task(service.process_message_queue())

                    # 回复确认
                    await websocket.send_json({
                        "type": "message_received",
                        "status": "ok",
                        "user_id": user_id
                    })

            except json.JSONDecodeError:
                logger.error(f"JSON 解析失败: {data}")

    except WebSocketDisconnect:
        logger.info(f"WebSocket 断开: {device_id}")
    except Exception as e:
        logger.error(f"WebSocket 错误: {e}")
    finally:
        manager.disconnect(device_id)


class WsSendCommandRequest(BaseModel):
    device_id: str
    action: str
    params: Optional[Dict[str, Any]] = {}


@router.post("/ws/send")
async def ws_send_command(request: WsSendCommandRequest):
    """
    通过 WebSocket 发送命令到设备
    """
    import uuid
    cmd_id = str(uuid.uuid4())[:8]

    command = {
        "id": cmd_id,
        "action": request.action,
        **(request.params or {})
    }

    success = await manager.send_command(request.device_id, command)

    if not success:
        raise HTTPException(status_code=404, detail="设备未连接或WebSocket未建立")

    return {
        "success": True,
        "command_id": cmd_id,
        "message": "命令已发送"
    }
