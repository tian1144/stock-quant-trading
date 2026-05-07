"""
Market data ingestion hub.

This module coordinates stock-universe sync, verified realtime snapshots,
historical K-line backfill, intraday refresh priorities, and coverage reports.
It is intentionally conservative: official caches should only be written by
the existing data_fetcher verification paths. The hub mostly schedules work and
summarizes what has already been verified.
"""
import os
import time
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional

from loguru import logger

from app.services import data_fetcher, state_store, disclosure_service


KLINE_PERIODS = {
    101: "daily",
    102: "weekly",
    103: "monthly",
}

DATA_TYPES = {
    "daily_kline": "日K",
    "weekly_kline": "周K",
    "monthly_kline": "月K",
    "realtime": "实时",
    "intraday": "分时",
    "money_flow": "资金流",
    "orderbook": "盘口",
    "finance": "财务",
}
DATA_TYPES["disclosure_risk"] = "公告财报风险"


_hub_state = {
    "started_at": None,
    "updated_at": None,
    "mode": "idle",
    "message": "行情数据引入中枢待启动",
    "jobs": {
        "universe_sync": {"status": "idle", "message": "等待同步"},
        "kline_backfill": {"status": "idle", "message": "等待补库"},
        "realtime_snapshots": {"status": "idle", "message": "等待交易时段"},
        "intraday_refresh": {"status": "idle", "message": "等待重点股票队列"},
    },
    "priority_queue": {"first": [], "second": [], "third_sample": []},
    "last_error": "",
}


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_code(code) -> str:
    return "".join(ch for ch in str(code or "") if ch.isalnum())


def _file_mtime(path: str) -> Optional[str]:
    try:
        if os.path.exists(path):
            return datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    return None


def _count_files(root: str, suffix: str = "") -> int:
    if not os.path.isdir(root):
        return 0
    count = 0
    for _, _, files in os.walk(root):
        for name in files:
            if not suffix or name.endswith(suffix):
                count += 1
    return count


def _count_latest_realtime_with_any_field(codes: Iterable[str], fields: Iterable[str]) -> int:
    wanted = tuple(fields or ())
    count = 0
    for code in codes or []:
        payload = data_fetcher.read_realtime_cache(code) or {}
        if any(payload.get(field) not in (None, "", 0) for field in wanted):
            count += 1
    return count


def _count_code_files(codes: Iterable[str], root: str, suffix: str, dated: bool = False) -> int:
    if not os.path.isdir(root):
        return 0
    count = 0
    for code in codes or []:
        safe = _safe_code(code)
        if dated:
            if _latest_dated_file(root, safe, suffix):
                count += 1
        elif os.path.exists(os.path.join(root, f"{safe}{suffix}")):
            count += 1
    return count


def _exists(path: str) -> bool:
    return bool(path and os.path.exists(path))


def _kline_path(code: str, period: int) -> str:
    return os.path.join(data_fetcher.KLINE_CACHE_DIR, f"period_{int(period)}", f"{_safe_code(code)}.csv")


def _kline_candidate_root(period: int) -> str:
    return os.path.join(data_fetcher.KLINE_CACHE_DIR, "candidates", f"period_{int(period)}")


def _latest_dated_file(root: str, code: str, suffix: str) -> Optional[str]:
    safe = _safe_code(code)
    if not os.path.isdir(root):
        return None
    paths = []
    try:
        for date_name in os.listdir(root):
            path = os.path.join(root, date_name, f"{safe}{suffix}")
            if os.path.exists(path):
                paths.append(path)
    except Exception:
        return None
    return sorted(paths)[-1] if paths else None


def _single_status(available: bool, source: str = "", validation_status: str = "", checked_at: str = "", note: str = "") -> dict:
    return {
        "available": bool(available),
        "source": source or ("cache_file" if available else "missing"),
        "validation_status": validation_status or ("verified_or_cached" if available else "missing"),
        "checked_at": checked_at or "",
        "note": note or "",
    }


def start_hub() -> dict:
    _hub_state["started_at"] = _hub_state["started_at"] or _now_text()
    _hub_state["updated_at"] = _now_text()
    _hub_state["mode"] = "running"
    _hub_state["message"] = "行情数据引入中枢已接管调度状态"
    return get_hub_status()


