"""
实时买卖信号检测模块
核心原则：禁止追涨杀跌
每5秒运行一次，检测候选池和持仓的买卖信号
"""
from datetime import datetime, timedelta
from typing import List, Tuple
from loguru import logger

from app.services import state_store, technical_analysis, portfolio_manager, risk_manager

# 反追高规则
ANTI_CHASE_RULES = {
    "max_intraday_gain_pct": 3.0,       # 日内涨>3%禁止买入
    "max_5min_surge_pct": 1.5,          # 5分钟急涨>1.5%禁止买入
    "min_pullback_from_high": 0.01,     # 涨>1%需从高点回落1%才可买
    "max_consecutive_up_days": 5,        # 连涨5日禁止买入
    "vwap_deviation_max": 0.03,         # 价格偏离VWAP>3%禁止买入
}


def check_anti_chase(code: str, realtime: dict, daily_df=None) -> Tuple[bool, str]:
    """反追高检查 - 返回(可买入, 原因)"""
    pct_change = realtime.get("pct_change", 0)
    price = realtime.get("price", 0)

    # Rule 1: 日内涨幅限制
    if pct_change > ANTI_CHASE_RULES["max_intraday_gain_pct"]:
        return False, f"今日涨幅{pct_change:.1f}%>{ANTI_CHASE_RULES['max_intraday_gain_pct']}%，禁止追高"

    # Rule 2: 5分钟急涨限制
    price_5min_ago = state_store.get_price_5min_ago(code)
    if price_5min_ago and price_5min_ago > 0:
        surge = (price - price_5min_ago) / price_5min_ago * 100
        if surge > ANTI_CHASE_RULES["max_5min_surge_pct"]:
            return False, f"5分钟急涨{surge:.1f}%，禁止追高"

    # Rule 3: 日内高点回落检查
    high = realtime.get("high", 0)
    if high > 0 and pct_change > 1.0:
        pullback = (high - price) / high
        if pullback < ANTI_CHASE_RULES["min_pullback_from_high"]:
            return False, f"涨{pct_change:.1f}%但未从高点回落，等待回调"

    # Rule 4: 连续上涨限制
    if daily_df is not None and len(daily_df) >= 5:
        last_5 = daily_df["pct_change"].tail(5).values
        if all(c > 0 for c in last_5):
            return False, "连续上涨5日，禁止追高"

    # Rule 5: VWAP偏离限制
    high_val = realtime.get("high", 0)
    low_val = realtime.get("low", 0)
    if high_val > 0 and low_val > 0:
        vwap = (high_val + low_val + price) / 3
        deviation = (price - vwap) / vwap
        if deviation > ANTI_CHASE_RULES["vwap_deviation_max"]:
            return False, f"价格偏离均价{deviation*100:.1f}%，禁止追高"

    return True, "通过反追高检查"


