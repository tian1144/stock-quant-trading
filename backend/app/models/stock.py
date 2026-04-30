# 股票模型

from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class Stock(Base):
    __tablename__ = "stocks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(10), unique=True, nullable=False, index=True, comment="股票代码")
    name = Column(String(50), nullable=False, comment="股票名称")
    exchange = Column(String(10), nullable=False, comment="交易所(sh/sz/bj)")
    market = Column(String(20), comment="板块")
    industry = Column(String(50), comment="行业")
    is_st = Column(Boolean, default=False, comment="是否ST")
    status = Column(String(10), default="active", comment="状态")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
