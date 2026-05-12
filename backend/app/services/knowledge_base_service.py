"""SQLite knowledge base for Feishu/customer-service AI answers."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sqlite3
import threading
from datetime import datetime
from typing import Any


BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
DATA_DIR = os.path.join(BACKEND_ROOT, "data")
DB_PATH = os.getenv("LIANGHUA_SQLITE_PATH") or os.path.join(DATA_DIR, "lianghua_app.sqlite3")
NO_ANSWER_TEXT = "知识库未找到相关依据，暂时无法回答。"

_lock = threading.RLock()
_initialized = False
_fts_available: bool | None = None


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_loads(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _normalize_tags(tags: Any) -> list[str]:
    if isinstance(tags, str):
        raw = re.split(r"[,，、\s]+", tags)
    elif isinstance(tags, (list, tuple, set)):
        raw = list(tags)
    else:
        raw = []
    return [str(x).strip() for x in raw if str(x).strip()]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _split_chunks(content: str, max_chars: int = 900) -> list[str]:
    text = str(content or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs or [text]:
        if len(buf) + len(para) + 2 <= max_chars:
            buf = f"{buf}\n\n{para}".strip()
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        while len(para) > max_chars:
            chunks.append(para[:max_chars])
            para = para[max_chars:]
        buf = para
    if buf:
        chunks.append(buf)
    return chunks[:80]


def init_db() -> None:
    global _initialized, _fts_available
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        with _connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS knowledge_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    tags_json TEXT DEFAULT '[]',
                    source TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_items_updated
                ON knowledge_items(enabled, updated_at);

                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT '',
                    tags_json TEXT DEFAULT '[]',
                    source TEXT DEFAULT '',
                    enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(item_id) REFERENCES knowledge_items(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_item
                ON knowledge_chunks(item_id, enabled);

                CREATE TABLE IF NOT EXISTS feishu_message_logs (
                    event_id TEXT PRIMARY KEY,
                    chat_id TEXT,
                    sender_id TEXT,
                    message_id TEXT,
                    question TEXT,
                    answer TEXT,
                    matched_item_ids TEXT DEFAULT '[]',
                    status TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
                    USING fts5(title, content, category, tags, source, content='knowledge_chunks', content_rowid='id')
                    """
                )
                _fts_available = True
            except Exception:
                _fts_available = False
        _initialized = True


def db_status() -> dict:
    init_db()
    with _lock, _connect() as conn:
        items = conn.execute("SELECT COUNT(*) AS c FROM knowledge_items").fetchone()["c"]
        chunks = conn.execute("SELECT COUNT(*) AS c FROM knowledge_chunks").fetchone()["c"]
        enabled = conn.execute("SELECT COUNT(*) AS c FROM knowledge_items WHERE enabled = 1").fetchone()["c"]
    return {"path": DB_PATH, "exists": os.path.exists(DB_PATH), "items": items, "enabled_items": enabled, "chunks": chunks, "fts_available": bool(_fts_available)}


