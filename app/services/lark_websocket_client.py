"""
飞书 WebSocket 长连接客户端
使用飞书官方 SDK 建立长连接接收消息
"""
import asyncio
import base64
import json
import os
import threading
from typing import Optional
from loguru import logger

from lark_oapi.ws import Client as WSClient
from lark_oapi.event.dispatcher_handler import EventDispatcherHandler

from app.config import get_settings
from app.services.lark_mobile_agent import LarkMobileAgent

settings = get_settings()


class LarkWSClient:
    """飞书 WebSocket 长连接客户端"""

    def __init__(self):
        self.client: Optional[WSClient] = None
        self.agent = LarkMobileAgent()
        self.running = False
        self._thread = None

    def start(self):
        """启动飞书长连接"""
        if self.running:
            logger.warning("飞书客户端已在运行中")
            return

        logger.info("启动飞书 WebSocket 客户端...")

        try:
            # 创建事件处理器
            handler = EventDispatcherHandler.builder(
                "",  # encrypt_key (长连接模式不需要)
                ""   # verification_token (长连接模式不需要)
            ).register_p2_im_message_receive_v1(self._on_im_message_receive).build()

            # 创建客户端
            self.client = WSClient(
                settings.lark_agent_app_id,
                settings.lark_agent_app_secret,
                event_handler=handler
            )

            # 在独立线程中启动
            self._thread = threading.Thread(target=self._run_in_thread, daemon=True)
            self._thread.start()
            self.running = True

            logger.info("飞书 WebSocket 客户端已启动")

        except Exception as e:
            logger.error(f"启动飞书客户端失败: {e}")
            raise

    def _run_in_thread(self):
        """在新线程中运行客户端"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_async())
        except Exception as e:
            logger.error(f"飞书客户端运行异常: {e}")

    async def _run_async(self):
        """异步运行客户端"""
        if self.client:
            try:
                self.client.start()
            except Exception as e:
                logger.error(f"飞书客户端运行异常: {e}")

    def _on_im_message_receive(self, data):
        """处理消息接收事件"""
        try:
            logger.info(f"收到飞书事件数据类型: {type(data)}")

            # 从 data.event 获取消息数据
            event = getattr(data, 'event', None)
            if not event:
                logger.warning("无法获取 event 对象")
                return

            message = getattr(event, 'message', None)
            sender = getattr(event, 'sender', None)

            if not message:
                logger.warning("无法获取 message 对象")
                return

            # 获取消息类型
            message_type = getattr(message, 'message_type', None)
            logger.info(f"message_type: {message_type}")

            if message_type != "text":
                logger.info(f"忽略非文本消息: {message_type}")
                return

            # 获取文本内容
            content = getattr(message, 'content', None)
            logger.info(f"content: {content}")

            text_content = ""
            if content:
                try:
                    text_content = json.loads(content).get("text", "").strip()
                except:
                    text_content = str(content).strip()

            # 获取发送者 open_id
            open_id = None
            if sender:
                sender_id_obj = getattr(sender, 'sender_id', None)
                if sender_id_obj:
                    open_id = getattr(sender_id_obj, 'open_id', None)
                    if open_id is None:
                        open_id = getattr(sender_id_obj, 'user_id', None)
                    if open_id is None:
                        open_id = getattr(sender_id_obj, 'union_id', None)

            logger.info(f"open_id: {open_id}, text: {text_content}")

            if not open_id:
                logger.warning("无法获取发送者open_id")
                return

            # 异步处理消息
            asyncio.create_task(self._process_message(str(open_id), text_content))

        except Exception as e:
            logger.error(f"处理消息异常: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def _process_message(self, open_id: str, text: str):
        """处理用户消息"""
        try:
            # 发送处理中消息
            await self.agent.send_message(open_id, "收到指令，正在处理...")

            # 处理命令并获取结果
            result = await self.agent.process_command(text, open_id)

            # 发送结果
            await self.agent.send_message(open_id, result)

        except Exception as e:
            logger.error(f"处理消息失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            await self.agent.send_message(open_id, f"处理失败: {str(e)}")

    def stop(self):
        """停止客户端"""
        if self.client:
            self.client.stop()
        self.running = False
        logger.info("飞书 WebSocket 客户端已停止")


# 全局单例
_lark_ws_client: Optional[LarkWSClient] = None


def get_lark_ws_client() -> LarkWSClient:
    global _lark_ws_client
    if _lark_ws_client is None:
        _lark_ws_client = LarkWSClient()
    return _lark_ws_client


def start_lark_ws_client():
    """启动飞书 WebSocket 客户端（供 main.py 调用）"""
    client = get_lark_ws_client()
    client.start()
    return client
