# 推荐结果数据验证模式

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class RecommendationResponse(BaseModel):
    """推荐结果响应"""
    id: int
    recommend_date: datetime
    stock_code: str
    stock_name: Optional[str] = None
    recommend_type: str
    cycle: Optional[str] = None
    score: float
    up_probability: Optional[float] = None
    limit_up_probability: Optional[float] = None
    expected_return_min: Optional[float] = None
    expected_return_max: Optional[float] = None
    suggested_buy_price: Optional[float] = None
    suggested_sell_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    reason: Optional[str] = None
    risk_level: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class RecommendationListResponse(BaseModel):
    """推荐列表响应"""
    total: int
    recommendations: List[RecommendationResponse]

class StockPoolResponse(BaseModel):
    """股票池响应"""
    id: int
    pool_date: datetime
    pool_type: str
    stock_code: str
    stock_name: Optional[str] = None
    base_score: Optional[float] = None
    reason: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True