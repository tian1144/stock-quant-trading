"""
事件评分模块 - S/A/B/C分级 + 可信度 + already_priced
"""
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

from app.services import state_store

EVENT_LEVELS = {
    "S": {"score_range": (90, 100), "description": "可能影响全市场或必须暂停交易", "risk_pause": True},
    "A": {"score_range": (70, 89), "description": "影响行业或板块", "risk_pause": False},
    "B": {"score_range": (40, 69), "description": "影响单个公司", "risk_pause": False},
    "C": {"score_range": (0, 39), "description": "噪音或营销信息", "risk_pause": False},
}

S_LEVEL_KEYWORDS = ["监管禁令", "交易所事故", "战争", "重大突发", "熔断", "系统性风险", "金融风暴"]
A_LEVEL_KEYWORDS = ["降息", "加息", "政策文件", "监管动作", "SEC", "重大政策", "产业规划", "央行", "证监会", "发改委"]
B_LEVEL_KEYWORDS = ["业绩预告", "增持", "回购", "合作", "签约", "中标", "升级", "减持", "诉讼"]
C_LEVEL_KEYWORDS = ["KOL", "喊单", "传闻", "转载", "重复"]

LEVEL_RANK = {"S": 4, "A": 3, "B": 2, "C": 1}
LEVEL_WEIGHT = {"S": 1.5, "A": 1.25, "B": 1.0, "C": 0.55}
CREDIBILITY_WEIGHT = {"high": 1.0, "medium": 0.85, "low": 0.65, "unverified": 0.4}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _event_direction_sign(direction: str) -> int:
    if direction == "positive":
        return 1
    if direction == "negative":
        return -1
    return 0


