# Redis 连接模块
# 用于缓存最新行情、实时价格快照、推荐结果等

import redis.asyncio as redis
from typing import Optional
import json

from app.core.config import settings

# Redis 连接池
redis_pool: Optional[redis.Redis] = None

async def init_redis() -> redis.Redis:
    """初始化 Redis 连接池"""
    global redis_pool
    redis_pool = redis.from_url(
        settings.REDIS_URL,
        password=settings.REDIS_PASSWORD,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
    )
    # 测试连接
    await redis_pool.ping()
    return redis_pool

async def get_redis() -> redis.Redis:
    """获取 Redis 连接（依赖注入）"""
    global redis_pool
    if redis_pool is None:
        redis_pool = await init_redis()
    return redis_pool

async def close_redis():
    """关闭 Redis 连接"""
    global redis_pool
    if redis_pool is not None:
        await redis_pool.close()
        redis_pool = None

async def set_market_snapshot(stock_code: str, data: dict, expire_seconds: int = 300):
    """设置股票行情快照"""
    redis_client = await get_redis()
    key = f"market:snapshot:{stock_code}"
    await redis_client.setex(key, expire_seconds, json.dumps(data, ensure_ascii=False))

async def get_market_snapshot(stock_code: str) -> Optional[dict]:
    """获取股票行情快照"""
    redis_client = await get_redis()
    key = f"market:snapshot:{stock_code}"
    data = await redis_client.get(key)
    if data:
        return json.loads(data)
    return None

async def get_market_snapshots(stock_codes: list) -> dict:
    """批量获取股票行情快照"""
    redis_client = await get_redis()
    result = {}
    for code in stock_codes:
        key = f"market:snapshot:{code}"
        data = await redis_client.get(key)
        if data:
            result[code] = json.loads(data)
    return result