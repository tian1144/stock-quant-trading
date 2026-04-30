# 认证数据验证模式

from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str

class RegisterRequest(BaseModel):
    """注册请求"""
    username: str
    password: str
    phone: Optional[str] = None
    nickname: Optional[str] = None

class TokenResponse(BaseModel):
    """令牌响应"""
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str

class UserInfoResponse(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    nickname: Optional[str] = None
    phone: Optional[str] = None
    avatar: Optional[str] = None
    role: str
    status: int
    last_login_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True