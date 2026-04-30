# 模拟盘模型

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base

class SimPortfolio(Base):
    """模拟盘表"""
    __tablename__ = "sim_portfolios"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    initial_cash = Column(Float, default=100000.0)  # 初始资金
    available_cash = Column(Float, default=100000.0)  # 可用现金
    frozen_cash = Column(Float, default=0.0)  # 冻结资金
    market_value = Column(Float, default=0.0)  # 持仓市值
    total_asset = Column(Float, default=100000.0)  # 总资产
    total_profit = Column(Float, default=0.0)  # 总盈亏
    total_profit_ratio = Column(Float, default=0.0)  # 总收益率(%)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 预留字段
    portfolio_id = Column(String(50), nullable=True)  # 预留：多组合ID
    portfolio_type = Column(String(20), default="simulation")  # 预留：simulation, strategy, real
    strategy_type = Column(String(50), nullable=True)  # 预留：策略类型
    trading_mode = Column(String(20), default="manual")  # 预留：manual, auto
    
    # 关联关系
    user = relationship("User", back_populates="portfolios")
    positions = relationship("SimPosition", back_populates="portfolio")
    orders = relationship("SimOrder", back_populates="portfolio")
    
    def __repr__(self):
        return f"<SimPortfolio user={self.user_id} total={self.total_asset}>"

class SimPosition(Base):
    """模拟持仓表"""
    __tablename__ = "sim_positions"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    portfolio_id = Column(Integer, ForeignKey("sim_portfolios.id"), index=True, nullable=False)
    stock_code = Column(String(20), index=True, nullable=False)  # 股票代码
    stock_name = Column(String(50), nullable=True)  # 股票名称
    quantity = Column(Integer, default=0)  # 持仓数量
    available_quantity = Column(Integer, default=0)  # 可卖数量（T+1）
    avg_cost = Column(Float, default=0.0)  # 成本价
    current_price = Column(Float, default=0.0)  # 当前价
    market_value = Column(Float, default=0.0)  # 市值
    floating_profit = Column(Float, default=0.0)  # 浮动盈亏
    floating_profit_ratio = Column(Float, default=0.0)  # 浮动盈亏比例(%)
    buy_date = Column(DateTime, nullable=True)  # 买入日期
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关联关系
    portfolio = relationship("SimPortfolio", back_populates="positions")
    
    def __repr__(self):
        return f"<SimPosition {self.stock_code} qty={self.quantity}>"

class SimOrder(Base):
    """模拟订单表"""
    __tablename__ = "sim_orders"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    portfolio_id = Column(Integer, ForeignKey("sim_portfolios.id"), index=True, nullable=False)
    stock_code = Column(String(20), index=True, nullable=False)  # 股票代码
    stock_name = Column(String(50), nullable=True)  # 股票名称
    side = Column(String(10), nullable=False)  # 买卖方向：buy, sell
    order_type = Column(String(20), default="market")  # 订单类型：market, limit
    price = Column(Float, nullable=False)  # 成交价格
    quantity = Column(Integer, nullable=False)  # 成交数量
    amount = Column(Float, nullable=False)  # 成交金额
    fee = Column(Float, default=0.0)  # 佣金
    tax = Column(Float, default=0.0)  # 印花税
    total_cost = Column(Float, default=0.0)  # 总费用
    status = Column(String(20), default="filled")  # 状态：pending, filled, rejected, cancelled
    reject_reason = Column(String(200), nullable=True)  # 拒绝原因
    created_at = Column(DateTime, default=datetime.now)
    filled_at = Column(DateTime, nullable=True)  # 成交时间
    
    # 预留字段
    order_source = Column(String(20), default="manual")  # 预留：manual, auto, signal
    broker_order_id = Column(String(50), nullable=True)  # 预留：券商订单ID
    is_simulated = Column(Boolean, default=True)  # 预留：是否模拟
    risk_status = Column(String(20), nullable=True)  # 预留：风险状态
    
    # 关联关系
    portfolio = relationship("SimPortfolio", back_populates="orders")
    
    def __repr__(self):
        return f"<SimOrder {self.stock_code} {self.side} qty={self.quantity}>"