def get_hub_status() -> dict:
    state = {
        **_hub_state,
        "updated_at": _now_text(),
        "cache_root": data_fetcher.market_cache_root(),
        "rules": {
            "universe_sync": "每日开盘前/收盘后同步股票池、新股、退市、更名、ST、停复牌",
            "kline_backfill": "日K/周K/月K分批补库，正式缓存只写至少双源一致数据；单源进入候选缓存",
            "realtime": "交易日09:25-15:00全市场批次1秒三源快照，双源一致写正式缓存，冲突写校验报告",
            "intraday": "重点股票15-30秒分时补齐，全市场1-3分钟低频轮询",
            "priority": "自选/持仓/AI推荐/短线震荡池优先，其次热门板块与成交额/涨跌幅前列，最后全市场低频补齐",
        },
    }
    return state


def build_priority_queues(
    watchlist_codes: Optional[Iterable[str]] = None,
    volatile_codes: Optional[Iterable[str]] = None,
    stocks: Optional[List[dict]] = None,
) -> dict:
    watchlist = [_safe_code(c) for c in (watchlist_codes or []) if _safe_code(c)]
    positions = [_safe_code(c) for c in state_store.get_positions().keys()]
    ai_codes = [_safe_code(item.get("code")) for item in (state_store.get_ai_recommendations().get("recommendations") or [])]
    volatile = [_safe_code(c) for c in (volatile_codes or []) if _safe_code(c)]

    def unique(rows):
        seen, out = set(), []
        for code in rows:
            if code and code not in seen:
                out.append(code)
                seen.add(code)
        return out

    all_stocks = stocks if stocks is not None else list(state_store.get_stock_universe().values())
    ranked = sorted(
        [s for s in (all_stocks or []) if s.get("code")],
        key=lambda x: (abs(float(x.get("pct_change") or 0)), float(x.get("amount") or 0)),
        reverse=True,
    )
    second = unique([_safe_code(s.get("code")) for s in ranked[:300]])
    first = unique(watchlist + positions + ai_codes + volatile)
    third = unique([_safe_code(s.get("code")) for s in (all_stocks or [])])

    queues = {
        "first": first,
        "second": [c for c in second if c not in set(first)],
        "third_sample": [c for c in third if c not in set(first)],
        "counts": {"first": len(first), "second": len(second), "third": len(third)},
        "updated_at": _now_text(),
    }
    _hub_state["priority_queue"] = queues
    _hub_state["updated_at"] = _now_text()
    return queues


def sync_universe(fetcher: Callable[[], list]) -> dict:
    job = _hub_state["jobs"]["universe_sync"]
    job.update({"status": "running", "started_at": _now_text(), "message": "正在同步股票主数据"})
    try:
        stocks = fetcher()
        changes = data_fetcher.read_stock_universe_changes()
        job.update({
            "status": "ok",
            "finished_at": _now_text(),
            "total": len(stocks or []),
            "changes": changes.get("summary", {}),
            "message": "股票主数据同步完成",
        })
        return {"status": "ok", "total": len(stocks or []), "changes": changes}
    except Exception as exc:
        job.update({"status": "error", "finished_at": _now_text(), "message": str(exc)})
        _hub_state["last_error"] = str(exc)
        logger.warning(f"market data hub universe sync failed: {exc}")
        return {"status": "error", "message": str(exc)}


def refresh_realtime(codes: Iterable[str], batch_size: int = 50) -> dict:
    clean_codes = [_safe_code(c) for c in codes if _safe_code(c)]
    job = _hub_state["jobs"]["realtime_snapshots"]
    job.update({"status": "running", "started_at": _now_text(), "total": len(clean_codes), "message": "正在三源校验实时快照"})
    ok = 0
    for i in range(0, len(clean_codes), max(int(batch_size), 1)):
        batch = clean_codes[i:i + batch_size]
        result = data_fetcher.fetch_verified_realtime_batch(batch, require_verified_for_cache=True)
        ok += len([v for v in result.values() if v])
    job.update({"status": "ok", "finished_at": _now_text(), "success": ok, "message": "实时快照刷新完成"})
    return {"status": "ok", "total": len(clean_codes), "success": ok}


