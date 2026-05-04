"""
情绪评分模块 - 基于新闻情绪、市场涨跌比、北向资金等
"""
from datetime import datetime
from typing import Dict, Optional
from loguru import logger

from app.services import state_store


FOMO_KEYWORDS = ["牛市", "暴涨", "疯涨", "历史新高", "全民炒股", "跑步入场", "满仓"]
PANIC_KEYWORDS = ["暴跌", "崩盘", "股灾", "恐慌", "熔断", "千股跌停", "熊市"]


def calc_news_sentiment_score(news: list) -> dict:
    if not news:
        return {"score": 50, "level": "neutral", "fomo_detected": False, "panic_detected": False}

    positive_count = 0
    negative_count = 0
    fomo_count = 0
    panic_count = 0

    positive_kw = ["利好", "增长", "突破", "新高", "支持", "增持", "回购", "超预期"]
    negative_kw = ["利空", "下降", "违规", "处罚", "减持", "暴雷", "退市", "亏损"]

    for item in news:
        text = item.get("title", "") + " " + item.get("content", "")
        pos_hit = any(kw in text for kw in positive_kw)
        neg_hit = any(kw in text for kw in negative_kw)
        if pos_hit:
            positive_count += 1
        if neg_hit:
            negative_count += 1
        if any(kw in text for kw in FOMO_KEYWORDS):
            fomo_count += 1
        if any(kw in text for kw in PANIC_KEYWORDS):
            panic_count += 1

    total = positive_count + negative_count
    if total > 0:
        raw_score = (positive_count - negative_count) / total * 50 + 50
    else:
        raw_score = 50

    fomo_deduction = min(20, fomo_count * 5)
    panic_deduction = min(15, panic_count * 5)

    score = raw_score - fomo_deduction
    score = max(0, min(100, score))

    if score > 70:
        level = "greedy"
    elif score > 55:
        level = "optimistic"
    elif score > 45:
        level = "neutral"
    elif score > 30:
        level = "pessimistic"
    else:
        level = "fearful"

    return {
        "score": round(score, 1),
        "level": level,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "fomo_detected": fomo_count > 0,
        "fomo_count": fomo_count,
        "panic_detected": panic_count > 0,
        "panic_count": panic_count,
        "fomo_deduction": fomo_deduction,
    }


def calc_market_breadth_score() -> dict:
    universe = state_store.get_stock_universe()
    if not universe:
        return {"score": 50, "advance_ratio": 0.5, "up_count": 0, "down_count": 0}

    up_count = sum(1 for s in universe.values() if s.get("pct_change", 0) > 0)
    down_count = sum(1 for s in universe.values() if s.get("pct_change", 0) < 0)
    flat_count = sum(1 for s in universe.values() if s.get("pct_change", 0) == 0)
    total = up_count + down_count

    advance_ratio = up_count / total if total > 0 else 0.5
    score = advance_ratio * 100

    return {
        "score": round(score, 1),
        "advance_ratio": round(advance_ratio, 3),
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
    }


def calc_northbound_sentiment_score() -> dict:
    nb = state_store.get_northbound_flow()
    net_flow = nb.get("total_net", 0) if nb else 0

    if net_flow > 5e9:
        score = 85
    elif net_flow > 2e9:
        score = 70
    elif net_flow > 0:
        score = 60
    elif net_flow > -2e9:
        score = 40
    elif net_flow > -5e9:
        score = 25
    else:
        score = 15

    direction = "inflow" if net_flow > 0 else "outflow"

    return {
        "score": score,
        "direction": direction,
        "net_flow": net_flow,
    }


def calc_sentiment_score(code: str = None) -> dict:
    news = state_store.get_news()
    news_sentiment = calc_news_sentiment_score(news)
    market_breadth = calc_market_breadth_score()
    northbound = calc_northbound_sentiment_score()

    weights = {"news": 0.40, "breadth": 0.35, "northbound": 0.25}
    final_score = (
        news_sentiment["score"] * weights["news"] +
        market_breadth["score"] * weights["breadth"] +
        northbound["score"] * weights["northbound"]
    )

    is_extreme = news_sentiment.get("fomo_detected") or news_sentiment.get("panic_detected")
    contrarian_signal = None
    if news_sentiment.get("panic_detected") and final_score < 30:
        contrarian_signal = "possible_bottom"
    elif news_sentiment.get("fomo_detected") and final_score > 80:
        contrarian_signal = "possible_top"

    return {
        "sentiment_score": round(final_score, 1),
        "news_sentiment": news_sentiment,
        "market_breadth": market_breadth,
        "northbound_sentiment": northbound,
        "is_extreme": is_extreme,
        "contrarian_signal": contrarian_signal,
        "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
