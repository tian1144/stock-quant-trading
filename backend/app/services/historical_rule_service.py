"""
Historical effectiveness for similar screening rules.

The goal is not a full portfolio backtest. For each candidate we look for past
days where the local rule state was similar enough, then measure the forward
5/10-day outcome. This gives the AI quality scorer a concrete historical prior
instead of a vague prompt.
"""
import math
import os
import re
import time
from datetime import datetime
from typing import Optional

import pandas as pd
from loguru import logger

from app.services import data_fetcher


CACHE_DIR = os.path.join(data_fetcher.DATA_DIR, "historical_rule")
_memory_cache: dict[str, dict] = {}


def _safe_code(code: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]", "", str(code or ""))


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-") or (isinstance(value, float) and math.isnan(value)):
            return default
        return float(value)
    except Exception:
        return default


def _cache_key(code: str, profile: dict, lookback_days: int, horizon_days: int) -> str:
    return "|".join([
        _safe_code(code),
        str(lookback_days),
        str(horizon_days),
        str(profile.get("strategy") or ""),
        str(profile.get("support_pool_status") or ""),
        str(round(_to_float(profile.get("near_support_pct"), 0), 1)),
        str(round(_to_float(profile.get("drawdown_from_high_pct"), 0), 1)),
        str(round(_to_float(profile.get("volume_ratio"), 0), 1)),
        str(round(_to_float(profile.get("turnover_rate"), 0), 1)),
    ])


