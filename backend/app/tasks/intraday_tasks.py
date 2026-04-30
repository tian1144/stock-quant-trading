# 盘中实时任务

import logging
from app.core.database import async_session_factory
from app.services.market_service import market_service

logger = logging.getLogger(__name__)

async def refresh_realtime_prices():
    """刷新实时价格任务（盘中每5-10秒执行）"""
    try:
        async with async_session_factory() as db:
            await market_service.refresh_realtime_prices(db)
    except Exception as e:
        logger.error(f"刷新实时价格任务失败: {e}")