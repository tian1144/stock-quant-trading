# 股票数据服务

import requests
import logging

logger = logging.getLogger(__name__)


class StockService:
    """股票数据服务（东方财富网API）"""
    
    BASE_URL = "http://push2.eastmoney.com/api"
    
    @classmethod
    def get_stock_list(cls, page: int = 1, page_size: int = 20):
        url = f"{cls.BASE_URL}/qt/clist/get"
        params = {
            "pn": page, "pz": page_size,
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f12,f14,f100",
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data and "data" in data and data["data"] and "diff" in data["data"]:
                stocks = []
                for key, item in data["data"]["diff"].items():
                    stock_code = item.get("f12", "")
                    stock_name = item.get("f14", "")
                    if stock_code and stock_name:
                        stocks.append({"code": stock_code, "name": stock_name, "industry": item.get("f100", "")})
                return {"total": data["data"].get("total", 0), "items": stocks}
            return {"total": 0, "items": []}
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return {"total": 0, "items": [], "error": str(e)}
    
    @classmethod
    def search_stocks(cls, keyword: str):
        url = f"{cls.BASE_URL}/qt/clist/get"
        params = {
            "pn": 1, "pz": 50,
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f12,f14,f100",
        }
        try:
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data and "data" in data and data["data"] and "diff" in data["data"]:
                results = []
                for key, item in data["data"]["diff"].items():
                    stock_code = item.get("f12", "")
                    stock_name = item.get("f14", "")
                    if keyword.lower() in stock_code.lower() or keyword.lower() in stock_name.lower():
                        results.append({"code": stock_code, "name": stock_name, "industry": item.get("f100", "")})
                return results[:20]
            return []
        except Exception as e:
            logger.error(f"搜索股票失败: {e}")
            return []
