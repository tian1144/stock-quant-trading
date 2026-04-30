# 市场行情服务

import requests
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


class MarketService:
    """市场行情服务（东方财富网API）"""
    
    BASE_URL = "http://push2.eastmoney.com/api"
    
    @classmethod
    def get_stock_quote(cls, stock_code: str) -> Optional[dict]:
        exchange = '1' if stock_code.startswith('6') else '0'
        secid = f"{exchange}.{stock_code}"
        url = f"{cls.BASE_URL}/qt/stock/get"
        params = {"secid": secid, "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f171"}
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data and "data" in data and data["data"]:
                d = data["data"]
                return {
                    "code": stock_code, "name": d.get("f58", ""),
                    "current_price": d.get("f43", 0) / 100,
                    "high_price": d.get("f44", 0) / 100,
                    "low_price": d.get("f45", 0) / 100,
                    "open_price": d.get("f46", 0) / 100,
                    "volume": d.get("f47", 0), "amount": d.get("f48", 0),
                    "change": (d.get("f169", 0) - d.get("f170", 0)) / 100,
                    "change_percent": d.get("f170", 0) / 100,
                }
            return None
        except Exception as e:
            logger.error(f"获取{stock_code}行情失败: {e}")
            return None
    
    @classmethod
    def get_stock_quotes_batch(cls, stock_codes: List[str]) -> List[dict]:
        if not stock_codes:
            return []
        secids = [f"{'1' if c.startswith('6') else '0'}.{c}" for c in stock_codes]
        url = f"{cls.BASE_URL}/qt/ulist.np/get"
        params = {"secids": ",".join(secids), "fields": "f2,f3,f4,f5,f6,f12,f14"}
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            results = []
            if data and "data" in data and data["data"] and "diff" in data["data"]:
                for item in data["data"]["diff"]:
                    results.append({
                        "code": item.get("f12", ""), "name": item.get("f14", ""),
                        "current_price": item.get("f2", 0) / 100,
                        "change_percent": item.get("f3", 0) / 100,
                        "volume": item.get("f5", 0), "amount": item.get("f6", 0),
                    })
            return results
        except Exception as e:
            logger.error(f"批量获取行情失败: {e}")
            return []
    
    @classmethod
    def get_kline_data(cls, stock_code: str, period: str = "daily", count: int = 60) -> List[dict]:
        exchange = '1' if stock_code.startswith('6') else '0'
        secid = f"{exchange}.{stock_code}"
        klt_map = {"daily": 101, "weekly": 102, "monthly": 103}
        klt = klt_map.get(period, 101)
        url = f"{cls.BASE_URL}/qt/stock/kline/get"
        params = {"secid": secid, "klt": klt, "fqt": 1, "end": 20500101, "lmt": count, "fields": "f43,f44,f45,f46,f47,f48,f60"}
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            kline_list = []
            if data and "data" in data and data["data"] and "klines" in data["data"]:
                for kline in data["data"]["klines"]:
                    parts = kline.split(",")
                    if len(parts) >= 7:
                        kline_list.append({
                            "trade_date": parts[0], "open_price": float(parts[1]),
                            "close_price": float(parts[2]), "high_price": float(parts[3]),
                            "low_price": float(parts[4]), "volume": int(parts[5]), "amount": float(parts[6]),
                        })
            return kline_list
        except Exception as e:
            logger.error(f"获取{stock_code}K线失败: {e}")
            return []
    
    @classmethod
    def get_market_overview(cls) -> dict:
        indices = [("1.000001", "上证指数"), ("0.399001", "深证成指"), ("0.399006", "创业板指")]
        results = []
        for secid, name in indices:
            try:
                response = requests.get(f"{cls.BASE_URL}/qt/stock/get", params={"secid": secid, "fields": "f43,f169,f170"}, timeout=5)
                data = response.json()
                if data and "data" in data and data["data"]:
                    d = data["data"]
                    results.append({
                        "code": secid.split(".")[1], "name": name,
                        "price": d.get("f43", 0) / 100,
                        "change": d.get("f169", 0) / 100,
                        "change_percent": d.get("f170", 0) / 100,
                    })
            except Exception as e:
                logger.error(f"获取{name}指数失败: {e}")
        return {"indices": results}
