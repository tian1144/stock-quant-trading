# 提醒模型

from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from datetime import datetime

from app.core.database import Base

class Alert(Base):
    """提醒表"""
    __tablename__ = "alerts"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    stock_code = Column(String(20), index=True, nullable=False)  # 股票代码
    stock_name = Column(String(50), nullable=True)  # 股票名称
    alert_type = Column(String(30), nullable=False)  # 提醒类型
    title = Column(String(100), nullable=False)  # 提醒标题
    content = Column(String(500), nullable=True)  # 提醒内容
    trigger_price = Column(Float, nullable=True)  # 触发价格
    status = Column(String(20), default="unread")  # 状态：unread, read, dismissed
    created_at = Column(DateTime, default=datetime.now)
    read_at = Column(DateTime, nullable=True)  # 阅读时间
    
    def __repr__(self):
        return f"<Alert {self.alert_type} {self.stock_code}>"