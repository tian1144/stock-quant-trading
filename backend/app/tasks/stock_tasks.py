# 股票相关定时任务

import logging
from app.core.database import async_session_factory
from app.services.stock_service import stock_service

logger = logging.getLogger(__name__)

async def sync_stock_list():
    """同步股票列表任务（每天执行一次）"""
    logger.info("开始执行股票列表同步任务...")
    try:
        async with async_session_factory() as db:
            result = await stock_service.sync_stock_list(db)
            logger.info(f"股票列表同步任务完成：{result}")
    except Exception as e:
        logger.error(f"股票列表同步任务失败: {e}")