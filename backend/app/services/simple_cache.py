import copy
import threading
import time
from builtins import set as set_type
from typing import Any, Optional


_CACHE: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
_MAX_ITEMS = 500


TTL_REALTIME_SECONDS = 20
TTL_INTRADAY_SECONDS = 20
TTL_KLINE_SECONDS = 180
TTL_AI_ANALYSIS_SECONDS = 900
TTL_SCREENING_SECONDS = 180


def make_key(namespace: str, *parts: Any, **params: Any) -> str:
    key_parts = [namespace]
    key_parts.extend(str(part) for part in parts if part is not None)
    for name in sorted(params):
        value = params[name]
        if isinstance(value, (list, tuple, set_type)):
            value = ",".join(str(item) for item in value)
        key_parts.append(f"{name}={value}")
    return "|".join(key_parts)


def get(key: str) -> Optional[Any]:
    now = time.time()
    with _LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        if item["expires_at"] <= now:
            return None
        item["last_access"] = now
        return copy.deepcopy(item["value"])


def get_stale(key: str) -> Optional[Any]:
    with _LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        item["last_access"] = time.time()
        return copy.deepcopy(item["value"])


def set(key: str, value: Any, ttl_seconds: int) -> Any:
    now = time.time()
    with _LOCK:
        if len(_CACHE) >= _MAX_ITEMS and key not in _CACHE:
            _evict_one_unlocked()
        _CACHE[key] = {
            "value": copy.deepcopy(value),
            "created_at": now,
            "expires_at": now + max(1, int(ttl_seconds)),
            "last_access": now,
        }
    return value


def invalidate_prefix(prefix: str):
    with _LOCK:
        for key in list(_CACHE):
            if key.startswith(prefix):
                _CACHE.pop(key, None)


def mark(payload: Any, hit: bool, stale: bool = False) -> Any:
    if isinstance(payload, dict):
        result = copy.deepcopy(payload)
        result["cache"] = bool(hit)
        if stale:
            result["cache_stale"] = True
        return result
    return payload


def _evict_one_unlocked():
    if not _CACHE:
        return
    now = time.time()
    expired = [key for key, item in _CACHE.items() if item["expires_at"] <= now]
    if expired:
        _CACHE.pop(expired[0], None)
        return
    oldest = min(_CACHE.items(), key=lambda pair: pair[1].get("last_access", 0))[0]
    _CACHE.pop(oldest, None)
