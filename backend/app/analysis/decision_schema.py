"""
决策输出结构模块 - 统一score_card.json和decision.json
"""
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

from app.services import state_store
from app.analysis.event_scoring import get_event_score_for_symbol
from app.analysis.sentiment_scoring import calc_sentiment_score
from app.analysis.kline_scoring import calc_kline_score
from app.analysis.fund_flow_scoring import calc_fund_flow_score


SCORE_WEIGHTS = {
    "short": {
        "event": 0.25, "sentiment": 0.10, "kline": 0.15,
        "technical": 0.10, "fund_flow": 0.25, "backtest": 0.05, "risk_deduction": 0.10,
    },
    "long": {
        "event": 0.35, "sentiment": 0.10, "kline": 0.10,
        "technical": 0.15, "fund_flow": 0.15, "backtest": 0.05, "risk_deduction": 0.10,
    },
    "event_driven": {
        "event": 0.45, "sentiment": 0.10, "kline": 0.10,
        "technical": 0.05, "fund_flow": 0.20, "backtest": 0.00, "risk_deduction": 0.10,
    },
}


def calc_technical_score(code: str) -> dict:
    daily_df = state_store.get_daily_bars(code)
    if daily_df is None or len(daily_df) < 20:
        return {"score": 50, "indicators": {}}

    from app.services import technical_analysis
    df = technical_analysis.calc_all_indicators(daily_df.copy())
    last = df.iloc[-1]
    score = 50

    indicators = {}
    if "ma5" in df.columns and "ma20" in df.columns:
        ma_bullish = last["ma5"] > last["ma20"]
        indicators["ma_bullish"] = ma_bullish
        score += 15 if ma_bullish else -10

    if "macd_hist" in df.columns:
        macd_positive = last["macd_hist"] > 0
        indicators["macd_positive"] = macd_positive
        score += 10 if macd_positive else -5

    if "rsi_6" in df.columns:
        rsi = last["rsi_6"]
        indicators["rsi"] = round(rsi, 1)
        if 40 <= rsi <= 60:
            score += 5
        elif rsi < 30:
            score += 10
        elif rsi > 80:
            score -= 15

    if "kdj_j" in df.columns:
        kdj_j = last["kdj_j"]
        indicators["kdj_j"] = round(kdj_j, 1)
        if kdj_j < 20:
            score += 10
        elif kdj_j > 80:
            score -= 10

    return {"score": max(0, min(100, score)), "indicators": indicators}


def calc_risk_deduction(code: str, news_impact_factor: dict = None) -> dict:
    deductions = []
    total_deduction = 0

    stock_info = state_store.get_stock_info(code)
    if stock_info:
        name = stock_info.get("name", "")
        if "ST" in name.upper():
            deductions.append({"reason": "ST股票", "deduction": -30})
            total_deduction += 30

    realtime = state_store.get_realtime(code)
    if realtime:
        pct = realtime.get("pct_change", 0)
        if abs(pct) > 9.5:
            deductions.append({"reason": "涨跌停附近", "deduction": -15})
            total_deduction += 15

        volume = realtime.get("volume", 0)
        if volume < 100000:
            deductions.append({"reason": "成交量极低", "deduction": -10})
            total_deduction += 10

    negative_news = state_store.get_negative_news()
    if code in negative_news:
        deductions.append({"reason": "有负面新闻", "deduction": -15})
        total_deduction += 15

    news_impact_factor = news_impact_factor or {}
    impact_score = news_impact_factor.get("impact_score", 50)
    multiplier = news_impact_factor.get("position_multiplier", 1.0)
    negative_count = news_impact_factor.get("negative_count", 0)
    if multiplier == 0:
        deductions.append({"reason": "新闻/公告触发暂停交易", "deduction": -30})
        total_deduction += 30
    elif impact_score <= 30:
        deductions.append({"reason": "新闻/公告影响分过低", "deduction": -20})
        total_deduction += 20
    elif impact_score <= 40 or negative_count >= 2:
        deductions.append({"reason": "新闻/公告偏负面，降低评分", "deduction": -12})
        total_deduction += 12
    elif news_impact_factor.get("action_bias") in ("verify", "confirm"):
        deductions.append({"reason": "新闻/公告仍需核验", "deduction": -8})
        total_deduction += 8

    return {"deduction": min(40, total_deduction), "details": deductions}


