# 选股推荐模型

from sqlalchemy import Column, String, Integer, Float, DateTime, Text
from sqlalchemy.sql import func
from app.core.database import Base


class StockRecommendation(Base):
    __tablename__ = "stock_recommendations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_code = Column(String(10), nullable=False, index=True)
    strategy_name = Column(String(50), nullable=False)
    score = Column(Float, comment="推荐评分")
    reason = Column(Text, comment="推荐理由")
    indicators = Column(Text, comment="技术指标(JSON)")
    trade_date = Column(String(10))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
