"""
组合管理模块 - 订单执行、持仓管理、盈亏计算
模拟20万资金的托管交易系统
"""
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from loguru import logger

from app.services import state_store, risk_manager


def execute_buy(code: str, price: float, quantity: int, reason: str = "") -> dict:
    """执行买入"""
    # 风控验证
    approved, reject_reason = risk_manager.validate_buy_order(code, price, quantity)
    if not approved:
        return {"success": False, "error": reject_reason}

    # 计算费用
    fees = risk_manager.calculate_fees("buy", price, quantity)
    trade_amount = price * quantity
    total_cost = trade_amount + fees["total_fee"]

    # 更新组合
    portfolio = state_store.get_portfolio()
    portfolio["available_cash"] -= total_cost
    state_store.update_portfolio(portfolio)

    # 更新持仓
    positions = state_store.get_positions()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if code in positions:
        pos = positions[code]
        old_qty = pos["quantity"]
        old_cost = pos["avg_cost"] * old_qty
        new_qty = old_qty + quantity
        new_avg_cost = (old_cost + trade_amount) / new_qty
        pos["quantity"] = new_qty
        pos["avg_cost"] = round(new_avg_cost, 3)
        pos["current_price"] = price
        pos["market_value"] = round(price * new_qty, 2)
        pos["floating_profit"] = round((price - new_avg_cost) * new_qty, 2)
        pos["floating_profit_pct"] = round((price - new_avg_cost) / new_avg_cost * 100, 2)
        pos["updated_at"] = now
        # 注意：新买入的股份当日不可卖（T+1），不增加available_quantity
    else:
        stock_info = state_store.get_stock_info(code)
        name = stock_info.get("name", "") if stock_info else ""
        stop_loss = risk_manager.calculate_stop_loss(price)
        take_profit = risk_manager.calculate_take_profit(price)

        state_store.set_position(code, {
            "code": code,
            "name": name,
            "quantity": quantity,
            "available_quantity": 0,  # T+1: 当日买入不可卖
            "avg_cost": round(price, 3),
            "current_price": price,
            "market_value": round(trade_amount, 2),
            "floating_profit": 0.0,
            "floating_profit_pct": 0.0,
            "stop_loss": round(stop_loss, 2),
            "take_profit": round(take_profit, 2),
            "peak_price": price,
            "buy_date": now,
            "updated_at": now,
        })

    # 记录订单
    order = {
        "order_id": f"BUY_{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "type": "buy",
        "code": code,
        "name": state_store.get_stock_info(code).get("name", "") if state_store.get_stock_info(code) else "",
        "price": price,
        "quantity": quantity,
        "amount": round(trade_amount, 2),
        "commission": fees["commission"],
        "stamp_tax": fees["stamp_tax"],
        "total_fee": fees["total_fee"],
        "total_cost": round(total_cost, 2),
        "reason": reason,
        "created_at": now,
    }
    state_store.add_order(order)

    # 更新交易计数
    risk_manager.record_trade()

    # 更新总资产
    _recalculate_portfolio()

    logger.info(f"买入成功: {code} {quantity}股 @ {price} 金额{trade_amount:.2f} 费用{fees['total_fee']:.2f}")
    return {"success": True, "order": order}


