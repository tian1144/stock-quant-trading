"""
A股规则适配模块 - T+1/涨跌停/停牌/ST处理
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple
import pandas as pd
from loguru import logger


A_SHARE_CONFIG = {
    "commission_rate": 0.00025,
    "stamp_tax_rate": 0.0005,
    "min_commission": 5.0,
    "slippage_pct": 0.001,
    "min_lot_size": 100,
    "normal_limit_pct": 0.10,
    "gem_limit_pct": 0.20,
    "star_limit_pct": 0.20,
    "bse_limit_pct": 0.30,
}


def get_limit_pct(code: str) -> float:
    if code.startswith('688') or code.startswith('689'):
        return A_SHARE_CONFIG["star_limit_pct"]
    if code.startswith('300') or code.startswith('301'):
        return A_SHARE_CONFIG["gem_limit_pct"]
    if code.startswith('8') or code.startswith('4'):
        return A_SHARE_CONFIG["bse_limit_pct"]
    return A_SHARE_CONFIG["normal_limit_pct"]


def is_gem_or_star(code: str) -> bool:
    return code.startswith('300') or code.startswith('301') or code.startswith('688') or code.startswith('689')


def is_st_stock(name: str) -> bool:
    return 'ST' in name.upper() or '*ST' in name.upper()


def check_can_buy(code: str, price: float, prev_close: float, name: str = "") -> Tuple[bool, str]:
    if is_st_stock(name):
        return False, "ST股票禁止买入"
    if prev_close <= 0:
        return False, "前收盘价为0，可能停牌"
    limit_pct = get_limit_pct(code)
    upper_limit = prev_close * (1 + limit_pct)
    if price >= upper_limit:
        return False, f"涨停价{upper_limit:.2f}，无法买入"
    return True, "可买入"


def check_can_sell(code: str, price: float, prev_close: float) -> Tuple[bool, str]:
    if prev_close <= 0:
        return False, "前收盘价为0，可能停牌"
    limit_pct = get_limit_pct(code)
    lower_limit = prev_close * (1 - limit_pct)
    if price <= lower_limit:
        return False, f"跌停价{lower_limit:.2f}，无法卖出"
    return True, "可卖出"


def check_t_plus_1(buy_date: str, sell_date: str) -> Tuple[bool, str]:
    try:
        bd = buy_date[:10] if len(buy_date) >= 10 else buy_date
        sd = sell_date[:10] if len(sell_date) >= 10 else sell_date
        if sd <= bd:
            return False, "T+1规则：当日买入不可当日卖出"
        return True, "T+1检查通过"
    except Exception:
        return True, "T+1检查跳过（日期格式异常）"


def calculate_a_share_fees(side: str, price: float, quantity: int) -> dict:
    amount = price * quantity
    commission = max(amount * A_SHARE_CONFIG["commission_rate"], A_SHARE_CONFIG["min_commission"])
    stamp_tax = amount * A_SHARE_CONFIG["stamp_tax_rate"] if side == "sell" else 0
    total_fee = commission + stamp_tax
    return {
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "total_fee": round(total_fee, 2),
    }


def apply_slippage(side: str, price: float) -> float:
    slip = price * A_SHARE_CONFIG["slippage_pct"]
    if side == "buy":
        return round(price + slip, 3)
    return round(price - slip, 3)


def simulate_fill(code: str, side: str, price: float, prev_close: float, name: str = "") -> dict:
    can_trade, reason = check_can_buy(code, price, prev_close, name) if side == "buy" else check_can_sell(code, price, prev_close)
    if not can_trade:
        return {"filled": False, "reason": reason, "fill_price": 0}
    fill_price = apply_slippage(side, price)
    return {"filled": True, "reason": "成交", "fill_price": fill_price}