def detect_buy_signals() -> list:
    """检测买入信号"""
    screening = state_store.get_screening_results()
    if not screening:
        return []

    signals = []
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expire_str = (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    for candidate in screening:
        if candidate.get("signal_type") != "buy_candidate":
            continue

        code = candidate["code"]
        realtime = state_store.get_realtime(code)
        if not realtime or realtime.get("price", 0) <= 0:
            continue

        price = realtime["price"]
        daily_df = state_store.get_daily_bars(code)

        # 反追高检查
        can_buy, chase_reason = check_anti_chase(code, realtime, daily_df)
        if not can_buy:
            continue

        # 检测买入条件
        conditions_met = []
        strength_score = 0

        # 条件1: 量价突破 - 量比>1.5且价格上涨
        vr = realtime.get("volume_ratio", 0)
        pct = realtime.get("pct_change", 0)
        if vr > 1.5 and 0 < pct < 3:
            conditions_met.append("量比突破")
            strength_score += 1

        # 条件2: 技术面信号
        if daily_df is not None and len(daily_df) >= 20:
            df = technical_analysis.calc_all_indicators(daily_df.copy())
            if technical_analysis.is_macd_golden_cross(df):
                conditions_met.append("MACD金叉")
                strength_score += 2
            if technical_analysis.is_ma_bullish_aligned(df):
                conditions_met.append("均线多头")
                strength_score += 1
            if technical_analysis.is_kdj_oversold_recovery(df):
                conditions_met.append("KDJ超卖回升")
                strength_score += 1

        # 条件3: 资金流入
        flow = state_store.get_money_flow(code)
        if flow and flow.get("latest_main_net_inflow", 0) > 0:
            conditions_met.append("主力净流入")
            strength_score += 1
            if flow.get("consecutive_inflow_days", 0) >= 3:
                conditions_met.append("连续净流入")
                strength_score += 1

        # 至少满足2个条件才出信号
        if len(conditions_met) < 2:
            continue

        # 判断信号强度
        if strength_score >= 4:
            strength = "strong"
        elif strength_score >= 2:
            strength = "medium"
        else:
            strength = "weak"

        # 计算目标价和止损价
        sr = technical_analysis.calc_support_resistance(daily_df) if daily_df is not None else {}
        supports = sr.get("support_levels", [])
        resistances = sr.get("resistance_levels", [])

        target_price = price * 1.10  # 默认10%止盈
        stop_loss = price * 0.95     # 默认5%止损

        if resistances:
            target_price = min(target_price, max(r for r in resistances if r > price) if any(r > price for r in resistances) else target_price)
        if supports:
            stop_loss = max(stop_loss, max(s for s in supports if s < price) if any(s < price for s in supports) else stop_loss)

        signal = {
            "signal_id": f"BUY_{code}_{now.strftime('%Y%m%d_%H%M%S')}",
            "type": "buy",
            "code": code,
            "name": candidate.get("name", ""),
            "price": price,
            "entry_price": price,
            "target_price": round(target_price, 2),
            "stop_loss_price": round(stop_loss, 2),
            "strength": strength,
            "strength_score": strength_score,
            "conditions": conditions_met,
            "score": candidate.get("score", 0),
            "reason": " + ".join(conditions_met),
            "anti_chase_check": True,
            "anti_chase_reason": chase_reason,
            "generated_at": now_str,
            "expires_at": expire_str,
        }
        signals.append(signal)

    return signals


def detect_sell_signals() -> list:
    """检测卖出信号 - 持仓监控"""
    positions = state_store.get_positions()
    if not positions:
        return []

    signals = []
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    expire_str = (now + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    for code, pos in positions.items():
        realtime = state_store.get_realtime(code)
        if not realtime or realtime.get("price", 0) <= 0:
            continue

        price = realtime["price"]
        avg_cost = pos["avg_cost"]
        stop_loss = pos.get("stop_loss", 0)
        take_profit = pos.get("take_profit", 0)
        peak_price = pos.get("peak_price", avg_cost)
        daily_df = state_store.get_daily_bars(code)
        pct_change = realtime.get("pct_change", 0)

        sell_reasons = []
        strength = "medium"
        sell_quantity = pos["available_quantity"]

        if sell_quantity <= 0:
            continue

        # 条件1: 止损触发 - 必须卖出
        if stop_loss > 0 and price <= stop_loss:
            sell_reasons.append(f"触发止损({stop_loss:.2f})")
            strength = "strong"
            sell_quantity = pos["quantity"]  # 全部卖出

        # 条件2: 止盈触发 - 卖出50%
        if take_profit > 0 and price >= take_profit:
            sell_reasons.append(f"触发止盈({take_profit:.2f})")
            strength = "strong"
            sell_quantity = max(100, int(pos["available_quantity"] * 0.5 / 100) * 100)

        # 条件3: 移动止盈 - 盈利后从峰值回撤5%
        if price < peak_price * 0.95 and avg_cost < peak_price:
            sell_reasons.append(f"移动止盈(峰值{peak_price:.2f}回撤)")
            strength = "medium"
            sell_quantity = max(100, int(pos["available_quantity"] * 0.5 / 100) * 100)

        # 条件4: 技术卖出 - MACD死叉+量缩+破MA5
        if daily_df is not None and len(daily_df) >= 20:
            df = technical_analysis.calc_all_indicators(daily_df.copy())
            macd_death = technical_analysis.is_macd_death_cross(df)
            below_ma5 = len(df) >= 1 and df["close"].iloc[-1] < df["ma5"].iloc[-1] if "ma5" in df.columns else False
            vol_declining = len(df) >= 3 and df["volume"].iloc[-1] < df["volume"].iloc[-3] * 0.8

            if macd_death and below_ma5 and vol_declining:
                sell_reasons.append("技术卖出(MACD死叉+破MA5+量缩)")
                strength = "medium"

        # 反杀跌保护：单日跌>5%不恐慌卖出（除非止损触发）
        if pct_change < -5 and "止损" not in " ".join(sell_reasons):
            continue

        if not sell_reasons:
            continue

        signal = {
            "signal_id": f"SELL_{code}_{now.strftime('%Y%m%d_%H%M%S')}",
            "type": "sell",
            "code": code,
            "name": pos.get("name", ""),
            "price": price,
            "avg_cost": avg_cost,
            "quantity": sell_quantity,
            "available_quantity": pos["available_quantity"],
            "floating_profit_pct": round((price - avg_cost) / avg_cost * 100, 2),
            "strength": strength,
            "reasons": sell_reasons,
            "reason": " + ".join(sell_reasons),
            "anti_kill_low_check": True,
            "generated_at": now_str,
            "expires_at": expire_str,
        }
        signals.append(signal)

    return signals


def detect_all_signals() -> dict:
    """检测所有信号"""
    buy_signals = detect_buy_signals()
    sell_signals = detect_sell_signals()

    all_signals = buy_signals + sell_signals

    # 清理过期信号
    state_store.clear_expired_signals()

    # 更新信号
    state_store.set_signals(all_signals)
    state_store.update_system_state({
        "last_signal_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_signals_today": state_store.get_system_state().get("total_signals_today", 0) + len(all_signals),
    })

    if all_signals:
        logger.info(f"检测到信号: {len(buy_signals)}买入 + {len(sell_signals)}卖出")

    return {
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
        "total": len(all_signals),
    }
