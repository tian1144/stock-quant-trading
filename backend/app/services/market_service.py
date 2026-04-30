# 行情数据服务模块
# 使用 requests 获取日线行情和实时行情（东方财富网 API）

import requests
import json
from typing import List, Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from datetime import datetime, date, timedelta
import logging

from app.models.market import StockDailyBar, StockRealtimeQuote
from app.models.stock import Stock
from app.core.redis import set_market_snapshot, get_market_snapshot, get_market_snapshots

logger = logging.getLogger(__name__)

class MarketService:
    """行情数据服务类"""
    
    # 东方财富网 API 地址
    DAILY_BAR_URL = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    REALTIME_QUOTE_URL = "http://push2.eastmoney.com/api/qt/stock/get"
    BATCH_QUOTE_URL = "http://push2.eastmoney.com/api/qt/ulist.np/get"
    
    async def sync_daily_bars(self, db: AsyncSession, stock_code: str, days: int = 100) -> Dict[str, int]:
        """同步股票日线行情数据
        
        Args:
            db: 数据库会话
            stock_code: 股票代码
            days: 获取最近N天的数据
            
        Returns:
            Dict: {"total": 总数, "created": 新增数, "updated": 更新数}
        """
        try:
            logger.info(f"开始同步股票 {stock_code} 的日线行情...")
            
            # 构建股票代码（需要加上市场前缀）
            exchange = self._get_exchange(stock_code)
            secid = f"{exchange}.{stock_code}" if exchange != "unknown" else f"0.{stock_code}"
            
            # 使用东方财富网 API 获取日线行情
            params = {
                "secid": secid,
                "fields1": "f1,f2,f3,f4,f5,f6,f7,f8",
                "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                "klt": "101",  # 101:日线
                "fqt": "1",    # 1:前复权
                "end": "20500101",
                "lmt": days,   # 获取条数
            }
            
            response = requests.get(self.DAILY_BAR_URL, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            if not data or "data" not in data or not data["data"]:
                logger.warning(f"股票 {stock_code} 日线数据为空")
                return {"total": 0, "created": 0, "updated": 0}
            
            klines = data["data"].get("klines", [])
            total = len(klines)
            created_count = 0
            updated_count = 0
            
            for kline in klines:
                # 解析K线数据：日期,开盘,收盘,最高,最低,成交量,成交额,振幅,涨跌幅,涨跌额,换手率
                parts = kline.split(",")
                if len(parts) < 11:
                    continue
                
                trade_date = datetime.strptime(parts[0], "%Y-%m-%d").date()
                open_price = float(parts[1])
                close_price = float(parts[2])
                high_price = float(parts[3])
                low_price = float(parts[4])
                volume = int(parts[5])
                amount = float(parts[6])
                pct_change = float(parts[8])
                turnover_rate = float(parts[10])
                
                # 检查是否已存在
                result = await db.execute(
                    select(StockDailyBar).where(
                        StockDailyBar.stock_code == stock_code,
                        StockDailyBar.trade_date == trade_date
                    )
                )
                existing_bar = result.scalar_one_or_none()
                
                if existing_bar:
                    # 更新
                    existing_bar.open = open_price
                    existing_bar.high = high_price
                    existing_bar.low = low_price
                    existing_bar.close = close_price
                    existing_bar.volume = volume
                    existing_bar.amount = amount
                    existing_bar.pct_change = pct_change
                    existing_bar.turnover_rate = turnover_rate
                    updated_count += 1
                else:
                    # 新增
                    new_bar = StockDailyBar(
                        stock_code=stock_code,
                        trade_date=trade_date,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        volume=volume,
                        amount=amount,
                        pct_change=pct_change,
                        turnover_rate=turnover_rate,
                    )
                    db.add(new_bar)
                    created_count += 1
            
            await db.commit()
            logger.info(f"股票 {stock_code} 日线同步完成：总数{total}，新增{created_count}，更新{updated_count}")
            
            return {"total": total, "created": created_count, "updated": updated_count}
            
        except Exception as e:
            logger.error(f"同步股票 {stock_code} 日线失败: {e}")
            await db.rollback()
            raise
    
    async def get_daily_bars(self, db: AsyncSession, stock_code: str, limit: int = 100) -> List[StockDailyBar]:
        """获取股票日线行情数据"""
        result = await db.execute(
            select(StockDailyBar)
            .where(StockDailyBar.stock_code == stock_code)
            .order_by(desc(StockDailyBar.trade_date))
            .limit(limit)
        )
        return result.scalars().all()
    
    async def get_realtime_quote(self, stock_code: str) -> Optional[Dict]:
        """获取股票实时行情（优先从 Redis 缓存获取）"""
        # 先从 Redis 获取
        snapshot = await get_market_snapshot(stock_code)
        if snapshot:
            return snapshot
        
        # 如果缓存没有，从东方财富网 API 获取
        try:
            exchange = self._get_exchange(stock_code)
            secid = f"{exchange}.{stock_code}" if exchange != "unknown" else f"0.{stock_code}"
            
            params = {
                "secid": secid,
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f171",
            }
            
            response = requests.get(self.REALTIME_QUOTE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data and "data" in data and data["data"]:
                stock_data = data["data"]
                quote = {
                    "code": stock_code,
                    "name": stock_data.get("f58", ""),
                    "price": stock_data.get("f43", 0) / 100,  # 价格需要除以100
                    "pct_change": stock_data.get("f170", 0) / 100,  # 涨跌幅
                    "volume": stock_data.get("f47", 0),
                    "amount": stock_data.get("f48", 0),
                    "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                # 缓存到 Redis
                await set_market_snapshot(stock_code, quote, expire_seconds=300)
                return quote
        except Exception as e:
            logger.error(f"获取股票 {stock_code} 实时行情失败: {e}")
        
        return None
    
    async def get_realtime_quotes_batch(self, stock_codes: List[str]) -> Dict[str, Dict]:
        """批量获取股票实时行情"""
        result = {}
        
        # 先从 Redis 批量获取
        cached = await get_market_snapshots(stock_codes)
        result.update(cached)
        
        # 获取缓存中没有的股票
        missing_codes = [code for code in stock_codes if code not in result]
        if missing_codes:
            try:
                # 构建批量查询参数
                secids = []
                for code in missing_codes[:50]:  # 限制最多50只
                    exchange = self._get_exchange(code)
                    secid = f"{exchange}.{code}" if exchange != "unknown" else f"0.{code}"
                    secids.append(secid)
                
                params = {
                    "secids": ",".join(secids),
                    "fields": "f12,f14,f43,f44,f45,f46,f47,f48,f60,f169,f170",
                }
                
                response = requests.get(self.BATCH_QUOTE_URL, params=params, timeout=15)
                response.raise_for_status()
                data = response.json()
                
                if data and "data" in data and data["data"] and "diff" in data["data"]:
                    diff_data = data["data"]["diff"]
                    for key, item in diff_data.items():
                        code = item.get("f12", "")
                        if code in missing_codes:
                            quote = {
                                "code": code,
                                "name": item.get("f14", ""),
                                "price": item.get("f43", 0) / 100,
                                "pct_change": item.get("f170", 0) / 100,
                                "volume": item.get("f47", 0),
                                "amount": item.get("f48", 0),
                                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            }
                            result[code] = quote
                            # 缓存到 Redis
                            await set_market_snapshot(code, quote, expire_seconds=300)
            except Exception as e:
                logger.error(f"批量获取实时行情失败: {e}")
        
        return result
    
    async def refresh_realtime_prices(self, db: AsyncSession):
        """刷新实时价格（定时任务调用）"""
        try:
            # 获取所有活跃股票
            result = await db.execute(
                select(Stock).where(Stock.status == "active", Stock.is_suspended == False)
            )
            stocks = result.scalars().all()
            
            if not stocks:
                return
            
            # 批量获取实时行情
            stock_codes = [stock.code for stock in stocks]
            quotes = await self.get_realtime_quotes_batch(stock_codes)
            
            updated_count = 0
            for code, quote in quotes.items():
                if quote:
                    updated_count += 1
            
            logger.info(f"实时价格刷新完成，更新 {updated_count} 只股票")
            
        except Exception as e:
            logger.error(f"刷新实时价格失败: {e}")
    
    def _get_exchange(self, stock_code: str) -> str:
        """根据股票代码判断交易所"""
        if stock_code.startswith('6'):
            return '1'  # 上海证券交易所
        elif stock_code.startswith('0') or stock_code.startswith('3'):
            return '0'  # 深圳证券交易所
        elif stock_code.startswith('4') or stock_code.startswith('8'):
            return '0'  # 北京证券交易所
        else:
            return '0'

# 创建服务实例
market_service = MarketService()