def _sync_item_chunks(conn: sqlite3.Connection, item_id: int, title: str, content: str, category: str, tags: list[str], source: str, enabled: bool) -> None:
    now = _now()
    if _fts_available:
        try:
            conn.execute("DELETE FROM knowledge_chunks_fts WHERE rowid IN (SELECT id FROM knowledge_chunks WHERE item_id = ?)", (item_id,))
        except Exception:
            pass
    conn.execute("DELETE FROM knowledge_chunks WHERE item_id = ?", (item_id,))
    chunks = _split_chunks(content) or [content[:900]]
    for idx, chunk in enumerate(chunks):
        cur = conn.execute(
            """
            INSERT INTO knowledge_chunks
                (item_id, chunk_index, title, content, category, tags_json, source, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, idx, title, chunk, category, _json_dumps(tags), source, int(enabled), now, now),
        )
        if _fts_available:
            try:
                conn.execute(
                    "INSERT INTO knowledge_chunks_fts(rowid, title, content, category, tags, source) VALUES (?, ?, ?, ?, ?, ?)",
                    (cur.lastrowid, title, chunk, category, " ".join(tags), source),
                )
            except Exception:
                pass


def upsert_item(payload: dict) -> dict:
    init_db()
    title = _clean_text(payload.get("title"))
    content = str(payload.get("content") or "").strip()
    if not title or not content:
        return {"ok": False, "error": "标题和正文不能为空。"}
    category = _clean_text(payload.get("category"))
    source = _clean_text(payload.get("source"))
    tags = _normalize_tags(payload.get("tags"))
    enabled = bool(payload.get("enabled", True))
    item_id = int(payload.get("id") or 0)
    now = _now()
    with _lock, _connect() as conn:
        if item_id:
            conn.execute(
                """
                UPDATE knowledge_items
                SET title = ?, content = ?, category = ?, tags_json = ?, source = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, content, category, _json_dumps(tags), source, int(enabled), now, item_id),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO knowledge_items (title, content, category, tags_json, source, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (title, content, category, _json_dumps(tags), source, int(enabled), now, now),
            )
            item_id = int(cur.lastrowid)
        _sync_item_chunks(conn, item_id, title, content, category, tags, source, enabled)
    return {"ok": True, "item": get_item(item_id)}


def get_item(item_id: int) -> dict | None:
    init_db()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM knowledge_items WHERE id = ?", (int(item_id),)).fetchone()
    return _row_to_item(row) if row else None


def _row_to_item(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "category": row["category"] or "",
        "tags": _json_loads(row["tags_json"], []),
        "source": row["source"] or "",
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_items(search: str = "", limit: int = 100, offset: int = 0, enabled: str | None = None) -> dict:
    init_db()
    where = []
    params: list[Any] = []
    if search:
        like = f"%{search}%"
        where.append("(title LIKE ? OR content LIKE ? OR category LIKE ? OR source LIKE ? OR tags_json LIKE ?)")
        params.extend([like, like, like, like, like])
    if enabled in {"0", "1"}:
        where.append("enabled = ?")
        params.append(int(enabled))
    sql_where = "WHERE " + " AND ".join(where) if where else ""
    with _lock, _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM knowledge_items {sql_where}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM knowledge_items {sql_where} ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?",
            [*params, int(limit), int(offset)],
        ).fetchall()
    return {"ok": True, "items": [_row_to_item(r) for r in rows], "total": total, "status": db_status()}


def delete_item(item_id: int) -> dict:
    init_db()
    with _lock, _connect() as conn:
        if _fts_available:
            try:
                conn.execute("DELETE FROM knowledge_chunks_fts WHERE rowid IN (SELECT id FROM knowledge_chunks WHERE item_id = ?)", (int(item_id),))
            except Exception:
                pass
        conn.execute("DELETE FROM knowledge_chunks WHERE item_id = ?", (int(item_id),))
        cur = conn.execute("DELETE FROM knowledge_items WHERE id = ?", (int(item_id),))
    return {"ok": True, "deleted": cur.rowcount}


def _fts_query(text: str) -> str:
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", text or "")
    return " OR ".join(tokens[:12])


def _search_terms(text: str) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text or ""):
        token = token.strip().lower()
        if not token:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            for size in (2, 3):
                for idx in range(0, len(token) - size + 1):
                    terms.append(token[idx:idx + size])
        else:
            terms.append(token)
    seen = set()
    result = []
    for term in terms:
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result[:24]


def _rank_rows(rows: list[sqlite3.Row], query: str, limit: int) -> list[sqlite3.Row]:
    terms = _search_terms(query)
    if not terms:
        return []
    ranked: list[tuple[int, sqlite3.Row]] = []
    exact = query.lower()
    for row in rows:
        title = str(row["title"] or "").lower()
        content = str(row["content"] or "").lower()
        weak = " ".join([str(row["category"] or ""), str(row["source"] or ""), str(row["tags_json"] or "")]).lower()
        score = 0
        if exact and exact in content:
            score += 12
        if exact and exact in title:
            score += 8
        for term in terms:
            if term in content:
                score += 4
            if term in title:
                score += 3
            if term in weak:
                score += 1
        if score >= 4:
            ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in ranked[:limit]]


