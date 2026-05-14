"""
Notification Driver - 通知驱动模块
实现事件驱动的手机通知监听和处理
"""
import asyncio
import hashlib
import hmac
import time
import uuid
import json
from typing import Optional, List, Dict, Callable, Any
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger
from fastapi import FastAPI, Request, HTTPException, Header
from pydantic import BaseModel

from app.config import get_settings
from app.services.task_planner import TaskPlanner, NotificationHandler

settings = get_settings()


class NotificationType(Enum):
    """通知类型"""
    XIANYU_MESSAGE = "xianyu_message"  # 闲鱼新消息
    XIANYU_ORDER = "xianyu_order"  # 闲鱼订单
    XIANYU_SYSTEM = "xianyu_system"  # 闲鱼系统通知
    PHONE_CALL = "phone_call"  # 电话
    SMS = "sms"  # 短信
    OTHER = "other"  # 其他


@dataclass
class Notification:
    """通知数据模型"""
    notif_id: str
    type: NotificationType
    source: str  # 来源包名/应用名
    title: str  # 通知标题
    content: str  # 通知内容
    timestamp: float = field(default_factory=time.time)
    raw_data: Dict = field(default_factory=dict)  # 原始数据
    processed: bool = False
    process_result: Any = None


class NotificationFilter:
    """通知过滤器"""

    # 需要关注的包名
    INTERESTED_PACKAGES = {
        "com.taobao.idlefish": ["message", "order", "system"],
        "com.taobao.android": ["message"],
    }

    # 忽略的通知关键词
    IGNORE_KEYWORDS = [
        "广告", "推送", "促销", "营销",
        "系统更新", "版本更新", "下载",
    ]

    # 关键词映射到通知类型
    KEYWORD_TO_TYPE = {
        "消息": NotificationType.XIANYU_MESSAGE,
        "订单": NotificationType.XIANYU_ORDER,
        "下单": NotificationType.XIANYU_ORDER,
        "购买": NotificationType.XIANYU_ORDER,
        "电影票": NotificationType.XIANYU_ORDER,
        "影院": NotificationType.XIANYU_ORDER,
    }

    @classmethod
    def should_process(cls, source: str, title: str, content: str) -> bool:
        """判断是否应该处理此通知"""
        # 检查来源
        if source not in cls.INTERESTED_PACKAGES:
            return False

        # 检查是否包含忽略关键词
        full_text = title + content
        for keyword in cls.IGNORE_KEYWORDS:
            if keyword in full_text:
                return False

        return True

    @classmethod
    def classify(cls, title: str, content: str) -> NotificationType:
        """分类通知"""
        full_text = title + content

        for keyword, notif_type in cls.KEYWORD_TO_TYPE.items():
            if keyword in full_text:
                return notif_type

        return NotificationType.XIANYU_MESSAGE  # 默认当作消息处理


