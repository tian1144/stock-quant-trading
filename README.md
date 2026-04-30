# 股票量化智能选股与实时模拟盘

基于 Python FastAPI 的股票量化选股系统，支持实时行情、小程序和H5网页。

## 功能特性
- 📊 **实时行情**: 新浪财经 + 同花顺双数据源，覆盖5511只A股
- 🌐 **H5网页**: 一键启动，支持远程分享
- 📱 **小程序**: uni-app跨平台，支持微信小程序
- 🔍 **搜索**: 支持代码/名称搜索
- ⏱ **自动刷新**: 每5秒更新行情
- 💾 **缓存**: 300秒TTL，秒级响应

## 快速开始

### 启动后端
```bash
cd backend
pip install -r requirements.txt
python run_simple.py
```
访问 http://localhost:8000 查看实时行情网页

### 一键启动（Windows）
双击 `启动股票行情.bat`

## 数据源
- 股票列表：新浪财经API
- 实时行情：同花顺API

## 项目结构
```
backend/        # FastAPI后端
miniapp/        # uni-app小程序
启动股票行情.bat  # 一键启动脚本
```

## 技术栈
- 后端：Python 3.8+ / FastAPI / Uvicorn
- 前端：uni-app (Vue 3)
- 数据：新浪财经 + 同花顺API