def search_knowledge(question: str, limit: int = 5) -> list[dict]:
    init_db()
    query = _clean_text(question)
    if not query:
        return []
    rows = []
    with _lock, _connect() as conn:
        if _fts_available:
            fts = _fts_query(query)
            if fts:
                try:
                    rows = conn.execute(
                        """
                        SELECT c.*, bm25(knowledge_chunks_fts) AS score
                        FROM knowledge_chunks_fts
                        JOIN knowledge_chunks c ON c.id = knowledge_chunks_fts.rowid
                        WHERE knowledge_chunks_fts MATCH ? AND c.enabled = 1
                        ORDER BY score ASC
                        LIMIT ?
                        """,
                        (fts, int(limit)),
                    ).fetchall()
                except Exception:
                    rows = []
        if not rows:
            terms = _search_terms(query)
            where = " OR ".join(["title LIKE ? OR content LIKE ? OR category LIKE ? OR source LIKE ? OR tags_json LIKE ?" for _ in terms])
            params: list[Any] = []
            for term in terms:
                like = f"%{term}%"
                params.extend([like, like, like, like, like])
            candidates = conn.execute(
                f"SELECT * FROM knowledge_chunks WHERE enabled = 1 AND ({where or 'content LIKE ?'}) ORDER BY updated_at DESC LIMIT 500",
                params or [f"%{query}%"],
            ).fetchall()
            rows = _rank_rows(candidates, query, int(limit))
    results = []
    for row in rows:
        content = row["content"] or ""
        results.append(
            {
                "chunk_id": row["id"],
                "item_id": row["item_id"],
                "title": row["title"],
                "content": content,
                "snippet": content[:360],
                "category": row["category"] or "",
                "tags": _json_loads(row["tags_json"], []),
                "source": row["source"] or "",
            }
        )
    return results


def import_text(filename: str, content: str, category: str = "", source: str = "") -> dict:
    init_db()
    filename = filename or "import.txt"
    ext = os.path.splitext(filename.lower())[1]
    created = []
    if ext == ".csv":
        reader = csv.DictReader(io.StringIO(content or ""))
        for idx, row in enumerate(reader):
            title = row.get("title") or row.get("标题") or row.get("question") or row.get("问题") or f"{filename} #{idx + 1}"
            body = row.get("content") or row.get("正文") or row.get("answer") or row.get("答案") or " ".join(str(v or "") for v in row.values())
            result = upsert_item({"title": title, "content": body, "category": row.get("category") or category, "tags": row.get("tags") or "", "source": row.get("source") or source or filename, "enabled": True})
            if result.get("ok"):
                created.append(result["item"])
    else:
        result = upsert_item({"title": os.path.splitext(os.path.basename(filename))[0] or filename, "content": content or "", "category": category, "tags": [], "source": source or filename, "enabled": True})
        if result.get("ok"):
            created.append(result["item"])
        else:
            return result
    return {"ok": True, "created": created, "count": len(created), "status": db_status()}


def has_event(event_id: str) -> bool:
    if not event_id:
        return False
    init_db()
    with _lock, _connect() as conn:
        row = conn.execute("SELECT event_id FROM feishu_message_logs WHERE event_id = ?", (event_id,)).fetchone()
    return bool(row)


def record_feishu_log(event_id: str, **payload) -> None:
    if not event_id:
        return
    init_db()
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO feishu_message_logs
                (event_id, chat_id, sender_id, message_id, question, answer, matched_item_ids, status, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                payload.get("chat_id") or "",
                payload.get("sender_id") or "",
                payload.get("message_id") or "",
                payload.get("question") or "",
                payload.get("answer") or "",
                _json_dumps(payload.get("matched_item_ids") or []),
                payload.get("status") or "",
                payload.get("error") or "",
                now,
            ),
        )
