# 行情数据验证模式

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date

class DailyBarResponse(BaseModel):
    """日线行情响应"""
    stock_code: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    pre_close: Optional[float] = None
    pct_change: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    turnover_rate: Optional[float] = None
    
    class Config:
        from_attributes = True

class RealtimeQuoteResponse(BaseModel):
    """实时行情响应"""
    code: str
    name: Optional[str] = None
    current_price: float
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    pre_close: Optional[float] = None
    pct_change: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    update_time: Optional[datetime] = None

class MarketSnapshotResponse(BaseModel):
    """行情快照响应"""
    code: str
    name: Optional[str] = None
    price: float
    pct_change: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    update_time: Optional[str] = None

class DailyBarListResponse(BaseModel):
    """日线行情列表响应"""
    stock_code: str
    bars: List[DailyBarResponse]

class SnapshotListResponse(BaseModel):
    """行情快照列表响应"""
    snapshots: List[MarketSnapshotResponse]