from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import logging
import os
import time
import re
import json
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0'

app = FastAPI(
    title="股票量化智能选股与实时模拟盘",
    version="1.0.0",
    description="股票量化智能选股与实时模拟盘小程序后端 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_stock_cache = {"stocks": [], "updated_at": 0}
CACHE_TTL = 300

def _classify_stock(symbol: str):
    code = symbol.replace("sh", "").replace("sz", "").replace("bj", "")
    if code.startswith('6'):
        exchange = 'sh'
    elif code.startswith('0') or code.startswith('3'):
        exchange = 'sz'
    else:
        exchange = 'bj'

    if code.startswith('60'):
        market = '主板'
    elif code.startswith('000') or code.startswith('001'):
        market = '主板'
    elif code.startswith('002') or code.startswith('003'):
        market = '中小板'
    elif code.startswith('300') or code.startswith('301'):
        market = '创业板'
    elif code.startswith('688') or code.startswith('689'):
        market = '科创板'
    else:
        market = '北交所'

    return exchange, market, code

def _fetch_all_stocks_sina():
    """通过新浪API分页获取全部A股数据"""
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
    headers = {'Referer': 'https://finance.sina.com.cn/', 'User-Agent': UA}
    all_stocks = []
    page = 1

    while True:
        params = {
            'page': page,
            'num': 80,
            'sort': 'symbol',
            'asc': 1,
            'node': 'hs_a',
            'symbol': '',
            '_s_r_a': 'init'
        }
        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
            data = json.loads(response.text)
            if not data:
                break

            for item in data:
                symbol = item.get("symbol", "")
                exchange, market, code = _classify_stock(symbol)
                name = item.get("name", "")
                all_stocks.append({
                    "code": code,
                    "name": name,
                    "exchange": exchange,
                    "market": market,
                    "industry": "",
                    "is_st": 'ST' in name.upper(),
                    "price": float(item.get("trade", 0)),
                    "pct_change": float(item.get("changepercent", 0)),
                    "volume": int(float(item.get("volume", 0))),
                    "amount": float(item.get("amount", 0)),
                })

            if len(data) < 80:
                break

            page += 1
            if page > 80:
                break
        except Exception as e:
            logger.error(f"新浪API第{page}页请求失败: {e}")
            break

    return all_stocks

def _fetch_ths_quote(code: str):
    """通过同花顺API获取单只股票实时行情"""
    try:
        r = requests.get(
            f'http://d.10jqka.com.cn/v6/line/hs_{code}/01/today.js',
            headers={'User-Agent': UA, 'Referer': 'http://stockpage.10jqka.com.cn/'},
            timeout=5
        )
        if r.status_code == 200:
            match = re.search(r'\((.*)\)', r.text, re.S)
            if match:
                data = json.loads(match.group(1))
                key = list(data.keys())[0]
                info = data[key]
                return {
                    "name": info.get("name", ""),
                    "open": float(info.get("7", 0)),
                    "price": float(info.get("11", 0)),
                    "volume": int(info.get("13", 0)),
                    "amount": float(info.get("19", 0)),
                }
    except Exception as e:
        logger.debug(f"同花顺行情获取失败 {code}: {e}")
    return None

@app.get("/", response_class=HTMLResponse)
async def root():
    html_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(html_file):
        with open(html_file, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>股票行情系统</h1><p>网页文件未找到</p>")

@app.get("/api/v1/health")
async def health_check():
    return {"status": "ok", "message": "服务运行正常"}

@app.get("/api/v1/stocks")
async def get_stocks(
    limit: int = Query(100, ge=1, le=10000),
    offset: int = Query(0, ge=0)
):
    """获取股票列表（带分页，数据来自新浪财经）"""
    try:
        now = time.time()
        if not _stock_cache["stocks"] or now - _stock_cache["updated_at"] > CACHE_TTL:
            logger.info("正在从新浪API获取全部A股数据...")
            stocks = _fetch_all_stocks_sina()
            if stocks:
                _stock_cache["stocks"] = stocks
                _stock_cache["updated_at"] = now
                logger.info(f"获取到 {len(stocks)} 只股票")
            else:
                logger.warning("新浪API返回空数据")

        all_stocks = _stock_cache["stocks"]
        total = len(all_stocks)
        paginated_stocks = all_stocks[offset:offset + limit]

        return {"total": total, "stocks": paginated_stocks}

    except Exception as e:
        logger.error(f"获取股票列表失败: {e}")
        return {"total": 0, "stocks": [], "error": str(e)}

@app.get("/api/v1/stocks/search")
async def search_stocks(
    keyword: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100)
):
    """搜索股票（本地缓存过滤）"""
    try:
        now = time.time()
        if not _stock_cache["stocks"] or now - _stock_cache["updated_at"] > CACHE_TTL:
            stocks = _fetch_all_stocks_sina()
            if stocks:
                _stock_cache["stocks"] = stocks
                _stock_cache["updated_at"] = now

        all_stocks = _stock_cache["stocks"]
        kw = keyword.lower()
        results = [
            s for s in all_stocks
            if kw in s["code"].lower() or kw in s["name"].lower()
        ]

        return results[:limit]

    except Exception as e:
        logger.error(f"搜索股票失败: {e}")
        return []

@app.post("/api/v1/stocks/sync")
async def sync_stock_list():
    """强制刷新股票缓存"""
    stocks = _fetch_all_stocks_sina()
    _stock_cache["stocks"] = stocks
    _stock_cache["updated_at"] = time.time()
    return {"message": "同步成功", "total": len(stocks)}

@app.get("/api/v1/market/snapshot/{stock_code}")
async def get_snapshot(stock_code: str):
    """获取单只股票实时行情（同花顺数据源）"""
    quote = _fetch_ths_quote(stock_code)
    if quote:
        return {
            "code": stock_code,
            "name": quote["name"],
            "current_price": quote["price"],
            "open": quote["open"],
            "volume": quote["volume"],
            "amount": quote["amount"],
            "source": "同花顺",
        }
    return {"error": "获取行情数据失败"}

@app.get("/api/v1/market/snapshots")
async def get_snapshots(
    codes: str = Query(..., description="股票代码，逗号分隔")
):
    """批量获取股票实时行情（同花顺数据源）"""
    stock_codes = [code.strip() for code in codes.split(",") if code.strip()][:20]
    snapshots = []

    for code in stock_codes:
        quote = _fetch_ths_quote(code)
        if quote:
            snapshots.append({
                "code": code,
                "name": quote["name"],
                "price": quote["price"],
                "open": quote["open"],
                "volume": quote["volume"],
                "amount": quote["amount"],
            })

    return {"snapshots": snapshots}
