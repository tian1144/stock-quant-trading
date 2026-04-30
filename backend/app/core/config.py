# 应用配置模块
# 包含数据库、Redis、定时任务等所有配置项

import os
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    """应用配置类"""
    
    # 应用基础配置
    APP_NAME: str = "股票量化智能选股与实时模拟盘"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    API_PREFIX: str = "/api/v1"
    
    # 数据库配置
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/stock_quant"
    DATABASE_ECHO: bool = False
    
    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: Optional[str] = None
    REDIS_MAX_CONNECTIONS: int = 10
    
    # JWT 安全配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24小时
    
    # 模拟盘配置
    DEFAULT_INITIAL_CASH: float = 100000.0  # 默认初始资金10万
    
    # 行情数据配置
    MARKET_REFRESH_INTERVAL: int = 5  # 盘中行情刷新间隔(秒)
    STOCK_LIST_REFRESH_INTERVAL: int = 86400  # 股票列表刷新间隔(秒)
    
    # 定时任务配置
    SCHEDULER_TIMEZONE: str = "Asia/Shanghai"
    
    # CORS 配置
    CORS_ORIGINS: list = ["*"]
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

@lru_cache()
def get_settings() -> Settings:
    """获取配置实例（单例模式）"""
    return Settings()

# 导出配置实例
settings = get_settings()