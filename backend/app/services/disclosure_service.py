"""
Structured disclosure and finance-risk helpers.

This module is intentionally conservative. Public web news can hint at risks,
but formal disclosure/finance data needs a stable provider token or licensed
terminal feed. When credentials are absent we return explicit missing-source
metadata instead of pretending the risk was checked.
"""
import os
import re
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
from loguru import logger

from app.services import data_fetcher, state_store


RISK_KEYWORDS = {
    "performance": ["业绩预告", "业绩快报", "亏损", "净利润下降", "大幅下降", "商誉减值", "资产减值", "业绩雷"],
    "reduction": ["减持", "拟减持", "被动减持", "清仓式减持"],
    "inquiry": ["问询函", "监管函", "关注函", "年报问询", "交易所问询"],
    "lawsuit": ["诉讼", "仲裁", "立案", "调查", "处罚", "行政处罚"],
    "audit": ["非标", "保留意见", "无法表示意见", "否定意见", "审计报告"],
    "pledge": ["质押", "冻结", "司法冻结", "轮候冻结"],
}

DISCLOSURE_CACHE_DIR = os.path.join(data_fetcher.DATA_DIR, "disclosures")
_memory_cache: Dict[str, dict] = {}

RISK_LABELS = {
    "performance": "业绩/减值风险",
    "reduction": "股东减持风险",
    "inquiry": "监管问询风险",
    "lawsuit": "诉讼/处罚风险",
    "audit": "审计非标风险",
    "pledge": "质押/冻结风险",
}

RISK_KEYWORDS["performance"].extend(["业绩修正", "更正公告", "预亏", "退市风险警示"])
RISK_KEYWORDS["reduction"].extend(["集中竞价减持", "大宗交易减持"])
RISK_KEYWORDS["inquiry"].extend(["监管工作函", "纪律处分"])
RISK_KEYWORDS["lawsuit"].extend(["证监会立案", "被立案", "重大诉讼"])
RISK_KEYWORDS["audit"].extend(["内控否定", "带强调事项段", "持续经营重大不确定性"])
RISK_KEYWORDS["pledge"].extend(["平仓风险", "质押比例"])


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _safe_code(code: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]", "", str(code or ""))


def _cache_path(code: str) -> str:
    return os.path.join(DISCLOSURE_CACHE_DIR, f"{_safe_code(code)}.json")


def _read_cache(code: str, max_age_seconds: int = 6 * 3600) -> Optional[dict]:
    cached = _memory_cache.get(code)
    if cached and time.time() - cached.get("_cached_ts", 0) <= max_age_seconds:
        return cached.get("payload")
    path = _cache_path(code)
    if not os.path.exists(path):
        return None
    try:
        if time.time() - os.path.getmtime(path) > max_age_seconds:
            return None
        import json
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        _memory_cache[code] = {"_cached_ts": time.time(), "payload": payload}
        return payload
    except Exception:
        return None


