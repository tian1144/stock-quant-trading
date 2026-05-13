"""Isolated market data worker.

The web backend stays responsive even when public quote providers are slow or
rate limited. This worker runs in a separate process, refreshes only a bounded
slice of market data per cycle, and writes durable file/SQLite caches for the
web backend to read.
"""

from __future__ import annotations

import json
import os
import signal
import time
from datetime import datetime
from typing import Iterable

from loguru import logger

from app.services import data_fetcher, database_cache_service, market_data_hub, state_store


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATUS_PATH = os.getenv("LIANGHUA_MARKET_WORKER_STATUS_PATH") or os.path.join(
    BACKEND_ROOT, "data", "jobs", "market_worker", "status.json"
)


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(int(os.getenv(name, default)), minimum)
    except Exception:
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(float(os.getenv(name, default)), minimum)
    except Exception:
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


REALTIME_INTERVAL_SECONDS = _env_float("LIANGHUA_WORKER_REALTIME_INTERVAL_SECONDS", 15, 5)
INTRADAY_INTERVAL_SECONDS = _env_float("LIANGHUA_WORKER_INTRADAY_INTERVAL_SECONDS", 180, 30)
UNIVERSE_INTERVAL_SECONDS = _env_float("LIANGHUA_WORKER_UNIVERSE_INTERVAL_SECONDS", 3600, 300)
IDLE_INTERVAL_SECONDS = _env_float("LIANGHUA_WORKER_IDLE_INTERVAL_SECONDS", 60, 15)
REALTIME_BATCH_SIZE = _env_int("LIANGHUA_WORKER_REALTIME_BATCH_SIZE", 5, 1)
FIRST_LIMIT = _env_int("LIANGHUA_WORKER_FIRST_LIMIT", 30, 0)
SECOND_LIMIT = _env_int("LIANGHUA_WORKER_SECOND_LIMIT", 30, 0)
THIRD_LIMIT = _env_int("LIANGHUA_WORKER_THIRD_LIMIT", 10, 0)
INTRADAY_FIRST_LIMIT = _env_int("LIANGHUA_WORKER_INTRADAY_FIRST_LIMIT", 20, 0)
INTRADAY_SECOND_LIMIT = _env_int("LIANGHUA_WORKER_INTRADAY_SECOND_LIMIT", 10, 0)
PER_CODE_DELAY_SECONDS = _env_float("LIANGHUA_WORKER_PER_CODE_DELAY_SECONDS", 0.2, 0)
ENABLE_REALTIME = _env_flag("LIANGHUA_WORKER_ENABLE_REALTIME", True)
ENABLE_INTRADAY = _env_flag("LIANGHUA_WORKER_ENABLE_INTRADAY", True)
ENABLE_UNIVERSE = _env_flag("LIANGHUA_WORKER_ENABLE_UNIVERSE", False)
RUN_ONCE = _env_flag("LIANGHUA_WORKER_ONCE", False)


_stop = False
_state = {
    "pid": os.getpid(),
    "started_at": "",
    "updated_at": "",
    "mode": "starting",
    "message": "market worker starting",
    "cycle": 0,
    "last_error": "",
    "last_realtime": {},
    "last_intraday": {},
    "last_universe": {},
    "config": {},
}
_third_cursor = 0


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_code(code) -> str:
    return "".join(ch for ch in str(code or "") if ch.isalnum())


def _write_status(extra: dict | None = None) -> None:
    _state.update(extra or {})
    _state["updated_at"] = _now_text()
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    tmp_path = f"{STATUS_PATH}.{os.getpid()}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, STATUS_PATH)


def _load_stocks() -> list[dict]:
    stocks = data_fetcher.read_stock_universe_cache()
    if stocks:
        return stocks
    if ENABLE_UNIVERSE:
        return data_fetcher.fetch_all_stocks_sina()
    return list(state_store.get_stock_universe().values())


def _is_trading_day(now: datetime) -> bool:
    return now.weekday() < 5


