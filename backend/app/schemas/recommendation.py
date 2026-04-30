from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class RecommendationResponse(BaseModel):
    id: int
    stock_code: str
    strategy_name: str
    score: Optional[float] = None
    reason: Optional[str] = None
    trade_date: Optional[str] = None
    class Config:
        from_attributes = True

class StrategyInfo(BaseModel):
    name: str
    display_name: str
    description: str

class StrategyListResponse(BaseModel):
    strategies: list[StrategyInfo]
    total: int
