"""
内存状态中心 - 替代数据库和Redis
所有服务通过此模块读写状态，使用模块级变量实现单例
"""
import time
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime

# ==================== 股票宇宙 ====================
_stock_universe: Dict[str, dict] = {}  # code -> stock info
_stock_universe_updated_at: float = 0

def get_stock_universe() -> Dict[str, dict]:
    return _stock_universe

def update_stock_universe(stocks: list):
    global _stock_universe, _stock_universe_updated_at
    _stock_universe = {s["code"]: s for s in stocks}
    _stock_universe_updated_at = time.time()

def get_stock_info(code: str) -> Optional[dict]:
    return _stock_universe.get(code)

def get_stock_universe_updated_at() -> float:
    return _stock_universe_updated_at

# ==================== 日线K线缓存 ====================
_daily_bars_cache: Dict[str, pd.DataFrame] = {}  # code -> DataFrame

def get_daily_bars(code: str) -> Optional[pd.DataFrame]:
    return _daily_bars_cache.get(code)

def set_daily_bars(code: str, df: pd.DataFrame):
    _daily_bars_cache[code] = df

def get_all_daily_bars() -> Dict[str, pd.DataFrame]:
    return _daily_bars_cache

def get_daily_bars_codes() -> list:
    return list(_daily_bars_cache.keys())

# ==================== 实时行情缓存 ====================
_realtime_cache: Dict[str, dict] = {}  # code -> realtime data
_realtime_updated_at: float = 0

def get_realtime(code: str) -> Optional[dict]:
    return _realtime_cache.get(code)

def set_realtime(code: str, data: dict):
    _realtime_cache[code] = data

def set_realtime_batch(data: Dict[str, dict]):
    _realtime_cache.update(data)

def get_all_realtime() -> Dict[str, dict]:
    return _realtime_cache

def get_realtime_updated_at() -> float:
    return _realtime_updated_at

def update_realtime_timestamp():
    global _realtime_updated_at
    _realtime_updated_at = time.time()

# ==================== 价格历史（5分钟内，用于反追高检测）====================
_price_history: Dict[str, list] = {}  # code -> [(timestamp, price), ...]

def add_price_snapshot(code: str, price: float):
    now = time.time()
    if code not in _price_history:
        _price_history[code] = []
    _price_history[code].append((now, price))
    # 保留最近5分钟的数据
    cutoff = now - 300
    _price_history[code] = [(t, p) for t, p in _price_history[code] if t > cutoff]

def get_price_5min_ago(code: str) -> Optional[float]:
    if code not in _price_history or not _price_history[code]:
        return None
    target_time = time.time() - 300
    closest = None
    min_diff = float('inf')
    for t, p in _price_history[code]:
        diff = abs(t - target_time)
        if diff < min_diff:
            min_diff = diff
            closest = p
    return closest

# ==================== 选股结果 ====================
_screening_results: list = []
_screening_updated_at: float = 0

def get_screening_results() -> list:
    return _screening_results

def set_screening_results(results: list):
    global _screening_results, _screening_updated_at
    _screening_results = results
    _screening_updated_at = time.time()

def get_screening_updated_at() -> float:
    return _screening_updated_at

# ==================== 交易信号 ====================
_signals: list = []
_signal_history: list = []
_ai_recommendations: dict = {
    "recommendations": [],
    "summary": {},
    "generated_at": None,
    "ai_meta": {},
}

def get_signals() -> list:
    return _signals

def set_signals(signals: list):
    global _signals
    _signals = signals

def add_signal(signal: dict):
    _signals.append(signal)
    _signal_history.append(signal)

def clear_expired_signals():
    global _signals
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _signals = [s for s in _signals if s.get("expires_at", "") > now]

def get_signal_history() -> list:
    return _signal_history

def get_ai_recommendations() -> dict:
    return _ai_recommendations.copy()

def set_ai_recommendations(data: dict):
    global _ai_recommendations
    _ai_recommendations = data or {
        "recommendations": [],
        "summary": {},
        "generated_at": None,
        "ai_meta": {},
    }

# ==================== 组合状态 ====================
_portfolio: dict = {
    "initial_cash": 200000.0,
    "available_cash": 200000.0,
    "frozen_cash": 0.0,
    "market_value": 0.0,
    "total_asset": 200000.0,
    "total_profit": 0.0,
    "total_profit_pct": 0.0,
    "today_profit": 0.0,
    "today_trade_count": 0,
}

def get_portfolio() -> dict:
    return _portfolio.copy()

def update_portfolio(updates: dict):
    _portfolio.update(updates)

# ==================== 持仓 ====================
_positions: Dict[str, dict] = {}  # code -> position dict

def get_positions() -> Dict[str, dict]:
    return _positions

def get_position(code: str) -> Optional[dict]:
    return _positions.get(code)

def set_position(code: str, pos: dict):
    _positions[code] = pos

def remove_position(code: str):
    _positions.pop(code, None)

def get_position_count() -> int:
    return len(_positions)

# ==================== 订单记录 ====================
_orders: list = []

def get_orders() -> list:
    return _orders

def add_order(order: dict):
    _orders.append(order)

# ==================== 新闻缓存 ====================
_news_cache: list = []
_news_negative: Dict[str, list] = {}  # code -> [negative_keywords]
_news_updated_at: float = 0
_news_meta: dict = {}