def _is_realtime_window(now: datetime) -> bool:
    if not _is_trading_day(now):
        return False
    current = now.hour * 60 + now.minute
    return 9 * 60 <= current <= 15 * 60


def _is_universe_window(now: datetime) -> bool:
    if not _is_trading_day(now):
        return False
    current = now.hour * 60 + now.minute
    return 8 * 60 + 30 <= current <= 9 * 60 or 15 * 60 + 30 <= current <= 16 * 60


def _unique(codes: Iterable[str]) -> list[str]:
    seen, out = set(), []
    for code in codes:
        safe = _safe_code(code)
        if safe and safe not in seen:
            out.append(safe)
            seen.add(safe)
    return out


def _worker_watch_codes() -> list[str]:
    raw = os.getenv("LIANGHUA_WORKER_WATCH_CODES", "")
    return _unique(part.strip() for part in raw.replace(";", ",").split(",") if part.strip())


def _build_realtime_codes(stocks: list[dict]) -> tuple[list[str], dict]:
    global _third_cursor
    queues = market_data_hub.build_priority_queues(
        watchlist_codes=_worker_watch_codes(),
        volatile_codes=[s.get("code") for s in (state_store.get_screening_results() or [])[:80]],
        stocks=stocks,
    )
    first = _unique(queues.get("first") or [])[:FIRST_LIMIT]
    second = [c for c in _unique(queues.get("second") or []) if c not in set(first)][:SECOND_LIMIT]
    priority = first + second
    third_pool = [c for c in _unique(queues.get("third_sample") or []) if c not in set(priority)]
    sample: list[str] = []
    if third_pool and THIRD_LIMIT:
        _third_cursor %= len(third_pool)
        for offset in range(min(THIRD_LIMIT, len(third_pool))):
            sample.append(third_pool[(_third_cursor + offset) % len(third_pool)])
        _third_cursor = (_third_cursor + len(sample)) % len(third_pool)
    return _unique(priority + sample), {
        "first": len(first),
        "second": len(second),
        "third_sample": len(sample),
        "third_pool": len(third_pool),
    }


def _persist_snapshot_cache(results: dict) -> None:
    for code, payload in (results or {}).items():
        if not payload:
            continue
        database_cache_service.upsert_stock_cache(
            "market_snapshot",
            code,
            payload,
            ttl_seconds=max(int(REALTIME_INTERVAL_SECONDS * 4), 60),
            source=payload.get("source", ""),
            status=payload.get("validation_status", ""),
        )


def _refresh_realtime(stocks: list[dict]) -> dict:
    codes, queue_stats = _build_realtime_codes(stocks)
    if not codes:
        return {"status": "skipped", "message": "no realtime codes", "queue": queue_stats}
    success = 0
    batches = 0
    for start in range(0, len(codes), REALTIME_BATCH_SIZE):
        batch = codes[start:start + REALTIME_BATCH_SIZE]
        result = data_fetcher.fetch_verified_realtime_batch(batch, require_verified_for_cache=True)
        _persist_snapshot_cache(result)
        success += len([item for item in result.values() if item])
        batches += 1
        if PER_CODE_DELAY_SECONDS:
            time.sleep(PER_CODE_DELAY_SECONDS)
    return {
        "status": "ok",
        "checked_at": _now_text(),
        "total": len(codes),
        "success": success,
        "batches": batches,
        "queue": queue_stats,
        "sample": codes[:12],
    }


