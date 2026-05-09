"""Runtime configuration shared by the FastAPI entrypoint.

Keep environment parsing here so main_simple.py stays focused on route wiring.
"""

from __future__ import annotations

import os


HEAVY_TASK_CONCURRENCY = int(os.getenv("LIANGHUA_HEAVY_TASK_CONCURRENCY", "2") or 2)
HEAVY_TASK_TIMEOUT_SECONDS = int(os.getenv("LIANGHUA_HEAVY_TASK_TIMEOUT_SECONDS", "180") or 180)
AI_TASK_TIMEOUT_SECONDS = int(os.getenv("LIANGHUA_AI_TASK_TIMEOUT_SECONDS", "150") or 150)
BACKTEST_TIMEOUT_SECONDS = int(os.getenv("LIANGHUA_BACKTEST_TIMEOUT_SECONDS", "45") or 45)

REALTIME_SECOND_LIMIT = max(20, int(os.getenv("LIANGHUA_REALTIME_SECOND_LIMIT", "60") or 60))
REALTIME_THIRD_LIMIT = max(20, int(os.getenv("LIANGHUA_REALTIME_THIRD_LIMIT", "60") or 60))
REALTIME_BATCH_SIZE = max(10, int(os.getenv("LIANGHUA_REALTIME_BATCH_SIZE", "30") or 30))
REALTIME_LOOP_SECONDS = max(3.0, float(os.getenv("LIANGHUA_REALTIME_LOOP_SECONDS", "10") or 10))
INTRADAY_PRIORITY_SECONDS = max(30.0, float(os.getenv("LIANGHUA_INTRADAY_PRIORITY_SECONDS", "60") or 60))
