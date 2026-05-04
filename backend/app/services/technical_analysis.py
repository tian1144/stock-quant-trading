"""
技术指标计算模块 - 纯计算，无外部依赖
输入pandas DataFrame（含OHLCV），输出添加指标列后的DataFrame
"""
import pandas as pd
import numpy as np
from typing import Dict, Optional


def calc_ma(df: pd.DataFrame, periods: list = None) -> pd.DataFrame:
    """计算移动平均线 MA5/MA10/MA20/MA60 + EMA12/EMA26"""
    if periods is None:
        periods = [5, 10, 20, 60]
    for p in periods:
        if len(df) >= p:
            df[f"ma{p}"] = df["close"].rolling(window=p).mean()
        else:
            df[f"ma{p}"] = np.nan
    df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
    df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
    return df


def calc_macd(df: pd.DataFrame) -> pd.DataFrame:
    """计算MACD指标: DIF, DEA, MACD柱"""
    if "ema12" not in df.columns:
        df["ema12"] = df["close"].ewm(span=12, adjust=False).mean()
    if "ema26" not in df.columns:
        df["ema26"] = df["close"].ewm(span=26, adjust=False).mean()
    df["dif"] = df["ema12"] - df["ema26"]
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = 2 * (df["dif"] - df["dea"])
    return df


def calc_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    """计算KDJ指标"""
    low_n = df["low"].rolling(window=n, min_periods=1).min()
    high_n = df["high"].rolling(window=n, min_periods=1).max()
    rsv = (df["close"] - low_n) / (high_n - low_n + 1e-10) * 100
    df["kdj_k"] = rsv.ewm(com=2, adjust=False).mean()
    df["kdj_d"] = df["kdj_k"].ewm(com=2, adjust=False).mean()
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]
    return df


def calc_rsi(df: pd.DataFrame, periods: list = None) -> pd.DataFrame:
    """计算RSI指标"""
    if periods is None:
        periods = [6, 12, 24]
    delta = df["close"].diff()
    for p in periods:
        gain = delta.where(delta > 0, 0).rolling(window=p).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=p).mean()
        rs = gain / (loss + 1e-10)
        df[f"rsi_{p}"] = 100 - (100 / (1 + rs))
    return df


def calc_bollinger(df: pd.DataFrame, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    """计算布林带"""
    df["boll_mid"] = df["close"].rolling(window=n).mean()
    std = df["close"].rolling(window=n).std()
    df["boll_upper"] = df["boll_mid"] + k * std
    df["boll_lower"] = df["boll_mid"] - k * std
    df["boll_width"] = (df["boll_upper"] - df["boll_lower"]) / (df["boll_mid"] + 1e-10)
    df["boll_pctb"] = (df["close"] - df["boll_lower"]) / (df["boll_upper"] - df["boll_lower"] + 1e-10)
    return df


def calc_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """计算成交量指标: 量均线、OBV"""
    df["vol_ma5"] = df["volume"].rolling(window=5).mean()
    df["vol_ma10"] = df["volume"].rolling(window=10).mean()
    # OBV
    obv = [0]
    for i in range(1, len(df)):
        if df["close"].iloc[i] > df["close"].iloc[i - 1]:
            obv.append(obv[-1] + df["volume"].iloc[i])
        elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
            obv.append(obv[-1] - df["volume"].iloc[i])
        else:
            obv.append(obv[-1])
    df["obv"] = obv
    # 量比（当日成交量 / 5日平均成交量）
    df["volume_ratio_hist"] = df["volume"] / (df["vol_ma5"] + 1e-10)
    return df


def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """计算ATR（平均真实波幅）"""
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - close_prev).abs(),
        (low - close_prev).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=period).mean()
    return df


def calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """计算VWAP（成交量加权平均价）- 日内近似"""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    df["vwap"] = cum_tp_vol / (cum_vol + 1e-10)
    return df


def calc_support_resistance(df: pd.DataFrame, lookback: int = 60) -> dict:
    """计算支撑位和阻力位"""
    if len(df) < 5:
        return {"support_levels": [], "resistance_levels": []}

    recent = df.tail(lookback)
    supports = []
    resistances = []

    # 方法1: 近期低点/高点
    if len(recent) >= 5:
        low_min = recent["low"].min()
        high_max = recent["high"].max()
        supports.append(round(low_min, 2))
        resistances.append(round(high_max, 2))

    # 方法2: 近20日低点/高点
    if len(recent) >= 20:
        low_20 = recent["low"].tail(20).min()
        high_20 = recent["high"].tail(20).max()
        if low_20 != supports[-1]:
            supports.append(round(low_20, 2))
        if high_20 != resistances[-1]:
            resistances.append(round(high_20, 2))

    # 方法3: 收盘价聚类（简化版：取分位数）
    closes = recent["close"]
    if len(closes) >= 10:
        q25 = closes.quantile(0.25)
        q75 = closes.quantile(0.75)
        supports.append(round(q25, 2))
        resistances.append(round(q75, 2))

    # 方法4: MA支撑
    if "ma20" in df.columns and pd.notna(df["ma20"].iloc[-1]):
        ma20 = df["ma20"].iloc[-1]
        current_price = df["close"].iloc[-1]
        if ma20 < current_price:
            supports.append(round(ma20, 2))
        else:
            resistances.append(round(ma20, 2))

    # 去重排序
    supports = sorted(list(set(supports)))
    resistances = sorted(list(set(resistances)))

    return {
        "support_levels": supports,
        "resistance_levels": resistances,
    }