def get_news() -> list:
    return _news_cache

def set_news(news: list):
    global _news_cache, _news_updated_at
    _news_cache = news
    _news_updated_at = time.time()

def get_news_meta() -> dict:
    return _news_meta.copy()

def set_news_meta(meta: dict):
    global _news_meta
    _news_meta = meta or {}

def get_negative_news() -> Dict[str, list]:
    return _news_negative

def set_negative_news(data: Dict[str, list]):
    global _news_negative
    _news_negative = data

def get_news_updated_at() -> float:
    return _news_updated_at

# ==================== 资金流向缓存 ====================
_money_flow_cache: Dict[str, dict] = {}  # code -> money flow data

def get_money_flow(code: str) -> Optional[dict]:
    return _money_flow_cache.get(code)

def set_money_flow(code: str, data: dict):
    _money_flow_cache[code] = data

def get_all_money_flow() -> Dict[str, dict]:
    return _money_flow_cache

# ==================== 系统状态 ====================
_system_state: dict = {
    "auto_trade_enabled": False,
    "last_screening_time": None,
    "last_signal_time": None,
    "last_news_time": None,
    "total_signals_today": 0,
    "startup_time": None,
}

def get_system_state() -> dict:
    return _system_state.copy()

def update_system_state(updates: dict):
    _system_state.update(updates)

# ==================== 北向资金 ====================
_northbound_flow: dict = {}
_northbound_updated_at: float = 0

def get_northbound_flow() -> dict:
    return _northbound_flow

def set_northbound_flow(data: dict):
    global _northbound_flow, _northbound_updated_at
    _northbound_flow = data
    _northbound_updated_at = time.time()

# ==================== 分时数据缓存 ====================
_intraday_cache: Dict[str, list] = {}  # code -> minute data list

def get_intraday(code: str) -> list:
    return _intraday_cache.get(code, [])

def set_intraday(code: str, data: list):
    _intraday_cache[code] = data

# ==================== 多周期K线缓存 ====================
_kline_cache: Dict[str, Dict[int, pd.DataFrame]] = {}  # code -> {period: DataFrame}

def get_kline(code: str, period: int = 101) -> Optional[pd.DataFrame]:
    if code in _kline_cache:
        return _kline_cache[code].get(period)
    return None

def set_kline(code: str, period: int, df: pd.DataFrame):
    if code not in _kline_cache:
        _kline_cache[code] = {}
    _kline_cache[code][period] = df

# ==================== 筹码分布缓存 ====================
_chip_cache: Dict[str, dict] = {}  # code -> chip distribution data

def get_chip_distribution(code: str) -> Optional[dict]:
    return _chip_cache.get(code)

def set_chip_distribution(code: str, data: dict):
    _chip_cache[code] = data

# ==================== 板块数据缓存 ====================
_sector_list: list = []
_sector_details: Dict[str, dict] = {}  # sector_code -> detail data
_sector_money_flow: list = []
_sector_updated_at: float = 0

def get_sector_list() -> list:
    return _sector_list

def set_sector_list(data: list):
    global _sector_list, _sector_updated_at
    _sector_list = data
    _sector_updated_at = time.time()

def get_sector_detail(code: str) -> Optional[dict]:
    return _sector_details.get(code)

def set_sector_detail(code: str, data: dict):
    _sector_details[code] = data

def get_sector_money_flow() -> list:
    return _sector_money_flow

def set_sector_money_flow(data: list):
    global _sector_money_flow
    _sector_money_flow = data

def get_sector_updated_at() -> float:
    return _sector_updated_at

# ==================== 用户交易偏好 ====================
_user_settings: dict = {
    "trading_style": "short",        # short=短线, medium=中线, long=长线
    "risk_appetite": "moderate",     # conservative=保守, moderate=稳健, aggressive=激进
    "board_allow": {
        "main": True,    # 主板
        "gem": True,     # 创业板
        "star": True,    # 科创板
        "bse": True,     # 北交所
    },
    "blocked_sectors": [],           # 黑名单板块名称列表
}

def get_user_settings() -> dict:
    return _user_settings.copy()

def update_user_settings(updates: dict):
    global _user_settings
    if "board_allow" in updates and isinstance(updates["board_allow"], dict):
        _user_settings["board_allow"].update(updates["board_allow"])
        updates = {k: v for k, v in updates.items() if k != "board_allow"}
    _user_settings.update(updates)

# ==================== 工具函数 ====================
def save_portfolio_to_file(filepath: str = "portfolio_state.json"):
    """将组合状态保存到文件，重启后可恢复"""
    import json
    state = {
        "portfolio": _portfolio,
        "positions": _positions,
        "orders": _orders[-100:],  # 只保存最近100条
        "user_settings": _user_settings,
        "saved_at": datetime.now().isoformat(),
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def load_portfolio_from_file(filepath: str = "portfolio_state.json"):
    """从文件恢复组合状态"""
    import json
    import os
    global _portfolio, _positions, _orders
    if not os.path.exists(filepath):
        return False
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            state = json.load(f)
        _portfolio.update(state.get("portfolio", {}))
        _positions.update(state.get("positions", {}))
        _orders.extend(state.get("orders", []))
        if "user_settings" in state:
            _user_settings.update(state["user_settings"])
        return True
    except Exception:
        return False