def build_position_policy(final_score: float, news_impact_factor: dict) -> dict:
    """Bind score and news impact into a conservative position policy."""
    if final_score >= 80:
        base_pct = 5
        base_text = "强候选"
    elif final_score >= 70:
        base_pct = 3
        base_text = "候选"
    elif final_score >= 60:
        base_pct = 0
        base_text = "观察"
    else:
        base_pct = 0
        base_text = "回避"

    multiplier = float(news_impact_factor.get("position_multiplier", 1.0))
    cap_pct = float(news_impact_factor.get("position_cap_pct", 5))
    adjusted_pct = min(base_pct * multiplier, cap_pct)
    if final_score < 70:
        adjusted_pct = 0
    adjusted_pct = round(adjusted_pct, 1)

    action_bias = news_impact_factor.get("action_bias", "normal")
    if action_bias == "pause" or adjusted_pct <= 0:
        suggestion = "建议观察，暂不建仓"
        if action_bias == "pause":
            suggestion = "新闻/公告触发暂停交易，建议仓位0%"
    elif adjusted_pct < base_pct:
        suggestion = f"建议仓位不超过{adjusted_pct:g}%（新闻/公告因子降仓）"
    elif adjusted_pct > base_pct:
        suggestion = f"建议仓位{adjusted_pct:g}%以内（{base_text}，新闻/公告因子支持）"
    else:
        suggestion = f"建议仓位{adjusted_pct:g}%以内（{base_text}）"

    return {
        "base_position_pct": base_pct,
        "news_multiplier": multiplier,
        "news_cap_pct": cap_pct,
        "suggested_position_pct": adjusted_pct,
        "action_bias": action_bias,
        "suggestion": suggestion,
        "risk_flags": news_impact_factor.get("risk_flags", []),
    }


