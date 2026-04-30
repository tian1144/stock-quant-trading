# 股票模型

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, JSON
from datetime import datetime

from app.core.database import Base

class Stock(Base):
    """股票基础信息表"""
    __tablename__ = "stocks"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    code = Column(String(20), unique=True, index=True, nullable=False)  # 股票代码
    name = Column(String(50), nullable=False)  # 股票名称
    exchange = Column(String(20), nullable=False)  # 交易所：sh, sz, bj
    market = Column(String(20), nullable=True)  # 市场类型：主板、创业板、科创板
    industry = Column(String(50), nullable=True)  # 所属行业
    concept_tags = Column(JSON, nullable=True)  # 概念标签
    list_date = Column(String(20), nullable=True)  # 上市日期
    is_st = Column(Boolean, default=False)  # 是否ST
    is_suspended = Column(Boolean, default=False)  # 是否停牌
    status = Column(String(20), default="active")  # 状态：active, suspended, delisted
    total_shares = Column(Float, nullable=True)  # 总股本
    circulating_shares = Column(Float, nullable=True)  # 流通股本
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    def __repr__(self):
        return f"<Stock {self.code} {self.name}>"