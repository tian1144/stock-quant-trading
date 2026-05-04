"""
K线结构评分模块 - 趋势/突破/成交量/关键位
"""
from datetime import datetime
from typing import Dict, Optional
import pandas as pd
import numpy as np
from loguru import logger

from app.services import technical_analysis


def calc_trend_score(daily_df: pd.DataFrame) -> dict:
    if daily_df is None or len(daily_df) < 20:
        return {"score": 50, "trend": "unknown"}

    df = technical_analysis.calc_all_indicators(daily_df.copy())
    last = df.iloc[-1]
    score = 50

    if "ma5" in df.columns and "ma10" in df.columns and "ma20" in df.columns:
        if last["ma5"] > last["ma10"] > last["ma20"]:
            score += 25
            trend = "bullish_aligned"
        elif last["ma5"] > last["ma10"]:
            score += 15
            trend = "short_term_bullish"
        elif last["close"] < last["ma20"]:
            score -= 15
            trend = "bearish"
        else:
            trend = "neutral"
    else:
        trend = "unknown"

    if "ma60" in df.columns and not pd.isna(last.get("ma60")):
        if last["close"] > last["ma60"]:
            score += 10
        else:
            score -= 10

    return {"score": max(0, min(100, score)), "trend": trend}


def calc_breakout_score(daily_df: pd.DataFrame) -> dict:
    if daily_df is None or len(daily_df) < 20:
        return {"score": 50, "breakout": False}

    df = daily_df.copy()
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    n_high = df["high"].tail(20).max()
    breakout = last["close"] > n_high and last["close"] > prev["close"]
    volume_confirmed = last["volume"] > df["volume"].tail(20).mean() * 1.5 if breakout else False

    score = 50
    if breakout:
        score += 30
    if volume_confirmed:
        score += 20

    return {"score": max(0, min(100, score)), "breakout": breakout, "volume_confirmed": volume_confirmed}


def calc_volume_score(daily_df: pd.DataFrame) -> dict:
    if daily_df is None or len(daily_df) < 10:
        return {"score": 50, "volume_trend": "unknown"}

    df = daily_df.copy()
    last_vol = df["volume"].iloc[-1]
    avg_vol = df["volume"].tail(20).mean()
    vol_ratio = last_vol / avg_vol if avg_vol > 0 else 1

    score = 50
    if 1.5 <= vol_ratio <= 5:
        score += 25
    elif vol_ratio > 5:
        score -= 10
    elif vol_ratio < 0.5:
        score -= 15

    recent_3 = df["volume"].tail(3)
    if all(recent_3.iloc[i] > recent_3.iloc[i - 1] for i in range(1, len(recent_3))):
        volume_trend = "increasing"
        score += 10
    elif all(recent_3.iloc[i] < recent_3.iloc[i - 1] for i in range(1, len(recent_3))):
        volume_trend = "decreasing"
        score -= 5
    else:
        volume_trend = "mixed"

    return {"score": max(0, min(100, score)), "volume_trend": volume_trend, "vol_ratio": round(vol_ratio, 2)}


def calc_key_level_score(daily_df: pd.DataFrame) -> dict:
    if daily_df is None or len(daily_df) < 20:
        return {"score": 50, "near_support": False, "near_resistance": False}

    sr = technical_analysis.calc_support_resistance(daily_df)
    supports = sr.get("support_levels", [])
    resistances = sr.get("resistance_levels", [])

    current_price = daily_df["close"].iloc[-1]
    near_support = False
    near_resistance = False
    score = 50

    for s in supports:
        if s < current_price and (current_price - s) / current_price < 0.03:
            near_support = True
            score += 15
            break

    for r in resistances:
        if r > current_price and (r - current_price) / current_price < 0.03:
            near_resistance = True
            score -= 10
            break

    return {
        "score": max(0, min(100, score)),
        "near_support": near_support,
        "near_resistance": near_resistance,
        "support_levels": supports[:3],
        "resistance_levels": resistances[:3],
    }


def calc_kline_score(daily_df: pd.DataFrame) -> dict:
    trend = calc_trend_score(daily_df)
    breakout = calc_breakout_score(daily_df)
    volume = calc_volume_score(daily_df)
    key_level = calc_key_level_score(daily_df)

    weights = {"trend": 0.35, "breakout": 0.25, "volume": 0.25, "key_level": 0.15}
    final_score = (
        trend["score"] * weights["trend"] +
        breakout["score"] * weights["breakout"] +
        volume["score"] * weights["volume"] +
        key_level["score"] * weights["key_level"]
    )

    return {
        "kline_score": round(final_score, 1),
        "trend": trend,
        "breakout": breakout,
        "volume": volume,
        "key_level": key_level,
        "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
