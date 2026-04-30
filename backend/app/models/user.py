# 用户/自选股/模拟交易模型

from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True))


class Watchlist(Base):
    __tablename__ = "watchlists"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    stock_code = Column(String(10), nullable=False)
    added_at = Column(DateTime(timezone=True), server_default=func.now())


class SimulatorAccount(Base):
    __tablename__ = "simulator_accounts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(50), nullable=False)
    initial_capital = Column(Float, default=100000)
    current_capital = Column(Float, default=100000)
    available_cash = Column(Float, default=100000)
    total_return = Column(Float, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SimulatorOrder(Base):
    __tablename__ = "simulator_orders"
    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False, index=True)
    stock_code = Column(String(10), nullable=False)
    order_type = Column(String(10), nullable=False, comment="buy/sell")
    price = Column(Float, nullable=False)
    quantity = Column(Integer, nullable=False)
    status = Column(String(10), default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
