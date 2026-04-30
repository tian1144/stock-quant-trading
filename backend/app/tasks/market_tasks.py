# 行情数据定时任务

import logging
from app.core.database import async_session_factory
from app.services.market_service import market_service
from app.services.stock_service import stock_service

logger = logging.getLogger(__name__)

async def sync_daily_bars():
    """同步日线行情任务（每天执行一次）"""
    logger.info("开始执行日线行情同步任务...")
    try:
        async with async_session_factory() as db:
            # 获取所有活跃股票
            stocks = await stock_service.get_all_stocks(db, limit=1000)
            
            success_count = 0
            fail_count = 0
            
            for stock in stocks:
                try:
                    result = await market_service.sync_daily_bars(db, stock.code, days=100)
                    success_count += 1
                    logger.debug(f"股票 {stock.code} 日线同步成功：{result}")
                except Exception as e:
                    fail_count += 1
                    logger.warning(f"股票 {stock.code} 日线同步失败: {e}")
            
            logger.info(f"日线行情同步任务完成：成功{success_count}，失败{fail_count}")
            
    except Exception as e:
        logger.error(f"日线行情同步任务失败: {e}")