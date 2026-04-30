# 股票数据验证模式

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class StockBase(BaseModel):
    """股票基础信息"""
    code: str
    name: str
    exchange: str
    market: Optional[str] = None
    industry: Optional[str] = None

class StockCreate(StockBase):
    """创建股票"""
    concept_tags: Optional[List[str]] = None
    list_date: Optional[str] = None
    is_st: bool = False
    total_shares: Optional[float] = None
    circulating_shares: Optional[float] = None

class StockResponse(StockBase):
    """股票响应"""
    id: int
    is_st: bool
    is_suspended: bool
    status: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class StockSearchRequest(BaseModel):
    """股票搜索请求"""
    keyword: str
    limit: int = 20

class StockListResponse(BaseModel):
    """股票列表响应"""
    total: int
    stocks: List[StockResponse]