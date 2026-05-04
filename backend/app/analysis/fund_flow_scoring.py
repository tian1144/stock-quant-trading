"""
资金流向评分模块 - 主力/散户/北向/板块资金
"""
from datetime import datetime
from typing import Dict, Optional
from loguru import logger

from app.services import state_store


def calc_main_fund_score(code: str) -> dict:
    flow = state_store.get_money_flow(code)
    if not flow or not flow.get("flows"):
        return {"score": 50, "direction": "unknown", "main_net_inflow": 0}

    flows = flow["flows"]
    latest_main = flows[-1].get("main_net_inflow", 0) if flows else 0

    score = 50
    if latest_main > 5e7:
        score = 85
    elif latest_main > 2e7:
        score = 75
    elif latest_main > 0:
        score = 65
    elif latest_main > -2e7:
        score = 40
    elif latest_main > -5e7:
        score = 25
    else:
        score = 15

    direction = "inflow" if latest_main > 0 else "outflow"

    return {
        "score": score,
        "direction": direction,
        "main_net_inflow": latest_main,
        "consecutive_inflow_days": flow.get("consecutive_inflow_days", 0),
    }


def calc_large_order_score(code: str) -> dict:
    flow = state_store.get_money_flow(code)
    if not flow or not flow.get("flows"):
        return {"score": 50, "large_net_inflow": 0}

    flows = flow["flows"]
    latest = flows[-1]
    large_inflow = latest.get("large_net_inflow", 0) + latest.get("super_large_net_inflow", 0)

    score = 50
    if large_inflow > 3e7:
        score = 80
    elif large_inflow > 1e7:
        score = 70
    elif large_inflow > 0:
        score = 60
    elif large_inflow > -1e7:
        score = 40
    else:
        score = 25

    return {"score": score, "large_net_inflow": large_inflow}


def calc_fund_trend_score(code: str) -> dict:
    flow = state_store.get_money_flow(code)
    if not flow or not flow.get("flows") or len(flow["flows"]) < 3:
        return {"score": 50, "trend": "unknown"}

    flows = flow["flows"]
    recent_3 = [f["main_net_inflow"] for f in flows[-3:]]

    score = 50
    if all(r > 0 for r in recent_3):
        score = 80
        trend = "strong_inflow"
    elif sum(1 for r in recent_3 if r > 0) >= 2:
        score = 65
        trend = "moderate_inflow"
    elif recent_3[-1] > recent_3[-2]:
        score = 55
        trend = "improving"
    elif all(r < 0 for r in recent_3):
        score = 25
        trend = "strong_outflow"
    else:
        score = 40
        trend = "mixed"

    return {"score": score, "trend": trend}


def calc_northbound_score(code: str) -> dict:
    nb = state_store.get_northbound_flow()
    if not nb:
        return {"score": 50, "impact": "unknown"}

    net = nb.get("total_net", 0)
    score = 50
    if net > 5e9:
        score = 80
    elif net > 0:
        score = 60
    elif net > -5e9:
        score = 40
    else:
        score = 20

    return {"score": score, "impact": "positive" if net > 0 else "negative", "net_flow": net}


def calc_fund_flow_score(code: str) -> dict:
    main_fund = calc_main_fund_score(code)
    large_order = calc_large_order_score(code)
    fund_trend = calc_fund_trend_score(code)
    northbound = calc_northbound_score(code)

    weights = {"main_fund": 0.35, "large_order": 0.25, "trend": 0.25, "northbound": 0.15}
    final_score = (
        main_fund["score"] * weights["main_fund"] +
        large_order["score"] * weights["large_order"] +
        fund_trend["score"] * weights["trend"] +
        northbound["score"] * weights["northbound"]
    )

    trend_support = main_fund["direction"] == "inflow" and fund_trend.get("trend") in ["strong_inflow", "moderate_inflow"]

    return {
        "fund_flow_score": round(final_score, 1),
        "main_fund": main_fund,
        "large_order": large_order,
        "fund_trend": fund_trend,
        "northbound": northbound,
        "trend_support": trend_support,
        "scored_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