def _refresh_intraday(stocks: list[dict]) -> dict:
    queues = market_data_hub.build_priority_queues(
        watchlist_codes=_worker_watch_codes(),
        volatile_codes=[s.get("code") for s in (state_store.get_screening_results() or [])[:80]],
        stocks=stocks,
    )
    first = _unique(queues.get("first") or [])[:INTRADAY_FIRST_LIMIT]
    second = [c for c in _unique(queues.get("second") or []) if c not in set(first)][:INTRADAY_SECOND_LIMIT]
    codes = _unique(first + second)
    if not codes:
        return {"status": "skipped", "message": "no intraday codes"}
    success = 0
    for code in codes:
        minutes = data_fetcher.fetch_intraday_minutes(code, allow_fallback=False)
        if minutes:
            success += 1
            payload = {
                "code": code,
                "minutes": minutes,
                "count": len(minutes),
                "source": minutes[-1].get("source", "eastmoney_trends") if isinstance(minutes[-1], dict) else "eastmoney_trends",
                "status": "ok",
                "updated_at": _now_text(),
            }
            database_cache_service.upsert_stock_cache(
                "stock_minutes",
                code,
                payload,
                params={"require_complete": not data_fetcher.is_trading_hours()},
                ttl_seconds=max(int(INTRADAY_INTERVAL_SECONDS * 3), 300),
                source=payload["source"],
                status="ok",
            )
        if PER_CODE_DELAY_SECONDS:
            time.sleep(PER_CODE_DELAY_SECONDS)
    return {
        "status": "ok",
        "checked_at": _now_text(),
        "total": len(codes),
        "success": success,
        "sample": codes[:12],
    }


def _refresh_universe() -> dict:
    stocks = data_fetcher.fetch_all_stocks_sina()
    return {"status": "ok", "checked_at": _now_text(), "total": len(stocks or [])}


def _handle_signal(signum, _frame) -> None:
    global _stop
    _stop = True
    _write_status({"mode": "stopping", "message": f"received signal {signum}"})


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    _state["started_at"] = _now_text()
    _state["config"] = {
        "realtime_interval_seconds": REALTIME_INTERVAL_SECONDS,
        "intraday_interval_seconds": INTRADAY_INTERVAL_SECONDS,
        "universe_interval_seconds": UNIVERSE_INTERVAL_SECONDS,
        "batch_size": REALTIME_BATCH_SIZE,
        "first_limit": FIRST_LIMIT,
        "second_limit": SECOND_LIMIT,
        "third_limit": THIRD_LIMIT,
        "intraday_first_limit": INTRADAY_FIRST_LIMIT,
        "intraday_second_limit": INTRADAY_SECOND_LIMIT,
        "enable_realtime": ENABLE_REALTIME,
        "enable_intraday": ENABLE_INTRADAY,
        "enable_universe": ENABLE_UNIVERSE,
        "status_path": STATUS_PATH,
    }
    _write_status({"mode": "running", "message": "market worker running"})
    logger.info("market worker started: {}", _state["config"])
    last_realtime = 0.0
    last_intraday = 0.0
    last_universe = 0.0
    while not _stop:
        now = datetime.now()
        try:
            stocks = _load_stocks()
            _state["cycle"] = int(_state.get("cycle") or 0) + 1
            if ENABLE_UNIVERSE and _is_universe_window(now) and time.time() - last_universe >= UNIVERSE_INTERVAL_SECONDS:
                _write_status({"mode": "universe", "message": "refreshing stock universe"})
                _state["last_universe"] = _refresh_universe()
                last_universe = time.time()
            if ENABLE_REALTIME and _is_realtime_window(now) and time.time() - last_realtime >= REALTIME_INTERVAL_SECONDS:
                _write_status({"mode": "realtime", "message": "refreshing realtime snapshots"})
                _state["last_realtime"] = _refresh_realtime(stocks)
                last_realtime = time.time()
            if ENABLE_INTRADAY and _is_realtime_window(now) and time.time() - last_intraday >= INTRADAY_INTERVAL_SECONDS:
                _write_status({"mode": "intraday", "message": "refreshing intraday priority data"})
                _state["last_intraday"] = _refresh_intraday(stocks)
                last_intraday = time.time()
            _write_status({"mode": "running", "message": "market worker idle", "stock_total": len(stocks or [])})
        except Exception as exc:
            logger.exception("market worker cycle failed")
            _write_status({"mode": "error", "message": str(exc), "last_error": str(exc)})
            time.sleep(10)
        if RUN_ONCE:
            break
        time.sleep(IDLE_INTERVAL_SECONDS if not _is_realtime_window(datetime.now()) else 3)
    _write_status({"mode": "stopped", "message": "market worker stopped"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
