# 市场行情 API 路由

from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter(prefix="/market", tags=["市场行情"])


@router.get("/overview")
async def get_market_overview():
    return {
        "indices": [
            {"code": "000001", "name": "上证指数", "price": 3100.00, "change": 0.5},
            {"code": "399001", "name": "深证成指", "price": 9800.00, "change": 0.3},
            {"code": "399006", "name": "创业板指", "price": 1900.00, "change": -0.2},
        ]
    }


@router.get("/snapshot/{stock_code}")
async def get_stock_snapshot(stock_code: str):
    return {
        "code": stock_code, "name": "", "current_price": 0,
        "change": 0, "change_percent": 0, "volume": 0, "amount": 0, "update_time": ""
    }


@router.get("/snapshots")
async def get_stock_snapshots(codes: str = Query(..., description="股票代码，逗号分隔")):
    return {"snapshots": []}


@router.get("/kline/{stock_code}")
async def get_stock_kline(
    stock_code: str,
    period: str = Query("daily", description="周期: daily/weekly/monthly"),
    limit: int = Query(60, ge=1, le=365),
):
    return {"code": stock_code, "period": period, "kline_data": []}


@router.get("/hot")
async def get_hot_stocks(limit: int = Query(20, ge=1, le=100)):
    return {"hot_stocks": []}


@router.get("/limit-up")
async def get_limit_up_stocks(date: Optional[str] = None):
    return {"limit_up_stocks": []}
