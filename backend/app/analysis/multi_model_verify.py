"""
Multi-model risk verification.

This combines local deterministic judges with an optional independent LLM risk
verifier. The independent LLM is configured separately from the primary model,
so risk control does not depend on one DeepSeek-style endpoint only.
"""
from __future__ import annotations

from datetime import datetime

from app.analysis.fund_flow_scoring import calc_fund_flow_score
from app.analysis.sentiment_scoring import calc_sentiment_score
from app.services import ai_model_service, state_store, technical_analysis


def technical_model_judge(code: str) -> dict:
    daily_df = state_store.get_daily_bars(code)
    if daily_df is None or len(daily_df) < 20:
        return {"direction": "neutral", "confidence": 0.3, "reason": "K线数据不足"}
    df = technical_analysis.calc_all_indicators(daily_df.copy())
    last = df.iloc[-1]
    signals = []
    if "ma5" in df.columns and "ma20" in df.columns:
        signals.append("MA5>MA20" if last["ma5"] > last["ma20"] else "MA5<MA20")
    if "macd_hist" in df.columns:
        signals.append("MACD多头" if last["macd_hist"] > 0 else "MACD空头")
    if "rsi_6" in df.columns:
        if last["rsi_6"] < 30:
            signals.append("RSI超卖")
        elif last["rsi_6"] > 70:
            signals.append("RSI超买")

    bullish = sum(1 for s in signals if s in ("MA5>MA20", "MACD多头", "RSI超卖"))
    bearish = sum(1 for s in signals if s in ("MA5<MA20", "MACD空头", "RSI超买"))
    if bullish >= 2:
        return {"direction": "long", "confidence": min(0.6 + bullish * 0.1, 0.9), "reason": "+".join(signals)}
    if bearish >= 2:
        return {"direction": "short", "confidence": min(0.6 + bearish * 0.1, 0.9), "reason": "+".join(signals)}
    return {"direction": "neutral", "confidence": 0.35, "reason": "+".join(signals) or "技术信号中性"}


def capital_model_judge(code: str) -> dict:
    fund_result = calc_fund_flow_score(code)
    main_fund = fund_result.get("main_fund", {})
    trend = fund_result.get("fund_trend", {})
    direction = "neutral"
    confidence = 0.3
    if main_fund.get("direction") == "inflow" and trend.get("trend") in ("strong_inflow", "moderate_inflow"):
        direction, confidence = "long", 0.7
    elif main_fund.get("direction") == "outflow" and trend.get("trend") == "strong_outflow":
        direction, confidence = "short", 0.7
    elif main_fund.get("direction") == "inflow":
        direction, confidence = "long", 0.5
    elif main_fund.get("direction") == "outflow":
        direction, confidence = "short", 0.5
    return {"direction": direction, "confidence": confidence, "reason": f"主力{main_fund.get('direction', 'unknown')}，趋势{trend.get('trend', 'unknown')}"}


def sentiment_model_judge(code: str) -> dict:
    sentiment_result = calc_sentiment_score(code)
    score = sentiment_result.get("sentiment_score", 50)
    if score > 65:
        return {"direction": "long", "confidence": min(0.5 + (score - 65) / 100, 0.8), "reason": f"情绪评分{score}"}
    if score < 35:
        return {"direction": "short", "confidence": min(0.5 + (35 - score) / 100, 0.8), "reason": f"情绪评分{score}"}
    return {"direction": "neutral", "confidence": 0.3, "reason": f"情绪评分{score}"}


def macro_model_judge() -> dict:
    nb = state_store.get_northbound_flow()
    nb_net = nb.get("total_net", 0) if nb else 0
    if nb_net > 3e9:
        return {"direction": "long", "confidence": 0.6, "reason": f"北向资金净流入{abs(nb_net)/1e8:.1f}亿"}
    if nb_net < -3e9:
        return {"direction": "short", "confidence": 0.6, "reason": f"北向资金净流出{abs(nb_net)/1e8:.1f}亿"}
    if nb_net > 0:
        return {"direction": "long", "confidence": 0.4, "reason": f"北向资金小幅净流入{abs(nb_net)/1e8:.1f}亿"}
    if nb_net < 0:
        return {"direction": "short", "confidence": 0.4, "reason": f"北向资金小幅净流出{abs(nb_net)/1e8:.1f}亿"}
    return {"direction": "neutral", "confidence": 0.3, "reason": "宏观资金中性或缺失"}


