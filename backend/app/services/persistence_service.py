"""Small SQLite persistence layer for user settings and analysis history.

This module deliberately uses the Python stdlib sqlite3 API. The existing
project has PostgreSQL/SQLAlchemy scaffolding, but main_simple.py currently
runs as a lightweight single-process app, so SQLite is the lowest-risk first
step for durable local state.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Any


BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(BACKEND_ROOT, "data")
DB_PATH = os.getenv("LIANGHUA_SQLITE_PATH") or os.path.join(DATA_DIR, "lianghua_app.sqlite3")
DEFAULT_USER_ID = "default"
_lock = threading.RLock()
_initialized = False


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _json_loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def mask_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def _connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


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
                CREATE TABLE IF NOT EXISTS ai_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    provider TEXT,
                    base_url TEXT,
                    api_key TEXT,
                    selected_model TEXT,
                    enabled INTEGER DEFAULT 0,
                    extra_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id)
                );

                CREATE TABLE IF NOT EXISTS watchlist_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    symbol TEXT NOT NULL,
                    name TEXT,
                    market TEXT,
                    source TEXT,
                    extra_json TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, symbol)
                );

                CREATE TABLE IF NOT EXISTS recent_stocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    symbol TEXT NOT NULL,
                    name TEXT,
                    source TEXT,
                    extra_json TEXT DEFAULT '{}',
                    last_analyzed_at TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    UNIQUE(user_id, symbol, source)
                );

                CREATE TABLE IF NOT EXISTS ai_analysis_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    symbol TEXT NOT NULL,
                    strategy TEXT,
                    summary TEXT,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS backtest_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    symbol TEXT NOT NULL,
                    strategy TEXT,
                    params_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
        _initialized = True


def db_status() -> dict:
    init_db()
    return {"path": DB_PATH, "exists": os.path.exists(DB_PATH)}


def save_ai_settings(user_id: str = DEFAULT_USER_ID, *, provider: str = "", base_url: str = "", api_key: str = "", selected_model: str = "", enabled: bool | None = None, extra: dict | None = None) -> dict:
    init_db()
    user_id = user_id or DEFAULT_USER_ID
    now = _now()
    with _lock, _connect() as conn:
        current = conn.execute("SELECT * FROM ai_settings WHERE user_id = ?", (user_id,)).fetchone()
        merged = {
            "provider": provider or (current["provider"] if current else ""),
            "base_url": base_url or (current["base_url"] if current else ""),
            "api_key": api_key if api_key and "..." not in api_key else (current["api_key"] if current else ""),
            "selected_model": selected_model or (current["selected_model"] if current else ""),
            "enabled": int(enabled if enabled is not None else (current["enabled"] if current else False)),
            "extra_json": _json_dumps({**(_json_loads(current["extra_json"], {}) if current else {}), **(extra or {})}),
        }
        conn.execute(
            """
            INSERT INTO ai_settings (user_id, provider, base_url, api_key, selected_model, enabled, extra_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                provider=excluded.provider,
                base_url=excluded.base_url,
                api_key=excluded.api_key,
                selected_model=excluded.selected_model,
                enabled=excluded.enabled,
                extra_json=excluded.extra_json,
                updated_at=excluded.updated_at
            """,
            (user_id, merged["provider"], merged["base_url"], merged["api_key"], merged["selected_model"], merged["enabled"], merged["extra_json"], now, now),
        )
    return get_ai_settings(user_id)


def get_ai_settings(user_id: str = DEFAULT_USER_ID) -> dict:
    init_db()
    user_id = user_id or DEFAULT_USER_ID
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM ai_settings WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return {
            "provider": os.getenv("LIANGHUA_AI_PROVIDER", ""),
            "base_url": os.getenv("LIANGHUA_AI_BASE_URL", ""),
            "selected_model": os.getenv("LIANGHUA_AI_MODEL", ""),
            "enabled": bool(os.getenv("LIANGHUA_AI_API_KEY")),
            "has_api_key": bool(os.getenv("LIANGHUA_AI_API_KEY")),
            "api_key_masked": mask_key(os.getenv("LIANGHUA_AI_API_KEY", "")),
            "source": "env" if os.getenv("LIANGHUA_AI_API_KEY") else "empty",
        }
    api_key = row["api_key"] or ""
    return {
        "provider": row["provider"] or "",
        "base_url": row["base_url"] or "",
        "selected_model": row["selected_model"] or "",
        "enabled": bool(row["enabled"]),
        "has_api_key": bool(api_key),
        "api_key_masked": mask_key(api_key),
        "updated_at": row["updated_at"],
        "extra": _json_loads(row["extra_json"], {}),
        "source": "sqlite",
    }


def list_watchlist(user_id: str = DEFAULT_USER_ID) -> list[dict]:
    init_db()
    user_id = user_id or DEFAULT_USER_ID
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watchlist_items WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
            (user_id,),
        ).fetchall()
    return [
        {
            "code": row["symbol"],
            "symbol": row["symbol"],
            "name": row["name"] or row["symbol"],
            "market": row["market"] or "",
            "source": row["source"] or "服务端自选",
            "added_at": row["created_at"],
            "updated_at": row["updated_at"],
            **_json_loads(row["extra_json"], {}),
        }
        for row in rows
    ]


def upsert_watchlist_item(user_id: str = DEFAULT_USER_ID, item: dict | None = None) -> dict:
    init_db()
    item = item or {}
    symbol = str(item.get("symbol") or item.get("code") or "").strip()
    if not symbol:
        return {"ok": False, "error": "缺少股票代码。"}
    user_id = user_id or DEFAULT_USER_ID
    now = _now()
    extra = {k: v for k, v in item.items() if k not in {"symbol", "code", "name", "market", "source"}}
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO watchlist_items (user_id, symbol, name, market, source, extra_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, symbol) DO UPDATE SET
                name=excluded.name,
                market=excluded.market,
                source=excluded.source,
                extra_json=excluded.extra_json,
                updated_at=excluded.updated_at
            """,
            (user_id, symbol, item.get("name") or symbol, item.get("market") or "", item.get("source") or "H5", _json_dumps(extra), now, now),
        )
    return {"ok": True, "item": next((x for x in list_watchlist(user_id) if x["code"] == symbol), {"code": symbol})}


