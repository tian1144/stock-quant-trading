import redis.asyncio as aioredis
import json
from typing import Optional, Any
from app.core.config import get_settings

settings = get_settings()
redis_pool: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    global redis_pool
    if redis_pool is None:
        redis_pool = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return redis_pool


async def close_redis():
    global redis_pool
    if redis_pool:
        await redis_pool.close()
        redis_pool = None


async def cache_set(key: str, value: Any, expire: int = 300):
    redis = await get_redis()
    await redis.set(key, json.dumps(value, ensure_ascii=False), ex=expire)


async def cache_get(key: str) -> Optional[Any]:
    redis = await get_redis()
    data = await redis.get(key)
    if data:
        return json.loads(data)
    return None


async def cache_delete(key: str):
    redis = await get_redis()
    await redis.delete(key)


class MarketSnapshotCache:
    PREFIX = "market:snapshot:"
    EXPIRE = 5

    @classmethod
    async def set(cls, code: str, data: dict):
        await cache_set(f"{cls.PREFIX}{code}", data, cls.EXPIRE)

    @classmethod
    async def get(cls, code: str) -> Optional[dict]:
        return await cache_get(f"{cls.PREFIX}{code}")

    @classmethod
    async def mget(cls, codes: list) -> dict:
        redis = await get_redis()
        keys = [f"{cls.PREFIX}{code}" for code in codes]
        results = await redis.mget(keys)
        return {code: json.loads(data) if data else None for code, data in zip(codes, results)}
