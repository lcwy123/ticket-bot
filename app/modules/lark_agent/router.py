"""
飞书Agent路由
处理来自飞书的消息事件
"""
import hashlib
import hmac
import time
from fastapi import APIRouter, Request, Header, HTTPException
from pydantic import BaseModel
from typing import Optional, Any, Dict
import json
import asyncio
from loguru import logger

from app.config import get_settings
from app.services.lark_mobile_agent import get_lark_agent

settings = get_settings()
router = APIRouter(prefix="/webhook/lark_agent", tags=["飞书Agent"])


class LarkEvent(BaseModel):
    """飞书事件模型"""
    schema: str = "2.0"
    header: Dict[str, Any]
    body: Dict[str, Any]


class LarkChallengeRequest(BaseModel):
    """飞书 Challenge 验证请求"""
    challenge: str


def verify_lark_signature(token: str, timestamp: str, signature: str) -> bool:
    """验证飞书签名"""
    if not settings.webhook_secret:
        logger.warning("webhook_secret 未配置，跳过签名验证")
        return True

    string_to_sign = f"{timestamp}{token}"
    hmac_code = hmac.new(
        settings.webhook_secret.encode(),
        string_to_sign.encode(),
        digestmod=hashlib.sha256
    ).hexdigest()
    return hmac_code == signature


async def handle_message(event: Dict) -> Optional[str]:
    """处理接收到的消息事件"""
    event_type = event.get("header", {}).get("event_type", "")

    if event_type == "im.message.receive_v1":
        return await handle_receive_message(event)
    elif event_type == "im.message.challenge":
        return event.get("body", {}).get("challenge", "")
    return None


async def handle_receive_message(event: Dict) -> Optional[str]:
    """处理消息接收事件"""
    body = event.get("body", {})
    message = body.get("message", {})
    sender = body.get("sender", {})

    message_type = message.get("message_type", "")
    if message_type != "text":
        return "仅支持文本消息"

    content = message.get("content", "{}")
    try:
        text_content = json.loads(content).get("text", "").strip()
    except:
        text_content = content.strip()

    if not text_content:
        return "消息内容为空"

    open_id = sender.get("open_id", "")
    if not open_id:
        return "无法获取发送者ID"

    logger.info(f"收到飞书消息 from {open_id}: {text_content}")

    # 处理用户指令
    agent = get_lark_agent()
    try:
        result = await agent.process_command(text_content, open_id)
        # 发送回复
        await agent.send_message(open_id, result)
        return "OK"
    except Exception as e:
        logger.error(f"处理消息失败: {e}")
        await agent.send_message(open_id, f"处理失败: {str(e)}")
        return "ERROR"


@router.post("/event")
async def handle_lark_event(
    request: Request,
    x_lark_signature: Optional[str] = Header(None),
    x_lark_timestamp: Optional[str] = Header(None)
):
    """
    飞书事件回调端点
    """
    body = await request.json()
    logger.info(f"收到飞书事件: {json.dumps(body)[:500]}")

    # Challenge 验证
    if "challenge" in body:
        return {"challenge": body["challenge"]}

    # 获取签名验证参数
    header = body.get("header", {})
    event_type = header.get("event_type", "")

    # 验证签名
    token = header.get("token", "")
    timestamp = header.get("timestamp", "")
    signature = x_lark_signature or ""

    if not verify_lark_signature(token, timestamp, signature):
        logger.warning("飞书签名验证失败")
        raise HTTPException(status_code=401, detail="签名验证失败")

    # 处理事件
    if event_type == "im.message.receive_v1":
        result = await handle_receive_message(body)
        return {"code": 0, "msg": result or "OK"}
    elif event_type == "im.message.challenge":
        return {"code": 0, "challenge": body.get("body", {}).get("challenge", "")}
    else:
        logger.info(f"忽略事件类型: {event_type}")
        return {"code": 0, "msg": "ignored"}


@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "lark_agent"}