def _normalize_daily_df(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    out = df.copy()
    for col in ("open", "close", "high", "low", "volume", "pct_change", "turnover_rate"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "date" in out.columns:
        out = out.sort_values("date")
    out = out.dropna(subset=["close", "high", "low"])
    return out.reset_index(drop=True)


def _build_profile(stock: dict, support_detail: dict, strategy: str) -> dict:
    return {
        "strategy": strategy,
        "support_pool_status": stock.get("support_pool_status"),
        "near_support_pct": support_detail.get("near_support_pct"),
        "drawdown_from_high_pct": support_detail.get("drawdown_from_high_pct"),
        "box_width_pct": support_detail.get("box_width_pct"),
        "ma20_slope_pct": support_detail.get("ma20_slope_pct"),
        "pct_5": support_detail.get("pct_5"),
        "latest_pct": support_detail.get("latest_pct"),
        "turnover_rate": stock.get("turnover_rate"),
        "volume_ratio": stock.get("volume_ratio"),
    }


def _similar_to_profile(row: pd.Series, profile: dict, strategy: str) -> bool:
    close = _to_float(row.get("close"))
    ma20 = _to_float(row.get("ma20"))
    high20 = _to_float(row.get("high20"))
    low20 = _to_float(row.get("low20"))
    pct_5 = _to_float(row.get("pct_5"))
    turnover = _to_float(row.get("turnover_rate"))
    latest_pct = _to_float(row.get("pct_change"))
    if close <= 0 or ma20 <= 0 or high20 <= low20:
        return False
    near_support = (close - low20) / close * 100
    drawdown = (high20 - close) / high20 * 100
    box_width = (high20 - low20) / max(low20, 1e-9) * 100
    ma20_slope = _to_float(row.get("ma20_slope_pct"))
    if strategy == "short":
        return (
            -1 <= near_support <= 7
            and 2 <= drawdown <= 24
            and 4 <= box_width <= 30
            and abs(ma20_slope) <= 6
            and -16 <= pct_5 <= 5
            and -7 <= latest_pct <= 4
            and (turnover <= 12 or turnover == 0)
        )
    target_near = _to_float(profile.get("near_support_pct"), 5)
    target_drawdown = _to_float(profile.get("drawdown_from_high_pct"), 8)
    return (
        abs(near_support - target_near) <= 4
        and abs(drawdown - target_drawdown) <= 8
        and -18 <= pct_5 <= 10
        and -8 <= latest_pct <= 6
    )


def evaluate_similar_rule_effectiveness(
    stock: dict,
    daily_df: Optional[pd.DataFrame],
    support_detail: Optional[dict] = None,
    strategy: str = "short",
    lookback_days: int = 260,
    horizon_days: int = 5,
) -> dict:
    code = _safe_code(stock.get("code", ""))
    support_detail = support_detail or {}
    profile = _build_profile(stock, support_detail, strategy)
    key = _cache_key(code, profile, lookback_days, horizon_days)
    cached = _memory_cache.get(key)
    if cached and time.time() - cached.get("_ts", 0) < 6 * 3600:
        return cached["payload"]

    df = _normalize_daily_df(daily_df)
    if df is None or len(df) < 80:
        payload = {
            "data_status": "insufficient_kline",
            "score": 50,
            "sample_count": 0,
            "sample_sufficient": False,
            "note": "历史K线不足，无法评估相似规则有效性",
        }
        _memory_cache[key] = {"_ts": time.time(), "payload": payload}
        return payload

    df = df.tail(max(lookback_days + horizon_days + 30, 120)).copy()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma20_slope_pct"] = df["ma20"].pct_change(5) * 100
    df["high20"] = df["high"].rolling(20).max()
    df["low20"] = df["low"].rolling(20).min()
    df["pct_5"] = df["close"].pct_change(5) * 100

    rows = []
    max_idx = len(df) - horizon_days - 1
    for idx in range(25, max_idx):
        row = df.iloc[idx]
        if not _similar_to_profile(row, profile, strategy):
            continue
        entry = _to_float(row.get("close"))
        future = df.iloc[idx + 1: idx + horizon_days + 1]
        if entry <= 0 or future.empty:
            continue
        max_ret = (future["high"].max() - entry) / entry * 100
        min_ret = (future["low"].min() - entry) / entry * 100
        close_ret = (_to_float(future.iloc[-1].get("close")) - entry) / entry * 100
        rows.append({"max_ret": max_ret, "min_ret": min_ret, "close_ret": close_ret})

    sample_count = len(rows)
    if not rows:
        payload = {
            "data_status": "no_similar_samples",
            "score": 48,
            "sample_count": 0,
            "sample_sufficient": False,
            "horizon_days": horizon_days,
            "note": "近似规则历史样本不足",
        }
    else:
        close_rets = [r["close_ret"] for r in rows]
        max_rets = [r["max_ret"] for r in rows]
        min_rets = [r["min_ret"] for r in rows]
        win_rate = sum(1 for r in close_rets if r > 0) / sample_count * 100
        target_hit_rate = sum(1 for r in max_rets if r >= 3) / sample_count * 100
        stop_hit_rate = sum(1 for r in min_rets if r <= -3) / sample_count * 100
        avg_return = sum(close_rets) / sample_count
        avg_max_gain = sum(max_rets) / sample_count
        avg_max_drawdown = sum(min_rets) / sample_count
        score = (
            42
            + (win_rate - 50) * 0.35
            + avg_return * 4
            + target_hit_rate * 0.12
            - stop_hit_rate * 0.10
            + min(sample_count, 30) * 0.25
        )
        payload = {
            "data_status": "ready",
            "score": round(max(0, min(100, score)), 1),
            "sample_count": sample_count,
            "sample_sufficient": sample_count >= 8,
            "horizon_days": horizon_days,
            "win_rate_pct": round(win_rate, 1),
            "target_hit_rate_pct": round(target_hit_rate, 1),
            "stop_hit_rate_pct": round(stop_hit_rate, 1),
            "avg_return_pct": round(avg_return, 2),
            "avg_max_gain_pct": round(avg_max_gain, 2),
            "avg_max_drawdown_pct": round(avg_max_drawdown, 2),
            "note": "基于本股历史相似形态的前视收益统计，不使用未来数据参与当前信号生成",
        }

    payload.update({
        "code": code,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": lookback_days,
        "rule_profile": profile,
    })
    _memory_cache[key] = {"_ts": time.time(), "payload": payload}
    return payload


def neutral_effectiveness(code: str = "", reason: str = "未进入历史相似规则评估触发条件") -> dict:
    return {
        "code": _safe_code(code),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_status": "not_triggered",
        "score": 50,
        "sample_count": 0,
        "sample_sufficient": False,
        "note": reason,
    }
