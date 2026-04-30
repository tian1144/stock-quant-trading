# 行情数据 API 路由

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.core.database import get_db
from app.services.market_service import market_service
from app.services.stock_service import stock_service
from app.schemas.market import (
    DailyBarResponse, DailyBarListResponse,
    RealtimeQuoteResponse, MarketSnapshotResponse, SnapshotListResponse
)

router = APIRouter(prefix="/market", tags=["行情"])

@router.get("/daily/{stock_code}", response_model=DailyBarListResponse)
async def get_daily_bars(
    stock_code: str,
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db)
):
    """获取股票日线行情数据"""
    # 检查股票是否存在
    stock = await stock_service.get_stock_by_code(db, stock_code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")
    
    bars = await market_service.get_daily_bars(db, stock_code, limit)
    return DailyBarListResponse(stock_code=stock_code, bars=bars)

@router.get("/snapshot/{stock_code}", response_model=RealtimeQuoteResponse)
async def get_snapshot(
    stock_code: str,
    db: AsyncSession = Depends(get_db)
):
    """获取股票实时行情快照"""
    # 检查股票是否存在
    stock = await stock_service.get_stock_by_code(db, stock_code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")
    
    quote = await market_service.get_realtime_quote(stock_code)
    if not quote:
        raise HTTPException(status_code=404, detail="行情数据获取失败")
    
    return RealtimeQuoteResponse(
        code=quote.get("code"),
        name=quote.get("name"),
        current_price=quote.get("price", 0),
        pct_change=quote.get("pct_change"),
        volume=quote.get("volume"),
        amount=quote.get("amount"),
        update_time=quote.get("update_time"),
    )

@router.get("/snapshots", response_model=SnapshotListResponse)
async def get_snapshots(
    codes: str = Query(..., description="股票代码，逗号分隔"),
    db: AsyncSession = Depends(get_db)
):
    """批量获取股票实时行情快照"""
    stock_codes = [code.strip() for code in codes.split(",") if code.strip()]
    if not stock_codes:
        raise HTTPException(status_code=400, detail="请提供股票代码")
    
    if len(stock_codes) > 50:
        raise HTTPException(status_code=400, detail="单次最多查询50只股票")
    
    quotes = await market_service.get_realtime_quotes_batch(stock_codes)
    
    snapshots = []
    for code in stock_codes:
        if code in quotes:
            q = quotes[code]
            snapshots.append(MarketSnapshotResponse(
                code=q.get("code"),
                name=q.get("name"),
                price=q.get("price", 0),
                pct_change=q.get("pct_change"),
                volume=q.get("volume"),
                amount=q.get("amount"),
                update_time=q.get("update_time"),
            ))
    
    return SnapshotListResponse(snapshots=snapshots)

@router.post("/sync/{stock_code}")
async def sync_daily_bars(
    stock_code: str,
    days: int = Query(100, ge=1, le=365),
    db: AsyncSession = Depends(get_db)
):
    """手动触发股票日线行情同步"""
    # 检查股票是否存在
    stock = await stock_service.get_stock_by_code(db, stock_code)
    if not stock:
        raise HTTPException(status_code=404, detail="股票不存在")
    
    try:
        result = await market_service.sync_daily_bars(db, stock_code, days)
        return {"message": "同步成功", "data": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")