import asyncio
import json
from fastapi import APIRouter, HTTPException, BackgroundTasks, Header
from pydantic import BaseModel
from typing import Optional, List, Dict
from loguru import logger
from app.services.xianyu_browser import XianyuBrowser

router = APIRouter()


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str
    session_id: str


class LarkWebhookRequest(BaseModel):
    schema: str = "2.0"
    header: Dict
    body: Dict


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """AI客服对话接口"""
    from app.modules.customer_service.service import CustomerService

    service = CustomerService()
    reply = await service.chat(
        user_id=request.user_id,
        message=request.message,
        session_id=request.session_id
    )
    return ChatResponse(reply=reply, session_id=request.session_id or "")


@router.post("/chat/with-context")
async def chat_with_context(
    user_id: str,
    message: str,
    context: Dict,
    session_id: Optional[str] = None
):
    """带上下文的AI客服对话"""
    from app.modules.customer_service.service import CustomerService

    service = CustomerService()
    reply = await service.chat_with_context(
        user_id=user_id,
        message=message,
        context=context,
        session_id=session_id
    )
    return {"reply": reply, "session_id": session_id or ""}


@router.post("/queue")
async def queue_message(
    source: str,
    user_id: str,
    content: str,
    session_id: Optional[str] = None
):
    """将消息加入处理队列"""
    from app.modules.customer_service.service import CustomerService, MessageSource

    service = CustomerService()
    msg = CustomerService.__new__(CustomerService)
    msg.source = MessageSource(source)
    msg.user_id = user_id
    msg.content = content
    msg.session_id = session_id or ""

    session_id = await service.queue_message(msg)
    return {"status": "queued", "session_id": session_id}


@router.post("/process-queue")
async def process_queue(background_tasks: BackgroundTasks):
    """触发队列处理"""
    from app.modules.customer_service.service import CustomerService

    service = CustomerService()

    async def process():
        await service.process_message_queue()

    background_tasks.add_task(process)
    return {"status": "processing"}


@router.get("/sessions/{user_id}")
async def get_sessions(user_id: str):
    """获取用户会话历史"""
    from app.modules.customer_service.service import CustomerService

    service = CustomerService()
    sessions = await service.get_user_sessions(user_id)
    return {"sessions": sessions}


@router.get("/sessions/{session_id}/history")
async def get_conversation_history(session_id: str, limit: int = 20):
    """获取会话历史"""
    from app.modules.customer_service.service import CustomerService

    service = CustomerService()
    history = await service.get_conversation_history(session_id, limit)
    return {"history": history}


@router.post("/sessions/{user_id}/clear")
async def clear_sessions(user_id: str):
    """清除用户会话历史"""
    from app.modules.customer_service.service import CustomerService

    service = CustomerService()
    await service.clear_user_sessions(user_id)
    return {"status": "cleared"}


@router.get("/queue/count")
async def get_queue_count():
    """获取待处理消息数量"""
    from app.modules.customer_service.service import CustomerService

    service = CustomerService()
    count = await service.get_pending_messages_count()
    return {"count": count}


# ============== 飞书 Webhook 接口 ==============

@router.post("/webhook/lark")
async def lark_webhook(
    request: LarkWebhookRequest,
    background_tasks: BackgroundTasks,
    x_lark_signature: Optional[str] = Header(None, alias="x-lark-signature")
):
    """
    飞书事件回调Webhook

    需要在飞书开放平台配置：
    - 事件：im.message.receive_v1
    - 请求URL：https://your-domain.com/api/customer-service/webhook/lark
    """
    from app.modules.customer_service.service import CustomerService, MessageSource

    logger = __import__("loguru").logger

    event = request.body.get("event", {})
    event_type = request.header.get("event_type", "")

    # 只处理消息事件
    if event_type != "im.message.receive_v1":
        return {"status": "ignored"}

    message = event.get("message", {})
    sender = event.get("sender", {})

    # 跳过机器人自身消息
    if sender.get("sender_type") == "app":
        return {"status": "ignored"}

    content = message.get("content", "{}")
    try:
        import json
        content_obj = json.loads(content)
    except:
        content_obj = {"text": content}

    text = content_obj.get("text", "")
    user_id = sender.get("open_id", "")

    if not text or not user_id:
        return {"status": "invalid"}

    logger.info(f"Lark message from {user_id}: {text[:50]}")

    # 加入消息队列
    service = CustomerService()
    msg = CustomerService.__new__(CustomerService)
    msg.source = MessageSource.LARK
    msg.user_id = user_id
    msg.content = text
    msg.session_id = ""
    msg.metadata = {"platform": "lark", "message_id": message.get("message_id")}

    await service.queue_message(msg)

    # 触发后台处理
    async def process():
        await service.process_message_queue()

    background_tasks.add_task(process)

    return {"status": "received"}


