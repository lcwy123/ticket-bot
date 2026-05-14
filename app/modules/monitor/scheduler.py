from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger


def setup_scheduler(scheduler: AsyncIOScheduler):
    """配置定时任务"""

    # 每天早上9点检查新上映电影
    scheduler.add_job(
        check_new_movies,
        CronTrigger(hour=9, minute=0),
        id="check_new_movies",
        name="检查新上映电影",
        replace_existing=True
    )

    # 每30分钟检查一次热门电影价格变化
    scheduler.add_job(
        check_price_changes,
        CronTrigger(minute='*/30'),
        id="check_price_changes",
        name="检查票价变化",
        replace_existing=True
    )

    logger.info("Scheduler jobs configured")


async def check_new_movies():
    """检查新上映电影并自动上架"""
    from app.modules.monitor.service import MonitorService

    logger.info("Running check_new_movies job")
    service = MonitorService()
    await service.check_and_list_new_movies()


async def check_price_changes():
    """检查票价变化并更新商品"""
    from app.modules.monitor.service import MonitorService

    logger.info("Running check_price_changes job")
    service = MonitorService()
    await service.update_listed_prices()
