# 股票数据同步定时任务

import logging

logger = logging.getLogger(__name__)


async def sync_stock_list_task():
    logger.info("开始同步股票列表...")
    logger.info("股票列表同步完成")