# ============== 闲鱼消息同步接口 ==============

@router.post("/sync/xianyu")
async def sync_xianyu_messages(background_tasks: BackgroundTasks):
    """
    同步闲鱼消息（由定时任务调用）

    使用Playwright获取闲鱼最新消息并加入处理队列
    """
    from app.services.xianyu_browser import XianyuBrowser

    async def sync():
        browser = await XianyuBrowser().__aenter__()
        try:
            messages = await browser.get_messages()
            if messages:
                from app.modules.customer_service.service import CustomerService, MessageSource
                service = CustomerService()
                for msg in messages:
                    chat_msg = CustomerService.__new__(CustomerService)
                    chat_msg.source = MessageSource.XIANYU
                    chat_msg.user_id = msg.get("user_id", "")
                    chat_msg.content = msg.get("content", "")
                    chat_msg.session_id = ""
                    chat_msg.metadata = {"platform": "xianyu"}
                    await service.queue_message(chat_msg)
        finally:
            await browser.__aexit__(None, None, None)

    background_tasks.add_task(sync)
    return {"status": "syncing"}


# ============== 闲鱼登录接口 ==============

# 存储当前的浏览器实例和登录状态（简单实现）
_xianyu_browser_instance = None
_login_pending = False


@router.post("/xianyu/login/start")
async def start_xianyu_sms_login():
    """
    开始闲鱼短信登录流程

    调用此接口后，会打开浏览器并发送短信验证码
    然后需要调用 /xianyu/login/code 输入验证码
    """
    global _xianyu_browser_instance, _login_pending

    try:
        _xianyu_browser_instance = XianyuBrowser()
        await _xianyu_browser_instance.init()

        # 开始短信登录（会等待验证码）
        _login_pending = True
        asyncio.create_task(_xianyu_browser_instance.login_with_sms())

        return {
            "status": "pending",
            "message": "验证码已发送，请调用 /xianyu/login/code 输入验证码"
        }
    except Exception as e:
        _login_pending = False
        return {"status": "error", "message": str(e)}


@router.post("/xianyu/login/code")
async def submit_sms_code(code: str):
    """
    提交短信验证码完成登录

    Args:
        code: 收到的短信验证码
    """
    global _xianyu_browser_instance, _login_pending

    if not _xianyu_browser_instance:
        return {"status": "error", "message": "请先调用 /xianyu/login/start"}

    try:
        _xianyu_browser_instance.set_sms_code(code)
        await asyncio.sleep(8)  # 等待登录完成

        if await _xianyu_browser_instance.ensure_logged_in():
            cookies = await _xianyu_browser_instance.context.cookies()
            with open('/opt/ticket-bot/xianyu_cookies.json', 'w') as f:
                json.dump(cookies, f, indent=2)

            _login_pending = False
            return {
                "status": "success",
                "message": "登录成功，cookies已保存"
            }
        else:
            return {
                "status": "failed",
                "message": "验证码可能错误，请重试"
            }
    except Exception as e:
        _login_pending = False
        return {"status": "error", "message": str(e)}


@router.get("/xianyu/login/status")
async def get_login_status():
    """获取当前登录状态"""
    global _xianyu_browser_instance, _login_pending

    if not _xianyu_browser_instance:
        return {"logged_in": False, "pending": False}

    try:
        logged_in = await _xianyu_browser_instance.ensure_logged_in()
    except:
        logged_in = False

    return {
        "logged_in": logged_in,
        "pending": _login_pending
    }


@router.post("/xianyu/logout")
async def logout_xianyu():
    """退出闲鱼登录"""
    global _xianyu_browser_instance, _login_pending

    if _xianyu_browser_instance:
        await _xianyu_browser_instance.close()
        _xianyu_browser_instance = None

    _login_pending = False

    # 清除cookies文件
    try:
        import os
        if os.path.exists('/opt/ticket-bot/xianyu_cookies.json'):
            os.remove('/opt/ticket-bot/xianyu_cookies.json')
    except:
        pass

    return {"status": "logged_out"}
