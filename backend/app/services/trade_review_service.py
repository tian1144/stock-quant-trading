"""
Human review layer for OCR/PDF trade-note candidates.

OCR rows are clues, not facts. This service keeps noisy candidates separate from
verified trade reviews so the AI can learn cautiously.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from typing import Any

from app.services import strategy_memory_service


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ai", "youzi_trade_notes")
CANDIDATE_JSON = os.path.join(DATA_DIR, "trade_review_candidates.json")
VERIFIED_CSV = os.path.join(DATA_DIR, "verified_trade_reviews.csv")
VERIFIED_JSON = os.path.join(DATA_DIR, "verified_trade_reviews.json")

VERIFIED_FIELDS = [
    "candidate_id",
    "source_type",
    "source_path",
    "trader_or_folder",
    "trade_date",
    "code",
    "name",
    "side",
    "setup_type",
    "entry_reason",
    "exit_reason",
    "pnl_pct_or_amount",
    "plan_followed",
    "next_day_validation",
    "loss_reason",
    "source_confidence",
    "review_note",
    "reviewer",
    "verified_at",
]


def _ensure_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, payload: Any) -> None:
    _ensure_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _read_verified_rows() -> list[dict]:
    if not os.path.exists(VERIFIED_CSV):
        return []
    rows: list[dict] = []
    try:
        with open(VERIFIED_CSV, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                rows.append({field: row.get(field, "") for field in VERIFIED_FIELDS})
    except Exception:
        return []
    return rows


def _write_verified_rows(rows: list[dict]) -> None:
    _ensure_dir()
    with open(VERIFIED_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=VERIFIED_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in VERIFIED_FIELDS})
    _write_json(
        VERIFIED_JSON,
        {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(rows),
            "csv_path": VERIFIED_CSV,
            "rows": rows,
        },
    )


def get_trade_review_candidates(
    status: str = "",
    search: str = "",
    offset: int = 0,
    limit: int = 50,
) -> dict:
    payload = _read_json(CANDIDATE_JSON, {"rows": []})
    rows = payload.get("rows") or []
    verified = {row.get("candidate_id"): row for row in _read_verified_rows()}
    for row in rows:
        if row.get("candidate_id") in verified:
            row["verified_review"] = verified[row.get("candidate_id")]
            row["review_status"] = "verified"

    if status:
        rows = [row for row in rows if row.get("review_status") == status]
    if search:
        needle = search.lower()
        rows = [
            row for row in rows
            if needle in json.dumps(row, ensure_ascii=False).lower()
        ]

    start = max(0, int(offset or 0))
    end = start + max(1, min(int(limit or 50), 500))
    status_counts: dict[str, int] = {}
    for row in payload.get("rows") or []:
        key = "verified" if row.get("candidate_id") in verified else row.get("review_status", "unknown")
        status_counts[key] = status_counts.get(key, 0) + 1
    return {
        "ok": True,
        "candidate_path": CANDIDATE_JSON,
        "verified_csv": VERIFIED_CSV,
        "verified_json": VERIFIED_JSON,
        "total": len(rows),
        "offset": start,
        "limit": end - start,
        "row_count": payload.get("row_count", len(payload.get("rows") or [])),
        "status_counts": status_counts,
        "category_counts": payload.get("category_counts", {}),
        "rows": rows[start:end],
    }


def upsert_verified_trade_review(payload: dict) -> dict:
    candidate_id = str(payload.get("candidate_id") or "").strip()
    if not candidate_id:
        return {"ok": False, "error": "candidate_id 不能为空"}

    candidates = {
        row.get("candidate_id"): row
        for row in (_read_json(CANDIDATE_JSON, {"rows": []}).get("rows") or [])
    }
    candidate = candidates.get(candidate_id, {})
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = {
        "candidate_id": candidate_id,
        "source_type": candidate.get("source_type", ""),
        "source_path": candidate.get("source_path", ""),
        "trader_or_folder": candidate.get("trader_or_folder", ""),
        "trade_date": str(payload.get("trade_date") or "").strip(),
        "code": str(payload.get("code") or "").strip(),
        "name": str(payload.get("name") or "").strip(),
        "side": str(payload.get("side") or "").strip(),
        "setup_type": str(payload.get("setup_type") or "").strip(),
        "entry_reason": str(payload.get("entry_reason") or "").strip(),
        "exit_reason": str(payload.get("exit_reason") or "").strip(),
        "pnl_pct_or_amount": str(payload.get("pnl_pct_or_amount") or "").strip(),
        "plan_followed": str(payload.get("plan_followed") or "").strip(),
        "next_day_validation": str(payload.get("next_day_validation") or "").strip(),
        "loss_reason": str(payload.get("loss_reason") or "").strip(),
        "source_confidence": str(payload.get("source_confidence") or "medium").strip(),
        "review_note": str(payload.get("review_note") or "").strip(),
        "reviewer": str(payload.get("reviewer") or "human").strip(),
        "verified_at": now,
    }

    rows = _read_verified_rows()
    replaced = False
    for idx, old in enumerate(rows):
        if old.get("candidate_id") == candidate_id:
            rows[idx] = row
            replaced = True
            break
    if not replaced:
        rows.insert(0, row)
    _write_verified_rows(rows)

    learned = False
    if payload.get("learn_to_ai"):
        strategy_memory_service.append_learning_note({
            "type": "verified_trade_review_v1",
            "title": f"已校验交割单复盘：{row.get('name') or row.get('code') or candidate_id}",
            "candidate_id": candidate_id,
            "verified_trade": row,
            "takeaways": [
                f"买点类型：{row.get('setup_type') or '未标注'}；方向：{row.get('side') or '未标注'}；置信度：{row.get('source_confidence')}",
                f"入场原因：{row.get('entry_reason') or '未填写'}",
                f"退出/结果：{row.get('exit_reason') or row.get('pnl_pct_or_amount') or '未填写'}",
                f"亏损归因：{row.get('loss_reason') or '无/未填写'}；是否按计划：{row.get('plan_followed') or '未填写'}",
            ],
        })
        learned = True

    return {
        "ok": True,
        "row": row,
        "count": len(rows),
        "verified_csv": VERIFIED_CSV,
        "learned": learned,
        "message": "已保存校验记录" + ("，并写入AI策略记忆" if learned else ""),
    }

