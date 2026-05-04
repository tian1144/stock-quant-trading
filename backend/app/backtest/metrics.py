"""
回测指标计算模块
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime


def calc_total_return(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    return (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100


def calc_annualized_return(total_return: float, trading_days: int) -> float:
    if trading_days <= 0:
        return 0.0
    years = trading_days / 252
    if years <= 0:
        return 0.0
    return ((1 + total_return / 100) ** (1 / years) - 1) * 100


def calc_max_drawdown(equity_curve: pd.Series) -> float:
    if equity_curve.empty:
        return 0.0
    cummax = equity_curve.cummax()
    drawdown = (equity_curve - cummax) / cummax * 100
    return round(drawdown.min(), 2)


def calc_max_drawdown_duration(equity_curve: pd.Series) -> int:
    if equity_curve.empty:
        return 0
    cummax = equity_curve.cummax()
    in_drawdown = equity_curve < cummax
    max_duration = 0
    current_duration = 0
    for dd in in_drawdown:
        if dd:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0
    return max_duration


def calc_sharpe_ratio(daily_returns: pd.Series, risk_free_rate: float = 0.02) -> float:
    if daily_returns.empty or daily_returns.std() == 0:
        return 0.0
    excess_returns = daily_returns - risk_free_rate / 252
    return round(excess_returns.mean() / daily_returns.std() * np.sqrt(252), 2)


def calc_win_rate(trades: list) -> float:
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
    return round(wins / len(trades) * 100, 1)


def calc_profit_factor(trades: list) -> float:
    if not trades:
        return 0.0
    gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))
    if gross_loss == 0:
        return 999.99 if gross_profit > 0 else 0.0
    return round(gross_profit / gross_loss, 2)


def calc_avg_holding_period(trades: list) -> float:
    if not trades:
        return 0.0
    periods = []
    for t in trades:
        entry = t.get("entry_time", "")
        exit_ = t.get("exit_time", "")
        if entry and exit_:
            try:
                ed = pd.to_datetime(entry)
                xd = pd.to_datetime(exit_)
                periods.append((xd - ed).days)
            except Exception:
                pass
    return round(sum(periods) / len(periods), 1) if periods else 0.0


def calc_avg_trade_pnl(trades: list) -> float:
    if not trades:
        return 0.0
    return round(sum(t.get("pnl", 0) for t in trades) / len(trades), 2)


def calc_max_consecutive_wins(trades: list) -> int:
    max_streak = 0
    current = 0
    for t in trades:
        if t.get("pnl", 0) > 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def calc_max_consecutive_losses(trades: list) -> int:
    max_streak = 0
    current = 0
    for t in trades:
        if t.get("pnl", 0) <= 0:
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def generate_backtest_metrics(equity_curve: pd.Series, trades: list, benchmark_returns: pd.Series = None) -> dict:
    completed_trades = [
        t for t in trades
        if t.get("type") == "sell" or "pnl" in t
    ]

    total_return = calc_total_return(equity_curve)
    max_dd = calc_max_drawdown(equity_curve)
    max_dd_dur = calc_max_drawdown_duration(equity_curve)
    trading_days = len(equity_curve)
    annual_return = calc_annualized_return(total_return, trading_days)

    daily_returns = equity_curve.pct_change().dropna() if len(equity_curve) > 1 else pd.Series(dtype=float)
    sharpe = calc_sharpe_ratio(daily_returns)

    win_rate = calc_win_rate(completed_trades)
    profit_factor = calc_profit_factor(completed_trades)
    avg_pnl = calc_avg_trade_pnl(completed_trades)
    avg_hold = calc_avg_holding_period(completed_trades)
    max_consec_wins = calc_max_consecutive_wins(completed_trades)
    max_consec_losses = calc_max_consecutive_losses(completed_trades)

    sample_sufficient = len(completed_trades) >= 30

    metrics = {
        "total_return_pct": round(total_return, 2),
        "annualized_return_pct": round(annual_return, 2),
        "max_drawdown_pct": max_dd,
        "max_drawdown_duration_days": max_dd_dur,
        "sharpe_ratio": sharpe,
        "win_rate_pct": win_rate,
        "profit_factor": profit_factor,
        "trade_count": len(completed_trades),
        "order_count": len(trades),
        "avg_trade_pnl": avg_pnl,
        "avg_holding_days": avg_hold,
        "max_consecutive_wins": max_consec_wins,
        "max_consecutive_losses": max_consec_losses,
        "sample_sufficient": sample_sufficient,
        "sample_note": "" if sample_sufficient else "样本不足（<30笔），结论不可靠",
    }

    if benchmark_returns is not None and not benchmark_returns.empty:
        alpha = total_return - calc_total_return((1 + benchmark_returns).cumprod() * equity_curve.iloc[0])
        metrics["alpha_pct"] = round(alpha, 2)

    return metrics
