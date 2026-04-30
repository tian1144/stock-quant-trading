# 自选股模型

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base

class Watchlist(Base):
    """自选股表"""
    __tablename__ = "watchlists"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    stock_code = Column(String(20), index=True, nullable=False)  # 股票代码
    stock_name = Column(String(50), nullable=True)  # 股票名称
    remark = Column(String(200), nullable=True)  # 备注
    created_at = Column(DateTime, default=datetime.now)
    
    # 关联关系
    user = relationship("User", back_populates="watchlists")
    
    def __repr__(self):
        return f"<Watchlist user={self.user_id} stock={self.stock_code}>"