def execute_sell(code: str, price: float, quantity: int, reason: str = "") -> dict:
    """执行卖出"""
    # 风控验证
    approved, reject_reason = risk_manager.validate_sell_order(code, quantity)
    if not approved:
        return {"success": False, "error": reject_reason}

    # 计算费用
    fees = risk_manager.calculate_fees("sell", price, quantity)
    trade_amount = price * quantity
    net_amount = trade_amount - fees["total_fee"]

    # 获取持仓信息
    positions = state_store.get_positions()
    pos = positions[code]
    avg_cost = pos["avg_cost"]
    realized_pnl = (price - avg_cost) * quantity - fees["total_fee"]

    # 更新组合
    portfolio = state_store.get_portfolio()
    portfolio["available_cash"] += net_amount
    portfolio["today_profit"] = portfolio.get("today_profit", 0) + realized_pnl
    state_store.update_portfolio(portfolio)

    # 更新持仓
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    remaining_qty = pos["quantity"] - quantity

    if remaining_qty <= 0:
        state_store.remove_position(code)
    else:
        pos["quantity"] = remaining_qty
        pos["available_quantity"] = min(pos["available_quantity"], remaining_qty)
        pos["current_price"] = price
        pos["market_value"] = round(price * remaining_qty, 2)
        pos["floating_profit"] = round((price - avg_cost) * remaining_qty, 2)
        pos["floating_profit_pct"] = round((price - avg_cost) / avg_cost * 100, 2)
        pos["updated_at"] = now

    # 记录订单
    order = {
        "order_id": f"SELL_{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "type": "sell",
        "code": code,
        "name": pos.get("name", ""),
        "price": price,
        "quantity": quantity,
        "amount": round(trade_amount, 2),
        "commission": fees["commission"],
        "stamp_tax": fees["stamp_tax"],
        "total_fee": fees["total_fee"],
        "net_amount": round(net_amount, 2),
        "avg_cost": avg_cost,
        "realized_pnl": round(realized_pnl, 2),
        "reason": reason,
        "created_at": now,
    }
    state_store.add_order(order)

    # 记录冷却
    risk_manager.record_cooldown(code)
    risk_manager.record_trade()

    # 更新总资产
    _recalculate_portfolio()

    pnl_str = f"盈利{realized_pnl:.2f}" if realized_pnl >= 0 else f"亏损{abs(realized_pnl):.2f}"
    logger.info(f"卖出成功: {code} {quantity}股 @ {price} {pnl_str}")
    return {"success": True, "order": order}


def update_positions_realtime():
    """更新所有持仓的实时数据"""
    positions = state_store.get_positions()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for code, pos in positions.items():
        realtime = state_store.get_realtime(code)
        if realtime and realtime.get("price", 0) > 0:
            price = realtime["price"]
            avg_cost = pos["avg_cost"]
            qty = pos["quantity"]

            pos["current_price"] = price
            pos["market_value"] = round(price * qty, 2)
            pos["floating_profit"] = round((price - avg_cost) * qty, 2)
            pos["floating_profit_pct"] = round((price - avg_cost) / avg_cost * 100, 2)
            pos["updated_at"] = now

            # 更新峰值价格（用于移动止盈）
            if price > pos.get("peak_price", 0):
                pos["peak_price"] = price

            # 更新移动止损
            new_stop = _update_trailing_stop(pos, price)
            if new_stop > pos.get("stop_loss", 0):
                pos["stop_loss"] = round(new_stop, 2)

    # 更新T+1可卖数量
    today = datetime.now().strftime("%Y-%m-%d")
    for code, pos in positions.items():
        buy_date = pos.get("buy_date", "")
        if buy_date and buy_date[:10] != today:
            pos["available_quantity"] = pos["quantity"]

    _recalculate_portfolio()


def _update_trailing_stop(position: dict, current_price: float) -> float:
    """更新移动止损"""
    avg_cost = position.get("avg_cost", 0)
    if current_price <= avg_cost:
        return position.get("stop_loss", 0)

    peak = max(position.get("peak_price", avg_cost), current_price)
    trailing_stop = peak * 0.95

    # 盈利后止损上移到成本线以上
    breakeven_stop = avg_cost * 1.005
    return max(trailing_stop, breakeven_stop, position.get("stop_loss", 0))


def _recalculate_portfolio():
    """重新计算组合总资产"""
    portfolio = state_store.get_portfolio()
    positions = state_store.get_positions()

    market_value = sum(pos.get("market_value", 0) for pos in positions.values())
    total_asset = portfolio["available_cash"] + market_value
    total_profit = total_asset - portfolio["initial_cash"]
    total_profit_pct = total_profit / portfolio["initial_cash"] * 100

    portfolio["market_value"] = round(market_value, 2)
    portfolio["total_asset"] = round(total_asset, 2)
    portfolio["total_profit"] = round(total_profit, 2)
    portfolio["total_profit_pct"] = round(total_profit_pct, 2)
    state_store.update_portfolio(portfolio)