def delete_watchlist_item(user_id: str = DEFAULT_USER_ID, symbol: str = "") -> dict:
    init_db()
    user_id = user_id or DEFAULT_USER_ID
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM watchlist_items WHERE user_id = ? AND symbol = ?", (user_id, symbol))
    return {"ok": True, "deleted": cur.rowcount, "symbol": symbol}


def record_recent_stock(user_id: str = DEFAULT_USER_ID, symbol: str = "", name: str = "", source: str = "analysis", extra: dict | None = None):
    if not symbol:
        return
    init_db()
    user_id = user_id or DEFAULT_USER_ID
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO recent_stocks (user_id, symbol, name, source, extra_json, last_analyzed_at, count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(user_id, symbol, source) DO UPDATE SET
                name=excluded.name,
                extra_json=excluded.extra_json,
                last_analyzed_at=excluded.last_analyzed_at,
                count=count+1
            """,
            (user_id, symbol, name or symbol, source, _json_dumps(extra), now),
        )


def list_recent_stocks(user_id: str = DEFAULT_USER_ID, limit: int = 50) -> list[dict]:
    init_db()
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM recent_stocks WHERE user_id = ? ORDER BY last_analyzed_at DESC LIMIT ?",
            (user_id or DEFAULT_USER_ID, int(limit or 50)),
        ).fetchall()
    return [dict(row) | {"extra": _json_loads(row["extra_json"], {})} for row in rows]


def record_ai_analysis(user_id: str = DEFAULT_USER_ID, symbol: str = "", strategy: str = "", result: dict | None = None):
    if not symbol:
        return
    init_db()
    result = result or {}
    analysis = result.get("analysis") or {}
    summary = analysis.get("ai_action") or analysis.get("ai_reason") or result.get("error") or ""
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO ai_analysis_history (user_id, symbol, strategy, summary, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id or DEFAULT_USER_ID, symbol, strategy or "", str(summary)[:500], _json_dumps(result), _now()),
        )


def list_ai_history(user_id: str = DEFAULT_USER_ID, limit: int = 50, symbol: str = "") -> list[dict]:
    init_db()
    params: list[Any] = [user_id or DEFAULT_USER_ID]
    where = "user_id = ?"
    if symbol:
        where += " AND symbol = ?"
        params.append(symbol)
    params.append(int(limit or 50))
    with _lock, _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM ai_analysis_history WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "symbol": row["symbol"],
            "strategy": row["strategy"],
            "summary": row["summary"],
            "created_at": row["created_at"],
            "result": _json_loads(row["result_json"], {}),
        }
        for row in rows
    ]


def record_backtest(user_id: str = DEFAULT_USER_ID, symbol: str = "", strategy: str = "", params: dict | None = None, result: dict | None = None):
    if not symbol:
        return
    init_db()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO backtest_records (user_id, symbol, strategy, params_json, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id or DEFAULT_USER_ID, symbol, strategy or "", _json_dumps(params), _json_dumps(result), _now()),
        )


def list_backtests(user_id: str = DEFAULT_USER_ID, limit: int = 50, symbol: str = "") -> list[dict]:
    init_db()
    params: list[Any] = [user_id or DEFAULT_USER_ID]
    where = "user_id = ?"
    if symbol:
        where += " AND symbol = ?"
        params.append(symbol)
    params.append(int(limit or 50))
    with _lock, _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM backtest_records WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [
        {
            "id": row["id"],
            "symbol": row["symbol"],
            "strategy": row["strategy"],
            "params": _json_loads(row["params_json"], {}),
            "result": _json_loads(row["result_json"], {}),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
