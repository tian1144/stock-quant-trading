from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import logging

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def init_scheduler():
    from app.tasks.stock_tasks import sync_stock_list_task
    scheduler.add_job(sync_stock_list_task, CronTrigger(hour=4, minute=0), id="sync_stock_list", name="同步股票列表", replace_existing=True)
    from app.tasks.market_tasks import update_market_quotes_task
    scheduler.add_job(update_market_quotes_task, IntervalTrigger(seconds=5), id="update_market_quotes", name="更新实时行情", replace_existing=True)
    from app.tasks.market_tasks import update_daily_kline_task
    scheduler.add_job(update_daily_kline_task, CronTrigger(hour=15, minute=30), id="update_daily_kline", name="更新日K线", replace_existing=True)
    from app.tasks.intraday_tasks import update_intraday_data_task
    scheduler.add_job(update_intraday_data_task, IntervalTrigger(minutes=1), id="update_intraday_data", name="更新分钟线", replace_existing=True)
    scheduler.start()
    logger.info("定时任务调度器已启动")


async def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("定时任务调度器已关闭")
