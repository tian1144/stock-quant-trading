"""
Backtest context helpers.

This module keeps event/sentiment data on the same time axis as the K-line
loop. When historical news is not available for a day, it returns neutral
news context instead of leaking today's news into old trades.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

from app.analysis.event_scoring import score_event


POSITIVE_WORDS = [
    "利好", "增长", "中标", "订单", "回购", "增持", "突破", "盈利", "上调",
    "批准", "合作", "签约", "创新高", "景气", "复苏",
]
NEGATIVE_WORDS = [
    "利空", "下滑", "亏损", "减持", "处罚", "调查", "风险", "暴跌", "违约",
    "终止", "诉讼", "退市", "爆雷", "监管", "澄清",
]
PANIC_WORDS = ["暴跌", "恐慌", "崩盘", "踩踏", "系统性风险"]
FOMO_WORDS = ["涨停潮", "抢筹", "逼空", "爆发", "疯狂", "大涨"]
ANNOUNCEMENT_WORDS = [
    "公告", "业绩预告", "定增", "重组", "停牌", "复牌", "减持计划", "增持计划",
    "回购方案", "股权激励", "重大合同", "诉讼", "监管函", "问询函",
]
OFFICIAL_SOURCES = ["交易所", "巨潮", "上交所", "深交所", "北交所", "证监会", "公告"]


def build_context_provider(
    news: Optional[List[dict]] = None,
    stock_name: str = "",
    market_snapshot: Optional[dict] = None,
    sentiment_snapshot: Optional[dict] = None,
    news_window_days: int = 3,
    announcement_window_days: int = 5,
) -> Callable[[pd.DataFrame, int, str], dict]:
    prepared_news = [_prepare_news_item(item) for item in (news or [])]

    def provider(df: pd.DataFrame, idx: int, symbol: str = "") -> dict:
        row = df.iloc[idx]
        date = _parse_date(row.get("timestamp", row.get("date", None)))
        price_context = _build_price_market_state(df, idx)
        related_news = _filter_news(prepared_news, symbol, stock_name, date, news_window_days, category="news")
        related_announcements = _filter_news(
            prepared_news, symbol, stock_name, date, announcement_window_days, category="announcement"
        )
        news_context = _score_news(related_news, category="news")
        announcement_context = _score_news(related_announcements, category="announcement")
        snapshot_context = _normalize_market_snapshot(
            market_snapshot if _snapshot_available_on(market_snapshot, date) else None
        )
        sentiment_context = _normalize_sentiment_snapshot(
            sentiment_snapshot if _snapshot_available_on(sentiment_snapshot, date) else None
        )

        market_score = price_context["market_score"]
        if snapshot_context["breadth_score"] is not None:
            market_score = round(market_score * 0.75 + snapshot_context["breadth_score"] * 0.25, 1)

        combined_score = round(
            news_context["score"] * 0.25
            + announcement_context["score"] * 0.20
            + sentiment_context["score"] * 0.20
            + market_score * 0.35,
            1,
        )
        risk_pause = (
            news_context["risk_pause"]
            or announcement_context["risk_pause"]
            or sentiment_context["risk_pause"]
            or combined_score <= 25
            or price_context["regime"] == "stress"
        )
        exposure_multiplier = _calc_exposure_multiplier(
            combined_score, news_context, announcement_context, sentiment_context, price_context
        )

        return {
            "date": date.strftime("%Y-%m-%d") if date else str(row.get("timestamp", row.get("date", idx)))[:10],
            "combined_score": combined_score,
            "news": news_context,
            "announcement": announcement_context,
            "sentiment_env": sentiment_context,
            "market": {
                **price_context,
                "breadth_score": snapshot_context["breadth_score"],
                "snapshot_level": snapshot_context["level"],
            },
            "risk_pause": risk_pause,
            "allow_buy": not risk_pause and combined_score >= 35,
            "risk_exit": risk_pause or combined_score <= 20,
            "exposure_multiplier": exposure_multiplier,
            "reason": _build_context_reason(
                combined_score, news_context, announcement_context, sentiment_context, price_context, risk_pause
            ),
        }

    return provider


def summarize_backtest_context(context_history: Iterable[dict]) -> dict:
    items = list(context_history or [])
    if not items:
        return {
            "enabled": False,
            "coverage_days": 0,
            "avg_combined_score": 50,
            "risk_pause_days": 0,
            "news_event_days": 0,
            "announcement_event_days": 0,
            "extreme_sentiment_days": 0,
            "regime_counts": {},
            "note": "No context history was produced.",
        }

    regime_counts: Dict[str, int] = {}
    for item in items:
        regime = item.get("market", {}).get("regime", "unknown")
        regime_counts[regime] = regime_counts.get(regime, 0) + 1

    scores = [float(item.get("combined_score", 50)) for item in items]
    news_scores = [float(item.get("news", {}).get("score", 50)) for item in items]
    announcement_scores = [float(item.get("announcement", {}).get("score", 50)) for item in items]
    sentiment_scores = [float(item.get("sentiment_env", {}).get("score", 50)) for item in items]
    risk_pause_days = sum(1 for item in items if item.get("risk_pause"))
    news_event_days = sum(1 for item in items if item.get("news", {}).get("matched_count", 0) > 0)
    announcement_event_days = sum(1 for item in items if item.get("announcement", {}).get("matched_count", 0) > 0)
    extreme_sentiment_days = sum(1 for item in items if item.get("sentiment_env", {}).get("is_extreme"))

    return {
        "enabled": True,
        "model": "news_announcement_sentiment_market",
        "coverage_days": len(items),
        "avg_combined_score": round(sum(scores) / len(scores), 1),
        "min_combined_score": round(min(scores), 1),
        "max_combined_score": round(max(scores), 1),
        "avg_news_score": round(sum(news_scores) / len(news_scores), 1),
        "avg_announcement_score": round(sum(announcement_scores) / len(announcement_scores), 1),
        "avg_sentiment_score": round(sum(sentiment_scores) / len(sentiment_scores), 1),
        "risk_pause_days": risk_pause_days,
        "risk_pause_pct": round(risk_pause_days / len(items) * 100, 1),
        "news_event_days": news_event_days,
        "news_coverage_pct": round(news_event_days / len(items) * 100, 1),
        "announcement_event_days": announcement_event_days,
        "announcement_coverage_pct": round(announcement_event_days / len(items) * 100, 1),
        "extreme_sentiment_days": extreme_sentiment_days,
        "regime_counts": regime_counts,
        "note": "News, announcements and sentiment are matched by event timestamp and never applied before they exist.",
    }


def _prepare_news_item(item: dict) -> dict:
    text = f"{item.get('title', '')} {item.get('content', '')}"
    source = item.get("source", "")
    scored = score_event(item.get("title", ""), item.get("content", item.get("brief", "")), source)
    return {
        **item,
        "_date": _parse_date(item.get("time") or item.get("datetime") or item.get("created_at")),
        "_text": text,
        "_category": _classify_event_category(item, text, source),
        "_event_score": scored.get("event_score", 50),
        "_impact_level": scored.get("impact_level", "C"),
        "_direction": scored.get("direction", "neutral"),
        "_credibility": scored.get("credibility", "low"),
        "_risk_pause": scored.get("risk_pause", False),
    }


def _parse_date(value) -> Optional[datetime]:
    if value is None or value == "":
        return None


def _snapshot_available_on(snapshot: Optional[dict], date: Optional[datetime], max_age_days: int = 1) -> bool:
    if not snapshot or date is None:
        return False
    snapshot_date = _parse_date(
        snapshot.get("scored_at")
        or snapshot.get("updated_at")
        or snapshot.get("time")
        or snapshot.get("date")
    )
    if snapshot_date is None:
        return False
    delta_days = (date.date() - snapshot_date.date()).days
    return 0 <= delta_days <= max_age_days
    if isinstance(value, datetime):
        return value
    try:
        return pd.to_datetime(value).to_pydatetime()
    except Exception:
        return None


def _classify_event_category(item: dict, text: str, source: str) -> str:
    explicit_type = str(item.get("type") or item.get("category") or "").lower()
    if "announce" in explicit_type or "公告" in explicit_type:
        return "announcement"
    if any(word in text for word in ANNOUNCEMENT_WORDS) or any(src in source for src in OFFICIAL_SOURCES):
        return "announcement"
    return "news"


def _filter_news(
    news: List[dict],
    symbol: str,
    stock_name: str,
    date: Optional[datetime],
    window_days: int,
    category: str = "news",
) -> List[dict]:
    if not news or date is None:
        return []
    start = date - timedelta(days=max(0, window_days - 1))
    result = []
    for item in news:
        item_date = item.get("_date")
        if item_date is None or item_date.date() < start.date() or item_date.date() > date.date():
            continue
        if item.get("_category") != category:
            continue
        text = item.get("_text", "")
        if symbol and symbol in text:
            result.append(item)
        elif stock_name and stock_name in text:
            result.append(item)
        elif not symbol and not stock_name:
            result.append(item)
    return sorted(result, key=lambda x: (x.get("_date") or date), reverse=True)


def _score_news(news: List[dict], category: str = "news") -> dict:
    if not news:
        return {
            "score": 50,
            "level": "neutral",
            "category": category,
            "matched_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "s_level_count": 0,
            "a_level_count": 0,
            "risk_pause": False,
            "headline_samples": [],
        }

    positive = 0
    negative = 0
    panic = 0
    fomo = 0
    impact_scores = []
    s_level = 0
    a_level = 0
    for item in news:
        text = item.get("_text", "")
        positive += int(any(word in text for word in POSITIVE_WORDS))
        negative += int(any(word in text for word in NEGATIVE_WORDS))
        panic += int(any(word in text for word in PANIC_WORDS))
        fomo += int(any(word in text for word in FOMO_WORDS))
        impact_scores.append(float(item.get("_event_score", 50)))
        s_level += int(item.get("_impact_level") == "S")
        a_level += int(item.get("_impact_level") == "A")
        if item.get("_direction") == "positive":
            positive += 1
        elif item.get("_direction") == "negative":
            negative += 1

    total = positive + negative
    direction_score = 50 if total == 0 else 50 + (positive - negative) / total * 35
    impact_score = sum(impact_scores) / len(impact_scores) if impact_scores else 50
    score = direction_score * 0.60 + impact_score * 0.40
    score = max(0, min(100, score - min(15, panic * 5) - min(10, fomo * 3)))

    if score >= 70:
        level = "positive"
    elif score >= 55:
        level = "mild_positive"
    elif score >= 45:
        level = "neutral"
    elif score >= 30:
        level = "negative"
    else:
        level = "panic"

    return {
        "score": round(score, 1),
        "level": level,
        "category": category,
        "matched_count": len(news),
        "positive_count": positive,
        "negative_count": negative,
        "panic_count": panic,
        "fomo_count": fomo,
        "s_level_count": s_level,
        "a_level_count": a_level,
        "risk_pause": s_level > 0 or panic > 0 or (category == "announcement" and negative >= 1) or negative >= 2,
        "headline_samples": [item.get("title", "") for item in news[:3]],
        "event_samples": [
            {
                "title": item.get("title", ""),
                "time": item.get("time", ""),
                "source": item.get("source", ""),
                "impact_level": item.get("_impact_level", "C"),
                "event_score": item.get("_event_score", 50),
                "direction": item.get("_direction", "neutral"),
                "credibility": item.get("_credibility", "low"),
            }
            for item in news[:3]
        ],
    }


def _build_price_market_state(df: pd.DataFrame, idx: int) -> dict:
    close = pd.to_numeric(df["close"].iloc[: idx + 1], errors="coerce")
    current = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else current
    ma20 = float(close.tail(20).mean()) if len(close) >= 20 else current
    momentum_5d = (current / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 and close.iloc[-6] else 0
    volatility_20d = float(close.pct_change().tail(20).std() * 100) if len(close) >= 20 else 0
    pct_change = (current / prev - 1) * 100 if prev else 0
    ma_gap_pct = (current / ma20 - 1) * 100 if ma20 else 0

    score = 50 + ma_gap_pct * 2 + momentum_5d * 1.5 - max(0, volatility_20d - 3) * 2
    score = max(0, min(100, score))

    if pct_change <= -7 or (ma_gap_pct < -8 and volatility_20d > 5):
        regime = "stress"
    elif ma_gap_pct >= 3 and momentum_5d > 0:
        regime = "bullish"
    elif ma_gap_pct <= -3 and momentum_5d < 0:
        regime = "bearish"
    else:
        regime = "neutral"

    return {
        "market_score": round(score, 1),
        "regime": regime,
        "pct_change": round(pct_change, 2),
        "ma20_gap_pct": round(ma_gap_pct, 2),
        "momentum_5d_pct": round(momentum_5d, 2),
        "volatility_20d_pct": round(volatility_20d, 2),
    }


def _normalize_market_snapshot(snapshot: Optional[dict]) -> dict:
    if not snapshot:
        return {"breadth_score": None, "level": "unknown"}
    if "sentiment_score" in snapshot:
        score = float(snapshot.get("sentiment_score", 0))
        return {"breadth_score": round((score + 100) / 2, 1), "level": snapshot.get("level", "snapshot")}
    if "advance_ratio" in snapshot:
        ratio = float(snapshot.get("advance_ratio", 50))
        return {"breadth_score": round(ratio if ratio > 1 else ratio * 100, 1), "level": snapshot.get("level", "snapshot")}
    return {"breadth_score": None, "level": snapshot.get("level", "unknown")}


def _normalize_sentiment_snapshot(snapshot: Optional[dict]) -> dict:
    if not snapshot:
        return {"score": 50, "level": "neutral", "is_extreme": False, "risk_pause": False, "contrarian_signal": None}
    raw_score = snapshot.get("sentiment_score", snapshot.get("score", 50))
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        score = 50
    if score < 0:
        score = (score + 100) / 2
    news_sentiment = snapshot.get("news_sentiment", {}) if isinstance(snapshot.get("news_sentiment"), dict) else {}
    is_extreme = bool(snapshot.get("is_extreme") or news_sentiment.get("panic_detected") or news_sentiment.get("fomo_detected"))
    return {
        "score": round(max(0, min(100, score)), 1),
        "level": snapshot.get("level") or news_sentiment.get("level", "neutral"),
        "is_extreme": is_extreme,
        "risk_pause": bool(news_sentiment.get("panic_detected")) or score <= 25,
        "contrarian_signal": snapshot.get("contrarian_signal"),
        "market_breadth": snapshot.get("market_breadth", {}),
        "northbound_sentiment": snapshot.get("northbound_sentiment", {}),
    }


def _calc_exposure_multiplier(
    combined_score: float,
    news_context: dict,
    announcement_context: dict,
    sentiment_context: dict,
    market_context: dict,
) -> float:
    if (
        news_context.get("risk_pause")
        or announcement_context.get("risk_pause")
        or sentiment_context.get("risk_pause")
        or market_context.get("regime") == "stress"
    ):
        return 0.0
    if combined_score >= 75:
        return 1.1
    if combined_score >= 60:
        return 0.9
    if combined_score >= 45:
        return 0.65
    if combined_score >= 35:
        return 0.35
    return 0.0


def _build_context_reason(
    combined_score: float,
    news_context: dict,
    announcement_context: dict,
    sentiment_context: dict,
    market_context: dict,
    risk_pause: bool,
) -> str:
    parts = [
        f"context_score={combined_score}",
        f"news={news_context.get('level')}",
        f"announcement={announcement_context.get('level')}",
        f"sentiment={sentiment_context.get('level')}",
        f"market={market_context.get('regime')}",
    ]
    if news_context.get("matched_count", 0):
        parts.append(f"news_events={news_context.get('matched_count')}")
    if announcement_context.get("matched_count", 0):
        parts.append(f"announcements={announcement_context.get('matched_count')}")
    if risk_pause:
        parts.append("risk_pause")
    return ", ".join(parts)
