# 股票相关 API 路由

from fastapi import APIRouter, Depends, Query
from typing import Optional

router = APIRouter(prefix="/stocks", tags=["股票管理"])


@router.get("/")
async def get_stocks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    exchange: Optional[str] = None,
    keyword: Optional[str] = None,
):
    return {"total": 0, "page": page, "page_size": page_size, "items": []}


@router.get("/{stock_code}")
async def get_stock_detail(stock_code: str):
    return {"code": stock_code, "detail": {}}


@router.post("/sync")
async def sync_stocks():
    return {"message": "同步任务已启动"}


@router.get("/search")
async def search_stocks(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=50),
):
    return {"keyword": keyword, "results": []}
