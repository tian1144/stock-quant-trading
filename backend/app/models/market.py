# 市场行情数据模型

from sqlalchemy import Column, String, Integer, Float, DateTime, BigInteger
from sqlalchemy.sql import func
from app.core.database import Base


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, index=True)
    name = Column(String(50))
    current_price = Column(Float)
    open_price = Column(Float)
    high_price = Column(Float)
    low_price = Column(Float)
    pre_close = Column(Float)
    volume = Column(BigInteger)
    amount = Column(Float)
    change = Column(Float)
    change_percent = Column(Float)
    turnover_rate = Column(Float)
    update_time = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class KLineData(Base):
    __tablename__ = "kline_data"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, index=True)
    period = Column(String(10), nullable=False, comment="daily/weekly/monthly")
    trade_date = Column(String(10), nullable=False)
    open_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    close_price = Column(Float, nullable=False)
    volume = Column(BigInteger)
    amount = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class IntradayData(Base):
    __tablename__ = "intraday_data"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, index=True)
    trade_time = Column(DateTime(timezone=True), nullable=False)
    price = Column(Float)
    volume = Column(BigInteger)
    amount = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