def build_news_impact_factor(event_result: dict) -> dict:
    """Convert raw event scores into a score and position policy modifier."""
    events = event_result.get("events", []) or []
    if not events:
        return {
            "impact_score": 50,
            "adjusted_event_score": 50,
            "direction_bias": "neutral",
            "position_multiplier": 1.0,
            "position_cap_pct": 5,
            "action_bias": "normal",
            "risk_flags": [],
            "positive_count": 0,
            "negative_count": 0,
            "direct_event_count": 0,
            "highest_level": "C",
            "summary": "暂无直接相关新闻，事件因子按中性处理。",
        }

    signed_total = 0.0
    weight_total = 0.0
    positive_count = 0
    negative_count = 0
    low_credibility_count = 0
    high_credibility_count = 0
    top_event = max(events, key=lambda e: e.get("event_score", 0))
    highest_level = min(
        (e.get("impact_level", "C") for e in events),
        key=lambda level: {"S": 0, "A": 1, "B": 2, "C": 3}.get(level, 3),
    )

    for event in events:
        direction = event.get("direction", "neutral")
        score = float(event.get("event_score", 50))
        sign = _event_direction_sign(direction)
        if sign == 0 and score <= 40:
            sign = -1
        elif sign == 0 and score >= 70:
            sign = 1
        if sign > 0:
            positive_count += 1
        elif sign < 0:
            negative_count += 1

        credibility = event.get("credibility", "low")
        if credibility in ("high", "medium"):
            high_credibility_count += 1
        else:
            low_credibility_count += 1

        level = event.get("impact_level", "C")
        level_weight = LEVEL_WEIGHT.get(level, 0.55)
        credibility_weight = CREDIBILITY_WEIGHT.get(credibility, 0.65)
        weight = level_weight * credibility_weight
        if event.get("already_priced"):
            weight *= 0.75

        if sign == 0:
            signed_strength = (score - 50) * 0.35
        elif sign > 0:
            signed_strength = max(10, score - 45)
        else:
            signed_strength = -max(15, score)

        signed_total += signed_strength * weight
        weight_total += weight

    signed_avg = signed_total / weight_total if weight_total else 0
    impact_score = int(round(_clamp(50 + signed_avg, 0, 100)))
    adjusted_event_score = impact_score

    if impact_score >= 65:
        direction_bias = "positive"
    elif impact_score <= 40:
        direction_bias = "negative"
    else:
        direction_bias = "neutral"

    position_multiplier = 1.0
    position_cap_pct = 5
    action_bias = "normal"
    risk_flags = []

    has_s_event = highest_level == "S" or event_result.get("risk_pause", False)
    has_negative_a_or_s = any(
        (e.get("direction") == "negative" or e.get("event_score", 50) <= 40) and e.get("impact_level") in ("S", "A")
        for e in events
    )
    has_positive_a_or_s = any(
        (e.get("direction") == "positive" or e.get("event_score", 50) >= 70) and e.get("impact_level") in ("S", "A")
        for e in events
    )

    if has_s_event and negative_count:
        position_multiplier = 0.0
        position_cap_pct = 0
        action_bias = "pause"
        risk_flags.append("S级负面事件触发暂停交易")
    elif has_negative_a_or_s or impact_score <= 30:
        position_multiplier = 0.25
        position_cap_pct = 1
        action_bias = "defensive"
        risk_flags.append("高影响负面新闻压低仓位")
    elif negative_count >= 2 or impact_score <= 40:
        position_multiplier = 0.5
        position_cap_pct = 2
        action_bias = "reduce"
        risk_flags.append("新闻/公告偏负面，建议轻仓或等待澄清")
    elif has_s_event:
        position_multiplier = 0.5
        position_cap_pct = 2
        action_bias = "confirm"
        risk_flags.append("S级事件需要人工复核后再执行")
    elif has_positive_a_or_s and high_credibility_count:
        position_multiplier = 1.2
        position_cap_pct = 6
        action_bias = "upgrade"
    elif impact_score >= 65:
        position_multiplier = 1.1
        position_cap_pct = 5
        action_bias = "support"

    if positive_count and low_credibility_count >= positive_count and high_credibility_count == 0:
        position_multiplier = min(position_multiplier, 0.7)
        position_cap_pct = min(position_cap_pct, 2)
        action_bias = "verify"
        risk_flags.append("利好来源可信度不足，限制仓位")

    if top_event.get("already_priced") and direction_bias == "positive":
        position_multiplier = min(position_multiplier, 0.8)
        position_cap_pct = min(position_cap_pct, 3)
        risk_flags.append("利好可能已被价格反映")

    summary = (
        f"相关新闻{len(events)}条，最高等级{highest_level}，"
        f"正面{positive_count}条、负面{negative_count}条，影响分{impact_score}。"
    )

    return {
        "impact_score": impact_score,
        "adjusted_event_score": adjusted_event_score,
        "direction_bias": direction_bias,
        "position_multiplier": round(position_multiplier, 2),
        "position_cap_pct": position_cap_pct,
        "action_bias": action_bias,
        "risk_flags": risk_flags,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "low_credibility_count": low_credibility_count,
        "high_credibility_count": high_credibility_count,
        "direct_event_count": len(events),
        "highest_level": highest_level,
        "top_event_title": top_event.get("title", ""),
        "summary": summary,
    }


def classify_event_level(title: str, content: str = "") -> str:
    text = (title + " " + content).lower()

    for kw in S_LEVEL_KEYWORDS:
        if kw in text:
            return "S"

    for kw in A_LEVEL_KEYWORDS:
        if kw in text:
            return "A"

    for kw in B_LEVEL_KEYWORDS:
        if kw in text:
            return "B"

    return "C"


def assess_credibility(source: str, has_official_link: bool = False, source_count: int = 1) -> dict:
    official_sources = ["证监会", "央行", "发改委", "交易所", "巨潮", "统计局", "国务院", "财政部"]
    is_official = any(s in source for s in official_sources) if source else False

    if is_official or has_official_link:
        credibility = "high"
        score = 90
    elif source_count >= 2:
        credibility = "medium"
        score = 70
    elif source_count == 1:
        credibility = "low"
        score = 50
    else:
        credibility = "unverified"
        score = 20

    return {"credibility": credibility, "score": score, "is_official": is_official}


