from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    initial_capital: float = Field(100000, ge=1000)

class AccountResponse(BaseModel):
    id: int
    name: str
    initial_capital: float
    current_capital: float
    available_cash: float
    total_return: float
    class Config:
        from_attributes = True

class OrderCreate(BaseModel):
    stock_code: str
    order_type: str = Field(..., pattern="^(buy|sell)$")
    price: float = Field(..., gt=0)
    quantity: int = Field(..., gt=0)

class OrderResponse(BaseModel):
    id: int
    stock_code: str
    order_type: str
    price: float
    quantity: int
    status: str
    class Config:
        from_attributes = True
