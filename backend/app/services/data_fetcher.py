"""
统一数据采集层 - 从免费API获取行情、日线、资金流、新闻等数据
数据源：新浪财经、东方财富、同花顺、财联社
"""
import time
import re
import json
import math
import random
import os
import html as html_lib
import xml.etree.ElementTree as ET
import uuid
import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

from app.services import state_store

# 请求限速：同一host最小间隔200ms
_last_request_time: Dict[str, float] = {}
RATE_LIMIT_MS = 200

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
}

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
DEFAULT_MARKET_CACHE_DIR = (
    r"E:\lianghua_market_cache"
    if os.name == "nt"
    else os.path.join(DATA_DIR, "market_cache")
)
MARKET_CACHE_DIR = os.environ.get("LIANGHUA_MARKET_CACHE_DIR") or DEFAULT_MARKET_CACHE_DIR
KLINE_CACHE_DIR = os.path.join(MARKET_CACHE_DIR, "kline")
INTRADAY_CACHE_DIR = os.path.join(MARKET_CACHE_DIR, "intraday")
REALTIME_CACHE_DIR = os.path.join(MARKET_CACHE_DIR, "realtime")
MONEY_FLOW_CACHE_DIR = os.path.join(MARKET_CACHE_DIR, "money_flow")
CHIP_CACHE_DIR = os.path.join(MARKET_CACHE_DIR, "chips")
UNIVERSE_CACHE_DIR = os.path.join(MARKET_CACHE_DIR, "universe")
VALIDATION_CACHE_DIR = os.path.join(MARKET_CACHE_DIR, "validation")
THS_LOCAL_ROOT = os.environ.get("LIANGHUA_THS_ROOT") or r"D:\同花顺\同花顺"


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _safe_code(code: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]", "", str(code))


def active_stock_universe_limit() -> int:
    try:
        return int(os.getenv("LIANGHUA_ACTIVE_STOCK_TOTAL", "5511") or 0)
    except Exception:
        return 5511


def apply_active_stock_scope(stocks: list) -> list:
    target = active_stock_universe_limit()
    if target and stocks and len(stocks) > target:
        return list(stocks[:target])
    return stocks or []


def _today_key() -> str:
    return datetime.now().strftime("%Y%m%d")


def _write_json_cache(path: str, data):
    try:
        _ensure_dir(os.path.dirname(path))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"写入缓存失败 {path}: {e}")


def _read_json_cache(path: str):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取缓存失败 {path}: {e}")
        return None


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except Exception:
        return default


def _to_int(value, default: int = 0) -> int:
    try:
        if value in (None, "", "-"):
            return default
        return int(float(value))
    except Exception:
        return default


def _relative_close(a, b, tolerance: float) -> bool:
    a = _to_float(a)
    b = _to_float(b)
    if a == 0 and b == 0:
        return True
    base = max(abs(a), abs(b), 1.0)
    return abs(a - b) / base <= tolerance


def _normalize_price_by_reference(value, reference_price: float = 0.0) -> float:
    price = _to_float(value)
    if price <= 0:
        return 0.0
    ref = _to_float(reference_price)
    if ref > 0:
        for divisor in (100, 1000, 10000):
            scaled = price / divisor
            if _relative_close(scaled, ref, 0.25):
                return round(scaled, 4)
        if price > ref * 20:
            return round(price / 100, 4)
    if price > 10000:
        return round(price / 100, 4)
    return price