def refresh_intraday_priority(first_limit: int = 120, second_limit: int = 240) -> dict:
    queues = _hub_state.get("priority_queue") or {}
    first = list(queues.get("first") or [])[:first_limit]
    second = list(queues.get("second") or [])[:second_limit]
    codes = first + [c for c in second if c not in set(first)]
    job = _hub_state["jobs"]["intraday_refresh"]
    job.update({"status": "running", "started_at": _now_text(), "total": len(codes), "message": "正在刷新重点分时队列"})
    ok = 0
    for code in codes:
        minutes = data_fetcher.fetch_intraday_minutes(code, allow_fallback=False)
        ok += 1 if minutes else 0
    job.update({"status": "ok", "finished_at": _now_text(), "success": ok, "message": "重点分时队列刷新完成"})
    return {"status": "ok", "total": len(codes), "success": ok}


def backfill_kline_batch(codes: Iterable[str], periods: Iterable[int] = (101, 102, 103), days: int = 1000) -> dict:
    clean_codes = [_safe_code(c) for c in codes if _safe_code(c)]
    clean_periods = [int(p) for p in periods if str(p).strip()]
    job = _hub_state["jobs"]["kline_backfill"]
    job.update({"status": "running", "started_at": _now_text(), "total": len(clean_codes), "periods": clean_periods, "message": "正在补齐历史K线"})
    success, failed = 0, 0
    for code in clean_codes:
        stock_ok = False
        for period in clean_periods:
            df = data_fetcher.fetch_kline(code, period=period, days=days, allow_fallback=False, prefer_cache=False, force_refresh=True)
            stock_ok = stock_ok or (df is not None and not df.empty)
        if stock_ok:
            success += 1
        else:
            failed += 1
    job.update({"status": "ok", "finished_at": _now_text(), "success": success, "failed": failed, "message": "历史K线补库批次完成"})
    return {"status": "ok", "total": len(clean_codes), "success": success, "failed": failed}


def get_stock_data_availability(code: str) -> dict:
    safe = _safe_code(code)
    realtime = data_fetcher.read_realtime_cache(safe) or state_store.get_realtime(safe) or {}
    k101 = _kline_path(safe, 101)
    k102 = _kline_path(safe, 102)
    k103 = _kline_path(safe, 103)
    intraday_path = _latest_dated_file(data_fetcher.INTRADAY_CACHE_DIR, safe, ".csv")
    realtime_path = _latest_dated_file(data_fetcher.REALTIME_CACHE_DIR, safe, ".json")
    money_path = os.path.join(data_fetcher.MONEY_FLOW_CACHE_DIR, f"{safe}.json")
    chip_path = os.path.join(data_fetcher.CHIP_CACHE_DIR, f"{safe}.json")

    kline_report = data_fetcher._read_json_cache(data_fetcher._validation_report_path(safe, "kline_101")) or {}
    realtime_report = data_fetcher._read_json_cache(data_fetcher._validation_report_path(safe, "realtime")) or {}

    daily_available = _exists(k101)
    candidate_available = _count_files(_kline_candidate_root(101), ".csv") > 0
    return {
        "code": safe,
        "updated_at": _now_text(),
        "items": {
            "daily_kline": _single_status(daily_available, "cache_file" if daily_available else "missing", kline_report.get("status") or ("verified" if daily_available else "missing"), _file_mtime(k101), "正式缓存只写入至少双源一致数据" if daily_available else ("存在候选缓存" if candidate_available else "缺少已验证日K")),
            "weekly_kline": _single_status(_exists(k102), "cache_file" if _exists(k102) else "missing", "verified_or_cached" if _exists(k102) else "missing", _file_mtime(k102)),
            "monthly_kline": _single_status(_exists(k103), "cache_file" if _exists(k103) else "missing", "verified_or_cached" if _exists(k103) else "missing", _file_mtime(k103)),
            "realtime": _single_status(bool(realtime), realtime.get("source") or ("cache_file" if realtime_path else "missing"), realtime.get("validation_status") or realtime_report.get("status") or ("verified" if realtime else "missing"), realtime.get("validation_checked_at") or _file_mtime(realtime_path), f"accepted={realtime.get('accepted_sources', [])}" if realtime else ""),
            "intraday": _single_status(bool(intraday_path or state_store.get_intraday(safe)), "cache_file" if intraday_path else "memory_or_missing", "single_source", _file_mtime(intraday_path), "分时目前以东方财富趋势数据为主，重点队列高频刷新"),
            "money_flow": _single_status(_exists(money_path), "eastmoney_money_flow" if _exists(money_path) else "missing", "single_source", _file_mtime(money_path)),
            "orderbook": _single_status(False, "missing", "missing", "", "真实五档/逐笔盘口尚未接入，前端只允许标注推断口径"),
            "finance": _single_status(False, "missing", "missing", "", "财务数据源待接入"),
            "chips": _single_status(_exists(chip_path), "derived_from_verified_kline" if _exists(chip_path) else "missing", "derived", _file_mtime(chip_path)),
        },
    }


