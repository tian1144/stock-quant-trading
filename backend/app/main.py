from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
from app.core.database import init_db, close_db
from app.core.redis import get_redis, close_redis
from app.core.scheduler import init_scheduler, shutdown_scheduler
from app.api.v1.router import api_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("正在启动股票量化智能选股系统...")
    await init_db()
    logger.info("数据库初始化完成")
    await get_redis()
    logger.info("Redis连接初始化完成")
    await init_scheduler()
    logger.info("定时任务调度器初始化完成")
    yield
    logger.info("正在关闭系统...")
    await shutdown_scheduler()
    await close_redis()
    await close_db()


app = FastAPI(title="股票量化智能选股与实时模拟盘", version="1.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {"name": "股票量化智能选股与实时模拟盘", "version": "1.0.0", "docs": "/docs", "api": "/api/v1"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "服务运行正常"}