def calc_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """一次性计算所有技术指标"""
    if df is None or len(df) < 5:
        return df
    df = calc_ma(df)
    df = calc_macd(df)
    df = calc_kdj(df)
    df = calc_rsi(df)
    df = calc_bollinger(df)
    df = calc_volume_indicators(df)
    df = calc_atr(df)
    df = calc_vwap(df)
    return df


# ==================== 信号辅助判断 ====================

def is_ma_bullish_aligned(df: pd.DataFrame) -> bool:
    """判断均线是否多头排列 MA5 > MA10 > MA20"""
    if len(df) < 20:
        return False
    last = df.iloc[-1]
    cols = ["ma5", "ma10", "ma20"]
    if not all(c in df.columns for c in cols):
        return False
    vals = [last.get(c, np.nan) for c in cols]
    if any(pd.isna(v) for v in vals):
        return False
    return vals[0] > vals[1] > vals[2]


def is_macd_golden_cross(df: pd.DataFrame, lookback: int = 5) -> bool:
    """判断MACD是否近期金叉"""
    if len(df) < lookback + 1 or "dif" not in df.columns:
        return False
    recent = df.tail(lookback + 1)
    for i in range(1, len(recent)):
        if recent["dif"].iloc[i] > recent["dea"].iloc[i] and recent["dif"].iloc[i - 1] <= recent["dea"].iloc[i - 1]:
            return True
    return False


def is_macd_death_cross(df: pd.DataFrame, lookback: int = 5) -> bool:
    """判断MACD是否近期死叉"""
    if len(df) < lookback + 1 or "dif" not in df.columns:
        return False
    recent = df.tail(lookback + 1)
    for i in range(1, len(recent)):
        if recent["dif"].iloc[i] < recent["dea"].iloc[i] and recent["dif"].iloc[i - 1] >= recent["dea"].iloc[i - 1]:
            return True
    return False


def is_kdj_oversold_recovery(df: pd.DataFrame) -> bool:
    """判断KDJ是否超卖回升（J值从20以下上穿）"""
    if len(df) < 3 or "kdj_j" not in df.columns:
        return False
    recent = df.tail(3)
    return (recent["kdj_j"].iloc[-1] > 20 and recent["kdj_j"].iloc[-2] <= 20)


def is_rsi_healthy(df: pd.DataFrame) -> bool:
    """判断RSI是否在健康区间（30-70）"""
    if len(df) < 2 or "rsi_6" not in df.columns:
        return False
    rsi = df["rsi_6"].iloc[-1]
    return 30 < rsi < 70


def is_price_near_boll_lower(df: pd.DataFrame, threshold: float = 0.02) -> bool:
    """判断价格是否接近布林带下轨"""
    if len(df) < 2 or "boll_lower" not in df.columns:
        return False
    price = df["close"].iloc[-1]
    lower = df["boll_lower"].iloc[-1]
    if pd.isna(lower) or lower == 0:
        return False
    return (price - lower) / lower < threshold


def is_price_extended(current_price: float, vwap: float, threshold: float = 0.03) -> bool:
    """判断价格是否过度偏离VWAP（追高检测）"""
    if vwap <= 0:
        return False
    return (current_price - vwap) / vwap > threshold


def is_panic_sell(pct_change_today: float, threshold: float = -5.0) -> bool:
    """判断是否恐慌性下跌（杀跌检测）"""
    return pct_change_today < threshold


def get_signal_strength(df: pd.DataFrame) -> str:
    """根据技术指标判断信号强度"""
    if df is None or len(df) < 20:
        return "weak"
    score = 0
    if is_ma_bullish_aligned(df):
        score += 2
    if is_macd_golden_cross(df):
        score += 2
    if is_kdj_oversold_recovery(df):
        score += 1
    if is_rsi_healthy(df):
        score += 1
    if score >= 4:
        return "strong"
    elif score >= 2:
        return "medium"
    return "weak"