def generate_score_card(code: str, strategy_type: str = "short") -> dict:
    settings = state_store.get_user_settings()
    strategy_type = strategy_type or settings.get("trading_style", "short")
    weights = SCORE_WEIGHTS.get(strategy_type, SCORE_WEIGHTS["short"])

    event_result = get_event_score_for_symbol(code)
    news_impact_factor = event_result.get("news_impact_factor", {})
    event_score = event_result["event_score"]

    sentiment_result = calc_sentiment_score(code)
    sentiment_score = sentiment_result["sentiment_score"]

    daily_df = state_store.get_daily_bars(code)
    kline_result = calc_kline_score(daily_df)
    kline_score = kline_result["kline_score"]

    tech_result = calc_technical_score(code)
    technical_score = tech_result["score"]

    fund_result = calc_fund_flow_score(code)
    fund_flow_score = fund_result["fund_flow_score"]

    backtest_score = 50

    risk_result = calc_risk_deduction(code, news_impact_factor)
    risk_deduction = risk_result["deduction"]

    final_score = (
        event_score * weights["event"] +
        sentiment_score * weights["sentiment"] +
        kline_score * weights["kline"] +
        technical_score * weights["technical"] +
        fund_flow_score * weights["fund_flow"] +
        backtest_score * weights["backtest"] -
        risk_deduction
    )
    final_score = max(0, min(100, round(final_score, 1)))

    if final_score >= 80:
        decision = "strong_candidate"
    elif final_score >= 70:
        decision = "candidate"
    elif final_score >= 60:
        decision = "watch"
    else:
        decision = "avoid"

    confidence = round(final_score / 100, 2)
    position_policy = build_position_policy(final_score, news_impact_factor)
    need_human = (
        final_score < 75
        or event_result.get("risk_pause", False)
        or bool(news_impact_factor.get("risk_flags"))
        or news_impact_factor.get("action_bias") in ("verify", "confirm", "pause")
    )

    stock_info = state_store.get_stock_info(code)
    stock_name = stock_info.get("name", "") if stock_info else ""

    return {
        "market": "a_stock",
        "symbol": code,
        "stock_name": stock_name,
        "timeframe": "1d",
        "strategy_type": strategy_type,
        "scores": {
            "event_score": event_score,
            "news_impact_score": news_impact_factor.get("impact_score", 50),
            "sentiment_score": sentiment_score,
            "kline_score": kline_score,
            "technical_score": technical_score,
            "fund_flow_score": fund_flow_score,
            "backtest_score": backtest_score,
            "risk_deduction": risk_deduction,
        },
        "score_details": {
            "event": event_result,
            "news_impact_factor": news_impact_factor,
            "sentiment": sentiment_result,
            "kline": kline_result,
            "technical": tech_result,
            "fund_flow": fund_result,
            "risk": risk_result,
        },
        "final_score": final_score,
        "decision": decision,
        "confidence": confidence,
        "position_policy": position_policy,
        "need_human_confirm": need_human,
        "risk_pause": event_result.get("risk_pause", False),
        "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def generate_decision(code: str, strategy_type: str = "short") -> dict:
    score_card = generate_score_card(code, strategy_type)

    stock_info = state_store.get_stock_info(code)
    stock_name = stock_info.get("name", "") if stock_info else ""
    realtime = state_store.get_realtime(code)
    price = realtime.get("price", 0) if realtime else 0

    direction = "wait"
    if score_card["final_score"] >= 70:
        direction = "long"
    elif score_card["final_score"] < 40:
        direction = "short"

    news_impact_factor = score_card["score_details"].get("news_impact_factor", {})
    if news_impact_factor.get("action_bias") in ("pause", "defensive") and direction == "long":
        direction = "wait"

    market_state = "range"
    sentiment = score_card["score_details"].get("sentiment", {})
    if sentiment.get("sentiment_score", 50) > 70:
        market_state = "fomo"
    elif sentiment.get("sentiment_score", 50) < 30:
        market_state = "panic"
    elif score_card["scores"]["kline_score"] > 65:
        market_state = "trend"
    if news_impact_factor.get("direction_bias") == "negative":
        market_state = "event_risk"
    elif news_impact_factor.get("direction_bias") == "positive" and news_impact_factor.get("impact_score", 50) >= 70:
        market_state = "event_driven"

    entry_condition = ""
    invalid_condition = ""
    if direction == "long":
        tech = score_card["score_details"].get("technical", {})
        if tech.get("indicators", {}).get("ma_bullish"):
            entry_condition = "MA5>MA20确认，价格回踩MA5附近可入场"
        else:
            entry_condition = "等待MA5上穿MA20确认后入场"
        invalid_condition = "MA5下穿MA20或跌破支撑位，原逻辑失效"
    elif direction == "short":
        entry_condition = "技术面转弱确认后考虑减仓"
        invalid_condition = "技术面重新走强，空头逻辑失效"

    stop_loss = round(price * 0.95, 2) if price > 0 else ""
    take_profit = round(price * 1.10, 2) if price > 0 else ""

    if strategy_type == "long":
        stop_loss = round(price * 0.92, 2) if price > 0 else ""
        take_profit = round(price * 1.25, 2) if price > 0 else ""
    elif strategy_type == "event_driven":
        stop_loss = round(price * 0.94, 2) if price > 0 else ""
        take_profit = round(price * 1.12, 2) if price > 0 else ""
        if direction == "long":
            entry_condition = "事件影响分和资金确认同时成立后，只做短窗口模拟跟踪"
            invalid_condition = "事件证伪、情绪转负或资金承接不足，立即退出观察"

    reason_summary = []
    scores = score_card["scores"]
    if news_impact_factor.get("direct_event_count", 0) > 0:
        reason_summary.append(news_impact_factor.get("summary", "新闻/公告因子已纳入评分"))
    if scores["event_score"] >= 70:
        reason_summary.append("事件评分高")
    if scores["fund_flow_score"] >= 70:
        reason_summary.append("资金流入确认")
    if scores["kline_score"] >= 70:
        reason_summary.append("K线结构良好")
    if scores["technical_score"] >= 70:
        reason_summary.append("技术面支持")
    if scores["risk_deduction"] > 0:
        reason_summary.append(f"风险扣分{scores['risk_deduction']}")

    conflict_signals = []
    if scores["event_score"] >= 70 and scores["fund_flow_score"] < 40:
        conflict_signals.append("事件利好但资金流出")
    if scores["sentiment_score"] > 70 and scores["kline_score"] < 40:
        conflict_signals.append("情绪乐观但K线走弱")
    if news_impact_factor.get("direction_bias") == "negative" and scores["fund_flow_score"] >= 60:
        conflict_signals.append("资金尚可但新闻/公告偏负面")
    for flag in news_impact_factor.get("risk_flags", []):
        conflict_signals.append(flag)

    position_policy = score_card.get("position_policy", {})
    position_suggestion = position_policy.get("suggestion", "建议观察，暂不建仓")

    return {
        "symbol": code,
        "stock_name": stock_name,
        "market_state": market_state,
        "direction": direction,
        "final_score": score_card["final_score"],
        "confidence": score_card["confidence"],
        "entry_condition": entry_condition,
        "invalid_condition": invalid_condition,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "position_suggestion": position_suggestion,
        "position_policy": position_policy,
        "news_impact_factor": news_impact_factor,
        "reason_summary": reason_summary,
        "conflict_signals": conflict_signals,
        "need_human_confirm": score_card["need_human_confirm"],
        "score_card": score_card,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