def check_already_priced(title: str, content: str, pct_change: float = 0) -> dict:
    text = title + " " + content
    priced_keywords = ["已反映", "符合预期", "如预期", "落地", "兑现"]
    is_priced = any(kw in text for kw in priced_keywords)

    if abs(pct_change) > 5:
        is_priced = True
        reaction = "充分反应"
    elif abs(pct_change) > 2:
        reaction = "部分反应"
    else:
        reaction = "未反应"

    return {"already_priced": is_priced, "market_reaction": reaction}


def score_event(title: str, content: str = "", source: str = "",
                related_symbols: List[str] = None, pct_change: float = 0, source_count: int = 1) -> dict:
    level = classify_event_level(title, content)
    level_config = EVENT_LEVELS[level]
    base_score = level_config["score_range"][0]

    credibility = assess_credibility(source, source_count=source_count)
    priced = check_already_priced(title, content, pct_change)

    positive_keywords = ["利好", "增长", "突破", "新高", "支持", "获批", "中标", "增持", "回购"]
    negative_keywords = ["利空", "下降", "违规", "处罚", "减持", "暴雷", "退市", "亏损"]

    text = title + " " + content
    direction = "neutral"
    direction_score = 0
    pos_count = sum(1 for kw in positive_keywords if kw in text)
    neg_count = sum(1 for kw in negative_keywords if kw in text)
    if pos_count > neg_count:
        direction = "positive"
        direction_score = min(20, pos_count * 10)
    elif neg_count > pos_count:
        direction = "negative"
        direction_score = -min(20, neg_count * 10)

    event_score = base_score + direction_score
    if priced["already_priced"]:
        event_score = int(event_score * 0.6)

    event_score = max(0, min(100, event_score))

    truth_status = "verified" if credibility["is_official"] else "unverified"

    return {
        "title": title,
        "summary": content[:200] if content else title,
        "impact_level": level,
        "level_description": level_config["description"],
        "risk_pause": level_config["risk_pause"],
        "direction": direction,
        "event_score": event_score,
        "credibility": credibility["credibility"],
        "credibility_score": credibility["score"],
        "already_priced": priced["already_priced"],
        "market_reaction": priced["market_reaction"],
        "truth_status": truth_status,
        "related_symbols": related_symbols or [],
        "risk_note": f"{'S级事件-暂停交易' if level == 'S' else ''}",
        "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def score_news_batch(news_list: list) -> list:
    scored = []
    for item in news_list:
        title = item.get("title", "")
        content = item.get("content", item.get("brief", ""))
        source = item.get("source", "")
        source_count = len(item.get("duplicate_sources") or [source])
        result = score_event(title, content, source, source_count=source_count)
        result["original"] = item
        scored.append(result)
    return scored


def get_event_score_for_symbol(code: str) -> dict:
    news = state_store.get_news()
    stock_info = state_store.get_stock_info(code)
    stock_name = stock_info.get("name", "") if stock_info else ""

    related_events = []
    for item in news:
        title = item.get("title", "")
        content = item.get("content", item.get("brief", ""))
        text = title + " " + content
        if code in text or stock_name in text:
            source_count = len(item.get("duplicate_sources") or [item.get("source", "")])
            scored = score_event(title, content, item.get("source", ""), source_count=source_count)
            related_events.append(scored)

    if not related_events:
        result = {"event_score": 50, "event_count": 0, "events": [], "highest_level": "C"}
        result["news_impact_factor"] = build_news_impact_factor(result)
        return result

    max_score = max(e["event_score"] for e in related_events)
    highest_level = min((e["impact_level"] for e in related_events), key=lambda x: {"S": 0, "A": 1, "B": 2, "C": 3}[x])
    has_risk_pause = any(e["risk_pause"] for e in related_events)

    result = {
        "event_score": max_score,
        "event_count": len(related_events),
        "events": related_events,
        "highest_level": highest_level,
        "risk_pause": has_risk_pause,
    }
    result["news_impact_factor"] = build_news_impact_factor(result)
    result["event_score"] = result["news_impact_factor"]["adjusted_event_score"]
    return result
