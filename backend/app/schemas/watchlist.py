# 自选股数据验证模式

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class WatchlistCreate(BaseModel):
    """添加自选股"""
    stock_code: str
    stock_name: Optional[str] = None
    remark: Optional[str] = None

class WatchlistResponse(BaseModel):
    """自选股响应"""
    id: int
    user_id: int
    stock_code: str
    stock_name: Optional[str] = None
    remark: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class WatchlistListResponse(BaseModel):
    """自选股列表响应"""
    total: int
    watchlists: List[WatchlistResponse]