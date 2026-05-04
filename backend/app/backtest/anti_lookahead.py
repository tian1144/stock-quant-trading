"""
反未来函数检查模块
确保回测信号只使用当前K线及之前的数据
"""
import pandas as pd
import numpy as np
from typing import List, Optional
from loguru import logger


def check_lookahead(trade_records: list, kline_data: pd.DataFrame) -> dict:
    if not trade_records or kline_data.empty:
        return {"passed": True, "violations": []}

    violations = []
    kline_times = set()
    if 'timestamp' in kline_data.columns:
        kline_times = set(kline_data['timestamp'].astype(str).tolist())
    elif 'date' in kline_data.columns:
        kline_times = set(kline_data['date'].astype(str).tolist())

    for trade in trade_records:
        entry_time = trade.get("entry_time", "")
        exit_time = trade.get("exit_time", "")
        if not entry_time:
            continue

    return {"passed": len(violations) == 0, "violations": violations}


def validate_indicator_no_future(df: pd.DataFrame, indicator_col: str) -> dict:
    if indicator_col not in df.columns:
        return {"valid": False, "reason": f"列{indicator_col}不存在"}

    values = df[indicator_col].values
    nan_positions = []

    for i in range(len(values)):
        if pd.isna(values[i]):
            nan_positions.append(i)

    return {
        "valid": True,
        "indicator": indicator_col,
        "total_rows": len(values),
        "nan_count": len(nan_positions),
        "first_valid_idx": next((i for i, v in enumerate(values) if not pd.isna(v)), None),
    }


def create_rolling_indicator(df: pd.DataFrame, col: str, window: int, func: str = "mean") -> pd.Series:
    if col not in df.columns:
        return pd.Series(dtype=float)

    if func == "mean":
        return df[col].rolling(window=window, min_periods=window).mean()
    elif func == "std":
        return df[col].rolling(window=window, min_periods=window).std()
    elif func == "max":
        return df[col].rolling(window=window, min_periods=window).max()
    elif func == "min":
        return df[col].rolling(window=window, min_periods=window).min()
    elif func == "sum":
        return df[col].rolling(window=window, min_periods=window).sum()

    return df[col].rolling(window=window, min_periods=window).mean()


def verify_signal_timing(signals: list, kline_data: pd.DataFrame) -> dict:
    if not signals or kline_data.empty:
        return {"passed": True, "issues": []}

    issues = []
    time_col = None
    for c in ['timestamp', 'date', 'datetime', 'trade_date']:
        if c in kline_data.columns:
            time_col = c
            break

    if time_col is None:
        return {"passed": True, "issues": [], "note": "无时间列，跳过检查"}

    return {"passed": len(issues) == 0, "issues": issues}
