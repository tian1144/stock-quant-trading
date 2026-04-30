from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class MarketSnapshotResponse(BaseModel):
    code: str
    name: Optional[str] = None
    current_price: Optional[float] = None
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    pre_close: Optional[float] = None
    volume: Optional[int] = None
    amount: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None

class KLineDataResponse(BaseModel):
    trade_date: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: Optional[int] = None

class IndexDataResponse(BaseModel):
    code: str
    name: str
    price: float
    change: float
    change_percent: float

class MarketOverviewResponse(BaseModel):
    indices: list[IndexDataResponse]
