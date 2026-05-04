"""
风控管理模块 - QMT标准风控规则
管理仓位限制、止损止盈、交易限制等
"""
from datetime import datetime, timedelta
from typing import Tuple
from loguru import logger

from app.services import state_store

# 风控配置
RISK_CONFIG = {
    "initial_cash": 200000.0,
    "max_single_position_pct": 0.20,      # 单票最大20%
    "max_total_position_pct": 0.80,        # 总仓位最大80%
    "max_position_count": 10,              # 最多持有10只
    "default_stop_loss_pct": 0.05,         # 5%止损
    "default_take_profit_pct": 0.10,       # 10%止盈
    "max_daily_loss_pct": 0.03,            # 日亏损3%暂停交易
    "max_single_trade_amount": 40000.0,    # 单笔最大4万
    "min_trade_amount": 5000.0,            # 单笔最小5000
    "commission_rate": 0.00025,            # 佣金万2.5
    "stamp_tax_rate": 0.0005,              # 印花税万5（卖出）
    "min_commission": 5.0,                 # 最低佣金5元
    "cooldown_after_sell_minutes": 30,     # 卖出后30分钟冷却
    "max_daily_trades": 20,                # 每日最多20笔
}

# 冷却记录：code -> last_sell_time
_cooldown_records: dict = {}

# 今日交易计数
_today_trade_count: int = 0
_today_date: str = ""


def _reset_daily_counter():
    """重置每日计数器"""
    global _today_trade_count, _today_date
    today = datetime.now().strftime("%Y-%m-%d")
    if today != _today_date:
        _today_trade_count = 0
        _today_date = today


def validate_buy_order(code: str, price: float, quantity: int) -> Tuple[bool, str]:
    """验证买入订单是否符合风控规则"""
    from app.execution.kill_switch import check_can_trade

    can_trade, kill_reason = check_can_trade()
    if not can_trade:
        return False, kill_reason

    _reset_daily_counter()
    portfolio = state_store.get_portfolio()
    positions = state_store.get_positions()

    # 1. 数量必须是100的整数倍
    if quantity <= 0 or quantity % 100 != 0:
        return False, "买入数量必须是100的整数倍"

    # 2. 持仓数量限制
    if code not in positions and len(positions) >= RISK_CONFIG["max_position_count"]:
        return False, f"持仓数量已达上限{RISK_CONFIG['max_position_count']}只"

    # 3. 单票仓位限制
    trade_amount = price * quantity
    total_asset = portfolio["total_asset"]
    max_single = total_asset * RISK_CONFIG["max_single_position_pct"]
    existing_amount = 0
    if code in positions:
        existing_amount = positions[code].get("market_value", 0)
    if existing_amount + trade_amount > max_single:
        return False, f"单票仓位将超过{RISK_CONFIG['max_single_position_pct']*100:.0f}%上限"

    # 4. 总仓位限制
    current_market_value = portfolio["market_value"]
    max_total = total_asset * RISK_CONFIG["max_total_position_pct"]
    if current_market_value + trade_amount > max_total:
        return False, f"总仓位将超过{RISK_CONFIG['max_total_position_pct']*100:.0f}%上限"

    # 5. 可用资金检查
    commission = calculate_fees("buy", price, quantity)["total_fee"]
    total_cost = trade_amount + commission
    if total_cost > portfolio["available_cash"]:
        return False, f"可用资金不足（需要{total_cost:.2f}，可用{portfolio['available_cash']:.2f}）"

    # 6. 日亏损限制
    if check_daily_loss_limit():
        return False, "今日亏损已达上限，暂停交易"

    # 7. 每日交易次数限制
    if _today_trade_count >= RISK_CONFIG["max_daily_trades"]:
        return False, f"今日交易次数已达上限{RISK_CONFIG['max_daily_trades']}次"

    # 8. 冷却期检查
    if code in _cooldown_records:
        last_sell = _cooldown_records[code]
        cooldown_end = last_sell + timedelta(minutes=RISK_CONFIG["cooldown_after_sell_minutes"])
        if datetime.now() < cooldown_end:
            remaining = (cooldown_end - datetime.now()).seconds // 60
            return False, f"该股票卖出后冷却中，还需等待{remaining}分钟"

    # 9. 单笔金额限制
    if trade_amount > RISK_CONFIG["max_single_trade_amount"]:
        return False, f"单笔金额超过{RISK_CONFIG['max_single_trade_amount']:.0f}元上限"
    if trade_amount < RISK_CONFIG["min_trade_amount"]:
        return False, f"单笔金额低于{RISK_CONFIG['min_trade_amount']:.0f}元下限"

    return True, "通过风控检查"