def get_stock_data_availability(code: str) -> dict:
    safe = _safe_code(code)
    realtime = data_fetcher.read_realtime_cache(safe) or state_store.get_realtime(safe) or {}
    k101 = _kline_path(safe, 101)
    k102 = _kline_path(safe, 102)
    k103 = _kline_path(safe, 103)
    intraday_path = _latest_dated_file(data_fetcher.INTRADAY_CACHE_DIR, safe, ".csv")
    realtime_path = _latest_dated_file(data_fetcher.REALTIME_CACHE_DIR, safe, ".json")
    money_path = os.path.join(data_fetcher.MONEY_FLOW_CACHE_DIR, f"{safe}.json")
    chip_path = os.path.join(data_fetcher.CHIP_CACHE_DIR, f"{safe}.json")

    kline_report = data_fetcher._read_json_cache(data_fetcher._validation_report_path(safe, "kline_101")) or {}
    realtime_report = data_fetcher._read_json_cache(data_fetcher._validation_report_path(safe, "realtime")) or {}
    daily_available = _exists(k101)
    candidate_available = _count_files(_kline_candidate_root(101), ".csv") > 0
    has_orderbook = any(
        realtime.get(field) not in (None, "", 0)
        for field in ("bid_price1", "ask_price1", "bid_volume1", "ask_volume1")
    )
    has_finance_snapshot = any(
        realtime.get(field) not in (None, "", 0)
        for field in ("pe_ttm", "pe_dynamic", "pe_static", "pb", "market_cap", "float_market_cap")
    )
    disclosure = disclosure_service.get_disclosure_risk_profile(safe)

    return {
        "code": safe,
        "updated_at": _now_text(),
        "items": {
            "daily_kline": _single_status(
                daily_available,
                "cache_file" if daily_available else "missing",
                kline_report.get("status") or ("verified" if daily_available else "missing"),
                _file_mtime(k101),
                "official cache requires at least two consistent sources" if daily_available else (
                    "candidate cache exists" if candidate_available else "missing verified daily kline"
                ),
            ),
            "weekly_kline": _single_status(_exists(k102), "cache_file" if _exists(k102) else "missing", "verified_or_cached" if _exists(k102) else "missing", _file_mtime(k102)),
            "monthly_kline": _single_status(_exists(k103), "cache_file" if _exists(k103) else "missing", "verified_or_cached" if _exists(k103) else "missing", _file_mtime(k103)),
            "realtime": _single_status(bool(realtime), realtime.get("source") or ("cache_file" if realtime_path else "missing"), realtime.get("validation_status") or realtime_report.get("status") or ("verified" if realtime else "missing"), realtime.get("validation_checked_at") or _file_mtime(realtime_path), f"accepted={realtime.get('accepted_sources', [])}" if realtime else ""),
            "intraday": _single_status(bool(intraday_path or state_store.get_intraday(safe)), "cache_file" if intraday_path else "memory_or_missing", "single_source", _file_mtime(intraday_path), "priority queues refresh intraday more frequently"),
            "money_flow": _single_status(_exists(money_path), "eastmoney_money_flow" if _exists(money_path) else "missing", "single_source", _file_mtime(money_path)),
            "orderbook": _single_status(has_orderbook, "tencent_realtime_l1" if has_orderbook else "missing", "single_source_snapshot" if has_orderbook else "missing", realtime.get("cached_at") or _file_mtime(realtime_path), "Tencent realtime includes L1 five-level order book; tick/L2 still needs QMT or paid vendor."),
            "finance": _single_status(has_finance_snapshot, "tencent_realtime_valuation" if has_finance_snapshot else "missing", "snapshot_valuation" if has_finance_snapshot else "missing", realtime.get("cached_at") or _file_mtime(realtime_path), "Realtime valuation fields only; deep F10 finance is still pending."),
            "disclosure_risk": _single_status(
                bool(disclosure.get("items")),
                disclosure.get("data_status", "missing"),
                disclosure.get("risk_level", "missing"),
                disclosure.get("updated_at", ""),
                "Formal disclosure source requires TUSHARE_TOKEN; news keyword fallback is marked explicitly.",
            ),
            "chips": _single_status(_exists(chip_path), "derived_from_verified_kline" if _exists(chip_path) else "missing", "derived", _file_mtime(chip_path)),
        },
    }


