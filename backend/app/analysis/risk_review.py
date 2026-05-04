"""
风控复核模块 - 副模型一票否决 + risk_report.json
"""
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

from app.services import state_store, risk_manager
from app.analysis.multi_model_verify import multi_model_verify


def risk_review(decision: dict) -> dict:
    code = decision.get("symbol", "")
    final_score = decision.get("final_score", 0)
    direction = decision.get("direction", "wait")

    veto_reasons = []
    required_checks = []
    risk_level = "low"
    approved = True
    position_limit = ""
    score_card = decision.get("score_card", {})
    news_factor = score_card.get("score_details", {}).get("news_impact_factor", {})
    position_policy = score_card.get("position_policy", decision.get("position_policy", {}))

    if direction == "wait":
        checks = ["等待明确信号"]
        for flag in news_factor.get("risk_flags", []):
            checks.append(flag)
        return _build_risk_report(
            False,
            "high",
            "方向为wait，不执行交易",
            "0%",
            checks,
            None,
            news_factor,
            position_policy,
        )

    if final_score < 60:
        approved = False
        veto_reasons.append(f"综合评分{final_score}<60，禁止交易")
        risk_level = "high"

    if final_score >= 75:
        risk_level = "low"
    elif final_score >= 60:
        risk_level = "medium"

    mm_result = multi_model_verify(code)
    if mm_result["has_conflict"]:
        risk_level = "medium"
        required_checks.append("多模型存在冲突，建议降低仓位")
        if mm_result["consensus_strength"] < 2:
            approved = False
            veto_reasons.append("多模型严重冲突，一票否决")

    if not mm_result["can_execute"] and mm_result["consensus_strength"] < 3:
        position_limit = "2%"
        required_checks.append("模型一致性不足，限制仓位至2%")
    elif mm_result["consensus_strength"] >= 3:
        position_limit = "5%"
    else:
        position_limit = "0%"

    if score_card.get("risk_pause"):
        approved = False
        veto_reasons.append("S级事件触发，暂停交易")
        risk_level = "high"

    scores = score_card.get("scores", {})
    if scores.get("risk_deduction", 0) >= 20:
        risk_level = "high"
        required_checks.append("风险扣分较高，需要额外确认")

    event_details = score_card.get("score_details", {}).get("event", {})
    if event_details.get("highest_level") == "S":
        approved = False
        veto_reasons.append("存在S级事件，一票否决")

    if news_factor:
        for flag in news_factor.get("risk_flags", []):
            required_checks.append(flag)
        if news_factor.get("action_bias") == "pause" or news_factor.get("position_multiplier") == 0:
            approved = False
            veto_reasons.append("新闻/公告因子触发暂停交易")
            risk_level = "high"
        elif news_factor.get("action_bias") in ("defensive", "reduce"):
            risk_level = "high" if news_factor.get("impact_score", 50) <= 30 else "medium"
            required_checks.append("新闻/公告偏负面，必须按影响因子降低仓位")
        elif news_factor.get("action_bias") in ("verify", "confirm"):
            risk_level = "medium"
            required_checks.append("新闻/公告需要二次核验后再执行")

    suggested_pct = position_policy.get("suggested_position_pct")
    if suggested_pct is not None:
        try:
            suggested_limit = f"{float(suggested_pct):g}%"
            if position_limit == "0%" or float(suggested_pct) == 0:
                position_limit = "0%"
            else:
                current_pct = float(str(position_limit).replace("%", "") or 0)
                if current_pct > 0:
                    position_limit = f"{min(current_pct, float(suggested_pct)):g}%"
                else:
                    position_limit = suggested_limit
        except (TypeError, ValueError):
            pass

    portfolio = state_store.get_portfolio()
    positions = state_store.get_positions()
    if code in positions:
        existing_pct = positions[code].get("market_value", 0) / portfolio["total_asset"]
        if existing_pct > 0.15:
            required_checks.append("该股已有较大仓位，谨慎加仓")

    if risk_manager.check_daily_loss_limit():
        approved = False
        veto_reasons.append("今日亏损已达上限，暂停所有交易")

    if not approved:
        position_limit = "0%"

    return _build_risk_report(
        approved, risk_level,
        "; ".join(veto_reasons) if veto_reasons else "通过风控审查",
        position_limit,
        required_checks,
        mm_result,
        news_factor,
        position_policy,
    )


def _build_risk_report(approved: bool, risk_level: str, veto_reason: str,
                        position_limit: str, required_checks: list,
                        multi_model: dict = None,
                        news_impact_factor: dict = None,
                        position_policy: dict = None) -> dict:
    return {
        "approved": approved,
        "risk_level": risk_level,
        "veto_reason": veto_reason if not approved else "",
        "position_limit": position_limit,
        "required_checks": required_checks,
        "multi_model_result": multi_model,
        "news_impact_factor": news_impact_factor or {},
        "position_policy": position_policy or {},
        "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def full_risk_pipeline(code: str, strategy_type: str = "short") -> dict:
    from app.analysis.decision_schema import generate_decision

    decision = generate_decision(code, strategy_type)
    risk_report = risk_review(decision)

    return {
        "decision": decision,
        "risk_report": risk_report,
        "can_execute": risk_report["approved"],
        "final_direction": decision["direction"] if risk_report["approved"] else "wait",
        "final_position_limit": risk_report["position_limit"],
    }
