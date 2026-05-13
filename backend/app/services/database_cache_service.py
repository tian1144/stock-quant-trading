"""SQLite-backed cache for market data and news.

This layer is intentionally small: it keeps the existing memory/file caches in
place, and adds durable JSON payloads so service restarts do not lose recent
stock details, K lines, intraday data, snapshots, or news.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any


BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(BACKEND_ROOT, "data")
DB_PATH = os.getenv("LIANGHUA_SQLITE_PATH") or os.path.join(DATA_DIR, "lianghua_app.sqlite3")
_lock = threading.RLock()
_initialized = False


def _now() -> datetime:
    return datetime.now()


def _now_text() -> str:
    return _now().isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%m-%d %H:%M", "%H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt.startswith("%m") or fmt == "%H:%M":
                now = _now()
                parsed = parsed.replace(year=now.year)
                if fmt == "%H:%M":
                    parsed = parsed.replace(month=now.month, day=now.day)
            return parsed
        except Exception:
            continue
    return None


def _params_key(params: dict | None = None) -> str:
    if not params:
        return ""
    text = json.dumps(params, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def init_db():
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS stock_data_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    period TEXT NOT NULL DEFAULT '',
                    params_key TEXT NOT NULL DEFAULT '',
                    params_json TEXT NOT NULL DEFAULT '{}',
                    trade_date TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    source TEXT,
                    status TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    UNIQUE(cache_type, symbol, period, params_key, trade_date)
                );

                CREATE INDEX IF NOT EXISTS idx_stock_data_cache_lookup
                ON stock_data_cache(cache_type, symbol, period, params_key, updated_at);

                CREATE TABLE IF NOT EXISTS news_cache_items (
                    dedupe_key TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    source TEXT,
                    category TEXT,
                    sentiment TEXT,
                    published_at TEXT,
                    payload_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_news_cache_items_published
                ON news_cache_items(published_at, updated_at);

                CREATE TABLE IF NOT EXISTS news_cache_meta (
                    key TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
        _initialized = True


def db_cache_status() -> dict:
    init_db()
    with _lock, _connect() as conn:
        stock_rows = conn.execute("SELECT COUNT(*) AS c FROM stock_data_cache").fetchone()["c"]
        news_rows = conn.execute("SELECT COUNT(*) AS c FROM news_cache_items").fetchone()["c"]
    return {"path": DB_PATH, "exists": os.path.exists(DB_PATH), "stock_cache_rows": stock_rows, "news_rows": news_rows}


def upsert_stock_cache(
    cache_type: str,
    symbol: str,
    payload: dict | list,
    *,
    period: str | int = "",
    params: dict | None = None,
    trade_date: str | None = None,
    ttl_seconds: int | None = None,
    source: str = "",
    status: str = "",
) -> None:
    if not cache_type or not symbol or payload is None:
        return
    init_db()
    now = _now_text()
    expires_at = (_now() + timedelta(seconds=int(ttl_seconds))).isoformat(timespec="seconds") if ttl_seconds else None
    params_json = _json_dumps(params or {})
    key = _params_key(params)
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO stock_data_cache
                (cache_type, symbol, period, params_key, params_json, trade_date, payload_json, source, status, created_at, updated_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_type, symbol, period, params_key, trade_date) DO UPDATE SET
                payload_json=excluded.payload_json,
                source=excluded.source,
                status=excluded.status,
                updated_at=excluded.updated_at,
                expires_at=excluded.expires_at,
                params_json=excluded.params_json
            """,
            (
                cache_type,
                str(symbol),
                str(period or ""),
                key,
                params_json,
                trade_date or _now().strftime("%Y-%m-%d"),
                _json_dumps(payload),
                source,
                status,
                now,
                now,
                expires_at,
            ),
        )


def get_stock_cache(
    cache_type: str,
    symbol: str,
    *,
    period: str | int = "",
    params: dict | None = None,
    max_age_seconds: int | None = None,
    allow_expired: bool = False,
) -> dict | list | None:
    if not cache_type or not symbol:
        return None
    init_db()
    key = _params_key(params)
    with _lock, _connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM stock_data_cache
            WHERE cache_type = ? AND symbol = ? AND period = ? AND params_key = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (cache_type, str(symbol), str(period or ""), key),
        ).fetchone()
    if not row:
        return None
    updated_at = _parse_dt(row["updated_at"])
    expires_at = _parse_dt(row["expires_at"])
    now = _now()
    if max_age_seconds is not None and updated_at and (now - updated_at).total_seconds() > max_age_seconds and not allow_expired:
        return None
    if expires_at and expires_at < now and not allow_expired:
        return None
    payload = _json_loads(row["payload_json"], None)
    if isinstance(payload, dict):
        payload.setdefault("db_cache", True)
        payload.setdefault("db_cached_at", row["updated_at"])
    return payload


def _news_key(item: dict) -> str:
    raw = str(item.get("dedupe_key") or item.get("url") or "")
    if not raw:
        raw = f"{item.get('source', '')}|{item.get('time', '')}|{item.get('title', '')}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def upsert_news_cache(news: list, meta: dict | None = None) -> None:
    if not isinstance(news, list):
        return
    init_db()
    now = _now_text()
    with _lock, _connect() as conn:
        for item in news:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            key = str(item.get("dedupe_key") or _news_key(item))
            payload = {**item, "dedupe_key": key}
            conn.execute(
                """
                INSERT INTO news_cache_items
                    (dedupe_key, title, source, category, sentiment, published_at, payload_json, first_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    title=excluded.title,
                    source=excluded.source,
                    category=excluded.category,
                    sentiment=excluded.sentiment,
                    published_at=excluded.published_at,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    key,
                    str(item.get("title") or "")[:500],
                    str(item.get("source") or ""),
                    str(item.get("category") or ""),
                    str(item.get("sentiment") or ""),
                    str(item.get("time") or item.get("published_at") or ""),
                    _json_dumps(payload),
                    now,
                    now,
                ),
            )
        if meta is not None:
            conn.execute(
                """
                INSERT INTO news_cache_meta (key, payload_json, updated_at)
                VALUES ('latest', ?, ?)
                ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at
                """,
                (_json_dumps(meta), now),
            )


def list_news_cache(limit: int = 500, max_age_days: int = 14) -> tuple[list[dict], dict]:
    init_db()
    cutoff = _now() - timedelta(days=max_age_days)
    rows: list[sqlite3.Row]
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM news_cache_items
            ORDER BY COALESCE(published_at, updated_at) DESC, updated_at DESC
            LIMIT ?
            """,
            (int(limit or 500),),
        ).fetchall()
        meta_row = conn.execute("SELECT * FROM news_cache_meta WHERE key = 'latest'").fetchone()
    news: list[dict] = []
    for row in rows:
        published = _parse_dt(row["published_at"]) or _parse_dt(row["updated_at"]) or _now()
        if published < cutoff:
            continue
        item = _json_loads(row["payload_json"], {})
        if isinstance(item, dict) and item.get("title"):
            item.setdefault("dedupe_key", row["dedupe_key"])
            news.append(item)
    meta = _json_loads(meta_row["payload_json"], {}) if meta_row else {}
    meta = {
        **meta,
        "db_cache": True,
        "db_cache_count": len(news),
        "db_cache_path": DB_PATH,
        "db_cache_loaded_at": _now_text(),
    }
    return news, meta
