# API v1 路由聚合

from fastapi import APIRouter
from app.api.v1 import stocks, market

api_router = APIRouter()

# 注册子路由
api_router.include_router(stocks.router)
api_router.include_router(market.router)