def external_ai_risk_judge(code: str, local_models: dict) -> dict:
    payload = {
        "code": code,
        "local_models": local_models,
        "required_dimensions": [
            "announcement_financial_risk",
            "main_retail_structure",
            "historical_rule_effectiveness",
            "short_term_position",
            "trade_plan_failure_condition",
        ],
    }
    schema = """
{
  "direction": "long|short|neutral",
  "confidence": 0.0,
  "risk_level": "low|medium|high",
  "can_execute": false,
  "veto": false,
  "reason": "中文短原因",
  "required_checks": ["需要补充核验的项目"]
}
"""
    system_prompt = (
        "你是独立的A股风控复核模型，必须比主选股模型更保守。"
        "你要复核本地技术、资金、情绪、宏观模型是否一致，并额外检查公告财报风险、主力散户结构、"
        "历史相似规则有效性、短线位置和交易计划失效条件。证据不足时输出 neutral 或 veto=true。只返回 JSON。"
    )
    parsed, meta = ai_model_service.chat_json_with_risk_verifier(system_prompt, payload, schema)
    if not parsed:
        return {
            "direction": "neutral",
            "confidence": 0.0,
            "risk_level": "unknown",
            "can_execute": False,
            "veto": False,
            "reason": meta.get("error", "风控复核模型不可用"),
            "required_checks": ["配置独立风控复核模型"],
            "ai_meta": meta,
        }
    direction = str(parsed.get("direction") or "neutral")
    if direction not in ("long", "short", "neutral"):
        direction = "neutral"
    return {
        "direction": direction,
        "confidence": float(parsed.get("confidence") or 0),
        "risk_level": parsed.get("risk_level") or "medium",
        "can_execute": bool(parsed.get("can_execute")),
        "veto": bool(parsed.get("veto")),
        "reason": parsed.get("reason") or "",
        "required_checks": parsed.get("required_checks") or [],
        "ai_meta": meta,
    }


def multi_model_verify(code: str) -> dict:
    local_models = {
        "technical": technical_model_judge(code),
        "capital": capital_model_judge(code),
        "sentiment": sentiment_model_judge(code),
        "macro": macro_model_judge(),
    }
    external_ai = external_ai_risk_judge(code, local_models)
    models = {**local_models, "external_ai_risk": external_ai}

    long_count = sum(1 for m in models.values() if m.get("direction") == "long")
    short_count = sum(1 for m in models.values() if m.get("direction") == "short")
    neutral_count = sum(1 for m in models.values() if m.get("direction") == "neutral")
    has_conflict = long_count >= 1 and short_count >= 1

    consensus_direction = "neutral"
    consensus_strength = 0
    if long_count >= 3 and short_count == 0:
        consensus_direction, consensus_strength = "long", long_count
    elif short_count >= 3 and long_count == 0:
        consensus_direction, consensus_strength = "short", short_count
    elif long_count >= 2 and short_count == 0:
        consensus_direction, consensus_strength = "long", long_count
    elif short_count >= 2 and long_count == 0:
        consensus_direction, consensus_strength = "short", short_count

    position_multiplier = 1.0 if consensus_strength >= 3 else 0.5 if consensus_strength == 2 else 0.0
    external_ready = bool((external_ai.get("ai_meta") or {}).get("used_ai"))
    external_veto = bool(external_ai.get("veto"))
    can_execute = consensus_strength >= 3 and not has_conflict and not external_veto

    return {
        "models": models,
        "long_count": long_count,
        "short_count": short_count,
        "neutral_count": neutral_count,
        "consensus_direction": consensus_direction,
        "consensus_strength": consensus_strength,
        "position_multiplier": position_multiplier,
        "has_conflict": has_conflict,
        "external_ai_ready": external_ready,
        "external_ai_veto": external_veto,
        "can_execute": can_execute,
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
