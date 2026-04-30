# 推荐结果模型

from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from datetime import datetime

from app.core.database import Base

class Recommendation(Base):
    """推荐结果表"""
    __tablename__ = "recommendations"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    recommend_date = Column(DateTime, index=True, nullable=False)  # 推荐日期
    stock_code = Column(String(20), index=True, nullable=False)  # 股票代码
    stock_name = Column(String(50), nullable=True)  # 股票名称
    recommend_type = Column(String(20), nullable=False)  # 推荐类型：short, long, watch
    cycle = Column(String(20), nullable=True)  # 周期：1d, 3d, 5d, 10d, 20d
    score = Column(Float, nullable=False)  # 综合评分
    up_probability = Column(Float, nullable=True)  # 上涨概率
    limit_up_probability = Column(Float, nullable=True)  # 涨停概率
    expected_return_min = Column(Float, nullable=True)  # 预期最小收益
    expected_return_max = Column(Float, nullable=True)  # 预期最大收益
    suggested_buy_price = Column(Float, nullable=True)  # 建议买入价
    suggested_sell_price = Column(Float, nullable=True)  # 建议卖出价
    stop_loss_price = Column(Float, nullable=True)  # 止损价
    reason = Column(String(500), nullable=True)  # 推荐理由
    risk_level = Column(String(20), default="medium")  # 风险等级：low, medium, high
    model_version = Column(String(50), nullable=True)  # 预留：模型版本
    strategy_type = Column(String(50), nullable=True)  # 预留：策略类型
    score_detail = Column(JSON, nullable=True)  # 预留：评分明细
    explanation_json = Column(JSON, nullable=True)  # 预留：解释JSON
    created_at = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<Recommendation {self.stock_code} {self.recommend_type} score={self.score}>"

class StockPool(Base):
    """股票池表"""
    __tablename__ = "stock_pools"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    pool_date = Column(DateTime, index=True, nullable=False)  # 池日期
    pool_type = Column(String(30), nullable=False)  # 池类型：watch_next_day, short_candidate, long_candidate, risk_excluded
    stock_code = Column(String(20), index=True, nullable=False)  # 股票代码
    stock_name = Column(String(50), nullable=True)  # 股票名称
    base_score = Column(Float, nullable=True)  # 基础评分
    reason = Column(String(500), nullable=True)  # 入池原因
    created_at = Column(DateTime, default=datetime.now)
    
    def __repr__(self):
        return f"<StockPool {self.pool_date} {self.stock_code} {self.pool_type}>"