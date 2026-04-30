# 用户模型

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float
from sqlalchemy.orm import relationship
from datetime import datetime

from app.core.database import Base

class User(Base):
    """用户表"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=True)
    password_hash = Column(String(128), nullable=False)
    nickname = Column(String(50), nullable=True)
    avatar = Column(String(500), nullable=True)
    role = Column(String(20), default="user")  # 预留：user, admin
    status = Column(Integer, default=1)  # 预留：0禁用，1启用
    invite_code = Column(String(50), nullable=True)  # 预留邀请码
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关联关系
    settings = relationship("UserSetting", back_populates="user", uselist=False)
    portfolios = relationship("SimPortfolio", back_populates="user")
    watchlists = relationship("Watchlist", back_populates="user")

class UserSetting(Base):
    """用户设置表"""
    __tablename__ = "user_settings"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    prefer_mode = Column(String(20), default="both")  # short, long, both
    risk_level = Column(String(20), default="moderate")  # conservative, moderate, aggressive
    prefer_low_position = Column(Boolean, default=False)
    prefer_hot_sector = Column(Boolean, default=True)
    allow_gem = Column(Boolean, default=True)  # 创业板
    allow_star = Column(Boolean, default=True)  # 科创板
    initial_sim_cash = Column(Float, default=100000.0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    
    # 关联关系
    user = relationship("User", back_populates="settings")