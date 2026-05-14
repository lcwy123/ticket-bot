"""
飞书手机控制Agent服务
通过飞书接收指令，控制手机执行操作
"""
import asyncio
import base64
import json
import httpx
from typing import Optional, Dict, Any
from loguru import logger

from app.config import get_settings

settings = get_settings()


class LarkMobileAgent:
    """飞书手机控制Agent"""

    def __init__(self):
        self.tenant_access_token: Optional[str] = None
        self.token_expires_at: float = 0

    async def get_tenant_token(self) -> str:
        """获取飞书 tenant_access_token"""
        import time
        if self.tenant_access_token and time.time() < self.token_expires_at - 60:
            return self.tenant_access_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token"
        headers = {"Content-Type": "application/json"}
        data = {
            "app_id": settings.lark_agent_app_id,
            "app_secret": settings.lark_agent_app_secret
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=data, timeout=30)
            resp.raise_for_status()
            result = resp.json()

        if result.get("code") != 0:
            raise Exception(f"获取token失败: {result}")

        self.tenant_access_token = result["tenant_access_token"]
        # token有效期2小时，记录过期时间
        self.token_expires_at = result.get("expire", 7200) + time.time()
        return self.tenant_access_token

    async def send_message(self, open_id: str, text: str) -> Dict:
        """发送消息到飞书用户"""
        try:
            from lark_oapi import Client
            from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

            client = Client.builder() \
                .app_id(settings.lark_agent_app_id) \
                .app_secret(settings.lark_agent_app_secret) \
                .build()

            body = CreateMessageRequestBody.builder()
            body.receive_id(open_id)
            body.msg_type("text")
            body.content(json.dumps({"text": text}))

            request = CreateMessageRequest.builder()
            request.receive_id_type("open_id")
            request.request_body(body)

            resp = client.im.v1().message().create(request)

            logger.info(f"发送消息结果: code={resp.code}, msg={resp.msg}")
            return {"success": resp.code == 0, "response": str(resp)}

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {"success": False, "error": str(e)}

    async def analyze_screen_with_minimax(self, base64_image: str, user指令: str) -> Dict[str, Any]:
        """使用MiniMax分析截图并理解用户指令"""
        if not settings.anthropic_api_key:
            return {"success": False, "error": "Minimax API Key未配置"}

        url = f"{settings.anthropic_base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": settings.anthropic_api_key,
            "anthropic-version": "2023-06-01"
        }

        prompt = f"""你是一个手机控制助手。用户请求：{user指令}

分析截图内容，理解界面结构，然后给出操作建议。

你需要用JSON格式回复，包含：
- action: 操作类型 (click/swipe/input/back/home/done)
- x, y: 点击坐标 (如果是click)
- x1, y1, x2, y2: 滑动起点终点 (如果是swipe)
- text: 输入文本 (如果是input)
- reason: 为什么这样操作
- confidence: 置信度 0-1

如果用户请求已完成或无法完成，返回done。"""

        data = {
            "model": settings.anthropic_model,
            "max_tokens": settings.anthropic_max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64_image
                            }
                        },
                        {
                            "type": "text",
                            "text": prompt
                        }
                    ]
                }
            ]
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=data, headers=headers, timeout=60)
            resp.raise_for_status()
            result = resp.json()

        if "content" in result and len(result["content"]) > 0:
            text = result["content"][0].get("text", "")
            try:
                return json.loads(text)
            except:
                return {"success": False, "error": f"解析AI响应失败: {text}"}
        return {"success": False, "error": "AI返回为空"}

    async def process_command(self, user指令: str, open_id: str) -> str:
        """处理用户指令，控制手机并返回结果"""
        from app.services.autojs_device_client import get_command_server

        # 1. 截图
        await self.send_message(open_id, "正在截取屏幕...")

        server = get_command_server()
        device = server.devices.get("my_phone")

        if not device:
            return "手机未连接，请先运行AutoJS脚本"

        # 发送截图命令
        import uuid
        cmd_id = str(uuid.uuid4())[:8]
        from app.services.autojs_device_client import DeviceCommand
        command = DeviceCommand(
            id=cmd_id,
            action="screenshot",
            params={}
        )
        device.pending_commands[cmd_id] = command
        device.command_history.append(command)

        # 等待截图结果（最多30秒）
        for _ in range(300):
            await asyncio.sleep(0.1)
            if command.status != "pending":
                break

        if command.status != "success" or not command.result.get("success"):
            return f"截图失败: {command.result}"

        # 2. 获取截图路径
        screenshot_path = command.result.get("path", "/sdcard/autojs_screenshot.png")

        # 3. 读取截图并转为base64
        # 注意：这里需要通过ADB或其他方式获取图片
        # 由于截图保存在手机本地，我们用ADB拉取
        import subprocess
        local_path = f"/tmp/lark_agent_screenshot_{cmd_id}.png"
        try:
            subprocess.run([
                "adb", "-s", "192.168.31.242:5555",
                "pull", screenshot_path, local_path
            ], check=True, capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            return "截图传输超时"
        except subprocess.CalledProcessError:
            return "截图传输失败"

        with open(local_path, "rb") as f:
            img_data = f.read()
        img_base64 = base64.b64encode(img_data).decode()

        # 4. 分析截图
        await self.send_message(open_id, "正在分析截图...")
        ai_result = await self.analyze_screen_with_minimax(img_base64, user指令)

        if not ai_result.get("success", False) and "error" in ai_result:
            return f"分析失败: {ai_result['error']}"

        action = ai_result.get("action")
        reason = ai_result.get("reason", "")
        confidence = ai_result.get("confidence", 0)

        if action == "done":
            return f"任务已完成：{reason}"

        # 5. 执行操作
        await self.send_message(open_id, f"正在执行：{reason}")

        if action in ["click", "tap"]:
            x = ai_result.get("x", 0)
            y = ai_result.get("y", 0)
            cmd_id = str(uuid.uuid4())[:8]
            command = DeviceCommand(id=cmd_id, action="click", params={"x": x, "y": y})
            device.pending_commands[cmd_id] = command
            device.command_history.append(command)

            for _ in range(300):
                await asyncio.sleep(0.1)
                if command.status != "pending":
                    break

            result = "成功" if command.result.get("success") else "失败"
            return f"点击({x},{y})：{result}\n\n分析：{reason}"

        elif action in ["swipe"]:
            x1 = ai_result.get("x1", 0)
            y1 = ai_result.get("y1", 0)
            x2 = ai_result.get("x2", 0)
            y2 = ai_result.get("y2", 0)
            cmd_id = str(uuid.uuid4())[:8]
            command = DeviceCommand(id=cmd_id, action="swipe", params={
                "x1": x1, "y1": y1, "x2": x2, "y2": y2
            })
            device.pending_commands[cmd_id] = command
            device.command_history.append(command)

            for _ in range(300):
                await asyncio.sleep(0.1)
                if command.status != "pending":
                    break

            result = "成功" if command.result.get("success") else "失败"
            return f"滑动({x1},{y1})→({x2},{y2})：{result}\n\n分析：{reason}"

        elif action in ["input"]:
            text = ai_result.get("text", "")
            cmd_id = str(uuid.uuid4())[:8]
            command = DeviceCommand(id=cmd_id, action="input", params={"text": text})
            device.pending_commands[cmd_id] = command
            device.command_history.append(command)

            for _ in range(300):
                await asyncio.sleep(0.1)
                if command.status != "pending":
                    break

            result = "成功" if command.result.get("success") else "失败"
            return f"输入「{text}」：{result}\n\n分析：{reason}"

        elif action == "back":
            cmd_id = str(uuid.uuid4())[:8]
            command = DeviceCommand(id=cmd_id, action="back", params={})
            device.pending_commands[cmd_id] = command
            device.command_history.append(command)

            for _ in range(300):
                await asyncio.sleep(0.1)
                if command.status != "pending":
                    break

            result = "成功" if command.result.get("success") else "失败"
            return f"返回：{result}\n\n分析：{reason}"

        return f"不支持的操作：{action}\n\n分析：{reason}"


# 全局单例
_lark_agent: Optional[LarkMobileAgent] = None


def get_lark_agent() -> LarkMobileAgent:
    global _lark_agent
    if _lark_agent is None:
        _lark_agent = LarkMobileAgent()
    return _lark_agent
