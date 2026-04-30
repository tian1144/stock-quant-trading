from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WatchlistCreate(BaseModel):
    stock_code: str

class WatchlistResponse(BaseModel):
    id: int
    stock_code: str
    added_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class WatchlistWithQuoteResponse(BaseModel):
    id: int
    stock_code: str
    stock_name: str = ""
    current_price: Optional[float] = None
    change_percent: Optional[float] = None
    added_at: Optional[datetime] = None
