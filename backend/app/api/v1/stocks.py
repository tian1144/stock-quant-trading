# 股票 API 路由

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db
from app.services.stock_service import stock_service
from app.schemas.stock import StockResponse, StockListResponse, StockSearchRequest

router = APIRouter(prefix="/stocks", tags=["股票"])

@router.get("", response_model=StockListResponse)
async def get_stocks(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """获取股票列表"""
    stocks = await stock_service.get_all_stocks(db, limit=limit, offset=offset)
    total = await stock_service.get_stock_count(db)
    return StockListResponse(total=total, stocks=stocks)

@router.get("/search", response_model=List[StockResponse])
async def search_stocks(
    keyword: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """搜索股票（按代码或名称）"""
    stocks = await stock_service.search_stocks(db, keyword, limit)
    return stocks

@router.get("/{stock_code}", response_model=StockResponse)
async def get_stock(
    stock_code: str,
    db: AsyncSession = Depends(get_db)
):
    """根据股票代码获取股票信息"""
    stock = await stock_service.get_stock_by_code(db, stock_code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")
    return stock

@router.post("/sync")
async def sync_stock_list(db: AsyncSession = Depends(get_db)):
    """手动触发股票列表同步"""
    try:
        result = await stock_service.sync_stock_list(db)
        return {"message": "同步成功", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")