def get_portfolio_summary() -> dict:
    """获取组合概览"""
    portfolio = state_store.get_portfolio()
    positions = state_store.get_positions()
    orders = state_store.get_orders()

    today = datetime.now().strftime("%Y-%m-%d")
    today_orders = [o for o in orders if o.get("created_at", "").startswith(today)]

    return {
        "initial_cash": portfolio["initial_cash"],
        "available_cash": round(portfolio["available_cash"], 2),
        "market_value": round(portfolio["market_value"], 2),
        "total_asset": round(portfolio["total_asset"], 2),
        "total_profit": round(portfolio["total_profit"], 2),
        "total_profit_pct": round(portfolio["total_profit_pct"], 2),
        "today_profit": round(portfolio.get("today_profit", 0), 2),
        "position_count": len(positions),
        "today_trade_count": len(today_orders),
    }


def get_position_list() -> list:
    """获取持仓列表"""
    positions = state_store.get_positions()
    result = []
    for code, pos in positions.items():
        result.append({
            "code": pos["code"],
            "name": pos.get("name", ""),
            "quantity": pos["quantity"],
            "available_quantity": pos.get("available_quantity", 0),
            "avg_cost": pos["avg_cost"],
            "current_price": pos["current_price"],
            "market_value": pos["market_value"],
            "floating_profit": pos["floating_profit"],
            "floating_profit_pct": pos["floating_profit_pct"],
            "stop_loss": pos.get("stop_loss", 0),
            "take_profit": pos.get("take_profit", 0),
            "peak_price": pos.get("peak_price", 0),
            "buy_date": pos.get("buy_date", ""),
            "updated_at": pos.get("updated_at", ""),
        })
    result.sort(key=lambda x: x["floating_profit_pct"], reverse=True)
    return result


def get_order_history(limit: int = 50) -> list:
    """获取订单历史"""
    orders = state_store.get_orders()
    return list(reversed(orders[-limit:]))


def get_trade_statistics() -> dict:
    """获取交易统计"""
    orders = state_store.get_orders()
    sell_orders = [o for o in orders if o["type"] == "sell"]

    if not sell_orders:
        return {
            "total_trades": len(orders),
            "sell_count": 0,
            "win_count": 0,
            "loss_count": 0,
            "win_rate": 0,
            "avg_profit": 0,
            "max_single_profit": 0,
            "max_single_loss": 0,
            "total_realized_pnl": 0,
            "total_commission": 0,
            "total_stamp_tax": 0,
        }

    profits = [o["realized_pnl"] for o in sell_orders]
    win_count = sum(1 for p in profits if p > 0)
    loss_count = sum(1 for p in profits if p <= 0)
    total_pnl = sum(profits)
    total_commission = sum(o.get("commission", 0) for o in orders)
    total_tax = sum(o.get("stamp_tax", 0) for o in orders)

    return {
        "total_trades": len(orders),
        "sell_count": len(sell_orders),
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_count / len(sell_orders) * 100, 1) if sell_orders else 0,
        "avg_profit": round(total_pnl / len(sell_orders), 2) if sell_orders else 0,
        "max_single_profit": round(max(profits), 2) if profits else 0,
        "max_single_loss": round(min(profits), 2) if profits else 0,
        "total_realized_pnl": round(total_pnl, 2),
        "total_commission": round(total_commission, 2),
        "total_stamp_tax": round(total_tax, 2),
    }


def reset_portfolio():
    """重置组合到初始状态"""
    state_store.update_portfolio({
        "initial_cash": 200000.0,
        "available_cash": 200000.0,
        "frozen_cash": 0.0,
        "market_value": 0.0,
        "total_asset": 200000.0,
        "total_profit": 0.0,
        "total_profit_pct": 0.0,
        "today_profit": 0.0,
        "today_trade_count": 0,
    })
    # 清空持仓和订单
    from app.services.state_store import _positions, _orders
    _positions.clear()
    _orders.clear()
    logger.info("组合已重置为初始状态（20万资金）")