def validate_sell_order(code: str, quantity: int) -> Tuple[bool, str]:
    """验证卖出订单"""
    from app.execution.kill_switch import check_can_trade

    can_trade, kill_reason = check_can_trade()
    if not can_trade:
        return False, kill_reason

    _reset_daily_counter()
    positions = state_store.get_positions()

    # 1. 是否持有该股票
    if code not in positions:
        return False, "未持有该股票"

    pos = positions[code]

    # 2. 数量检查
    if quantity <= 0 or quantity % 100 != 0:
        return False, "卖出数量必须是100的整数倍"

    # 3. 可卖数量检查（T+1规则）
    available = pos.get("available_quantity", 0)
    if quantity > available:
        return False, f"可卖数量不足（可卖{available}，请求卖出{quantity}）"

    # 4. 每日交易次数限制
    if _today_trade_count >= RISK_CONFIG["max_daily_trades"]:
        return False, f"今日交易次数已达上限{RISK_CONFIG['max_daily_trades']}次"

    return True, "通过风控检查"


def calculate_position_size(price: float, signal_strength: str) -> int:
    """根据信号强度计算建议买入数量"""
    portfolio = state_store.get_portfolio()
    total_asset = portfolio["total_asset"]
    available = portfolio["available_cash"]

    max_amount = total_asset * RISK_CONFIG["max_single_position_pct"]
    strength_multiplier = {"strong": 0.8, "medium": 0.5, "weak": 0.3}
    target_amount = max_amount * strength_multiplier.get(signal_strength, 0.3)

    # 不超过可用资金的95%
    actual_amount = min(target_amount, available * 0.95)

    # 取整到100股
    shares = int(actual_amount / price / 100) * 100

    # 最小交易金额检查
    if shares * price < RISK_CONFIG["min_trade_amount"]:
        return 0

    return shares


def calculate_stop_loss(entry_price: float, support_level: float = 0) -> float:
    """计算止损价"""
    default_stop = entry_price * (1 - RISK_CONFIG["default_stop_loss_pct"])
    if support_level > 0:
        support_stop = support_level * 0.98
        return max(default_stop, support_stop)
    return default_stop


def calculate_take_profit(entry_price: float, resistance_level: float = 0) -> float:
    """计算止盈价"""
    default_tp = entry_price * (1 + RISK_CONFIG["default_take_profit_pct"])
    if resistance_level > 0:
        return min(default_tp, resistance_level)
    return default_tp


def calculate_fees(side: str, price: float, quantity: int) -> dict:
    """计算交易费用"""
    amount = price * quantity
    commission = max(amount * RISK_CONFIG["commission_rate"], RISK_CONFIG["min_commission"])
    stamp_tax = amount * RISK_CONFIG["stamp_tax_rate"] if side == "sell" else 0
    total_fee = commission + stamp_tax
    return {
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "total_fee": round(total_fee, 2),
    }


def check_daily_loss_limit() -> bool:
    """检查是否达到日亏损限制"""
    portfolio = state_store.get_portfolio()
    today_profit = portfolio.get("today_profit", 0)
    initial_cash = RISK_CONFIG["initial_cash"]
    max_loss = initial_cash * RISK_CONFIG["max_daily_loss_pct"]
    return today_profit < -max_loss


def record_trade():
    """记录交易次数"""
    global _today_trade_count
    _reset_daily_counter()
    _today_trade_count += 1


def record_cooldown(code: str):
    """记录卖出冷却"""
    _cooldown_records[code] = datetime.now()


def get_risk_status() -> dict:
    """获取当前风控状态"""
    _reset_daily_counter()
    portfolio = state_store.get_portfolio()
    positions = state_store.get_positions()

    total_asset = portfolio["total_asset"]
    market_value = portfolio["market_value"]
    exposure_pct = market_value / total_asset * 100 if total_asset > 0 else 0

    return {
        "initial_cash": RISK_CONFIG["initial_cash"],
        "total_asset": total_asset,
        "available_cash": portfolio["available_cash"],
        "market_value": market_value,
        "exposure_pct": round(exposure_pct, 1),
        "position_count": len(positions),
        "max_position_count": RISK_CONFIG["max_position_count"],
        "today_trade_count": _today_trade_count,
        "max_daily_trades": RISK_CONFIG["max_daily_trades"],
        "today_profit": portfolio.get("today_profit", 0),
        "daily_loss_limit": RISK_CONFIG["initial_cash"] * RISK_CONFIG["max_daily_loss_pct"],
        "daily_loss_halt": check_daily_loss_limit(),
        "active_cooldowns": len([c for c, t in _cooldown_records.items()
                                  if datetime.now() - t < timedelta(minutes=RISK_CONFIG["cooldown_after_sell_minutes"])]),
        "config": RISK_CONFIG,
    }


def get_risk_config() -> dict:
    """获取风控配置"""
    return RISK_CONFIG.copy()


def update_risk_config(updates: dict):
    """更新风控配置"""
    for key, value in updates.items():
        if key in RISK_CONFIG:
            RISK_CONFIG[key] = value
    logger.info(f"风控配置已更新: {updates}")
