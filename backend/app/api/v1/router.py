# API v1 路由汇总

from fastapi import APIRouter

from app.api.v1 import stocks, market

# 创建 v1 路由器
api_router = APIRouter(prefix="/api/v1")

# 注册子路由
api_router.include_router(stocks.router)
api_router.include_router(market.router)

@api_router.get("/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "message": "服务运行正常"}