def get_coverage_report(stocks: Optional[List[dict]] = None, sample_limit: int = 0) -> dict:
    all_stocks = stocks if stocks is not None else list(state_store.get_stock_universe().values())
    codes = [_safe_code(s.get("code")) for s in (all_stocks or []) if _safe_code(s.get("code"))]
    raw_total = len(codes)
    target_total = data_fetcher.active_stock_universe_limit()
    changes = data_fetcher.read_stock_universe_changes()
    previous_total = int(changes.get("previous_total") or 0)
    current_total = int(changes.get("current_total") or raw_total or 0)
    new_count = int((changes.get("summary") or {}).get("new_listed") or 0)
    total = target_total if target_total and raw_total > target_total else (
        previous_total if previous_total and new_count and current_total > previous_total else raw_total
    )
    active_codes = codes[:total] if total and raw_total > total else codes
    roots = {
        "daily_kline": os.path.join(data_fetcher.KLINE_CACHE_DIR, "period_101"),
        "weekly_kline": os.path.join(data_fetcher.KLINE_CACHE_DIR, "period_102"),
        "monthly_kline": os.path.join(data_fetcher.KLINE_CACHE_DIR, "period_103"),
        "realtime": data_fetcher.REALTIME_CACHE_DIR,
        "intraday": data_fetcher.INTRADAY_CACHE_DIR,
        "money_flow": data_fetcher.MONEY_FLOW_CACHE_DIR,
        "chips": data_fetcher.CHIP_CACHE_DIR,
    }

    counts = {
        "daily_kline": _count_code_files(active_codes, roots["daily_kline"], ".csv"),
        "weekly_kline": _count_code_files(active_codes, roots["weekly_kline"], ".csv"),
        "monthly_kline": _count_code_files(active_codes, roots["monthly_kline"], ".csv"),
        "realtime": _count_code_files(active_codes, roots["realtime"], ".json", dated=True),
        "intraday": _count_code_files(active_codes, roots["intraday"], ".csv", dated=True),
        "money_flow": _count_code_files(active_codes, roots["money_flow"], ".json"),
        "chips": _count_code_files(active_codes, roots["chips"], ".json"),
        "orderbook": _count_latest_realtime_with_any_field(active_codes, ("bid_price1", "ask_price1", "bid_volume1", "ask_volume1")),
        "finance": _count_latest_realtime_with_any_field(active_codes, ("pe_ttm", "pe_dynamic", "pe_static", "pb", "market_cap", "float_market_cap")),
        "disclosure_risk": _count_files(disclosure_service.DISCLOSURE_CACHE_DIR, ".json"),
    }
    candidate_counts = {
        "daily_kline": _count_files(_kline_candidate_root(101), ".csv"),
        "weekly_kline": _count_files(_kline_candidate_root(102), ".csv"),
        "monthly_kline": _count_files(_kline_candidate_root(103), ".csv"),
    }
    validation_conflicts = _count_files(data_fetcher.VALIDATION_CACHE_DIR, ".json")

    rows = []
    for key, label in DATA_TYPES.items():
        count = min(counts.get(key, 0), total) if total else counts.get(key, 0)
        if key == "disclosure_risk":
            status = "ok" if count >= total * 0.9 else "partial" if count else "missing_source"
        else:
            status = "ok" if total and count >= total * 0.9 else "partial" if count else "missing"
        rows.append({
            "key": key,
            "label": label,
            "covered": count,
            "total": total,
            "coverage_pct": round(count / total * 100, 2) if total else 0,
            "candidate": candidate_counts.get(key, 0),
            "status": status,
        })

    samples = []
    if sample_limit:
        for code in active_codes[:sample_limit]:
            samples.append(get_stock_data_availability(code))

    return {
        "updated_at": _now_text(),
        "cache_root": data_fetcher.market_cache_root(),
        "stock_total": total,
        "raw_stock_total": raw_total,
        "active_stock_total": total,
        "rows": rows,
        "candidate_counts": candidate_counts,
        "validation_report_files": validation_conflicts,
        "priority_queue": _hub_state.get("priority_queue", {}),
        "hub": get_hub_status(),
        "samples": samples,
    }
