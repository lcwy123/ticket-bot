import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from loguru import logger

from app.config import get_settings

settings = get_settings()
scheduler = AsyncIOScheduler()

# 全局组件实例
mobile_agent = None
task_planner = None
notification_listener = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mobile_agent, task_planner, notification_listener

    logger.info(f"Starting {settings.app_name}...")

    # Setup scheduler for movie monitoring
    from app.modules.monitor.scheduler import setup_scheduler
    setup_scheduler(scheduler)
    scheduler.start()
    logger.info("Scheduler started")

    # 初始化 MobileAgent
    from app.services.mobile_agent import EnhancedMobileAgent
    from app.services.xianyu_app_client import XianyuAppClient
    from app.services.task_planner import TaskPlanner, NotificationHandler
    from app.services.notification_driver import NotificationListener

    # 创建设备客户端（如果配置了设备地址）
    device_client = None
    if settings.xianyu_device_addr or settings.use_app_mode:
        try:
            device_client = XianyuAppClient(settings.xianyu_device_addr)
            device_client.connect()
            logger.info(f"设备已连接: {settings.xianyu_device_addr}")
        except Exception as e:
            logger.warning(f"设备连接失败: {e}，Agent 将以模拟模式运行")

    # 初始化 MobileAgent
    mobile_agent = EnhancedMobileAgent(device_client)

    # 初始化 TaskPlanner
    task_planner = TaskPlanner(mobile_agent)

    # 初始化飞书服务（用于通知）
    lark_service = None
    try:
        from app.services.lark_service import LarkService
        lark_service = LarkService()
    except Exception as e:
        logger.warning(f"飞书服务初始化失败: {e}")

    # 初始化 NotificationHandler
    notification_handler = NotificationHandler(task_planner, lark_service)

    # 初始化 NotificationListener
    notification_listener = NotificationListener(
        task_planner=task_planner,
        notification_handler=notification_handler,
        webhook_secret=getattr(settings, "webhook_secret", None)
    )

    # 注册通知端点
    from app.services.notification_driver import create_notification_endpoints
    create_notification_endpoints(app, notification_listener)

    # 启动 Xianyu 消息监听（背景任务）
    from app.modules.customer_service.message_listener import XianyuMessageListener
    listener = XianyuMessageListener(
        poll_interval=30,
        aggregation_window=30,
        proactive_enabled=True
    )
    asyncio.create_task(listener.start())
    logger.info("Xianyu message listener started")

    # 启动 ADB 通知监控（如果可用）
    if device_client and settings.use_app_mode:
        from app.services.notification_driver import ADBNotificationWatcher

        async def on_notification(notification):
            logger.info(f"收到 ADB 通知: {notification}")
            await notification_listener._process_notification(notification)

        watcher = ADBNotificationWatcher(device_client, on_notification)
        asyncio.create_task(watcher.start())
        logger.info("ADB 通知监控已启动")

    # 启动飞书 WebSocket 客户端
    if settings.lark_agent_app_id and settings.lark_agent_app_secret:
        try:
            from app.services.lark_websocket_client import start_lark_ws_client
            start_lark_ws_client()
            logger.info("飞书 WebSocket 客户端已启动")
        except Exception as e:
            logger.warning(f"飞书客户端启动失败: {e}")

    logger.info(f"{settings.app_name} 启动完成")

    yield

    logger.info("Shutting down...")
    listener.stop()
    scheduler.shutdown()

    # 停止飞书客户端
    try:
        from app.services.lark_websocket_client import get_lark_ws_client
        get_lark_ws_client().stop()
    except:
        pass

    if device_client:
        device_client.device = None


app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan
)


@app.get("/")
async def root():
    return {
        "status": "running",
        "app": settings.app_name,
        "components": {
            "mobile_agent": mobile_agent is not None,
            "task_planner": task_planner is not None,
            "notification_listener": notification_listener is not None
        }
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/agent/status")
async def get_agent_status():
    """获取 Agent 状态"""
    if not mobile_agent:
        return {"error": "Agent 未初始化"}

    status = mobile_agent.get_task_status()
    if not status:
        return {
            "state": "idle",
            "message": "Agent 空闲，无运行中任务"
        }

    return status


@app.post("/api/agent/task")
async def execute_agent_task(task: str, max_steps: int = 20):
    """执行 Agent 任务"""
    if not mobile_agent:
        return {"success": False, "error": "Agent 未初始化"}

    result = await mobile_agent.run_async(task, max_steps)
    return result


@app.get("/api/agent/plan/status")
async def get_plan_status():
    """获取当前计划状态"""
    if not task_planner:
        return {"error": "TaskPlanner 未初始化"}

    return task_planner.get_plan_status()


@app.post("/api/agent/plan/execute")
async def execute_plan(task: str):
    """解析并执行任务计划"""
    if not task_planner:
        return {"success": False, "error": "TaskPlanner 未初始化"}

    plan = task_planner.parse_task(task)
    result = await task_planner.execute_plan(plan)

    return {
        "success": result.success,
        "plan_id": result.plan_id,
        "completed_steps": result.completed_steps,
        "total_steps": result.total_steps,
        "errors": result.errors,
        "duration": f"{result.duration:.2f}s"
    }


@app.get("/admin/ticket")
async def ticket_admin():
    """票务管理后台页面"""
    from fastapi.responses import FileResponse
    import os
    template_path = os.path.join(os.path.dirname(__file__), "templates", "ticket_admin.html")
    return FileResponse(template_path)


# Import and register routers
from app.modules.customer_service.router import router as customer_service_router
from app.modules.ticket.router import router as ticket_router
from app.modules.monitor.router import router as monitor_router
from app.modules.lark_agent.router import router as lark_agent_router

app.include_router(customer_service_router, prefix="/api/customer-service", tags=["客服"])
app.include_router(ticket_router, prefix="/api/ticket", tags=["票务"])
app.include_router(monitor_router, prefix="/api/monitor", tags=["监控"])
app.include_router(lark_agent_router)  # 飞书Agent Webhook

# AutoJS 设备路由
from app.services.autojs_router import router as autojs_router
app.include_router(autojs_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