def _write_cache(code: str, payload: dict):
    _ensure_dir(DISCLOSURE_CACHE_DIR)
    try:
        import json
        with open(_cache_path(code), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        _memory_cache[code] = {"_cached_ts": time.time(), "payload": payload}
    except Exception as exc:
        logger.warning(f"disclosure cache write failed {code}: {exc}")


def _match_risk_flags(text: str) -> List[str]:
    flags = []
    for category, words in RISK_KEYWORDS.items():
        if any(word in text for word in words):
            flags.append(category)
    return flags


def _risk_terms_for_flags(text: str, flags: List[str]) -> List[str]:
    terms = []
    for flag in flags:
        for word in RISK_KEYWORDS.get(flag, []):
            if word in text and word not in terms:
                terms.append(word)
    return terms[:8]


def _announcement_from_news(code: str, limit: int = 20) -> list:
    stock = state_store.get_stock_info(code) or {}
    name = stock.get("name", "")
    rows = []
    for item in state_store.get_news() or []:
        text = f"{item.get('title', '')} {item.get('content', '')} {item.get('brief', '')}"
        if code not in text and (not name or name not in text):
            continue
        flags = _match_risk_flags(text)
        if flags:
            rows.append({
                "title": item.get("title", ""),
                "content": item.get("content") or item.get("brief") or "",
                "source": item.get("source", ""),
                "publish_time": item.get("publish_time") or item.get("time") or "",
                "url": item.get("url", ""),
                "risk_flags": flags,
                "risk_labels": [RISK_LABELS.get(flag, flag) for flag in flags],
                "matched_terms": _risk_terms_for_flags(text, flags),
                "source_type": "news_keyword",
            })
    return rows[:limit]


def _fetch_tushare_disclosures(code: str, days: int = 180) -> tuple[list, dict]:
    token = os.getenv("TUSHARE_TOKEN", "").strip()
    if not token:
        return [], {"enabled": False, "source": "tushare", "reason": "TUSHARE_TOKEN not configured"}
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    ts_code = f"{code}.SH" if str(code).startswith("6") else f"{code}.SZ"
    payload = {
        "api_name": "anns_d",
        "token": token,
        "params": {"ts_code": ts_code, "start_date": start_date, "end_date": end_date},
        "fields": "ts_code,ann_date,ann_time,title,url",
    }
    try:
        resp = requests.post("http://api.tushare.pro", json=payload, timeout=12)
        data = resp.json()
        if data.get("code") not in (0, "0", None):
            return [], {
                "enabled": True,
                "source": "tushare",
                "status": "provider_error",
                "code": data.get("code"),
                "reason": data.get("msg") or "Tushare returned non-zero code",
            }
        fields = ((data.get("data") or {}).get("fields") or [])
        items = ((data.get("data") or {}).get("items") or [])
        rows = []
        for item in items:
            row = dict(zip(fields, item))
            text = str(row.get("title") or "")
            flags = _match_risk_flags(text)
            if flags:
                rows.append({
                    "title": row.get("title", ""),
                    "publish_time": f"{row.get('ann_date', '')} {row.get('ann_time', '')}".strip(),
                    "url": row.get("url", ""),
                    "source": "tushare_anns_d",
                    "risk_flags": flags,
                    "risk_labels": [RISK_LABELS.get(flag, flag) for flag in flags],
                    "matched_terms": _risk_terms_for_flags(text, flags),
                    "source_type": "official_disclosure",
                })
        return rows, {"enabled": True, "source": "tushare", "status": "ok", "raw_count": len(items)}
    except Exception as exc:
        return [], {"enabled": True, "source": "tushare", "status": "error", "reason": str(exc)}


def get_disclosure_risk_profile(code: str, days: int = 180, force_refresh: bool = False) -> dict:
    code = _safe_code(code)
    if not force_refresh:
        cached = _read_cache(code)
        if cached:
            return cached

    formal_rows, formal_meta = _fetch_tushare_disclosures(code, days=days)
    news_rows = _announcement_from_news(code)
    rows = formal_rows + news_rows

    category_counts: Dict[str, int] = {}
    for row in rows:
        for flag in row.get("risk_flags", []):
            category_counts[flag] = category_counts.get(flag, 0) + 1

    risk_score = 0
    weights = {
        "performance": 25,
        "reduction": 18,
        "inquiry": 22,
        "lawsuit": 20,
        "audit": 30,
        "pledge": 12,
    }
    for flag, count in category_counts.items():
        risk_score += weights.get(flag, 10) * min(count, 3)
    risk_score = min(100, risk_score)

    formal_ok = bool(formal_meta.get("enabled") and formal_meta.get("status") == "ok")
    payload = {
        "code": code,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_days": days,
        "risk_score": risk_score,
        "risk_level": "high" if risk_score >= 60 else "medium" if risk_score >= 25 else "low",
        "risk_flags": sorted(category_counts.keys()),
        "risk_labels": [RISK_LABELS.get(flag, flag) for flag in sorted(category_counts.keys())],
        "category_counts": category_counts,
        "items": rows[:30],
        "sources": {
            "formal_disclosure": formal_meta,
            "news_keyword": {"enabled": True, "source": "state_store.news", "count": len(news_rows)},
        },
        "data_status": "formal" if formal_rows else ("formal_no_risk_hit" if formal_ok else ("news_keyword_only" if news_rows else "missing_formal_source")),
        "missing": [] if formal_ok or formal_rows else ["formal_disclosure_provider"],
    }
    _write_cache(code, payload)
    return payload
