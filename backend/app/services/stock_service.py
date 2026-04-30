# 股票服务模块
# 使用 requests 获取股票基础数据（东方财富网 API）

import requests
import json
from typing import List, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from datetime import datetime
import logging

from app.models.stock import Stock
from app.schemas.stock import StockCreate, StockResponse

logger = logging.getLogger(__name__)

class StockService:
    """股票服务类"""
    
    # 东方财富网 API 地址
    STOCK_LIST_URL = "http://80.push2.eastmoney.com/api/qt/clist/get"
    
    async def sync_stock_list(self, db: AsyncSession) -> Dict[str, int]:
        """同步股票列表到数据库
        
        Returns:
            Dict: {"total": 总数, "created": 新增数, "updated": 更新数}
        """
        try:
            logger.info("开始同步股票列表...")
            
            # 使用东方财富网 API 获取 A 股股票列表
            # 参数说明：
            # pn: 页码
            # pz: 每页数量
            # fs: 市场筛选（m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048）
            # fields: 字段列表
            params = {
                "pn": 1,
                "pz": 10000,  # 获取所有股票
                "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                "fields": "f12,f14,f100",  # f12:代码, f14:名称, f100:行业
            }
            
            response = requests.get(self.STOCK_LIST_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data or "data" not in data or not data["data"]:
                logger.warning("获取股票列表为空")
                return {"total": 0, "created": 0, "updated": 0}
            
            stock_dict = data["data"].get("diff", {})
            total = len(stock_dict)
            created_count = 0
            updated_count = 0
            
            for key, item in stock_dict.items():
                stock_code = str(item.get("f12", "")).zfill(6)  # 补齐6位
                stock_name = item.get("f14", "")
                industry = item.get("f100", "")
                
                if not stock_code or not stock_name:
                    continue
                
                # 判断交易所
                exchange = self._get_exchange(stock_code)
                market = self._get_market(stock_code)
                
                # 检查是否已存在
                result = await db.execute(
                    select(Stock).where(Stock.code == stock_code)
                )
                existing_stock = result.scalar_one_or_none()
                
                if existing_stock:
                    # 更新
                    existing_stock.name = stock_name
                    existing_stock.exchange = exchange
                    existing_stock.market = market
                    existing_stock.industry = industry
                    existing_stock.updated_at = datetime.now()
                    updated_count += 1
                else:
                    # 新增
                    new_stock = Stock(
                        code=stock_code,
                        name=stock_name,
                        exchange=exchange,
                        market=market,
                        industry=industry,
                        is_st=self._is_st(stock_name),
                        status="active",
                    )
                    db.add(new_stock)
                    created_count += 1
            
            await db.commit()
            logger.info(f"股票列表同步完成：总数{total}，新增{created_count}，更新{updated_count}")
            
            return {"total": total, "created": created_count, "updated": updated_count}
            
        except Exception as e:
            logger.error(f"同步股票列表失败: {e}")
            await db.rollback()
            raise
    
    async def get_stock_by_code(self, db: AsyncSession, stock_code: str) -> Optional[Stock]:
        """根据股票代码获取股票信息"""
        result = await db.execute(
            select(Stock).where(Stock.code == stock_code)
        )
        return result.scalar_one_or_none()
    
    async def search_stocks(self, db: AsyncSession, keyword: str, limit: int = 20) -> List[Stock]:
        """搜索股票（按代码或名称）"""
        result = await db.execute(
            select(Stock).where(
                (Stock.code.contains(keyword)) | (Stock.name.contains(keyword))
            ).limit(limit)
        )
        return result.scalars().all()
    
    async def get_all_stocks(self, db: AsyncSession, limit: int = 100, offset: int = 0) -> List[Stock]:
        """获取所有股票"""
        result = await db.execute(
            select(Stock).offset(offset).limit(limit)
        )
        return result.scalars().all()
    
    async def get_stock_count(self, db: AsyncSession) -> int:
        """获取股票总数"""
        result = await db.execute(select(func.count(Stock.id)))
        return result.scalar()
    
    def _get_exchange(self, stock_code: str) -> str:
        """根据股票代码判断交易所"""
        if stock_code.startswith('6'):
            return 'sh'  # 上海证券交易所
        elif stock_code.startswith('0') or stock_code.startswith('3'):
            return 'sz'  # 深圳证券交易所
        elif stock_code.startswith('4') or stock_code.startswith('8'):
            return 'bj'  # 北京证券交易所
        else:
            return 'unknown'
    
    def _get_market(self, stock_code: str) -> str:
        """根据股票代码判断市场类型"""
        if stock_code.startswith('60'):
            return '主板'  # 上海主板
        elif stock_code.startswith('000'):
            return '主板'  # 深圳主板
        elif stock_code.startswith('001'):
            return '主板'  # 深圳主板
        elif stock_code.startswith('002'):
            return '中小板'
        elif stock_code.startswith('003'):
            return '中小板'
        elif stock_code.startswith('300') or stock_code.startswith('301'):
            return '创业板'
        elif stock_code.startswith('688') or stock_code.startswith('689'):
            return '科创板'
        elif stock_code.startswith('4') or stock_code.startswith('8'):
            return '北交所'
        else:
            return '其他'
    
    def _is_st(self, stock_name: str) -> bool:
        """判断是否ST股票"""
        return 'ST' in stock_name.upper() or '*ST' in stock_name.upper()

# 创建服务实例
stock_service = StockService()