def _write_validation_report(code: str, data_type: str, report: dict):
    payload = dict(report or {})
    payload["code"] = code
    payload["data_type"] = data_type
    payload["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json_cache(_validation_report_path(code, data_type), payload)


def _kline_cache_path(code: str, period: int = 101) -> str:
    safe_code = _safe_code(code)
    safe_period = int(period)
    return os.path.join(KLINE_CACHE_DIR, f"period_{safe_period}", f"{safe_code}.csv")


def _kline_candidate_cache_path(code: str, period: int = 101) -> str:
    safe_code = _safe_code(code)
    safe_period = int(period)
    return os.path.join(KLINE_CACHE_DIR, "candidates", f"period_{safe_period}", _today_key(), f"{safe_code}.csv")


def _date_csv_cache_path(root: str, code: str, date_key: Optional[str] = None) -> str:
    return os.path.join(root, date_key or _today_key(), f"{_safe_code(code)}.csv")


def _single_json_cache_path(root: str, code: str) -> str:
    return os.path.join(root, f"{_safe_code(code)}.json")


def _dated_json_cache_path(root: str, code: str, date_key: Optional[str] = None) -> str:
    return os.path.join(root, date_key or _today_key(), f"{_safe_code(code)}.json")


def _validation_report_path(code: str, data_type: str, date_key: Optional[str] = None) -> str:
    return os.path.join(VALIDATION_CACHE_DIR, data_type, date_key or _today_key(), f"{_safe_code(code)}.json")


def _latest_file_for_code(root: str, code: str, suffix: str) -> Optional[str]:
    safe_code = _safe_code(code)
    if not os.path.isdir(root):
        return None
    candidates = []
    try:
        for date_name in os.listdir(root):
            path = os.path.join(root, date_name, f"{safe_code}{suffix}")
            if os.path.exists(path):
                candidates.append(path)
    except Exception as e:
        logger.warning(f"查找缓存失败 {root}/{safe_code}{suffix}: {e}")
        return None
    return sorted(candidates)[-1] if candidates else None


def market_cache_root() -> str:
    return MARKET_CACHE_DIR


def ths_local_root() -> str:
    return THS_LOCAL_ROOT


def scan_ths_local_day_files() -> dict:
    """Scan local Tonghuashun day-cache files. This is read-only."""
    roots = [
        ("sh", os.path.join(THS_LOCAL_ROOT, "history", "shase", "day")),
        ("sz", os.path.join(THS_LOCAL_ROOT, "history", "sznse", "day")),
        ("bj", os.path.join(THS_LOCAL_ROOT, "history", "stb", "day")),
    ]
    files = []
    by_market = {}
    for market, root in roots:
        count = 0
        if os.path.isdir(root):
            for name in os.listdir(root):
                if not name.lower().endswith(".day"):
                    continue
                code = os.path.splitext(name)[0]
                if not re.fullmatch(r"\d{6}", code):
                    continue
                path = os.path.join(root, name)
                try:
                    size = os.path.getsize(path)
                    modified_at = datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    size = 0
                    modified_at = ""
                files.append({"code": code, "market": market, "path": path, "size": size, "modified_at": modified_at})
                count += 1
        by_market[market] = {"root": root, "count": count}
    files.sort(key=lambda x: (x.get("modified_at") or "", x.get("code") or ""), reverse=True)
    return {
        "root": THS_LOCAL_ROOT,
        "exists": os.path.isdir(THS_LOCAL_ROOT),
        "total": len(files),
        "by_market": by_market,
        "files": files[:500],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "note": "同花顺本地 .day 是客户端按浏览/下载形成的历史缓存，不等于全市场完整库。",
    }


def get_market_cache_status() -> dict:
    buckets = {
        "universe": UNIVERSE_CACHE_DIR,
        "realtime": REALTIME_CACHE_DIR,
        "kline": KLINE_CACHE_DIR,
        "intraday": INTRADAY_CACHE_DIR,
        "money_flow": MONEY_FLOW_CACHE_DIR,
        "chips": CHIP_CACHE_DIR,
        "validation": VALIDATION_CACHE_DIR,
    }
    status = {
        "root": MARKET_CACHE_DIR,
        "exists": os.path.isdir(MARKET_CACHE_DIR),
        "buckets": {},
    }
    for name, path in buckets.items():
        file_count = 0
        if os.path.isdir(path):
            for _, _, files in os.walk(path):
                file_count += len(files)
        status["buckets"][name] = {"path": path, "exists": os.path.isdir(path), "files": file_count}
    return status


def _write_kline_cache(code: str, period: int, df: Optional[pd.DataFrame]):
    if df is None or df.empty:
        return
    try:
        cache_df = df.copy()
        if "source" in cache_df.columns:
            cache_df["source"] = "cache_file"
        cache_df["cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = _kline_cache_path(code, period)
        _ensure_dir(os.path.dirname(path))
        cache_df.to_csv(path, index=False, encoding="utf-8-sig")
    except Exception as e:
        logger.warning(f"写入K线缓存失败 {code} period={period}: {e}")


def _write_kline_cache_accepting_single_source(code: str, period: int, df: Optional[pd.DataFrame], source_note: str = ""):
    """Write usable public-source K-line rows when strict cross-source validation is unavailable."""
    if df is None or df.empty:
        return
    cache_df = df.copy()
    if "validation_status" not in cache_df.columns:
        cache_df["validation_status"] = "single_source"
    cache_df["validation_note"] = source_note or "public_source_single_or_supplemented"
    cache_df["validation_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_kline_cache(code, period, cache_df)


def _write_kline_candidate_cache(code: str, period: int, df: Optional[pd.DataFrame], report: Optional[dict] = None):
    if df is None or df.empty:
        return
    try:
        cache_df = df.copy()
        cache_df["candidate_cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = _kline_candidate_cache_path(code, period)
        _ensure_dir(os.path.dirname(path))
        cache_df.to_csv(path, index=False, encoding="utf-8-sig")
        if report:
            _write_json_cache(path[:-4] + ".json", report)
    except Exception as e:
        logger.warning(f"鍐欏叆K绾垮€欓€夌紦瀛樺け璐?{code} period={period}: {e}")


def _read_kline_cache(code: str, period: int = 101, days: Optional[int] = None) -> Optional[pd.DataFrame]:
    path = _kline_cache_path(code, period)
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path)
        if df.empty:
            return None
        if "date" in df.columns:
            df["date"] = df["date"].astype(str)
            df = df.sort_values("date").reset_index(drop=True)
        if "source" in df.columns and not df.empty and str(df["source"].iloc[0]) == "estimated":
            return None
        if days:
            df = df.tail(int(days)).reset_index(drop=True)
        df["source"] = "cache_file"
        df["cache_path"] = path
        state_store.set_kline(code, period, df)
        if period == 101:
            state_store.set_daily_bars(code, df)
        return df
    except Exception as e:
        logger.warning(f"读取K线缓存失败 {code} period={period}: {e}")
        return None


def _write_stock_universe_cache(stocks: list):
    if not stocks:
        return
    previous = read_stock_universe_cache()
    changes = build_stock_universe_changes(previous, stocks)
    payload = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(stocks),
        "stocks": stocks,
        "change_summary": changes.get("summary", {}),
    }
    _write_json_cache(os.path.join(UNIVERSE_CACHE_DIR, "stocks.json"), payload)
    _write_json_cache(os.path.join(UNIVERSE_CACHE_DIR, "changes.json"), changes)


def read_stock_universe_cache() -> list:
    payload = _read_json_cache(os.path.join(UNIVERSE_CACHE_DIR, "stocks.json"))
    stocks = payload.get("stocks", []) if isinstance(payload, dict) else []
    stocks = apply_active_stock_scope(stocks)
    if stocks:
        state_store.update_stock_universe(stocks)
    return stocks


def read_stock_universe_cache_meta() -> dict:
    payload = _read_json_cache(os.path.join(UNIVERSE_CACHE_DIR, "stocks.json"))
    if not isinstance(payload, dict):
        return {"updated_at": None, "total": 0, "raw_total": 0, "active_total": 0, "change_summary": {}}
    raw_total = payload.get("total", len(payload.get("stocks", []) or []))
    target_total = active_stock_universe_limit()
    changes = read_stock_universe_changes()
    previous_total = int(changes.get("previous_total") or 0)
    current_total = int(changes.get("current_total") or raw_total or 0)
    new_count = int((changes.get("summary") or {}).get("new_listed") or 0)
    active_total = target_total if target_total and raw_total > target_total else (
        previous_total if previous_total and new_count and current_total > previous_total else raw_total
    )
    return {
        "updated_at": payload.get("updated_at"),
        "total": active_total,
        "active_total": active_total,
        "raw_total": raw_total,
        "change_summary": payload.get("change_summary", {}),
    }


def read_stock_universe_changes() -> dict:
    payload = _read_json_cache(os.path.join(UNIVERSE_CACHE_DIR, "changes.json"))
    if isinstance(payload, dict):
        return payload
    return {
        "checked_at": None,
        "summary": {},
        "new_listed": [],
        "removed_or_delisted": [],
        "name_changed": [],
        "st_changed": [],
        "suspension_changed": [],
    }


def build_stock_universe_changes(previous: list, current: list) -> dict:
    prev_map = {str(item.get("code", "")): item for item in previous or [] if item.get("code")}
    curr_map = {str(item.get("code", "")): item for item in current or [] if item.get("code")}
    new_listed = [curr_map[c] for c in sorted(curr_map.keys() - prev_map.keys())]
    removed = [prev_map[c] for c in sorted(prev_map.keys() - curr_map.keys())]
    name_changed = []
    st_changed = []
    suspension_changed = []
    for code in sorted(prev_map.keys() & curr_map.keys()):
        old = prev_map[code]
        new = curr_map[code]
        if old.get("name") != new.get("name"):
            name_changed.append({
                "code": code,
                "old_name": old.get("name", ""),
                "new_name": new.get("name", ""),
                "exchange": new.get("exchange", old.get("exchange", "")),
                "market": new.get("market", old.get("market", "")),
            })
        if bool(old.get("is_st")) != bool(new.get("is_st")):
            st_changed.append({
                "code": code,
                "name": new.get("name", old.get("name", "")),
                "old_is_st": bool(old.get("is_st")),
                "new_is_st": bool(new.get("is_st")),
            })
        if bool(old.get("is_suspended")) != bool(new.get("is_suspended")):
            suspension_changed.append({
                "code": code,
                "name": new.get("name", old.get("name", "")),
                "old_is_suspended": bool(old.get("is_suspended")),
                "new_is_suspended": bool(new.get("is_suspended")),
            })
    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "previous_total": len(previous or []),
        "current_total": len(current or []),
        "summary": {
            "new_listed": len(new_listed),
            "removed_or_delisted": len(removed),
            "name_changed": len(name_changed),
            "st_changed": len(st_changed),
            "suspension_changed": len(suspension_changed),
        },
        "new_listed": new_listed[:200],
        "removed_or_delisted": removed[:200],
        "name_changed": name_changed[:200],
        "st_changed": st_changed[:200],
        "suspension_changed": suspension_changed[:200],
    }


def _write_realtime_cache(code: str, data: dict):
    if not data:
        return
    payload = dict(data)
    reference_price = payload.get("price") or payload.get("current_price") or payload.get("pre_close")
    for field in ("price", "open", "high", "low", "pre_close", "limit_up", "limit_down", "avg_price"):
        if field in payload:
            payload[field] = _normalize_price_by_reference(payload.get(field), reference_price)
    payload["source"] = payload.get("source") or "eastmoney_realtime"
    payload["cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json_cache(_dated_json_cache_path(REALTIME_CACHE_DIR, code), payload)


def _write_realtime_candidate_cache(code: str, data: dict):
    if not data:
        return
    payload = dict(data)
    payload["cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json_cache(_dated_json_cache_path(os.path.join(REALTIME_CACHE_DIR, "candidates"), code), payload)


def read_realtime_cache(code: str) -> Optional[dict]:
    path = _latest_file_for_code(REALTIME_CACHE_DIR, code, ".json")
    payload = _read_json_cache(path) if path else None
    if isinstance(payload, dict) and payload:
        reference_price = payload.get("price") or payload.get("current_price") or payload.get("pre_close")
        for field in ("price", "open", "high", "low", "pre_close", "limit_up", "limit_down", "avg_price"):
            if field in payload:
                payload[field] = _normalize_price_by_reference(payload.get(field), reference_price)
        payload["source"] = "cache_file"
        payload["cache_path"] = path
        state_store.set_realtime(code, payload)
        return payload
    return None


def supplement_daily_kline_from_realtime(code: str, realtime: dict) -> bool:
    """Merge a real Tencent/public realtime snapshot into today's daily K-line cache."""
    if not realtime:
        return False
    try:
        price = _to_float(realtime.get("price") or realtime.get("current_price"))
        open_price = _to_float(realtime.get("open"))
        high = _to_float(realtime.get("high"))
        low = _to_float(realtime.get("low"))
        pre_close = _to_float(realtime.get("pre_close"))
        if price <= 0 or open_price <= 0 or high <= 0 or low <= 0:
            return False
        trade_date = str(realtime.get("trade_date") or realtime.get("date") or datetime.now().strftime("%Y-%m-%d"))[:10]
        amplitude = _to_float(realtime.get("amplitude"))
        pct_change = _to_float(realtime.get("pct_change"))
        change = _to_float(realtime.get("change"))
        if not amplitude and pre_close:
            amplitude = round((high - low) / pre_close * 100, 2)
        if not pct_change and pre_close:
            pct_change = round((price - pre_close) / pre_close * 100, 2)
        if not change and pre_close:
            change = round(price - pre_close, 3)
        row = {
            "date": trade_date,
            "open": open_price,
            "close": price,
            "high": high,
            "low": low,
            "volume": _to_int(realtime.get("volume")),
            "amount": _to_float(realtime.get("amount")),
            "amplitude": amplitude,
            "pct_change": pct_change,
            "change": change,
            "turnover_rate": _to_float(realtime.get("turnover_rate")),
            "source": "realtime_daily_supplement",
            "validation_status": realtime.get("validation_status") or "single_source_snapshot",
            "validated_sources": ",".join([str(x) for x in realtime.get("validated_sources", [])]) if isinstance(realtime.get("validated_sources"), list) else realtime.get("validated_sources", ""),
            "accepted_sources": ",".join([str(x) for x in realtime.get("accepted_sources", [])]) if isinstance(realtime.get("accepted_sources"), list) else realtime.get("accepted_sources", ""),
            "validation_note": "daily row supplemented from realtime snapshot",
            "validation_checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        df = _read_kline_cache(code, 101, None)
        if df is None or df.empty:
            df = pd.DataFrame([row])
        else:
            df = df.copy()
            df["date"] = df["date"].astype(str).str[:10]
            df = df[df["date"] != trade_date]
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            df = df.sort_values("date").reset_index(drop=True)
        _write_kline_cache_accepting_single_source(code, 101, df, "realtime_daily_supplement")
        state_store.set_kline(code, 101, df)
        state_store.set_daily_bars(code, df)
        _write_validation_report(code, "kline_101", {
            "status": row["validation_status"],
            "verified": row["validation_status"] == "verified",
            "period": 101,
            "latest_date": trade_date,
            "latest_close": price,
            "sources": realtime.get("validated_sources") or [realtime.get("source", "realtime")],
            "note": "latest daily row supplemented from realtime snapshot",
        })
        return True
    except Exception as e:
        logger.warning(f"补齐当日日K失败 {code}: {e}")
        return False


def _write_intraday_cache(code: str, minutes: list):
    if not minutes:
        return
    try:
        df = pd.DataFrame(minutes)
        df["source"] = "cache_file"
        df["cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = _date_csv_cache_path(INTRADAY_CACHE_DIR, code)
        _ensure_dir(os.path.dirname(path))
        df.to_csv(path, index=False, encoding="utf-8-sig")
    except Exception as e:
        logger.warning(f"写入分时缓存失败 {code}: {e}")


def intraday_minutes_valid(minutes: list) -> bool:
    if not minutes:
        return False
    checked = 0
    for row in minutes[:20]:
        price = _to_float(row.get("price"))
        volume = _to_float(row.get("volume"))
        amount = _to_float(row.get("amount"))
        avg_price = _to_float(row.get("avg_price"))
        if not price or price <= 0:
            return False
        if avg_price and (avg_price < price * 0.7 or avg_price > price * 1.3):
            return False
        if volume and amount and price:
            implied_amount = volume * price * 100
            if amount < implied_amount * 0.05:
                return False
        checked += 1
    return checked > 0


def read_intraday_cache(code: str) -> list:
    path = _latest_file_for_code(INTRADAY_CACHE_DIR, code, ".csv")
    if not path:
        return []
    try:
        df = pd.read_csv(path)
        if df.empty:
            return []
        if "source" in df.columns and str(df["source"].iloc[0]) == "estimated":
            return []
        df["source"] = "cache_file"
        df["cache_path"] = path
        minutes = df.to_dict("records")
        if not intraday_minutes_valid(minutes):
            return []
        state_store.set_intraday(code, minutes)
        return minutes
    except Exception as e:
        logger.warning(f"读取分时缓存失败 {code}: {e}")
        return []


def _write_money_flow_cache(code: str, data: dict):
    if not data:
        return
    payload = dict(data)
    payload["source"] = payload.get("source") or "eastmoney_money_flow"
    payload["cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json_cache(_single_json_cache_path(MONEY_FLOW_CACHE_DIR, code), payload)


def read_money_flow_cache(code: str) -> Optional[dict]:
    payload = _read_json_cache(_single_json_cache_path(MONEY_FLOW_CACHE_DIR, code))
    if isinstance(payload, dict) and payload:
        payload["source"] = "cache_file"
        state_store.set_money_flow(code, payload)
        return payload
    return None


def _write_chip_cache(code: str, data: dict):
    if not data:
        return
    payload = dict(data)
    payload["source"] = "derived_from_kline"
    payload["cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _write_json_cache(_single_json_cache_path(CHIP_CACHE_DIR, code), payload)


def read_chip_cache(code: str) -> Optional[dict]:
    payload = _read_json_cache(_single_json_cache_path(CHIP_CACHE_DIR, code))
    if isinstance(payload, dict) and payload:
        payload["source"] = "cache_file"
        state_store.set_chip_distribution(code, payload)
        return payload
    return None


def _sina_symbol(code: str) -> str:
    code = str(code)
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "2", "3")):
        return f"sz{code}"
    if code.startswith(("8", "4", "920")):
        return f"bj{code}"
    return f"sh{code}"


def fetch_realtime_sina_batch(codes: list) -> dict:
    """从新浪官方行情接口获取实时快照，用于和东方财富/同花顺交叉校验。"""
    codes = [str(c) for c in codes if c]
    if not codes:
        return {}
    results = {}
    batch_size = 80
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        symbols = ",".join(_sina_symbol(c) for c in batch)
        _rate_limit("hq.sinajs.cn")
        try:
            resp = requests.get(
                f"https://hq.sinajs.cn/list={symbols}",
                headers={"User-Agent": HEADERS["User-Agent"], "Referer": "https://finance.sina.com.cn/"},
                timeout=8,
            )
            text = resp.content.decode("gbk", errors="ignore")
            for line in text.splitlines():
                m = re.search(r"var hq_str_(?:sh|sz|bj)(\d+)=\"(.*)\";", line)
                if not m:
                    continue
                code = m.group(1)
                parts = m.group(2).split(",")
                if len(parts) < 32 or not parts[0]:
                    continue
                pre_close = _to_float(parts[2])
                price = _to_float(parts[3])
                pct_change = round((price - pre_close) / pre_close * 100, 4) if pre_close else 0
                results[code] = {
                    "code": code,
                    "name": parts[0],
                    "open": _to_float(parts[1]),
                    "pre_close": pre_close,
                    "price": price,
                    "high": _to_float(parts[4]),
                    "low": _to_float(parts[5]),
                    "volume": _to_int(parts[8]) // 100,
                    "amount": _to_float(parts[9]),
                    "pct_change": pct_change,
                    "source": "sina_realtime",
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
        except Exception as e:
            logger.warning(f"新浪实时行情校验失败: {e}")
    return results


def fetch_realtime_ths(code: str) -> Optional[dict]:
    """从同花顺官网接口获取单只股票实时快照，用于交叉校验。"""
    try:
        _rate_limit("d.10jqka.com.cn")
        resp = requests.get(
            f"http://d.10jqka.com.cn/v6/line/hs_{code}/01/today.js",
            headers={"User-Agent": HEADERS["User-Agent"], "Referer": f"http://stockpage.10jqka.com.cn/{code}/"},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        match = re.search(r"\((.*)\)", resp.text, re.S)
        if not match:
            return None
        data = json.loads(match.group(1))
        key = list(data.keys())[0]
        info = data[key]
        price = _to_float(info.get("11"))
        open_price = _to_float(info.get("7"))
        volume = _to_int(info.get("13")) // 100
        amount = _to_float(info.get("19"))
        return {
            "code": code,
            "name": info.get("name", ""),
            "price": price,
            "open": open_price,
            "volume": volume,
            "amount": amount,
            "source": "ths_realtime",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as e:
        logger.warning(f"同花顺实时行情校验失败 {code}: {e}")
        return None


def _tencent_symbol(code: str) -> str:
    code = str(code)
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "2", "3")):
        return f"sz{code}"
    if code.startswith(("8", "4", "920")):
        return f"bj{code}"
    return f"sh{code}"


def fetch_realtime_tencent_batch(codes: list) -> dict:
    """Fetch Tencent Securities realtime quotes, including five-level book and F10-like fields."""
    codes = [str(c) for c in codes if c]
    if not codes:
        return {}
    results = {}
    batch_size = 60
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        symbols = ",".join(_tencent_symbol(c) for c in batch)
        _rate_limit("qt.gtimg.cn")
        try:
            resp = requests.get(
                f"https://qt.gtimg.cn/q={symbols}",
                headers={"User-Agent": HEADERS["User-Agent"], "Referer": "https://gu.qq.com/"},
                timeout=8,
            )
            text = resp.content.decode("gbk", errors="ignore")
            for line in text.splitlines():
                m = re.search(r'v_(?:sh|sz|bj)(\d+)="(.*)";', line)
                if not m:
                    continue
                code = m.group(1)
                parts = m.group(2).split("~")
                if len(parts) < 50 or _to_float(parts[3]) <= 0:
                    continue
                item = {
                    "code": code,
                    "name": parts[1],
                    "price": _to_float(parts[3]),
                    "pre_close": _to_float(parts[4]),
                    "open": _to_float(parts[5]),
                    "volume": _to_float(parts[6]),
                    "inner_volume": _to_float(parts[7]),
                    "outer_volume": _to_float(parts[8]),
                    "change": _to_float(parts[31]),
                    "pct_change": _to_float(parts[32]),
                    "high": _to_float(parts[33]),
                    "low": _to_float(parts[34]),
                    "amount": _to_float(parts[35].split("/")[-1] if "/" in parts[35] else parts[57]) or _to_float(parts[57]) * 10000,
                    "turnover_rate": _to_float(parts[38]),
                    "pe_ttm": _to_float(parts[39]),
                    "amplitude": _to_float(parts[43]),
                    "market_cap": _to_float(parts[44]) * 100000000,
                    "float_market_cap": _to_float(parts[45]) * 100000000,
                    "pb": _to_float(parts[46]),
                    "limit_up": _to_float(parts[47]),
                    "limit_down": _to_float(parts[48]),
                    "volume_ratio": _to_float(parts[49]),
                    "avg_price": _to_float(parts[51]),
                    "pe_dynamic": _to_float(parts[52]),
                    "pe_static": _to_float(parts[53]),
                    "total_shares": _to_float(parts[72]) if len(parts) > 72 else 0,
                    "float_shares": _to_float(parts[73]) if len(parts) > 73 else 0,
                    "entrust_ratio": _to_float(parts[74]) if len(parts) > 74 else 0,
                    "source": "tencent_realtime",
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                if len(parts) > 30 and re.fullmatch(r"\d{14}", parts[30] or ""):
                    item["trade_datetime"] = f"{parts[30][:4]}-{parts[30][4:6]}-{parts[30][6:8]} {parts[30][8:10]}:{parts[30][10:12]}:{parts[30][12:14]}"
                    item["trade_date"] = item["trade_datetime"][:10]
                for level in range(1, 6):
                    bid_idx = 9 + (level - 1) * 2
                    ask_idx = 19 + (level - 1) * 2
                    item[f"bid_price{level}"] = _to_float(parts[bid_idx])
                    item[f"bid_volume{level}"] = _to_float(parts[bid_idx + 1])
                    item[f"ask_price{level}"] = _to_float(parts[ask_idx])
                    item[f"ask_volume{level}"] = _to_float(parts[ask_idx + 1])
                results[code] = item
        except Exception as e:
            logger.warning(f"鑵捐璇佸埜瀹炴椂琛屾儏鎷夊彇澶辫触: {e}")
    return results


def _parse_eastmoney_kline_rows(klines: list, source: str = "eastmoney_kline") -> Optional[pd.DataFrame]:
    rows = []
    for line in klines or []:
        parts = str(line).split(",")
        if len(parts) >= 11:
            rows.append({
                "date": parts[0],
                "open": _to_float(parts[1]),
                "close": _to_float(parts[2]),
                "high": _to_float(parts[3]),
                "low": _to_float(parts[4]),
                "volume": _to_int(parts[5]),
                "amount": _to_float(parts[6]),
                "amplitude": _to_float(parts[7]),
                "pct_change": _to_float(parts[8]),
                "change": _to_float(parts[9]),
                "turnover_rate": _to_float(parts[10]),
                "source": source,
            })
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df["date"] = df["date"].astype(str)
    return df.sort_values("date").reset_index(drop=True)


def fetch_kline_eastmoney(code: str, period: int = 101, days: int = 120) -> Optional[pd.DataFrame]:
    _rate_limit("push2his.eastmoney.com")
    params = {
        "secid": _get_secid(code),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": period,
        "fqt": 1,
        "lmt": days,
        "end": "20500101",
    }
    try:
        resp = requests.get("https://push2his.eastmoney.com/api/qt/stock/kline/get", params=params, headers=HEADERS, timeout=15)
        data = resp.json()
        return _parse_eastmoney_kline_rows(data.get("data", {}).get("klines", []), "eastmoney_kline")
    except Exception as e:
        logger.warning(f"东方财富K线拉取失败 {code} period={period}: {e}")
        return None


def fetch_kline_sina(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    symbol = _sina_symbol(code)
    urls = [
        "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketData.getKLineData",
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
    ]
    for url in urls:
        try:
            _rate_limit("quotes.sina.cn" if "quotes.sina.cn" in url else "vip.stock.finance.sina.com.cn")
            resp = requests.get(
                url,
                params={"symbol": symbol, "scale": 240, "ma": "no", "datalen": int(days)},
                headers={"User-Agent": HEADERS["User-Agent"], "Referer": "https://finance.sina.com.cn/"},
                timeout=12,
            )
            rows = []
            for item in resp.json() or []:
                rows.append({
                    "date": str(item.get("day", ""))[:10],
                    "open": _to_float(item.get("open")),
                    "close": _to_float(item.get("close")),
                    "high": _to_float(item.get("high")),
                    "low": _to_float(item.get("low")),
                    "volume": _to_int(item.get("volume")),
                    "amount": _to_float(item.get("amount")),
                    "source": "sina_kline",
                })
            if rows:
                df = pd.DataFrame(rows)
                df = df[df["date"].astype(bool)].sort_values("date").reset_index(drop=True)
                return df
        except Exception as e:
            logger.warning(f"新浪历史K线拉取失败 {code}: {e}")
    return None


def fetch_kline_ths_daily(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    try:
        _rate_limit("d.10jqka.com.cn")
        resp = requests.get(
            f"http://d.10jqka.com.cn/v6/line/hs_{code}/01/today.js",
            headers={"User-Agent": HEADERS["User-Agent"], "Referer": f"http://stockpage.10jqka.com.cn/{code}/"},
            timeout=8,
        )
        if resp.status_code != 200:
            return None
        match = re.search(r"\((.*)\)", resp.text, re.S)
        if not match:
            return None
        info = list(json.loads(match.group(1)).values())[0]
        date_raw = str(info.get("1", ""))
        if len(date_raw) == 8:
            date_raw = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
        row = {
            "date": date_raw,
            "open": _to_float(info.get("7")),
            "high": _to_float(info.get("8")),
            "low": _to_float(info.get("9")),
            "close": _to_float(info.get("11")),
            "volume": _to_int(info.get("13")),
            "amount": _to_float(info.get("19")),
            "source": "ths_kline_latest",
        }
        if not row["date"] or row["close"] <= 0:
            return None
        return pd.DataFrame([row])
    except Exception as e:
        logger.warning(f"同花顺最新日K拉取失败 {code}: {e}")
        return None


def _kline_pair_matches(left: dict, right: dict) -> bool:
    return all(_relative_close(left.get(field), right.get(field), 0.003) for field in ("open", "close", "high", "low"))


def _merge_verified_kline_row(date: str, source_rows: dict, accepted_sources: list) -> dict:
    priority = ["eastmoney", "sina", "ths"]
    primary_name = sorted(accepted_sources, key=lambda s: priority.index(s) if s in priority else 99)[0]
    merged = dict(source_rows[primary_name])
    peer_rows = [source_rows[name] for name in accepted_sources if name in source_rows]
    for field in ("open", "close", "high", "low", "volume", "amount"):
        vals = [_to_float(row.get(field)) for row in peer_rows if _to_float(row.get(field)) > 0]
        if vals and field in ("open", "close", "high", "low"):
            merged[field] = round(sum(vals) / len(vals), 3)
        elif vals:
            merged[field] = round(sum(vals) / len(vals), 2)
    merged.update({
        "date": date,
        "source": "verified_kline",
        "validation_status": "verified",
        "validated_sources": ",".join(source_rows.keys()),
        "accepted_sources": ",".join(accepted_sources),
        "rejected_sources": ",".join([name for name in source_rows.keys() if name not in accepted_sources]),
        "validation_checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    return merged


def _validate_historical_kline_sources(code: str, period: int, days: int, source_frames: dict) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame], dict]:
    normalized = {}
    for source, df in (source_frames or {}).items():
        if df is None or df.empty:
            continue
        frame = df.copy()
        frame["date"] = frame["date"].astype(str).str[:10]
        normalized[source] = {
            row["date"]: row
            for row in frame.to_dict("records")
            if row.get("date") and _to_float(row.get("close")) > 0
        }
    all_dates = sorted(set().union(*(set(items.keys()) for items in normalized.values()))) if normalized else []
    if days:
        all_dates = all_dates[-int(days):]
    trusted_rows, candidate_rows, conflicts, single_source_rows = [], [], [], []
    priority = ["eastmoney", "sina", "ths"]
    for date in all_dates:
        rows = {source: by_date[date] for source, by_date in normalized.items() if date in by_date}
        base = dict(next(iter(rows.values()))) if rows else {"date": date}
        base.update({"date": date, "source": "candidate_kline", "validated_sources": ",".join(rows.keys()), "validation_checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        if len(rows) < 2:
            base["validation_status"] = "single_source"
            single_source_rows.append(date)
            candidate_rows.append(base)
            continue
        agreeing_pairs = []
        sources = list(rows.keys())
        for i, left in enumerate(sources):
            for right in sources[i + 1:]:
                if _kline_pair_matches(rows[left], rows[right]):
                    agreeing_pairs.append((left, right))
        if agreeing_pairs:
            accepted = sorted(set(agreeing_pairs[0]), key=lambda name: priority.index(name) if name in priority else 99)
            trusted_rows.append(_merge_verified_kline_row(date, rows, accepted))
        else:
            base["validation_status"] = "conflict"
            conflicts.append({"date": date, "sources": {source: {k: row.get(k) for k in ("open", "close", "high", "low", "volume")} for source, row in rows.items()}})
            candidate_rows.append(base)
    trusted_df = pd.DataFrame(trusted_rows).sort_values("date").reset_index(drop=True) if trusted_rows else None
    candidate_df = pd.DataFrame(candidate_rows).sort_values("date").reset_index(drop=True) if candidate_rows else None
    report = {
        "status": "verified" if trusted_rows and not candidate_rows else "partial_verified" if trusted_rows else "unverified",
        "verified": bool(trusted_rows),
        "period": period,
        "requested_days": days,
        "source_counts": {source: len(items) for source, items in normalized.items()},
        "source_coverage": {
            "eastmoney": "history" if "eastmoney" in normalized else "missing",
            "sina": "history" if "sina" in normalized else "missing",
            "ths": "latest_only" if "ths" in normalized else "missing",
        },
        "trusted_rows": len(trusted_rows),
        "candidate_rows": len(candidate_rows),
        "single_source_rows": len(single_source_rows),
        "conflict_rows": len(conflicts),
        "sources": list(normalized.keys()),
        "single_source_sample": single_source_rows[:20],
        "conflict_sample": conflicts[:20],
    }
    return trusted_df, candidate_df, report


def _validate_realtime_samples(code: str, samples: dict) -> tuple[Optional[dict], dict]:
    available = {k: v for k, v in samples.items() if isinstance(v, dict) and _to_float(v.get("price")) > 0}
    report = {
        "status": "unavailable",
        "verified": False,
        "sources": list(available.keys()),
        "source_count": len(available),
        "accepted_source": None,
        "disagreements": [],
    }
    if not available:
        return None, report

    def pair_ok(a: dict, b: dict) -> bool:
        price_ok = _relative_close(a.get("price"), b.get("price"), 0.003)
        volume_ok = True
        if _to_float(a.get("volume")) > 0 and _to_float(b.get("volume")) > 0:
            volume_ok = _relative_close(a.get("volume"), b.get("volume"), 0.08)
        amount_ok = True
        if _to_float(a.get("amount")) > 0 and _to_float(b.get("amount")) > 0:
            amount_ok = _relative_close(a.get("amount"), b.get("amount"), 0.08)
        return price_ok and volume_ok and amount_ok

    source_priority = ["eastmoney", "sina", "ths", "tencent"]
    pairs = []
    sources = list(available.keys())
    for i, left in enumerate(sources):
        for right in sources[i + 1:]:
            ok = pair_ok(available[left], available[right])
            pairs.append((ok, left, right))
            if not ok:
                report["disagreements"].append({
                    "source_pair": [left, right],
                    "left": {
                        "price": available[left].get("price"),
                        "volume": available[left].get("volume"),
                        "amount": available[left].get("amount"),
                    },
                    "right": {
                        "price": available[right].get("price"),
                        "volume": available[right].get("volume"),
                        "amount": available[right].get("amount"),
                    },
                })

    agreeing_pairs = [(left, right) for ok, left, right in pairs if ok]
    accepted_sources = []
    if agreeing_pairs:
        # 三源中任意两源一致即通过；优先选择覆盖东方财富/新浪的组合，再按固定优先级取基准样本。
        accepted_sources = sorted(
            agreeing_pairs[0],
            key=lambda name: source_priority.index(name) if name in source_priority else 99,
        )
    elif len(available) == 1:
        accepted_sources = [next(iter(available.keys()))]

    primary_source = accepted_sources[0] if accepted_sources else (
        "eastmoney" if "eastmoney" in available else next(iter(available.keys()))
    )
    primary = dict(available[primary_source])
    wrong_sources = [name for name in available.keys() if accepted_sources and name not in accepted_sources]
    if accepted_sources and len(accepted_sources) >= 2:
        peer = available[accepted_sources[1]]
        for field in ("price", "open", "high", "low", "pre_close", "volume", "amount", "pct_change"):
            a = _to_float(primary.get(field))
            b = _to_float(peer.get(field))
            if a > 0 and b > 0 and _relative_close(a, b, 0.003 if field in ("price", "open", "high", "low", "pre_close") else 0.08):
                primary[field] = round((a + b) / 2, 4 if field == "pct_change" else 2)

    supplemental_fields = (
        "bid_price1", "bid_volume1", "bid_price2", "bid_volume2", "bid_price3", "bid_volume3",
        "bid_price4", "bid_volume4", "bid_price5", "bid_volume5",
        "ask_price1", "ask_volume1", "ask_price2", "ask_volume2", "ask_price3", "ask_volume3",
        "ask_price4", "ask_volume4", "ask_price5", "ask_volume5",
        "inner_volume", "outer_volume", "limit_up", "limit_down", "avg_price", "pe_ttm",
        "pe_dynamic", "pe_static", "pb", "market_cap", "float_market_cap", "total_shares",
        "float_shares", "entrust_ratio", "amplitude", "turnover_rate", "volume_ratio",
    )
    supplemental_sources = accepted_sources + [name for name in ("tencent", "eastmoney", "sina", "ths") if name in available and name not in accepted_sources]
    for field in supplemental_fields:
        if not primary.get(field):
            for source_name in supplemental_sources:
                value = available.get(source_name, {}).get(field)
                if value not in (None, "", 0):
                    primary[field] = value
                    break

    if not agreeing_pairs and len(available) > 1:
        for source, sample in available.items():
            report["disagreements"].append({
                "source": source,
                "price": sample.get("price"),
                "volume": sample.get("volume"),
                "amount": sample.get("amount"),
            })

    verified = len(accepted_sources) >= 2
    merged = dict(primary)
    merged["source"] = "verified_realtime" if verified else primary.get("source", "realtime")
    merged["validation_status"] = "verified" if verified else "single_source" if len(available) == 1 else "conflict"
    merged["validated_sources"] = list(available.keys())
    merged["accepted_sources"] = accepted_sources
    merged["rejected_sources"] = wrong_sources
    merged["validation_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report.update({
        "status": merged["validation_status"],
        "verified": verified,
        "accepted_source": primary_source,
        "accepted_sources": accepted_sources,
        "rejected_sources": wrong_sources,
        "price": merged.get("price"),
    })
    return merged, report


def fetch_verified_realtime_batch(codes: list, require_verified_for_cache: bool = True) -> dict:
    """多源校验实时行情；通过校验的数据写入正式缓存，冲突数据只写候选缓存。"""
    codes = [str(c) for c in codes if c]
    if not codes:
        return {}
    eastmoney = _fetch_realtime_eastmoney_raw(codes)
    sina = fetch_realtime_sina_batch(codes)
    tencent = fetch_realtime_tencent_batch(codes)
    results = {}
    for code in codes:
        samples = {
            "eastmoney": eastmoney.get(code),
            "sina": sina.get(code),
            "tencent": tencent.get(code),
        }
        ths = fetch_realtime_ths(code)
        if ths:
            samples["ths"] = ths
        merged, report = _validate_realtime_samples(code, samples)
        _write_validation_report(code, "realtime", report)
        if merged:
            state_store.set_realtime(code, merged)
            if report.get("verified") or not require_verified_for_cache:
                _write_realtime_cache(code, merged)
            else:
                _write_realtime_candidate_cache(code, merged)
            supplement_daily_kline_from_realtime(code, merged)
            results[code] = merged
        else:
            cached = read_realtime_cache(code)
            if cached:
                results[code] = cached
    state_store.set_realtime_batch(results)
    state_store.update_realtime_timestamp()
    return results


def _validate_latest_kline_with_snapshots(code: str, df: pd.DataFrame, period: int) -> dict:
    report = {
        "status": "not_checked",
        "verified": False,
        "period": period,
        "sources": ["eastmoney_kline"],
        "disagreements": [],
    }
    if period != 101 or df is None or df.empty:
        return report
    try:
        last = df.iloc[-1].to_dict()
        close = _to_float(last.get("close"))
        open_price = _to_float(last.get("open"))
        high = _to_float(last.get("high"))
        low = _to_float(last.get("low"))
        volume = _to_float(last.get("volume"))
        snapshots = {
            "sina": fetch_realtime_sina_batch([code]).get(code),
            "ths": fetch_realtime_ths(code),
            "tencent": fetch_realtime_tencent_batch([code]).get(code),
        }
        checks = []
        for source, snap in snapshots.items():
            if not snap:
                continue
            report["sources"].append(source)
            price_ok = _relative_close(close, snap.get("price"), 0.003)
            open_ok = True if not snap.get("open") else _relative_close(open_price, snap.get("open"), 0.003)
            high_ok = True if not snap.get("high") else _relative_close(high, snap.get("high"), 0.003)
            low_ok = True if not snap.get("low") else _relative_close(low, snap.get("low"), 0.003)
            volume_ok = True
            if volume > 0 and _to_float(snap.get("volume")) > 0:
                volume_ok = _relative_close(volume, snap.get("volume"), 0.08)
            ok = price_ok and open_ok and high_ok and low_ok and volume_ok
            checks.append(ok)
            if not ok:
                report["disagreements"].append({
                    "source": source,
                    "price": snap.get("price"),
                    "open": snap.get("open"),
                    "high": snap.get("high"),
                    "low": snap.get("low"),
                    "volume": snap.get("volume"),
                })
        verified = any(checks)
        report.update({
            "status": "verified" if verified else "single_source" if len(report["sources"]) == 1 else "conflict",
            "verified": verified,
            "latest_date": str(last.get("date")),
            "latest_close": close,
            "source_count": len(report["sources"]),
        })
        return report
    except Exception as e:
        report["status"] = "validation_error"
        report["error"] = str(e)
        return report


def _rate_limit(host: str):
    """请求限速"""
    now = time.time() * 1000
    last = _last_request_time.get(host, 0)
    wait = RATE_LIMIT_MS - (now - last)
    if wait > 0:
        time.sleep(wait / 1000)
    _last_request_time[host] = time.time() * 1000


def is_trading_hours() -> bool:
    """判断是否在交易时段（9:15-11:30, 13:00-15:00, 周一至周五）"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    t = now.time()
    from datetime import time as dtime
    morning_start = dtime(9, 15)
    morning_end = dtime(11, 30)
    afternoon_start = dtime(13, 0)
    afternoon_end = dtime(15, 0)
    return (morning_start <= t <= morning_end) or (afternoon_start <= t <= afternoon_end)


def is_trading_day() -> bool:
    """判断今天是否是交易日（简单判断：非周末）"""
    return datetime.now().weekday() < 5


# ==================== 股票列表（新浪财经）====================

def fetch_all_stocks_sina() -> list:
    """从新浪财经获取全部A股列表（约5500只）"""
    all_stocks = []
    page = 1
    per_page = 80

    while True:
        _rate_limit("vip.stock.finance.sina.com.cn")
        url = (
            f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"Market_Center.getHQNodeData?page={page}&num={per_page}&sort=symbol&asc=1&node=hs_a&symbol=&_s_r_a=page"
        )
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200 or not resp.text.strip():
                break
            data = json.loads(resp.text)
            if not data:
                break
            for item in data:
                symbol = item.get("symbol", "")
                code = symbol[2:] if len(symbol) > 2 else symbol
                exchange = symbol[:2] if len(symbol) > 2 else ""
                name = item.get("name", "")
                is_st = "ST" in name.upper()
                price = float(item.get("trade", 0) or 0)
                pct_change = float(item.get("changepercent", 0) or 0)
                volume = int(float(item.get("volume", 0) or 0))
                amount = float(item.get("amount", 0) or 0)

                market = ""
                if code.startswith("6"):
                    market = "沪市"
                elif code.startswith("0"):
                    market = "深市"
                elif code.startswith("3"):
                    market = "创业板"
                elif code.startswith("8") or code.startswith("4"):
                    market = "北交所"

                all_stocks.append({
                    "code": code,
                    "name": name,
                    "exchange": exchange,
                    "market": market,
                    "is_st": is_st,
                    "price": price,
                    "pct_change": pct_change,
                    "volume": volume,
                    "amount": amount,
                    "is_suspended": price <= 0,
                    "trade_status": "停牌" if price <= 0 else "交易",
                })
            page += 1
            if len(data) < per_page:
                break
        except Exception as e:
            logger.error(f"获取股票列表第{page}页失败: {e}")
            break

    logger.info(f"从新浪获取到 {len(all_stocks)} 只A股")
    if all_stocks:
        state_store.update_stock_universe(all_stocks)
        _write_stock_universe_cache(all_stocks)
    return all_stocks


def fetch_all_stocks_eastmoney() -> list:
    """从东方财富获取沪深京 A 股列表，作为新浪股票池不完整时的补充来源。"""
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    fs_groups = [
        ("sh", "m:1+t:2,m:1+t:23"),
        ("sz", "m:0+t:6,m:0+t:80"),
        ("bj", "m:0+t:81+s:2048"),
    ]
    all_stocks: list = []
    for exchange_hint, fs in fs_groups:
        page = 1
        while True:
            _rate_limit("push2.eastmoney.com")
            params = {
                "pn": page,
                "pz": 100,
                "po": 1,
                "np": 1,
                "fltt": 2,
                "invt": 2,
                "fid": "f6",
                "fs": fs,
                "fields": "f2,f3,f5,f6,f12,f14",
            }
            try:
                resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
                data = resp.json().get("data", {}) if resp.status_code == 200 else {}
                rows = data.get("diff", []) or []
                if not rows:
                    break
                for item in rows:
                    code = str(item.get("f12", "")).strip()
                    name = str(item.get("f14", "")).strip()
                    if not code or not name:
                        continue
                    raw_price = item.get("f2", 0)
                    is_suspended = raw_price in ("-", None, "")
                    exchange = exchange_hint
                    if code.startswith(("4", "8", "920")):
                        exchange = "bj"
                    elif code.startswith(("6", "9")):
                        exchange = "sh"
                    elif code.startswith(("0", "2", "3")):
                        exchange = "sz"
                    if code.startswith(("688", "689")):
                        market = "科创板"
                    elif code.startswith(("300", "301")):
                        market = "创业板"
                    elif exchange == "bj":
                        market = "北交所"
                    elif exchange == "sh":
                        market = "沪市"
                    else:
                        market = "深市"
                    all_stocks.append({
                        "code": code,
                        "name": name,
                        "exchange": exchange,
                        "market": market,
                        "is_st": "ST" in name.upper(),
                        "price": _to_float(raw_price),
                        "pct_change": _to_float(item.get("f3")),
                        "volume": _to_int(item.get("f5")),
                        "amount": _to_float(item.get("f6")),
                        "is_suspended": is_suspended,
                        "trade_status": "停牌" if is_suspended else "交易",
                    })
                page += 1
                if len(rows) < 100 or page > 80:
                    break
            except Exception as e:
                logger.warning(f"东方财富股票池获取失败 {exchange_hint} 第{page}页: {e}")
                break
    if all_stocks:
        merged = {item["code"]: item for item in all_stocks}
        all_stocks = list(merged.values())
        state_store.update_stock_universe(all_stocks)
        _write_stock_universe_cache(all_stocks)
    logger.info(f"从东方财富获取到 {len(all_stocks)} 只A股")
    return all_stocks


# ==================== 日线K线（东方财富）====================

def _get_secid(code: str) -> str:
    """将股票代码转换为东方财富secid格式"""
    code = str(code)
    if code.startswith(("4", "8", "920")):
        return f"0.{code}"
    if code.startswith("6"):
        return f"1.{code}"
    elif code.startswith(("0", "2", "3")):
        return f"0.{code}"
    elif code.startswith(("8", "4")):
        return f"0.{code}"
    return f"1.{code}"


def fetch_daily_bars(code: str, days: int = 60) -> Optional[pd.DataFrame]:
    return fetch_kline(code, period=101, days=days, allow_fallback=False)


def _fetch_daily_bars_legacy(code: str, days: int = 60) -> Optional[pd.DataFrame]:
    """从东方财富获取日线K线数据"""
    cached = _read_kline_cache(code, 101, days)
    if cached is not None:
        return cached
    _rate_limit("push2his.eastmoney.com")
    secid = _get_secid(code)
    end_date = datetime.now().strftime("%Y%m%d")
    url = (
        f"https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&klt=101&fqt=1&end={end_date}&lmt={days}"
    )
    try:
        resp = requests.get(url, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://quote.eastmoney.com/",
        }, timeout=10)
        data = resp.json()
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return _read_kline_cache(code, 101, days)

        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 11:
                rows.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": int(float(parts[5])),
                    "amount": float(parts[6]),
                    "amplitude": float(parts[7]),  # 振幅
                    "pct_change": float(parts[8]),
                    "change": float(parts[9]),
                    "turnover_rate": float(parts[10]),
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["source"] = "eastmoney_kline"
            report = _validate_latest_kline_with_snapshots(code, df, 101)
            df["validation_status"] = report.get("status", "single_source")
            df["validated_sources"] = ",".join(report.get("sources", []))
            df["validation_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _write_validation_report(code, "kline_101", report)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        state_store.set_daily_bars(code, df)
        state_store.set_kline(code, 101, df)
        _write_kline_cache(code, 101, df)
        return df
    except Exception as e:
        logger.warning(f"获取{code}日线失败: {e}")
        return _read_kline_cache(code, 101, days)


def fetch_daily_bars_batch(codes: list, days: int = 60):
    """批量获取日线数据"""
    count = 0
    for code in codes:
        df = fetch_daily_bars(code, days)
        if df is not None:
            count += 1
        if count % 50 == 0 and count > 0:
            logger.info(f"已获取 {count}/{len(codes)} 只股票日线数据")
    logger.info(f"日线数据获取完成: {count}/{len(codes)}")
    return count


# ==================== 实时行情（东方财富批量）====================

def _fetch_realtime_eastmoney_raw(codes: list) -> dict:
    """批量获取东方财富实时行情原始快照。"""
    if not codes:
        return {}

    results = {}
    batch_size = 50

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        secids = ",".join([_get_secid(c) for c in batch])
        _rate_limit("push2.eastmoney.com")
        url = (
            f"https://push2.eastmoney.com/api/qt/ulist.np/get?"
            f"fields=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18"
            f"&secids={secids}"
        )
        try:
            resp = requests.get(url, headers={
                "User-Agent": HEADERS["User-Agent"],
                "Referer": "https://quote.eastmoney.com/",
            }, timeout=10)
            data = resp.json()
            diff = data.get("data", {}).get("diff", [])
            if isinstance(diff, dict):
                diff = list(diff.values())
            for item in diff:
                code = item.get("f12", "")
                if not code:
                    continue
                price = item.get("f2", 0)
                if price == "-":
                    price = 0
                price = float(price or 0) / 100 if isinstance(price, (int, float)) and price > 1000 else float(price or 0)
                pct_change = float(item.get("f3", 0) or 0)
                if isinstance(pct_change, (int, float)) and abs(pct_change) > 100:
                    pct_change = pct_change / 100
                volume = int(float(item.get("f5", 0) or 0))
                amount = float(item.get("f6", 0) or 0)
                turnover_rate = float(item.get("f8", 0) or 0)
                if isinstance(turnover_rate, (int, float)) and turnover_rate > 100:
                    turnover_rate = turnover_rate / 100
                volume_ratio = float(item.get("f10", 0) or 0)
                if isinstance(volume_ratio, (int, float)) and volume_ratio > 100:
                    volume_ratio = volume_ratio / 100
                high = _normalize_price_by_reference(item.get("f15", 0), price)
                low = _normalize_price_by_reference(item.get("f16", 0), price)
                open_price = _normalize_price_by_reference(item.get("f17", 0), price)
                pre_close = _normalize_price_by_reference(item.get("f18", 0), price)
                if price > 0 and pre_close > 0:
                    calc_pct_change = round((price - pre_close) / pre_close * 100, 4)
                    if abs(pct_change - calc_pct_change) > 5:
                        pct_change = calc_pct_change

                results[code] = {
                    "code": code,
                    "name": item.get("f14", ""),
                    "price": price,
                    "pct_change": pct_change,
                    "volume": volume,
                    "amount": amount,
                    "turnover_rate": turnover_rate,
                    "volume_ratio": volume_ratio,
                    "high": high,
                    "low": low,
                    "open": open_price,
                    "pre_close": pre_close,
                    "source": "eastmoney_realtime",
                    "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
                # 记录价格快照（用于反追高检测）
                if price > 0:
                    state_store.add_price_snapshot(code, price)
        except Exception as e:
            logger.warning(f"批量获取行情失败: {e}")

    return results


def fetch_realtime_batch(codes: list) -> dict:
    """批量获取实时行情：东方财富、同花顺、新浪多源校验后返回。"""
    return fetch_verified_realtime_batch(codes)


# ==================== 资金流向（东方财富）====================

def fetch_money_flow(code: str) -> Optional[dict]:
    """获取个股资金流向"""
    _rate_limit("push2.eastmoney.com")
    secid = _get_secid(code)
    url = (
        f"https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get?"
        f"secid={secid}&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65"
        f"&lmt=5"
    )
    try:
        resp = requests.get(url, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://quote.eastmoney.com/",
        }, timeout=10)
        data = resp.json()
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            return read_money_flow_cache(code)

        flows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 7:
                flows.append({
                    "date": parts[0],
                    "main_net_inflow": float(parts[1]),      # 主力净流入
                    "small_net_inflow": float(parts[2]),     # 小单净流入
                    "medium_net_inflow": float(parts[3]),    # 中单净流入
                    "large_net_inflow": float(parts[4]),     # 大单净流入
                    "super_large_net_inflow": float(parts[5]),  # 超大单净流入
                })

        result = {
            "code": code,
            "flows": flows,
            "latest_main_net_inflow": flows[-1]["main_net_inflow"] if flows else 0,
            "consecutive_inflow_days": _count_consecutive_inflow(flows),
            "source": "eastmoney_money_flow",
        }
        state_store.set_money_flow(code, result)
        _write_money_flow_cache(code, result)
        return result
    except Exception as e:
        logger.warning(f"获取{code}资金流向失败: {e}")
        return read_money_flow_cache(code)


def _count_consecutive_inflow(flows: list) -> int:
    """计算连续净流入天数"""
    count = 0
    for flow in reversed(flows):
        if flow["main_net_inflow"] > 0:
            count += 1
        else:
            break
    return count


# ==================== 北向资金 ====================

def fetch_northbound_flow() -> Optional[dict]:
    """获取北向资金净流入"""
    _rate_limit("push2.eastmoney.com")
    url = (
        "https://push2.eastmoney.com/api/qt/kamt.rtmin/get?"
        "fields1=f1,f2,f3,f4&fields2=f51,f54,f52,f58,f53,f62,f56,f57,f60,f61"
    )
    try:
        resp = requests.get(url, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://quote.eastmoney.com/",
        }, timeout=10)
        data = resp.json()
        s2n = data.get("data", {}).get("s2n", [])
        if not s2n:
            return None
        # 取最后一条数据
        latest = s2n[-1].split(",") if s2n else []
        result = {
            "time": latest[0] if len(latest) > 0 else "",
            "sh_net": float(latest[1]) if len(latest) > 1 and latest[1] != "-" else 0,
            "sz_net": float(latest[3]) if len(latest) > 3 and latest[3] != "-" else 0,
            "total_net": 0,
        }
        result["total_net"] = result["sh_net"] + result["sz_net"]
        state_store.set_northbound_flow(result)
        return result
    except Exception as e:
        logger.warning(f"获取北向资金失败: {e}")
        return None


# ==================== 财经新闻 ====================

NEWS_SOURCES = [
    "财联社", "新浪财经", "东方财富", "证券时报", "华尔街见闻", "韭研公社",
    "金融时报", "FT中文网", "中国证券报", "上海证券报", "同花顺",
]


def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", "", value or "")
    return html_lib.unescape(text).replace("\u3000", " ").strip()


def _format_news_time(value) -> str:
    """Normalize assorted external timestamps to YYYY-MM-DD HH:MM."""
    if not value:
        return ""
    try:
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 10_000_000_000:
                ts = ts / 1000
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        value_text = str(value).strip()
        if value_text.isdigit():
            return _format_news_time(int(value_text))
        value_text = value_text.replace("T", " ").replace("Z", "").replace("+08:00", "")
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                return datetime.strptime(value_text, fmt).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                continue
    except Exception:
        return ""
    return str(value)[:16]


def _news_time_key(item: dict) -> datetime:
    value = item.get("time", "")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            continue
    return datetime.min


def _standardize_news_item(
    source: str,
    title: str,
    content: str = "",
    time_value=None,
    url: str = "",
    item_id: str = "",
    category: str = "news",
) -> Optional[dict]:
    title = _strip_html(title)
    content = _strip_html(content)
    if not title or len(title) < 4:
        return None
    return {
        "id": str(item_id or url or f"{source}:{title[:40]}"),
        "title": title,
        "content": content[:300],
        "time": _format_news_time(time_value),
        "url": url or "",
        "source": source,
        "category": category,
    }


def _news_fingerprint(item: dict) -> str:
    title = item.get("title", "")
    title = re.sub(r"【.*?】|\[.*?\]|（.*?）|\(.*?\)", "", title)
    title = re.sub(r"[^\w\u4e00-\u9fff]+", "", title).lower()
    for prefix in ("快讯", "财联社", "华尔街见闻", "韭研公社", "证券时报", "金融时报", "FT中文网", "同花顺"):
        title = title.removeprefix(prefix)
    return title[:60] or item.get("url", "") or item.get("id", "")


def dedupe_news(news: list) -> list:
    """Deduplicate cross-source news while preserving source provenance."""
    merged: Dict[str, dict] = {}
    for item in news:
        if not item or not item.get("title"):
            continue
        key = _news_fingerprint(item)
        if not key:
            continue
        if key not in merged:
            normalized = item.copy()
            normalized["dedupe_key"] = key
            normalized["duplicate_sources"] = [item.get("source", "未知")]
            merged[key] = normalized
            continue

        existing = merged[key]
        source = item.get("source", "未知")
        if source not in existing["duplicate_sources"]:
            existing["duplicate_sources"].append(source)
        if len(item.get("content", "")) > len(existing.get("content", "")):
            existing["content"] = item.get("content", "")
        if not existing.get("url") and item.get("url"):
            existing["url"] = item.get("url", "")
        if _news_time_key(item) > _news_time_key(existing):
            existing["time"] = item.get("time", existing.get("time", ""))

    result = list(merged.values())
    result.sort(key=_news_time_key, reverse=True)
    return result


def build_news_source_meta(raw_news: list, deduped_news: list) -> dict:
    raw_source_counts: Dict[str, int] = {}
    kept_source_counts: Dict[str, int] = {}
    for item in raw_news:
        source = item.get("source", "未知")
        raw_source_counts[source] = raw_source_counts.get(source, 0) + 1
    for item in deduped_news:
        for source in item.get("duplicate_sources") or [item.get("source", "未知")]:
            kept_source_counts[source] = kept_source_counts.get(source, 0) + 1
    return {
        "source_count": len(raw_source_counts),
        "raw_count": len(raw_news),
        "deduped_count": len(deduped_news),
        "duplicate_count": max(0, len(raw_news) - len(deduped_news)),
        "raw_source_counts": raw_source_counts,
        "kept_source_counts": kept_source_counts,
        "sources": sorted(raw_source_counts.keys()),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _apply_source_floor(deduped_news: list, total_limit: int, floor_per_source: int = 5) -> list:
    """Keep the feed broad by reserving a few slots for every successful source."""
    selected = []
    selected_keys = set()
    sources = []
    for item in deduped_news:
        for source in item.get("duplicate_sources") or [item.get("source", "未知")]:
            if source not in sources:
                sources.append(source)

    for source in sources:
        added = 0
        for item in deduped_news:
            item_sources = item.get("duplicate_sources") or [item.get("source", "未知")]
            key = item.get("dedupe_key") or _news_fingerprint(item)
            if source in item_sources and key not in selected_keys:
                selected.append(item)
                selected_keys.add(key)
                added += 1
            if added >= floor_per_source:
                break

    for item in deduped_news:
        key = item.get("dedupe_key") or _news_fingerprint(item)
        if key not in selected_keys:
            selected.append(item)
            selected_keys.add(key)
        if len(selected) >= total_limit:
            break

    selected = selected[:total_limit]
    selected.sort(key=_news_time_key, reverse=True)
    return selected


def _parse_rss_feed(url: str, source: str, limit: int = 30) -> list:
    _rate_limit(re.sub(r"^https?://", "", url).split("/")[0])
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = resp.apparent_encoding or resp.encoding
        root = ET.fromstring(resp.text)
        news = []
        for item in root.findall(".//item")[:limit]:
            title = item.findtext("title") or ""
            content = item.findtext("description") or ""
            link = item.findtext("link") or ""
            pub_date = item.findtext("pubDate") or item.findtext("date") or ""
            normalized = _standardize_news_item(source, title, content, pub_date, link, category="rss")
            if normalized:
                news.append(normalized)
        return news
    except Exception as e:
        logger.warning(f"获取{source} RSS失败 {url}: {e}")
        return []


def _absolute_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    if href.startswith("//"):
        return f"https:{href}"
    if href.startswith("http"):
        return href
    base = base_url.rstrip("/")
    if href.startswith("/"):
        domain = re.match(r"^https?://[^/]+", base)
        return f"{domain.group(0)}{href}" if domain else href
    return f"{base}/{href}"


def _parse_anchor_news_page(url: str, source: str, limit: int = 30, category: str = "news") -> list:
    """Parse simple news listing pages from traditional finance media."""
    host = re.sub(r"^https?://", "", url).split("/")[0]
    _rate_limit(host)
    try:
        resp = requests.get(url, headers={"User-Agent": HEADERS["User-Agent"], "Referer": url}, timeout=12)
        resp.encoding = resp.apparent_encoding or resp.encoding
        text = resp.text
        matches = re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.S)
        news = []
        seen = set()
        for href, title_html in matches:
            title = _strip_html(title_html)
            if not title or len(title) < 6:
                continue
            if title in ("首页", "快讯", "新闻", "要闻", "金融", "证券", "公司", "公告", "更多"):
                continue
            if "${" in title or "javascript:" in href or href.startswith("#"):
                continue
            full_url = _absolute_url(href, url)
            key = f"{source}:{title}"
            if key in seen:
                continue
            seen.add(key)
            item_id = re.sub(r"\W+", "", full_url)[-48:]
            normalized = _standardize_news_item(source, title, "", None, full_url, item_id=item_id, category=category)
            if normalized:
                news.append(normalized)
            if len(news) >= limit:
                break
        return news
    except Exception as e:
        logger.warning(f"获取{source}页面新闻失败 {url}: {e}")
        return []

def fetch_news_cls(limit: int = 50) -> list:
    """从财联社获取财经新闻"""
    _rate_limit("www.cls.cn")
    url = "https://www.cls.cn/api/sw?app=CailianpressWeb&os=web&sv=7.7.5"
    try:
        resp = requests.get(url, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://www.cls.cn/",
        }, timeout=10)
        data = resp.json()
        items = data.get("data", {}).get("roll_data", [])
        news = []
        for item in items[:limit]:
            title = item.get("title", "")
            content = item.get("content", "") or item.get("brief", "")
            ctime = item.get("ctime", 0)
            time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
            news.append({
                "id": item.get("id", ""),
                "title": title,
                "content": content[:200],
                "time": time_str,
                "url": f"https://www.cls.cn/detail/{item.get('id', '')}",
                "source": "财联社",
            })
        return news
    except Exception as e:
        logger.warning(f"获取财联社新闻失败: {e}")
        return []


def fetch_news_sina() -> list:
    """从新浪财经获取新闻（备用）"""
    _rate_limit("finance.sina.com.cn")
    url = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=50&page=1"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()
        items = data.get("result", {}).get("data", [])
        news = []
        for item in items:
            ctime = int(item.get("ctime", 0))
            news.append({
                "id": item.get("oid", ""),
                "title": item.get("title", ""),
                "content": item.get("intro", "")[:200],
                "time": datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else "",
                "url": item.get("url", ""),
                "source": "新浪财经",
            })
        return news
    except Exception as e:
        logger.warning(f"获取新浪新闻失败: {e}")
        return []


def fetch_news_eastmoney(limit: int = 40) -> list:
    """从东方财富7x24快讯接口获取财经要闻。"""
    _rate_limit("np-listapi.eastmoney.com")
    url = "https://np-listapi.eastmoney.com/comm/web/getFastNewsList"
    params = {
        "client": "web",
        "biz": "web_724",
        "fastColumn": "102",
        "pageSize": limit,
        "sortEnd": "",
        "req_trace": str(uuid.uuid4()),
    }
    try:
        resp = requests.get(url, params=params, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://kuaixun.eastmoney.com/",
        }, timeout=10)
        data = resp.json()
        items = data.get("data", {}).get("fastNewsList", []) or []
        news = []
        for item in items[:limit]:
            normalized = _standardize_news_item(
                "东方财富",
                item.get("title", ""),
                item.get("summary", ""),
                item.get("showTime", ""),
                f"https://kuaixun.eastmoney.com/detail.html?id={item.get('code', '')}" if item.get("code") else "",
                item_id=item.get("code", ""),
                category="fast_news",
            )
            if normalized:
                news.append(normalized)
        return news
    except Exception as e:
        logger.warning(f"获取东方财富新闻失败: {e}")
        return []


def fetch_news_stcn(limit: int = 30) -> list:
    """从证券时报页面抓取快讯、要闻、金融、公司等传统媒体新闻。"""
    urls = [
        "https://www.stcn.com/article/list/kx.html",
        "https://www.stcn.com/article/list/xw.html",
        "https://www.stcn.com/article/list/yw.html",
        "https://www.stcn.com/article/list/finance.html",
        "https://www.stcn.com/article/list/gs.html",
        "https://www.stcn.com/article/index.html",
    ]
    news = []
    for url in urls:
        _rate_limit("www.stcn.com")
        try:
            resp = requests.get(url, headers={
                "User-Agent": HEADERS["User-Agent"],
                "Referer": "https://www.stcn.com/",
            }, timeout=10)
            resp.encoding = resp.apparent_encoding or resp.encoding
            text = resp.text
            matches = re.findall(r'<a[^>]+href="([^"]*?/article/detail/[^"]+)"[^>]*>(.*?)</a>', text, re.S)
            for href, title_html in matches:
                title = _strip_html(title_html)
                if not title or title in ("首页", "快讯", "新闻"):
                    continue
                href = href if href.startswith("http") else f"https://www.stcn.com{href}"
                normalized = _standardize_news_item("证券时报", title, "", None, href, category="news")
                if normalized:
                    news.append(normalized)
                if len(news) >= limit:
                    return dedupe_news(news)[:limit]
        except Exception as e:
            logger.warning(f"获取证券时报新闻失败 {url}: {e}")
    return dedupe_news(news)[:limit]


def fetch_news_financial_times_cn(limit: int = 35) -> list:
    """抓取国内《金融时报》主办的中国金融新闻网。"""
    urls = [
        "https://www.financialnews.com.cn/",
        "https://www.financialnews.com.cn/node_3002.html",
        "https://www.financialnews.com.cn/node_3003.html",
        "https://www.financialnews.com.cn/node_3004.html",
    ]
    news = []
    for url in urls:
        news.extend(_parse_anchor_news_page(url, "金融时报", limit=limit, category="traditional_media"))
        if len(news) >= limit:
            break
    return dedupe_news(news)[:limit]


def fetch_news_ftchinese(limit: int = 30) -> list:
    """抓取 FT 中文网 RSS，补充全球宏观和海外市场视角。"""
    urls = [
        "https://www.ftchinese.com/rss/news",
        "https://www.ftchinese.com/rss/feed",
    ]
    news = []
    for url in urls:
        news.extend(_parse_rss_feed(url, "FT中文网", limit=limit))
    return dedupe_news(news)[:limit]


def fetch_news_cs_cnstock(limit: int = 35) -> list:
    """抓取中国证券报/上海证券报等传统证券媒体。"""
    sources = [
        ("中国证券报", "https://www.cs.com.cn/sylm/jsbd/list.html"),
        ("中国证券报", "https://www.cs.com.cn/xwzx/hg/list.html"),
        ("中国证券报", "https://www.cs.com.cn/ssgs/gsxw/list.html"),
        ("上海证券报", "https://www.cnstock.com/"),
        ("上海证券报", "https://www.cnstock.com/company"),
        ("上海证券报", "https://www.cnstock.com/news"),
    ]
    news = []
    per_source_limit = max(8, limit // 2)
    for source, url in sources:
        news.extend(_parse_anchor_news_page(url, source, limit=per_source_limit, category="traditional_media"))
    return dedupe_news(news)[:limit]


def fetch_news_ths_market(limit: int = 35) -> list:
    """抓取同花顺公开财经/股票频道新闻。"""
    urls = [
        "https://news.10jqka.com.cn/",
        "https://stock.10jqka.com.cn/",
    ]
    news = []
    for url in urls:
        news.extend(_parse_anchor_news_page(url, "同花顺", limit=limit, category="ths_market"))
    return dedupe_news(news)[:limit]


def fetch_news_ths_watchlist(codes: list = None, limit_per_code: int = 8, total_limit: int = 80) -> list:
    """按自选股代码抓取同花顺个股新闻公告页。

    真实同花顺 App 自选推送通常依赖登录态和设备推送通道；这里使用公开个股新闻公告页作为可运行兜底。
    """
    codes = [str(code).strip() for code in (codes or []) if re.fullmatch(r"\d{6}", str(code).strip())]
    news = []
    for code in codes[:30]:
        url = f"https://stockpage.10jqka.com.cn/{code}/news/"
        rows = _parse_anchor_news_page(url, "同花顺自选", limit=limit_per_code, category="ths_watchlist")
        for row in rows:
            row["related_symbols"] = sorted(set((row.get("related_symbols") or []) + [code]))
            row["title"] = row["title"] if code in row["title"] else f"{code} {row['title']}"
            row["watchlist_hit"] = True
        news.extend(rows)
        if len(news) >= total_limit:
            break
    return dedupe_news(news)[:total_limit]


def fetch_news_wscn(limit: int = 40) -> list:
    """从华尔街见闻实时快讯接口获取宏观/市场新闻。"""
    _rate_limit("api-one-wscn.awtmt.com")
    url = "https://api-one-wscn.awtmt.com/apiv1/content/lives"
    params = {"channel": "global-channel", "limit": limit}
    try:
        resp = requests.get(url, params=params, headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://wallstreetcn.com/",
        }, timeout=10)
        data = resp.json()
        items = data.get("data", {}).get("items", [])
        news = []
        for item in items[:limit]:
            resource = item.get("resource") or item
            title = resource.get("title") or resource.get("content_text") or resource.get("content") or ""
            content = resource.get("content_text") or resource.get("content") or title
            display_time = resource.get("display_time") or resource.get("created_at") or item.get("display_time")
            uri = resource.get("uri") or resource.get("id") or ""
            url_value = uri if isinstance(uri, str) and uri.startswith("http") else (
                f"https://wallstreetcn.com/livenews/{uri}" if uri else ""
            )
            normalized = _standardize_news_item(
                "华尔街见闻",
                title,
                content,
                display_time,
                url_value,
                item_id=uri,
                category="macro",
            )
            if normalized:
                news.append(normalized)
        return news
    except Exception as e:
        logger.warning(f"获取华尔街见闻新闻失败: {e}")
        return []


def fetch_news_jiuyangongshe(limit: int = 30) -> list:
    """从韭研公社快讯接口尝试获取题材/个股情报。"""
    endpoints = [
        "https://app.jiuyangongshe.com/jystock-app/api/v1/action/kuaixun",
        "https://www.jiuyangongshe.com/jystock-app/api/v1/action/kuaixun",
    ]
    for url in endpoints:
        _rate_limit(re.sub(r"^https?://", "", url).split("/")[0])
        try:
            resp = requests.get(url, params={"limit": limit, "page": 1}, headers={
                "User-Agent": HEADERS["User-Agent"],
                "Referer": "https://www.jiuyangongshe.com/",
            }, timeout=10)
            data = resp.json()
            container = data.get("data", data)
            if isinstance(container, dict):
                items = (
                    container.get("list")
                    or container.get("items")
                    or container.get("records")
                    or container.get("data")
                    or []
                )
            else:
                items = container if isinstance(container, list) else []
            news = []
            for item in items[:limit]:
                title = item.get("title") or item.get("content") or item.get("summary") or ""
                content = item.get("content") or item.get("summary") or title
                time_value = item.get("time") or item.get("created_at") or item.get("create_time") or item.get("ctime")
                item_id = item.get("id") or item.get("article_id") or ""
                url_value = item.get("url") or (f"https://www.jiuyangongshe.com/action/{item_id}" if item_id else "")
                normalized = _standardize_news_item(
                    "韭研公社", title, content, time_value, url_value, item_id=item_id, category="theme"
                )
                if normalized:
                    news.append(normalized)
            if news:
                return news
        except Exception as e:
            logger.debug(f"韭研公社接口不可用，改用页面兜底 {url}: {e}")
    try:
        resp = requests.get("https://www.jiuyangongshe.com/index.html", headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": "https://www.jiuyangongshe.com/",
        }, timeout=10)
        resp.encoding = resp.apparent_encoding or resp.encoding
        text = resp.text
        news = []
        pattern = re.compile(
            r'article_id:"(?P<id>[^"]+)".{0,1200}?title:"(?P<title>.*?)".{0,1600}?'
            r'content:"(?P<content>.*?)".{0,1800}?create_time:"(?P<time>[^"]+)"',
            re.S,
        )
        for match in pattern.finditer(text):
            content = match.group("content")
            if "\\u" in content:
                content = content.encode("utf-8").decode("unicode_escape", errors="ignore")
            content = content.replace("\\u002F", "/")
            title = match.group("title")
            if "\\u" in title:
                title = title.encode("utf-8").decode("unicode_escape", errors="ignore")
            title = title.replace("\\u002F", "/")
            normalized = _standardize_news_item(
                "韭研公社",
                title,
                content,
                match.group("time"),
                f"https://www.jiuyangongshe.com/h5/article/{match.group('id')}",
                item_id=match.group("id"),
                category="theme",
            )
            if normalized:
                news.append(normalized)
            if len(news) >= limit:
                break
        return news
    except Exception as e:
        logger.warning(f"解析韭研公社页面失败: {e}")
        return []


def fetch_news_multi_source(limit_per_source: int = 35, total_limit: int = 220, watchlist_codes: list = None) -> dict:
    """Fetch broad financial news from multiple sources and deduplicate."""
    fetchers = [
        fetch_news_cls,
        fetch_news_sina,
        fetch_news_eastmoney,
        fetch_news_stcn,
        fetch_news_financial_times_cn,
        fetch_news_ftchinese,
        fetch_news_cs_cnstock,
        fetch_news_ths_market,
        fetch_news_wscn,
        fetch_news_jiuyangongshe,
    ]
    raw_news = []
    for fetcher in fetchers:
        try:
            if fetcher is fetch_news_sina:
                items = fetcher()
            else:
                items = fetcher(limit_per_source)
            raw_news.extend(items or [])
        except Exception as e:
            logger.warning(f"新闻源{fetcher.__name__}聚合失败: {e}")

    if watchlist_codes:
        try:
            raw_news.extend(fetch_news_ths_watchlist(watchlist_codes, limit_per_code=8, total_limit=100))
        except Exception as e:
            logger.warning(f"同花顺自选新闻聚合失败: {e}")

    deduped_all = dedupe_news(raw_news)
    deduped = _apply_source_floor(deduped_all, total_limit)
    return {
        "news": deduped,
        "raw_news": raw_news,
        "meta": build_news_source_meta(raw_news, deduped),
    }


def _safe_float(value, default=0.0):
    try:
        num = float(value)
        if math.isnan(num) or math.isinf(num):
            return default
        return num
    except (TypeError, ValueError):
        return default


# ==================== 分时数据 ====================

def fetch_intraday_minutes(code: str, allow_fallback: bool = False) -> list:
    """获取当日分时数据（分钟级）"""
    _rate_limit("push2.eastmoney.com")
    secid = _get_secid(code)
    url = f"https://push2.eastmoney.com/api/qt/stock/trends2/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
        "iscr": 0,
        "ndays": 1,
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=4)
        data = resp.json()
        trends = data.get("data", {}).get("trends", [])
        pre_close = data.get("data", {}).get("preClose", 0)
        minutes = []
        for trend in trends:
            parts = trend.split(",")
            if len(parts) >= 8:
                price = float(parts[1])
                volume = int(float(parts[5]))
                amount = float(parts[6])
                avg_price = float(parts[7])
                minutes.append({
                    "time": parts[0],
                    "price": price,
                    "avg_price": avg_price,
                    "volume": volume,
                    "amount": amount,
                    "pct_change": round((price - pre_close) / pre_close * 100, 2) if pre_close else 0,
                    "source": "eastmoney_trends",
                })
        if not minutes:
            return read_intraday_cache(code)
        if minutes:
            state_store.set_intraday(code, minutes)
            _write_intraday_cache(code, minutes)
        return minutes
    except Exception as e:
        logger.warning(f"获取分时数据失败 {code}: {e}")
        return read_intraday_cache(code)


# ==================== 多周期K线 ====================

def fetch_kline(code: str, period: int = 101, days: int = 120, allow_fallback: bool = True, prefer_cache: bool = True, force_refresh: bool = False) -> Optional[pd.DataFrame]:
    """获取多周期K线数据
    period: 1=1分, 5=5分, 15=15分, 30=30分, 60=60分, 101=日, 102=周
    """
    if prefer_cache and not force_refresh:
        cached = _read_kline_cache(code, period, days)
        if cached is not None:
            return cached
    if int(period) == 101:
        try:
            source_frames = {
                "eastmoney": fetch_kline_eastmoney(code, period=101, days=days),
                "sina": fetch_kline_sina(code, days=days),
                "ths": fetch_kline_ths_daily(code, days=days),
            }
            trusted_df, candidate_df, report = _validate_historical_kline_sources(code, 101, days, source_frames)
            _write_validation_report(code, "kline_101", report)
            if candidate_df is not None and not candidate_df.empty:
                _write_kline_candidate_cache(code, 101, candidate_df, report)
            if trusted_df is not None and not trusted_df.empty:
                state_store.set_kline(code, 101, trusted_df)
                state_store.set_daily_bars(code, trusted_df)
                _write_kline_cache(code, 101, trusted_df)
                return trusted_df
            if candidate_df is not None and not candidate_df.empty:
                _write_kline_cache_accepting_single_source(code, 101, candidate_df, "fallback_public_source_after_validation")
                state_store.set_kline(code, 101, candidate_df)
                state_store.set_daily_bars(code, candidate_df)
                return candidate_df
            cached = _read_kline_cache(code, period, days)
            if cached is not None:
                return cached
            return None
        except Exception as e:
            logger.warning(f"历史K线可信校验失败 {code}: {e}")
            cached = _read_kline_cache(code, period, days)
            if cached is not None:
                return cached
    _rate_limit("push2his.eastmoney.com")
    secid = _get_secid(code)
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": secid,
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": period,
        "fqt": 1,
        "lmt": days,
        "end": "20500101",
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=15)
        data = resp.json()
        klines = data.get("data", {}).get("klines", [])
        if not klines:
            cached = _read_kline_cache(code, period, days)
            if cached is not None:
                return cached
            return None

        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) >= 11:
                rows.append({
                    "date": parts[0],
                    "open": float(parts[1]),
                    "close": float(parts[2]),
                    "high": float(parts[3]),
                    "low": float(parts[4]),
                    "volume": int(float(parts[5])),
                    "amount": float(parts[6]),
                    "amplitude": float(parts[7]),
                    "pct_change": float(parts[8]),
                    "change": float(parts[9]),
                    "turnover_rate": float(parts[10]),
                })

        df = pd.DataFrame(rows)
        if not df.empty:
            df["source"] = "eastmoney_kline"
            report = _validate_latest_kline_with_snapshots(code, df, period)
            df["validation_status"] = report.get("status", "single_source")
            df["validated_sources"] = ",".join(report.get("sources", []))
            df["validation_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _write_validation_report(code, f"kline_{period}", report)
        state_store.set_kline(code, period, df)
        if period == 101:
            state_store.set_daily_bars(code, df)
        _write_kline_cache(code, period, df)
        return df
    except Exception as e:
        logger.warning(f"获取K线失败 {code} period={period}: {e}")
        cached = _read_kline_cache(code, period, days)
        if cached is not None:
            return cached
        return None


# ==================== 筹码分布（近似计算） ====================

def fetch_chip_distribution(code: str) -> dict:
    """基于120日K线数据近似计算筹码分布"""
    # 先确保有足够日线数据
    df = state_store.get_daily_bars(code)
    if df is None or len(df) < 30:
        df = fetch_kline(code, period=101, days=120, allow_fallback=False)

    if df is None or len(df) < 10:
        return read_chip_cache(code) or {}

    try:
        # 用价格和成交量构建筹码分布
        closes = df["close"].values
        volumes = df["volume"].values
        current_price = closes[-1]

        # 价格区间分为20档
        price_min = closes.min()
        price_max = closes.max()
        if price_max == price_min:
            return {"bins": [], "profit_ratio": 100, "current_price": current_price}

        bin_count = 20
        bin_width = (price_max - price_min) / bin_count
        bins = [0.0] * bin_count
        total_volume = 0

        # 按时间衰减加权（越近权重越高）
        for i in range(len(closes)):
            weight = 0.5 + 0.5 * (i / len(closes))  # 0.5~1.0
            vol = volumes[i] * weight
            price = closes[i]
            bin_idx = min(int((price - price_min) / bin_width), bin_count - 1)
            bins[bin_idx] += vol
            total_volume += vol

        # 归一化为百分比
        if total_volume > 0:
            bins = [round(b / total_volume * 100, 2) for b in bins]

        # 计算获利比例
        profit_vol = sum(volumes[i] for i in range(len(closes)) if closes[i] <= current_price)
        profit_ratio = round(profit_vol / sum(volumes) * 100, 1) if sum(volumes) > 0 else 50

        result = {
            "bins": bins,
            "prices": [round(price_min + (i + 0.5) * bin_width, 2) for i in range(bin_count)],
            "profit_ratio": profit_ratio,
            "current_price": current_price,
            "avg_cost": round(sum(closes * volumes) / sum(volumes), 2) if sum(volumes) > 0 else current_price,
            "price_range": [round(price_min, 2), round(price_max, 2)],
        }
        state_store.set_chip_distribution(code, result)
        _write_chip_cache(code, result)
        return result
    except Exception as e:
        logger.warning(f"计算筹码分布失败 {code}: {e}")
        return {}


# ==================== 板块数据 ====================

def _sector_fs(sector_type: str = "industry") -> str:
    """东方财富板块过滤条件。"""
    return "m:90+t:3" if sector_type == "concept" else "m:90+t:2"


def fetch_sector_list(sector_type: str = "industry") -> list:
    """获取行业/概念板块列表（东方财富）"""
    _rate_limit("push2.eastmoney.com")
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": 300,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",  # 按涨跌幅排序
        "fs": _sector_fs(sector_type),
        "fields": "f1,f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141",
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        diffs = data.get("data", {}).get("diff", [])
        sectors = []
        for item in diffs:
            sectors.append({
                "code": item.get("f12", ""),
                "name": item.get("f14", ""),
                "price": item.get("f2", 0),
                "pct_change": item.get("f3", 0),
                "change": item.get("f4", 0),
                "advance_count": item.get("f104", 0),
                "decline_count": item.get("f105", 0),
                "leader_code": item.get("f140", ""),
                "leader_name": item.get("f141", ""),
                "leader_pct_change": item.get("f136", 0),
                "sector_type": sector_type,
            })
        if sector_type == "industry":
            state_store.set_sector_list(sectors)
        return sectors
    except Exception as e:
        logger.warning(f"获取板块列表失败: {e}")
        return []


def fetch_sector_detail(sector_code: str) -> list:
    """获取板块成分股列表"""
    _rate_limit("push2.eastmoney.com")
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": 50,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": f"b:{sector_code}",
        "fields": "f2,f3,f4,f5,f6,f7,f8,f10,f12,f14,f15,f16,f17,f18",
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        diffs = data.get("data", {}).get("diff", [])
        stocks = []
        for item in diffs:
            stocks.append({
                "code": item.get("f12", ""),
                "name": item.get("f14", ""),
                "price": item.get("f2", 0),
                "pct_change": item.get("f3", 0),
                "change": item.get("f4", 0),
                "volume": item.get("f5", 0),
                "amount": item.get("f6", 0),
                "amplitude": item.get("f7", 0),
                "turnover_rate": item.get("f8", 0),
                "volume_ratio": item.get("f10", 0),
                "high": item.get("f15", 0),
                "low": item.get("f16", 0),
                "open": item.get("f17", 0),
                "pre_close": item.get("f18", 0),
            })
        state_store.set_sector_detail(sector_code, {"stocks": stocks})
        return stocks
    except Exception as e:
        logger.warning(f"获取板块详情失败 {sector_code}: {e}")
        return []


def fetch_sector_money_flow(sector_type: str = "industry") -> list:
    """获取行业/概念板块资金流向排名"""
    _rate_limit("push2.eastmoney.com")
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1,
        "pz": 300,
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f62",  # 按主力净流入排序
        "fs": _sector_fs(sector_type),
        "fields": "f2,f3,f12,f14,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87",
    }
    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = resp.json()
        diffs = data.get("data", {}).get("diff", [])
        flows = []
        for item in diffs:
            flows.append({
                "code": item.get("f12", ""),
                "name": item.get("f14", ""),
                "pct_change": item.get("f3", 0),
                "main_net_inflow": item.get("f62", 0),
                "main_net_pct": item.get("f184", 0),
                "super_large_inflow": item.get("f66", 0),
                "super_large_pct": item.get("f69", 0),
                "large_inflow": item.get("f72", 0),
                "large_pct": item.get("f75", 0),
                "medium_inflow": item.get("f78", 0),
                "medium_pct": item.get("f81", 0),
                "small_inflow": item.get("f84", 0),
                "small_pct": item.get("f87", 0),
                "sector_type": sector_type,
            })
        if sector_type == "industry":
            state_store.set_sector_money_flow(flows)
        return flows
    except Exception as e:
        logger.warning(f"获取板块资金流向失败: {e}")
        return []


# ==================== 初始化 ====================

def init_stock_data():
    """初始化股票数据：获取股票列表 + 日线数据"""
    logger.info("开始初始化股票数据...")
    stocks = fetch_all_stocks_sina()
    logger.info(f"股票列表获取完成: {len(stocks)} 只")

    # 按成交额排序，取前500只获取日线
    sorted_stocks = sorted(stocks, key=lambda x: x.get("amount", 0), reverse=True)
    top_codes = [s["code"] for s in sorted_stocks[:500]]
    logger.info(f"开始获取前500只股票日线数据...")
    fetch_daily_bars_batch(top_codes, days=60)
    logger.info("股票数据初始化完成")