class NotificationListener:
    """
    通知监听器

    支持两种模式：
    1. Webhook 模式 - 接收外部推送的通知
    2. 轮询模式 - 通过 ADB 轮询通知（未来扩展）
    """

    def __init__(
        self,
        task_planner: TaskPlanner,
        notification_handler: NotificationHandler,
        webhook_secret: str = None
    ):
        self.task_planner = task_planner
        self.notification_handler = notification_handler
        self.webhook_secret = webhook_secret or getattr(settings, "webhook_secret", None) or "default_secret"
        self.enabled = True
        self.notification_history: List[Notification] = []
        self.max_history = 100

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        timestamp: str
    ) -> bool:
        """验证 Webhook 签名"""
        if not self.webhook_secret:
            return True

        # 构造签名
        message = timestamp.encode() + payload
        expected_signature = hmac.new(
            self.webhook_secret.encode(),
            message,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(f"sha256={expected_signature}", signature)

    async def receive_webhook(
        self,
        request: Request,
        x_signature: str = Header(None),
        x_timestamp: str = Header(None)
    ) -> Dict:
        """
        接收 Webhook 通知

        请求体格式:
        {
            "source": "xianyu",
            "type": "message",
            "title": "新消息",
            "content": "买家: 你好，我想买票",
            "sender": "买家昵称",
            "extra": {}
        }
        """
        # 读取请求体
        body = await request.body()

        # 验证签名（如果有）
        if x_signature and x_timestamp:
            if not self.verify_webhook_signature(body, x_signature, x_timestamp):
                logger.warning("Webhook 签名验证失败")
                raise HTTPException(status_code=401, detail="Invalid signature")

        # 解析通知数据
        try:
            data = json.loads(body.decode())
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        # 构建通知对象
        notif_type_str = data.get("type", "message")
        notif_type = NotificationType.XIANYU_MESSAGE
        if notif_type_str == "order":
            notif_type = NotificationType.XIANYU_ORDER
        elif notif_type_str == "system":
            notif_type = NotificationType.XIANYU_SYSTEM

        notification = Notification(
            notif_id=str(uuid.uuid4())[:8],
            type=notif_type,
            source=data.get("source", "unknown"),
            title=data.get("title", ""),
            content=data.get("content", ""),
            raw_data=data
        )

        # 过滤
        if not NotificationFilter.should_process(
            notification.source,
            notification.title,
            notification.content
        ):
            logger.debug(f"通知被过滤: {notification.source} - {notification.title}")
            return {
                "success": True,
                "message": "filtered",
                "notif_id": notification.notif_id
            }

        # 分类（如果未指定）
        if notification.type == NotificationType.XIANYU_MESSAGE:
            notification.type = NotificationFilter.classify(
                notification.title,
                notification.content
            )

        # 处理通知
        result = await self._process_notification(notification)

        return {
            "success": result.get("success", False),
            "notif_id": notification.notif_id,
            "type": notification.type.value,
            "plan_id": result.get("plan_id"),
            "processed": result.get("processed", False)
        }

    async def _process_notification(self, notification: Notification) -> Dict:
        """处理单个通知"""
        logger.info(f"[通知监听] 处理通知: {notification.notif_id} - {notification.type.value}")

        # 记录历史
        self._add_to_history(notification)

        # 转换为任务规划器需要的格式
        task_notification = {
            "type": notification.type.value,
            "source": notification.source,
            "content": {
                "title": notification.title,
                "message": notification.content,
                "sender": notification.raw_data.get("sender", ""),
                "extra": notification.raw_data.get("extra", {})
            },
            "timestamp": notification.timestamp
        }

        # 调用处理器
        try:
            result = await self.notification_handler.handle_notification(task_notification)
            notification.processed = True
            notification.process_result = result
            return result
        except Exception as e:
            logger.error(f"[通知监听] 处理失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "processed": False
            }

    def _add_to_history(self, notification: Notification):
        """添加到历史记录"""
        self.notification_history.append(notification)
        if len(self.notification_history) > self.max_history:
            self.notification_history = self.notification_history[-self.max_history:]

    def get_history(self, limit: int = 20, notif_type: NotificationType = None) -> List[Dict]:
        """获取通知历史"""
        history = self.notification_history[-limit:]

        if notif_type:
            history = [n for n in history if n.type == notif_type]

        return [
            {
                "notif_id": n.notif_id,
                "type": n.type.value,
                "source": n.source,
                "title": n.title,
                "content": n.content[:100] + "..." if len(n.content) > 100 else n.content,
                "timestamp": n.timestamp,
                "processed": n.processed,
                "success": n.process_result.get("success") if n.process_result else None
            }
            for n in history
        ]

    def enable(self):
        """启用监听"""
        self.enabled = True
        logger.info("[通知监听] 已启用")

    def disable(self):
        """禁用监听"""
        self.enabled = False
        logger.info("[通知监听] 已禁用")

    def get_status(self) -> Dict:
        """获取监听状态"""
        total = len(self.notification_history)
        processed = sum(1 for n in self.notification_history if n.processed)

        return {
            "enabled": self.enabled,
            "total_notifications": total,
            "processed": processed,
            "pending": total - processed,
            "queue_size": self.notification_handler.get_pending_count() if self.notification_handler else 0
        }


class ADBNotificationWatcher:
    """
    ADB 通知监控器（备选方案）

    通过 ADB dump 监控通知变化
    注意：Android 14+ 需要特殊权限
    """

    def __init__(self, device_client, callback: Callable):
        self.device = device_client
        self.callback = callback
        self.last_notification_hash = ""
        self.running = False

    async def start(self, interval: float = 5.0):
        """
        启动监控

        Args:
            interval: 检查间隔（秒）
        """
        self.running = True
        logger.info("[ADB通知监控] 启动监控")

        while self.running:
            try:
                await self._check_notifications()
            except Exception as e:
                logger.error(f"[ADB通知监控] 检查失败: {e}")

            await asyncio.sleep(interval)

    def stop(self):
        """停止监控"""
        self.running = False
        logger.info("[ADB通知监控] 已停止")

    async def _check_notifications(self):
        """检查通知变化"""
        try:
            # 获取当前通知
            result = self.device._run([
                "shell", "dumpsys", "notification",
                "--noredact", "-p", "com.taobao.idlefish"
            ])

            if result.returncode != 0:
                return

            # 简单检查是否有新通知
            content = result.stdout

            # 如果内容变化，提取新通知
            content_hash = hashlib.md5(content.encode()).hexdigest()
            if content_hash != self.last_notification_hash:
                self.last_notification_hash = content_hash

                # 解析通知（简化版）
                if "com.taobao.idlefish" in content:
                    notification = self._parse_notification(content)
                    if notification:
                        await self.callback(notification)

        except Exception as e:
            logger.debug(f"[ADB通知监控] 解析通知失败: {e}")

    def _parse_notification(self, content: str) -> Optional[Dict]:
        """解析通知内容"""
        # 简化解析，实际可能需要更复杂的逻辑
        lines = content.split("\n")
        notification = {}

        for line in lines:
            if "android.title" in line:
                notification["title"] = line.split("=")[-1].strip()
            elif "android.text" in line:
                notification["content"] = line.split("=")[-1].strip()

        if notification:
            return {
                "source": "com.taobao.idlefish",
                "type": NotificationFilter.classify(
                    notification.get("title", ""),
                    notification.get("content", "")
                ).value,
                **notification
            }

        return None


def create_notification_endpoints(
    app: FastAPI,
    listener: NotificationListener
):
    """注册通知相关的 API 端点"""

    @app.post("/api/notifications/webhook")
    async def receive_notification(request: Request):
        """接收 Webhook 通知"""
        return await listener.receive_webhook(request)

    @app.get("/api/notifications/history")
    async def get_notification_history(
        limit: int = 20,
        notif_type: str = None
    ):
        """获取通知历史"""
        ntype = None
        if notif_type:
            try:
                ntype = NotificationType(notif_type)
            except ValueError:
                pass

        return {
            "history": listener.get_history(limit, ntype)
        }

    @app.get("/api/notifications/status")
    async def get_notification_status():
        """获取监听状态"""
        return listener.get_status()

    @app.post("/api/notifications/enable")
    async def enable_notifications():
        """启用通知监听"""
        listener.enable()
        return {"success": True, "message": "通知监听已启用"}

    @app.post("/api/notifications/disable")
    async def disable_notifications():
        """禁用通知监听"""
        listener.disable()
        return {"success": True, "message": "通知监听已禁用"}

    @app.post("/api/notifications/test")
    async def test_notification():
        """测试通知处理"""
        test_notification = {
            "source": "xianyu",
            "type": "message",
            "title": "新消息",
            "content": "你好，我想咨询电影票",
            "sender": "测试买家",
            "extra": {}
        }

        return {
            "received": test_notification
        }
