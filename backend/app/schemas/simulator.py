# 模拟盘数据验证模式

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class PortfolioResponse(BaseModel):
    """模拟盘响应"""
    id: int
    user_id: int
    initial_cash: float
    available_cash: float
    frozen_cash: float
    market_value: float
    total_asset: float
    total_profit: float
    total_profit_ratio: float
    updated_at: datetime
    
    class Config:
        from_attributes = True

class PositionResponse(BaseModel):
    """持仓响应"""
    id: int
    stock_code: str
    stock_name: Optional[str] = None
    quantity: int
    available_quantity: int
    avg_cost: float
    current_price: float
    market_value: float
    floating_profit: float
    floating_profit_ratio: float
    buy_date: Optional[datetime] = None
    updated_at: datetime
    
    class Config:
        from_attributes = True

class OrderResponse(BaseModel):
    """订单响应"""
    id: int
    stock_code: str
    stock_name: Optional[str] = None
    side: str
    order_type: str
    price: float
    quantity: int
    amount: float
    fee: float
    tax: float
    total_cost: float
    status: str
    reject_reason: Optional[str] = None
    created_at: datetime
    filled_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class BuyRequest(BaseModel):
    """买入请求"""
    stock_code: str
    quantity: int

class SellRequest(BaseModel):
    """卖出请求"""
    stock_code: str
    quantity: int

class PortfolioSummary(BaseModel):
    """模拟盘汇总"""
    total_asset: float
    available_cash: float
    market_value: float
    today_profit: float
    total_profit: float
    total_profit_ratio: float
    position_count: int
    today_trade_count: int