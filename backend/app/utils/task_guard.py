"""Lightweight in-process concurrency guard for heavy tasks."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime

from app.core.runtime_config import HEAVY_TASK_CONCURRENCY, HEAVY_TASK_TIMEOUT_SECONDS


class HeavyTaskGuard:
    def __init__(self, concurrency: int = HEAVY_TASK_CONCURRENCY):
        self._lock = threading.Lock()
        self._semaphore = threading.BoundedSemaphore(max(1, int(concurrency or 1)))
        self._running: dict[str, dict] = {}

    def acquire(self, task_key: str, label: str) -> tuple[bool, str]:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            if task_key in self._running:
                return False, f"{label}正在执行中，请等待当前任务完成。"
            if not self._semaphore.acquire(blocking=False):
                return False, "重任务并发数量已达上限，请稍后再试。"
            self._running[task_key] = {"task_key": task_key, "label": label, "started_at": now}
        return True, ""

    def release(self, task_key: str):
        should_release = False
        with self._lock:
            if task_key in self._running:
                self._running.pop(task_key, None)
                should_release = True
        if should_release:
            try:
                self._semaphore.release()
            except ValueError:
                pass

    def conflict(self, task_key: str) -> dict | None:
        with self._lock:
            task = self._running.get(task_key)
            return dict(task) if task else None


default_heavy_task_guard = HeavyTaskGuard()


async def run_limited_to_thread(task_key: str, label: str, timeout_seconds: int, func, *args, guard: HeavyTaskGuard = default_heavy_task_guard, **kwargs):
    acquired, message = guard.acquire(task_key, label)
    if not acquired:
        return {"ok": False, "error": message, "code": "TASK_ALREADY_RUNNING"}

    def _invoke_and_release():
        try:
            return func(*args, **kwargs)
        finally:
            guard.release(task_key)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_invoke_and_release), timeout=max(1, int(timeout_seconds or HEAVY_TASK_TIMEOUT_SECONDS)))
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"{label}请求超时，请稍后重试或缩小任务范围。", "code": "REQUEST_TIMEOUT"}
    except Exception:
        guard.release(task_key)
        raise
