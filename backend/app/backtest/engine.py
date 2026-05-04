"""
回测引擎核心 - 事件驱动回测框架
支持A股规则（T+1/涨跌停/停牌/ST）、反未来函数、手续费/滑点
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Callable
from loguru import logger

from app.backtest.a_share_rules import (
    A_SHARE_CONFIG, check_can_buy, check_can_sell, check_t_plus_1,
    calculate_a_share_fees, apply_slippage, simulate_fill, get_limit_pct
)
from app.backtest.metrics import generate_backtest_metrics
from app.backtest.anti_lookahead import check_lookahead
from app.backtest.context import summarize_backtest_context


class BacktestEngine:
    def __init__(self, initial_cash: float = 200000.0, config: dict = None):
        self.initial_cash = initial_cash
        self.config = config or A_SHARE_CONFIG.copy()
        self.reset()

    def reset(self):
        self.cash = self.initial_cash
        self.positions: Dict[str, dict] = {}
        self.trades: List[dict] = []
        self.equity_curve: List[float] = []
        self.equity_dates: List[str] = []
        self.daily_pnl: List[float] = []
        self.context_history: List[dict] = []
        self._current_context: dict = {}
        self.current_date: str = ""
        self._prev_close: Dict[str, float] = {}

    def run(
        self,
        kline_data: pd.DataFrame,
        strategy_func: Callable,
        symbol: str = "",
        name: str = "",
        context_provider: Optional[Callable] = None,
    ) -> dict:
        self.reset()

        if kline_data.empty:
            return self._empty_result(symbol, "K线数据为空")

        required_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in kline_data.columns:
                return self._empty_result(symbol, f"缺少必要列: {col}")

        df = kline_data.copy().sort_values(by=['timestamp'] if 'timestamp' in kline_data.columns else [kline_data.columns[0]])
        df = df.reset_index(drop=True)

        for i in range(len(df)):
            row = df.iloc[i]
            date_str = str(row.get('timestamp', row.get('date', f"day_{i}")))[:10]
            self.current_date = date_str

            current_price = float(row['close'])
            prev_close = float(df.iloc[i - 1]['close']) if i > 0 else current_price
            self._prev_close[symbol] = prev_close

            context = context_provider(df, i, symbol) if context_provider else {}
            if context:
                self.context_history.append(context)
            self._current_context = context

            try:
                signals = strategy_func(df, i, self.positions, self.cash, self.initial_cash, context)
            except TypeError:
                signals = strategy_func(df, i, self.positions, self.cash, self.initial_cash)

            if signals.get("buy") and symbol not in self.positions:
                self._execute_backtest_buy(
                    symbol, name, current_price, prev_close,
                    signals.get("quantity", 0), signals.get("reason", "策略买入"), date_str
                )

            if signals.get("sell") and symbol in self.positions:
                self._execute_backtest_sell(
                    symbol, current_price, prev_close,
                    signals.get("quantity", 0), signals.get("reason", "策略卖出"), date_str
                )

            self._update_position_prices(current_price, date_str)
            total_equity = self._calc_total_equity(current_price)
            self.equity_curve.append(total_equity)
            self.equity_dates.append(date_str)

        lookahead_result = check_lookahead(self.trades, kline_data)
        equity_series = pd.Series(self.equity_curve)
        metrics = generate_backtest_metrics(equity_series, self.trades)
        metrics["lookahead_check"] = lookahead_result
        context_summary = summarize_backtest_context(self.context_history)
        metrics["context_summary"] = context_summary

        return {
            "symbol": symbol,
            "name": name,
            "strategy": strategy_func.__name__ if hasattr(strategy_func, '__name__') else "custom",
            "initial_cash": self.initial_cash,
            "final_equity": round(self.equity_curve[-1], 2) if self.equity_curve else self.initial_cash,
            "metrics": metrics,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "equity_dates": self.equity_dates,
            "trade_count": len(self.trades),
            "context_summary": context_summary,
            "context_samples": self._build_context_samples(),
        }

    def _execute_backtest_buy(self, symbol: str, name: str, price: float,
                               prev_close: float, quantity: int, reason: str, date_str: str):
        can_buy, buy_reason = check_can_buy(symbol, price, prev_close, name)
        if not can_buy:
            return

        context = getattr(self, "_current_context", {}) or {}
        if context and not context.get("allow_buy", True):
            return

        if quantity <= 0:
            exposure_multiplier = float(context.get("exposure_multiplier", 1.0)) if context else 1.0
            max_amount = self.cash * 0.95 * max(0.0, min(1.2, exposure_multiplier))
            quantity = int(max_amount / price / 100) * 100
            if quantity <= 0:
                return

        fill_result = simulate_fill(symbol, "buy", price, prev_close, name)
        if not fill_result["filled"]:
            return

        fill_price = fill_result["fill_price"]
        fees = calculate_a_share_fees("buy", fill_price, quantity)
        total_cost = fill_price * quantity + fees["total_fee"]

        if total_cost > self.cash:
            quantity = int((self.cash * 0.95) / fill_price / 100) * 100
            if quantity <= 0:
                return
            fees = calculate_a_share_fees("buy", fill_price, quantity)
            total_cost = fill_price * quantity + fees["total_fee"]

        self.cash -= total_cost
        self.positions[symbol] = {
            "code": symbol,
            "name": name,
            "quantity": quantity,
            "available_quantity": 0,
            "avg_cost": fill_price,
            "entry_price": fill_price,
            "entry_time": date_str,
            "current_price": fill_price,
            "market_value": fill_price * quantity,
            "stop_loss": fill_price * (1 - 0.05),
            "take_profit": fill_price * (1 + 0.10),
            "peak_price": fill_price,
            "buy_date": date_str,
            "entry_context": self._compact_context(context),
        }

        self.trades.append({
            "type": "buy",
            "symbol": symbol,
            "name": name,
            "entry_time": date_str,
            "entry_price": round(fill_price, 3),
            "quantity": quantity,
            "amount": round(fill_price * quantity, 2),
            "commission": fees["commission"],
            "stamp_tax": fees["stamp_tax"],
            "total_fee": fees["total_fee"],
            "reason": reason,
            "context": self._compact_context(context),
        })

    def _execute_backtest_sell(self, symbol: str, price: float, prev_close: float,
                                quantity: int, reason: str, date_str: str):
        if symbol not in self.positions:
            return

        pos = self.positions[symbol]

        can_sell, sell_reason = check_can_sell(symbol, price, prev_close)
        if not can_sell:
            return

        t1_ok, t1_reason = check_t_plus_1(pos.get("buy_date", ""), date_str)
        if not t1_ok:
            return

        if quantity <= 0:
            quantity = pos["quantity"]

        quantity = min(quantity, pos["quantity"])

        fill_result = simulate_fill(symbol, "sell", price, prev_close)
        if not fill_result["filled"]:
            return

        fill_price = fill_result["fill_price"]
        fees = calculate_a_share_fees("sell", fill_price, quantity)
        net_amount = fill_price * quantity - fees["total_fee"]
        pnl = (fill_price - pos["avg_cost"]) * quantity - fees["total_fee"]

        self.cash += net_amount

        remaining = pos["quantity"] - quantity
        if remaining <= 0:
            del self.positions[symbol]
        else:
            pos["quantity"] = remaining
            pos["market_value"] = fill_price * remaining

        self.trades.append({
            "type": "sell",
            "symbol": symbol,
            "name": pos.get("name", ""),
            "exit_time": date_str,
            "exit_price": round(fill_price, 3),
            "quantity": quantity,
            "amount": round(fill_price * quantity, 2),
            "commission": fees["commission"],
            "stamp_tax": fees["stamp_tax"],
            "total_fee": fees["total_fee"],
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / (pos["avg_cost"] * quantity) * 100, 2) if pos["avg_cost"] * quantity > 0 else 0,
            "entry_time": pos.get("entry_time", ""),
            "entry_price": pos.get("entry_price", 0),
            "reason": reason,
            "entry_context": pos.get("entry_context", {}),
            "exit_context": self._compact_context(getattr(self, "_current_context", {}) or {}),
        })

    def _update_position_prices(self, current_price: float, date_str: str):
        for symbol, pos in self.positions.items():
            pos["current_price"] = current_price
            pos["market_value"] = current_price * pos["quantity"]
            if current_price > pos.get("peak_price", 0):
                pos["peak_price"] = current_price
            if date_str[:10] != pos.get("buy_date", "")[:10]:
                pos["available_quantity"] = pos["quantity"]

    def _calc_total_equity(self, current_price: float) -> float:
        market_value = sum(pos["quantity"] * current_price for pos in self.positions.values())
        return self.cash + market_value

    def _compact_context(self, context: dict) -> dict:
        if not context:
            return {}
        return {
            "date": context.get("date"),
            "combined_score": context.get("combined_score"),
            "risk_pause": context.get("risk_pause", False),
            "allow_buy": context.get("allow_buy", True),
            "exposure_multiplier": context.get("exposure_multiplier", 1.0),
            "reason": context.get("reason", ""),
            "news": {
                "score": context.get("news", {}).get("score"),
                "level": context.get("news", {}).get("level"),
                "matched_count": context.get("news", {}).get("matched_count", 0),
                "positive_count": context.get("news", {}).get("positive_count", 0),
                "negative_count": context.get("news", {}).get("negative_count", 0),
                "s_level_count": context.get("news", {}).get("s_level_count", 0),
                "a_level_count": context.get("news", {}).get("a_level_count", 0),
                "event_samples": context.get("news", {}).get("event_samples", []),
            },
            "announcement": {
                "score": context.get("announcement", {}).get("score"),
                "level": context.get("announcement", {}).get("level"),
                "matched_count": context.get("announcement", {}).get("matched_count", 0),
                "positive_count": context.get("announcement", {}).get("positive_count", 0),
                "negative_count": context.get("announcement", {}).get("negative_count", 0),
                "s_level_count": context.get("announcement", {}).get("s_level_count", 0),
                "a_level_count": context.get("announcement", {}).get("a_level_count", 0),
                "event_samples": context.get("announcement", {}).get("event_samples", []),
            },
            "sentiment_env": {
                "score": context.get("sentiment_env", {}).get("score"),
                "level": context.get("sentiment_env", {}).get("level"),
                "is_extreme": context.get("sentiment_env", {}).get("is_extreme", False),
                "contrarian_signal": context.get("sentiment_env", {}).get("contrarian_signal"),
            },
            "market": {
                "market_score": context.get("market", {}).get("market_score"),
                "regime": context.get("market", {}).get("regime"),
                "pct_change": context.get("market", {}).get("pct_change"),
                "ma20_gap_pct": context.get("market", {}).get("ma20_gap_pct"),
            },
        }

    def _build_context_samples(self) -> list:
        if not self.context_history:
            return []
        interesting = [
            item for item in self.context_history
            if item.get("risk_pause")
            or item.get("news", {}).get("matched_count", 0) > 0
            or item.get("announcement", {}).get("matched_count", 0) > 0
            or item.get("sentiment_env", {}).get("is_extreme")
        ]
        if not interesting:
            interesting = self.context_history[-5:]
        return [self._compact_context(item) for item in interesting[-10:]]

    def _empty_result(self, symbol: str, reason: str) -> dict:
        return {
            "symbol": symbol,
            "metrics": {"total_return_pct": 0, "max_drawdown_pct": 0, "win_rate_pct": 0,
                        "trade_count": 0, "sample_sufficient": False, "sample_note": reason},
            "trades": [],
            "equity_curve": [],
            "trade_count": 0,
        }


def ma_crossover_strategy(df: pd.DataFrame, idx: int, positions: dict,
                           cash: float, initial_cash: float) -> dict:
    if idx < 20:
        return {}

    ma5 = df['close'].iloc[max(0, idx - 5):idx + 1].mean()
    ma20 = df['close'].iloc[max(0, idx - 20):idx + 1].mean()
    prev_ma5 = df['close'].iloc[max(0, idx - 6):idx].mean()
    prev_ma20 = df['close'].iloc[max(0, idx - 21):idx - 1].mean() if idx >= 21 else ma20

    has_position = bool(positions)
    if not has_position and prev_ma5 <= prev_ma20 and ma5 > ma20:
        return {"buy": True, "reason": "MA5上穿MA20"}

    if has_position and prev_ma5 >= prev_ma20 and ma5 < ma20:
        return {"sell": True, "reason": "MA5下穿MA20"}

    return {}


def create_ma_crossover_strategy(short_window: int = 5, long_window: int = 20):
    def strategy(df: pd.DataFrame, idx: int, positions: dict,
                  cash: float, initial_cash: float, context: dict = None) -> dict:
        if idx < long_window:
            return {}
        context = context or {}

        ma_short = df['close'].iloc[max(0, idx - short_window):idx + 1].mean()
        ma_long = df['close'].iloc[max(0, idx - long_window):idx + 1].mean()
        prev_ma_short = df['close'].iloc[max(0, idx - short_window - 1):idx].mean()
        prev_ma_long = df['close'].iloc[max(0, idx - long_window - 1):idx].mean() if idx >= long_window + 1 else ma_long

        has_position = bool(positions)
        if has_position and context.get("risk_exit"):
            return {"sell": True, "reason": f"Context risk exit: {context.get('reason', '')}"}
        if not has_position and prev_ma_short <= prev_ma_long and ma_short > ma_long:
            return {"buy": True, "reason": f"MA{short_window}上穿MA{long_window}"}

        if has_position and prev_ma_short >= prev_ma_long and ma_short < ma_long:
            return {"sell": True, "reason": f"MA{short_window}下穿MA{long_window}"}

        return {}

    strategy.__name__ = f"ma_{short_window}_{long_window}_crossover"
    return strategy


def create_context_ma_crossover_strategy(short_window: int = 5, long_window: int = 20):
    def strategy(df: pd.DataFrame, idx: int, positions: dict,
                  cash: float, initial_cash: float, context: dict = None) -> dict:
        if idx < long_window:
            return {}
        context = context or {}

        ma_short = df['close'].iloc[max(0, idx - short_window):idx + 1].mean()
        ma_long = df['close'].iloc[max(0, idx - long_window):idx + 1].mean()
        prev_ma_short = df['close'].iloc[max(0, idx - short_window - 1):idx].mean()
        prev_ma_long = df['close'].iloc[max(0, idx - long_window - 1):idx].mean() if idx >= long_window + 1 else ma_long

        has_position = bool(positions)
        if has_position and context.get("risk_exit"):
            return {"sell": True, "reason": f"Context risk exit: {context.get('reason', '')}"}

        if not has_position and prev_ma_short <= prev_ma_long and ma_short > ma_long:
            if context and not context.get("allow_buy", True):
                return {}
            reason = f"MA{short_window} cross MA{long_window}"
            if context.get("reason"):
                reason = f"{reason}; {context['reason']}"
            return {"buy": True, "reason": reason}

        if has_position and prev_ma_short >= prev_ma_long and ma_short < ma_long:
            reason = f"MA{short_window} cross down MA{long_window}"
            if context.get("reason"):
                reason = f"{reason}; {context['reason']}"
            return {"sell": True, "reason": reason}

        return {}

    strategy.__name__ = f"context_ma_{short_window}_{long_window}_crossover"
    return strategy
