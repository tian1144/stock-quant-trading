from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class StockBase(BaseModel):
    code: str = Field(..., description="股票代码")
    name: str = Field(..., description="股票名称")
    exchange: str = Field(..., description="交易所")
    market: Optional[str] = None
    industry: Optional[str] = None
    is_st: bool = False

class StockCreate(StockBase):
    pass

class StockResponse(StockBase):
    id: int
    status: str = "active"
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class StockListResponse(BaseModel):
    total: int
    page: int = 1
    page_size: int = 20
    items: list[StockResponse]
