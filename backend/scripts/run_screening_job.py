"""Run a screening job outside the FastAPI process.

The web server starts this script as a child process, then polls the JSON file
written here. Keeping the heavy full-market scan out of the API process keeps
health checks and progress polling responsive.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PROJECT_ROOT = os.path.abspath(os.path.join(BACKEND_ROOT, ".."))
JOB_DIR = os.path.join(BACKEND_ROOT, "data", "jobs", "screening")

if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.services import agent_workspace, data_fetcher, state_store, stock_screener  # noqa: E402


def _json_safe(value):
    try:
        import numpy as np
        import pandas as pd
    except Exception:
        np = None
        pd = None
    if pd is not None and value is pd.NA:
        return None
    if np is not None and isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
        return None
    return value


def _safe_job_id(job_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", str(job_id or "screening-job"))


def _job_path(job_id: str) -> str:
    return os.path.join(JOB_DIR, f"{_safe_job_id(job_id)}.json")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _write_job(job: dict):
    os.makedirs(JOB_DIR, exist_ok=True)
    path = _job_path(job.get("job_id"))
    tmp_path = f"{path}.tmp"
    job["updated_at"] = _now()
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(_json_safe(job), f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _read_job(job_id: str) -> dict:
    path = _job_path(job_id)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _ensure_stock_universe():
    if state_store.get_stock_universe():
        return
    stocks = data_fetcher.read_stock_universe_cache() or []
    if not stocks:
        stocks = data_fetcher.fetch_all_stocks_eastmoney() or []
    state_store.update_stock_universe(stocks)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--strategy", default="")
    args = parser.parse_args()

    started = time.time()
    strategy = args.strategy if args.strategy in ("short", "long", "event_driven") else None
    job = _read_job(args.job_id) or {
        "job_id": args.job_id,
        "created_at": _now(),
        "params": {"strategy": strategy},
    }
    job.update({
        "status": "running",
        "stage": "prepare",
        "message": "正在准备股票池",
        "started_at": _now(),
        "finished_at": None,
        "result": None,
        "error": None,
    })
    _write_job(job)

    try:
        if strategy:
            state_store.update_user_settings({"trading_style": strategy})
        _ensure_stock_universe()
        total = len(state_store.get_stock_universe())
        job.update({
            "stage": "screening",
            "message": f"正在运行智能选股：全市场{total}只，策略={strategy or state_store.get_user_settings().get('trading_style', 'short')}",
            "total": total,
        })
        _write_job(job)

        def progress_callback(progress: dict):
            job.update(progress or {})
            _write_job(job)

        results = stock_screener.run_screening(strategy=strategy, progress_callback=progress_callback)
        state_store.update_system_state({"last_screening_time": _now()})
        agent_workspace.record_event("score", "screening", f"后台选股完成：{len(results)} 个候选。")
        result = {
            "message": "选股完成",
            "count": len(results),
            "results": _json_safe(results),
            "logic": stock_screener.get_screening_logic_summary(),
            "elapsed_seconds": round(time.time() - started, 1),
        }
        job.update({
            "status": "done",
            "stage": "done",
            "message": f"选股完成：{len(results)}只候选",
            "done": len(results),
            "result": result,
            "finished_at": _now(),
        })
        _write_job(job)
        return 0
    except Exception as exc:
        job.update({
            "status": "failed",
            "stage": "failed",
            "message": f"选股失败：{exc}",
            "error": str(exc),
            "finished_at": _now(),
        })
        _write_job(job)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
