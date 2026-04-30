# 行情数据模型

from sqlalchemy import Column, Integer, String, Float, DateTime, Date, BigInteger
from datetime import datetime

from app.core.database import Base

class StockDailyBar(Base):
    """股票日线行情表"""
    __tablename__ = "stock_daily_bars"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    stock_code = Column(String(20), index=True, nullable=False)  # 股票代码
    trade_date = Column(Date, index=True, nullable=False)  # 交易日期
    open = Column(Float, nullable=False)  # 开盘价
    high = Column(Float, nullable=False)  # 最高价
    low = Column(Float, nullable=False)  # 最低价
    close = Column(Float, nullable=False)  # 收盘价
    pre_close = Column(Float, nullable=True)  # 昨收价
    pct_change = Column(Float, nullable=True)  # 涨跌幅(%)
    volume = Column(BigInteger, nullable=True)  # 成交量(手)
    amount = Column(Float, nullable=True)  # 成交额(元)
    turnover_rate = Column(Float, nullable=True)  # 换手率(%)
    created_at = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<StockDailyBar {self.stock_code} {self.trade_date}>"

class StockRealtimeQuote(Base):
    """股票实时行情表（盘中使用）"""
    __tablename__ = "stock_realtime_quotes"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    stock_code = Column(String(20), unique=True, index=True, nullable=False)  # 股票代码
    current_price = Column(Float, nullable=False)  # 当前价格
    open_price = Column(Float, nullable=True)  # 今日开盘价
    high_price = Column(Float, nullable=True)  # 今日最高价
    low_price = Column(Float, nullable=True)  # 今日最低价
    pre_close = Column(Float, nullable=True)  # 昨日收盘价
    volume = Column(BigInteger, nullable=True)  # 成交量
    amount = Column(Float, nullable=True)  # 成交额
    bid_price1 = Column(Float, nullable=True)  # 买一价
    bid_volume1 = Column(Integer, nullable=True)  # 买一量
    ask_price1 = Column(Float, nullable=True)  # 卖一价
    ask_volume1 = Column(Integer, nullable=True)  # 卖一量
    update_time = Column(DateTime, nullable=True)  # 更新时间
    created_at = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<StockRealtimeQuote {self.stock_code} {self.current_price}>"