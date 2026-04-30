# 定时任务调度器模块
# 使用 APScheduler 管理定时任务

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from typing import Optional
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler: Optional[AsyncIOScheduler] = None

def init_scheduler() -> AsyncIOScheduler:
    """初始化调度器"""
    global scheduler
    scheduler = AsyncIOScheduler(timezone=settings.SCHEDULER_TIMEZONE)
    return scheduler

def get_scheduler() -> AsyncIOScheduler:
    """获取调度器实例"""
    global scheduler
    if scheduler is None:
        scheduler = init_scheduler()
    return scheduler

async def start_scheduler():
    """启动调度器"""
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("定时任务调度器已启动")

async def shutdown_scheduler():
    """关闭调度器"""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=True)
        logger.info("定时任务调度器已关闭")

def add_stock_list_sync_job():
    """添加股票列表同步任务（每天执行一次）"""
    from app.tasks.stock_tasks import sync_stock_list
    sched = get_scheduler()
    sched.add_job(
        sync_stock_list,
        CronTrigger(hour=18, minute=0),  # 每天18:00执行
        id="stock_list_sync",
        name="股票列表同步",
        replace_existing=True,
    )
    logger.info("股票列表同步任务已添加")

def add_market_data_sync_job():
    """添加日线行情同步任务（每天执行）"""
    from app.tasks.market_tasks import sync_daily_bars
    sched = get_scheduler()
    sched.add_job(
        sync_daily_bars,
        CronTrigger(hour=18, minute=30),  # 每天18:30执行
        id="market_data_sync",
        name="日线行情同步",
        replace_existing=True,
    )
    logger.info("日线行情同步任务已添加")

def add_realtime_price_job():
    """添加实时价格刷新任务（盘中执行）"""
    from app.tasks.intraday_tasks import refresh_realtime_prices
    sched = get_scheduler()
    sched.add_job(
        refresh_realtime_prices,
        IntervalTrigger(seconds=settings.MARKET_REFRESH_INTERVAL),
        id="realtime_price_refresh",
        name="实时价格刷新",
        replace_existing=True,
    )
    logger.info("实时价格刷新任务已添加")