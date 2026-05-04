"""
AI assisted stock picker.

The service keeps the quant engine as the first filter, then asks the configured
model to review only compact evidence. If the model is unavailable, it returns a
deterministic fallback so the H5 preview remains usable and testable.
"""
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import pandas as pd

from app.analysis.decision_schema import generate_decision, generate_score_card
from app.analysis.risk_review import full_risk_pipeline
from app.services import ai_model_service, data_fetcher, state_store, stock_screener, technical_analysis, disclosure_service


DEMO_FALLBACK_STOCKS = [
    {"code": "600519", "name": "贵州茅台", "market": "主板", "industry": "白酒", "is_st": False, "price": 1688.00, "pct_change": 1.26, "volume": 32600, "amount": 5500000000.0},
    {"code": "300750", "name": "宁德时代", "market": "创业板", "industry": "新能源", "is_st": False, "price": 212.35, "pct_change": -0.84, "volume": 185000, "amount": 3920000000.0},
    {"code": "601318", "name": "中国平安", "market": "主板", "industry": "保险", "is_st": False, "price": 48.72, "pct_change": 0.38, "volume": 420000, "amount": 2040000000.0},
    {"code": "000858", "name": "五粮液", "market": "主板", "industry": "白酒", "is_st": False, "price": 143.18, "pct_change": 0.92, "volume": 156000, "amount": 2230000000.0},
    {"code": "600036", "name": "招商银行", "market": "主板", "industry": "银行", "is_st": False, "price": 36.28, "pct_change": 0.67, "volume": 510000, "amount": 1850000000.0},
    {"code": "002594", "name": "比亚迪", "market": "主板", "industry": "汽车", "is_st": False, "price": 226.40, "pct_change": -1.12, "volume": 198000, "amount": 4480000000.0},
    {"code": "688981", "name": "中芯国际", "market": "科创板", "industry": "半导体", "is_st": False, "price": 55.66, "pct_change": 2.18, "volume": 690000, "amount": 3840000000.0},
    {"code": "601899", "name": "紫金矿业", "market": "主板", "industry": "有色金属", "is_st": False, "price": 18.92, "pct_change": 1.74, "volume": 980000, "amount": 1850000000.0},
]


BUCKETS = list(range(-10, 11))


def _market_retail_institution_mood() -> dict:
    stocks = list(state_store.get_stock_universe().values())
    if not stocks:
        stocks = data_fetcher.read_stock_universe_cache()
    stocks = stocks[:800]
    sampled = 0
    main_sum = 0.0
    retail_pressure_sum = 0.0
    inflow_count = 0
    for stock in stocks:
        code = stock.get("code")
        if not code:
            continue
        flow = stock_screener.summarize_retail_institution_flow(code)
        if flow.get("data_status") != "ready":
            continue
        sampled += 1
        main = _to_float(flow.get("main_net_inflow"))
        main_sum += main
        retail_pressure_sum += _to_float(flow.get("retail_pressure"), 50)
        if main > 0:
            inflow_count += 1
    avg_retail_pressure = retail_pressure_sum / sampled if sampled else 50
    return {
        "sampled": sampled,
        "main_net_inflow_sum": round(main_sum, 2),
        "main_inflow_ratio_pct": round(inflow_count / sampled * 100, 2) if sampled else 0,
        "avg_retail_pressure": round(avg_retail_pressure, 1),
        "main_sentiment": "positive" if main_sum > 0 and inflow_count >= sampled * 0.45 else "negative" if main_sum < 0 else "neutral",
        "retail_sentiment": "hot" if avg_retail_pressure >= 62 else "cold" if avg_retail_pressure <= 40 else "neutral",
        "data_status": "sampled_money_flow" if sampled else "missing_money_flow",
    }


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _get_daily_df(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    df = state_store.get_daily_bars(code)
    if df is None or df.empty:
        df = data_fetcher.fetch_kline(code, period=101, days=days, allow_fallback=False)
        if df is not None and not df.empty:
            state_store.set_daily_bars(code, df)
    return df


def _price_plan(stock: dict, df: Optional[pd.DataFrame]) -> dict:
    price = _to_float(stock.get("price"))
    if price <= 0 and df is not None and not df.empty:
        price = _to_float(df.iloc[-1].get("close"))
    support = price * 0.985 if price else 0
    resistance = price * 1.055 if price else 0
    if df is not None and len(df) >= 20:
        try:
            sr = technical_analysis.calc_support_resistance(df.copy())
            supports = [s for s in sr.get("support_levels", []) if _to_float(s) > 0 and _to_float(s) < price]
            resistances = [r for r in sr.get("resistance_levels", []) if _to_float(r) > price]
            if supports:
                support = max(support, max(supports))
            if resistances:
                resistance = min(resistance, min(resistances))
        except Exception:
            pass
    entry = min(price, support * 1.01) if price and support else price
    stop = entry * 0.965 if entry else 0
    return {
        "current_price": round(price, 2),
        "suggested_buy_price": round(entry, 2),
        "suggested_sell_price": round(resistance, 2),
        "stop_loss_price": round(stop, 2),
        "suggested_buy_time": "下一个交易日回踩支撑不破、分时承接放量时",
    }


def _kline_summary(df: Optional[pd.DataFrame]) -> dict:
    if df is None or df.empty:
        return {"data_status": "缺少K线", "reason": "无法计算趋势和波动"}
    recent = df.tail(30).copy()
    close = recent["close"].astype(float)
    volume = recent["volume"].astype(float) if "volume" in recent else pd.Series([])
    pct_5 = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6] * 100 if len(close) >= 6 and close.iloc[-6] else 0
    pct_20 = (close.iloc[-1] - close.iloc[0]) / close.iloc[0] * 100 if close.iloc[0] else 0
    vol_ratio = 1.0
    if len(volume) >= 10 and volume.tail(10).mean():
        vol_ratio = volume.tail(3).mean() / volume.tail(10).mean()
    return {
        "data_status": "可用",
        "pct_5": round(pct_5, 2),
        "pct_20": round(pct_20, 2),
        "volume_ratio_3_10": round(vol_ratio, 2),
        "latest_close": round(_to_float(close.iloc[-1]), 2),
    }


def _probability_ladder(stock: dict, score_card: dict, decision: dict, risk: dict, df: Optional[pd.DataFrame]) -> List[dict]:
    score = _to_float(score_card.get("final_score"), _to_float(stock.get("score"), 50))
    scores = score_card.get("scores") or {}
    kline_score = _to_float(scores.get("kline_score"), _to_float((stock.get("score_detail") or {}).get("technical"), 50))
    flow_score = _to_float(scores.get("fund_flow_score"), _to_float((stock.get("score_detail") or {}).get("capital_flow"), 50))
    event_score = _to_float(scores.get("event_score"), _to_float((stock.get("score_detail") or {}).get("news"), 50))
    risk_report = risk.get("risk_report") or {}
    veto = not risk_report.get("approved", False)
    volatility = 2.6
    if df is not None and len(df) >= 20 and "pct_change" in df:
        volatility = max(1.4, min(5.8, float(df["pct_change"].tail(20).astype(float).std() or 2.6)))
    edge = (score - 50) * 0.035 + (kline_score - 50) * 0.018 + (flow_score - 50) * 0.015 + (event_score - 50) * 0.012
    if decision.get("direction") != "buy":
        edge -= 0.6
    if veto:
        edge -= 1.0
    raw = []
    for bucket in BUCKETS:
        center = edge
        width = volatility * 1.35
        weight = pow(2.71828, -((bucket - center) ** 2) / (2 * width * width))
        if bucket >= 8 and score >= 78 and flow_score >= 65:
            weight *= 1.25
        if bucket <= -5 and (veto or event_score < 40):
            weight *= 1.4
        raw.append(weight)
    total = sum(raw) or 1
    rows = []
    for bucket, weight in zip(BUCKETS, raw):
        if bucket == 10:
            label = "涨停附近"
        elif bucket == -10:
            label = "跌停附近"
        elif bucket >= 0:
            label = f"涨{bucket}%到{min(bucket + 1, 10)}%"
        else:
            label = f"跌{abs(bucket)}%到{abs(bucket) - 1}%"
        rows.append({"range": label, "bucket": bucket, "probability": round(weight / total * 100, 2)})
    return rows


def _candidate_evidence(stock: dict, strategy: str) -> dict:
    code = stock.get("code", "")
    df = _get_daily_df(code)
    score_card = generate_score_card(code, strategy)
    decision = generate_decision(code, strategy)
    risk = full_risk_pipeline(code, strategy)
    plan = _price_plan(stock, df)
    kline = _kline_summary(df)
    retail_flow = stock.get("retail_institution_flow") or stock_screener.summarize_retail_institution_flow(code)
    disclosure = disclosure_service.get_disclosure_risk_profile(code)
    detail = {
        "估值财务": (stock.get("screening_logic") or {}).get("fundamental", {}),
        "量价结构": {
            "量比": stock.get("volume_ratio"),
            "换手率": stock.get("turnover_rate"),
            "成交额": stock.get("amount"),
        },
        "K线": kline,
        "资金": {
            "主力净流入": stock.get("main_net_inflow"),
            "资金分": (stock.get("score_detail") or {}).get("capital_flow"),
        },
        "新闻公告": (stock.get("screening_logic") or {}).get("news", {}),
        "风控": risk.get("risk_report", {}),
    }
    detail["capital_structure"] = retail_flow
    detail["disclosure_risk"] = disclosure
    detail["youzi_experience"] = (stock.get("screening_logic") or {}).get("youzi_experience", {})
    return {
        "code": code,
        "name": stock.get("name", ""),
        "score": stock.get("score"),
        "quality_score": stock.get("quality_score"),
        "ai_quality_score": stock.get("ai_quality_score"),
        "ai_quality_label": stock.get("ai_quality_label"),
        "ai_quality_reason": stock.get("ai_quality_reason"),
        "ai_quality_priority": stock.get("ai_quality_priority"),
        "signal_type": stock.get("signal_type"),
        "risk_level": stock.get("risk_level"),
        "reason": stock.get("reason", ""),
        "score_detail": stock.get("score_detail", {}),
        "score_card": score_card,
        "decision": decision,
        "risk": risk,
        "trade_plan": plan,
        "probability_ladder": _probability_ladder(stock, score_card, decision, risk, df),
        "retail_institution_flow": retail_flow,
        "disclosure_risk": disclosure,
        "youzi_experience": (stock.get("screening_logic") or {}).get("youzi_experience", {}),
        "evidence": detail,
    }


def _fallback_review(items: List[dict]) -> List[dict]:
    reviewed = []
    for item in items:
        score = _to_float(item.get("score_card", {}).get("final_score"), _to_float(item.get("score"), 50))
        risk_report = (item.get("risk") or {}).get("risk_report") or {}
        approved = bool(risk_report.get("approved"))
        flow = _to_float((item.get("score_card", {}).get("scores") or {}).get("fund_flow_score"), 50)
        kline = _to_float((item.get("score_card", {}).get("scores") or {}).get("kline_score"), 50)
        ai_quality = _to_float(item.get("ai_quality_score"), score)
        youzi = item.get("youzi_experience") or {}
        youzi_score = _to_float(youzi.get("win_probability"), _to_float((item.get("score_detail") or {}).get("youzi_experience"), 50))
        confidence = _clamp(score * 0.36 + ai_quality * 0.22 + flow * 0.14 + kline * 0.12 + youzi_score * 0.16 - (0 if approved else 14))
        action = "建议观察"
        if approved and confidence >= 72:
            action = "可小仓试单"
        elif confidence >= 64:
            action = "等待回踩确认"
        if not approved:
            action = "风控未通过，暂不买入"
        reasons = [
            f"综合评分{score:.1f}",
            f"AI质量分{ai_quality:.1f}",
            f"资金分{flow:.1f}",
            f"K线分{kline:.1f}",
            f"游资经验分{youzi_score:.1f}",
        ]
        if youzi.get("position_advice"):
            reasons.append(f"仓位纪律:{youzi.get('position_advice')}")
        if youzi.get("notes"):
            reasons.append("游资复核:" + "、".join(str(x) for x in youzi.get("notes", [])[:3]))
        if item.get("ai_quality_reason"):
            reasons.append(str(item.get("ai_quality_reason"))[:80])
        if not approved:
            reasons.append(risk_report.get("veto_reason") or "风控复核未通过")
        recommend_buy = bool(approved and confidence >= 72)
        reviewed.append({
            **item,
            "ai_rank_score": round(confidence, 1),
            "ai_action": action,
            "recommend_buy": recommend_buy,
            "holding_style": "短期" if recommend_buy else "短期观察",
            "ai_reason": "；".join(reasons),
            "ai_risks": risk_report.get("required_checks", [])[:4],
        })
    return sorted(reviewed, key=lambda x: x.get("ai_rank_score", 0), reverse=True)


def _merge_ai_review(items: List[dict], ai_payload: dict) -> List[dict]:
    rows = ai_payload.get("recommendations") if isinstance(ai_payload, dict) else None
    if not isinstance(rows, list):
        return _fallback_review(items)
    by_code = {item["code"]: item for item in items}
    merged = []
    for row in rows:
        code = str(row.get("code", "")).strip()
        if code not in by_code:
            continue
        base = by_code[code]
        plan = {**base.get("trade_plan", {}), **(row.get("trade_plan") or {})}
        ladder = row.get("probability_ladder") if isinstance(row.get("probability_ladder"), list) else base.get("probability_ladder")
        merged.append({
            **base,
            "trade_plan": plan,
            "probability_ladder": ladder,
            "ai_rank_score": round(_to_float(row.get("ai_rank_score"), _to_float(base.get("score"), 50)), 1),
            "ai_action": row.get("ai_action") or "AI建议观察",
            "youzi_quality_view": row.get("youzi_quality_view") or "",
            "ai_reason": row.get("ai_reason") or row.get("youzi_quality_view") or base.get("reason", ""),
            "ai_risks": row.get("ai_risks") or [],
        })
    if not merged:
        return _fallback_review(items)
    merged_codes = {item.get("code") for item in merged}
    missing = [item for item in items if item.get("code") not in merged_codes]
    if missing:
        merged.extend(_fallback_review(missing))
    return sorted(merged, key=lambda x: x.get("ai_rank_score", 0), reverse=True)


def _is_buy_recommendation(item: dict) -> bool:
    action_text = str(item.get("ai_action") or "")
    plan = item.get("trade_plan") or {}
    rank_score = _to_float(item.get("ai_rank_score"))
    if item.get("recommend_buy") is True:
        return True
    if any(word in action_text for word in ("暂不", "不推荐", "风控未通过", "等待", "观察")):
        return False
    if any(word in action_text for word in ("推荐购买", "可小仓", "试单", "买入")):
        return rank_score >= 65 and bool(plan.get("suggested_buy_price") or plan.get("suggested_buy_time"))
    return rank_score >= 72 and bool(plan.get("suggested_buy_price") or plan.get("suggested_buy_time"))


def _force_best_buy_recommendations(items: List[dict], target: int = 3) -> List[dict]:
    promoted = []
    for item in sorted(items or [], key=lambda x: _to_float(x.get("ai_rank_score"), _to_float(x.get("score"), 0)), reverse=True):
        if item.get("recommend_buy") is True:
            promoted.append(item)
            continue
        action_text = str(item.get("ai_action") or "")
        risk_report = (item.get("risk") or {}).get("risk_report") or {}
        veto_reason = risk_report.get("veto_reason") or ""
        severe_block = any(word in f"{action_text}{veto_reason}" for word in ("退市", "ST", "停牌", "熔断", "财务造假", "重大违法"))
        if severe_block:
            continue
        plan = item.get("trade_plan") or {}
        if not plan.get("suggested_buy_price"):
            price = _to_float(plan.get("current_price") or item.get("price"))
            if price > 0:
                plan["current_price"] = round(price, 2)
                plan["suggested_buy_price"] = round(price * 0.992, 2)
                plan["suggested_sell_price"] = round(price * 1.045, 2)
                plan["stop_loss_price"] = round(price * 0.965, 2)
        plan["suggested_buy_time"] = plan.get("suggested_buy_time") or "下一个交易日回踩支撑不破、分时承接放量时"
        reason = item.get("ai_reason") or item.get("reason") or "全市场复核池内相对更优，适合小仓模拟跟踪。"
        item.update({
            "trade_plan": plan,
            "ai_rank_score": max(68.0, round(_to_float(item.get("ai_rank_score"), _to_float(item.get("score"), 68)), 1)),
            "ai_action": "可小仓试单",
            "holding_style": item.get("holding_style") or "短期",
            "recommend_buy": True,
            "ai_reason": f"{reason}；全市场没有出现完美买点，本条为复核池内相对最优试单，需模拟盘和人工二次确认。",
        })
        promoted.append(item)
        if len(promoted) >= target:
            break
    return promoted[:target]


def _normalize_focus_codes(codes: Optional[List[str]] = None) -> List[str]:
    seen = set()
    normalized = []
    for raw in codes or []:
        code = str(raw or "").strip()
        if not code:
            continue
        digits = "".join(ch for ch in code if ch.isdigit())
        if len(digits) >= 6:
            code = digits[-6:]
        if len(code) != 6 or code in seen:
            continue
        seen.add(code)
        normalized.append(code)
    return normalized


def _build_focus_candidates(codes: List[str], screening: List[dict]) -> List[dict]:
    screening_map = {str(item.get("code", "")): item for item in screening or [] if item.get("code")}
    realtime = state_store.get_all_realtime()
    candidates = []
    for code in codes:
        stock = {**(state_store.get_stock_info(code) or {"code": code}), **(realtime.get(code) or {})}
        if code in screening_map:
            stock = {**stock, **screening_map[code]}
        stock.setdefault("code", code)
        stock.setdefault("name", code)
        stock.setdefault("score", stock.get("quality_score") or 55)
        stock.setdefault("quality_score", stock.get("score") or 55)
        stock.setdefault("score_detail", {})
        stock.setdefault("screening_logic", {})
        stock.setdefault("signal_type", "watch")
        stock.setdefault("risk_level", "medium")
        stock.setdefault("reason", "关注股票AI选股候选，来自自选、智能筛选或短线震荡池")
        candidates.append(stock)
    return candidates


def _compact_quality_candidate(stock: dict) -> dict:
    logic = stock.get("screening_logic") or {}
    detail = stock.get("score_detail") or {}
    support = logic.get("support_pullback") or {}
    news = logic.get("news") or {}
    sector = logic.get("sector") or {}
    fundamental = logic.get("fundamental") or {}
    historical_rule = logic.get("historical_rule") or {}
    youzi_experience = logic.get("youzi_experience") or {}
    return {
        "code": stock.get("code"),
        "name": stock.get("name"),
        "price": stock.get("price"),
        "pct_change": stock.get("pct_change"),
        "amount": stock.get("amount"),
        "volume_ratio": stock.get("volume_ratio"),
        "turnover_rate": stock.get("turnover_rate"),
        "main_net_inflow": stock.get("main_net_inflow"),
        "quant_score": stock.get("score"),
        "quality_score": stock.get("quality_score"),
        "support_pool_status": stock.get("support_pool_status"),
        "risk_level": stock.get("risk_level"),
        "signal_type": stock.get("signal_type"),
        "factor_scores": {
            "eligibility": detail.get("eligibility"),
            "fundamental": detail.get("fundamental"),
            "volume_turnover": detail.get("volume_turnover"),
            "capital_flow": detail.get("capital_flow"),
            "technical": detail.get("technical"),
            "support_pullback": detail.get("support_pullback"),
            "sector": detail.get("sector"),
            "news": detail.get("news"),
            "intraday": detail.get("intraday"),
            "sector_momentum": detail.get("sector_momentum"),
            "leader_follow": detail.get("leader_follow"),
            "historical_rule": detail.get("historical_rule"),
            "youzi_experience": detail.get("youzi_experience"),
        },
        "support": {
            "box_width_pct": support.get("box_width_pct"),
            "near_support_pct": support.get("near_support_pct"),
            "drawdown_from_high_pct": support.get("drawdown_from_high_pct"),
            "trend_health": support.get("trend_health"),
            "notes": support.get("notes", [])[:4],
            "data_status": support.get("data_status"),
        },
        "fundamental": {
            "pe_ttm": fundamental.get("pe_ttm"),
            "pb": fundamental.get("pb"),
            "market_cap": fundamental.get("market_cap"),
            "disclosure_risk": fundamental.get("disclosure_risk"),
            "missing": fundamental.get("missing", [])[:5],
            "notes": fundamental.get("notes", [])[:4],
        },
        "retail_institution_flow": stock.get("retail_institution_flow") or stock_screener.summarize_retail_institution_flow(stock.get("code", "")),
        "historical_rule_effectiveness": {
            "score": historical_rule.get("score"),
            "sample_count": historical_rule.get("sample_count"),
            "sample_sufficient": historical_rule.get("sample_sufficient"),
            "win_rate_pct": historical_rule.get("win_rate_pct"),
            "target_hit_rate_pct": historical_rule.get("target_hit_rate_pct"),
            "stop_hit_rate_pct": historical_rule.get("stop_hit_rate_pct"),
            "avg_return_pct": historical_rule.get("avg_return_pct"),
            "avg_max_drawdown_pct": historical_rule.get("avg_max_drawdown_pct"),
            "data_status": historical_rule.get("data_status"),
            "note": historical_rule.get("note"),
        },
        "youzi_experience": {
            "score": youzi_experience.get("win_probability") or detail.get("youzi_experience"),
            "market_phase": youzi_experience.get("market_phase"),
            "leader_status": youzi_experience.get("leader_status"),
            "tape_status": youzi_experience.get("tape_status"),
            "position_advice": youzi_experience.get("position_advice"),
            "sector_confirmed": youzi_experience.get("sector_confirmed"),
            "main_retail_confirmed": youzi_experience.get("main_retail_confirmed"),
            "news_confirmed_by_sector": youzi_experience.get("news_confirmed_by_sector"),
            "notes": youzi_experience.get("notes", [])[:6],
            "data_status": youzi_experience.get("data_status"),
        },
        "news": {
            "count": news.get("count"),
            "items": news.get("items", [])[:3],
            "data_status": news.get("data_status"),
        },
        "sector": {
            "matched": sector.get("matched", [])[:3],
            "data_status": sector.get("data_status"),
        },
        "reason": stock.get("reason", ""),
    }


def _fallback_quality_scores(candidates: List[dict], reason: str = "AI质量打分不可用，使用本地量化分降级排序") -> List[dict]:
    rows = []
    for stock in candidates or []:
        base = _to_float(stock.get("quality_score"), _to_float(stock.get("score"), 50))
        detail = stock.get("score_detail") or {}
        news = _to_float(detail.get("news"), 50)
        flow = _to_float(detail.get("capital_flow"), 50)
        technical = _to_float(detail.get("technical"), 50)
        support = _to_float(detail.get("support_pullback"), 50)
        historical = _to_float(detail.get("historical_rule"), 50)
        youzi = _to_float(detail.get("youzi_experience"), 50)
        ai_score = _clamp(base * 0.39 + news * 0.11 + flow * 0.12 + technical * 0.10 + support * 0.07 + historical * 0.09 + youzi * 0.12)
        stock = {
            **stock,
            "ai_quality_score": round(ai_score, 1),
            "ai_quality_label": "本地降级合格" if ai_score >= 68 else "本地降级观察",
            "ai_quality_reason": reason,
            "ai_quality_priority": "review" if ai_score >= 62 else "watch",
        }
        rows.append(stock)
    return sorted(rows, key=lambda x: _to_float(x.get("ai_quality_score"), _to_float(x.get("quality_score"))), reverse=True)


def _youzi_adjusted_quality_score(raw_score: float, stock: dict) -> float:
    youzi = ((stock.get("screening_logic") or {}).get("youzi_experience") or {})
    youzi_score = _to_float(youzi.get("win_probability"), _to_float((stock.get("score_detail") or {}).get("youzi_experience"), 50))
    adjusted = raw_score * 0.88 + youzi_score * 0.12
    if youzi.get("market_phase") == "risk_off":
        adjusted -= 5
    if youzi.get("tape_status") == "overheated":
        adjusted -= 6
    if youzi.get("position_advice") in ("空仓或仅观察", "观察"):
        adjusted -= 4
    if youzi.get("sector_confirmed") and youzi.get("main_retail_confirmed"):
        adjusted += 3
    return _clamp(adjusted)


def _merge_quality_scores(candidates: List[dict], ai_payloads: List[dict]) -> List[dict]:
    ai_by_code = {}
    for payload in ai_payloads or []:
        scores = payload.get("scores") if isinstance(payload, dict) else None
        if not isinstance(scores, list):
            continue
        for row in scores:
            code = str(row.get("code", "")).strip()
            if code:
                ai_by_code[code] = row
    if not ai_by_code:
        return _fallback_quality_scores(candidates)
    merged = []
    for stock in candidates or []:
        code = str(stock.get("code", "")).strip()
        row = ai_by_code.get(code)
        if row:
            raw_score = _clamp(_to_float(row.get("ai_quality_score"), _to_float(stock.get("quality_score"), 50)))
            score = _youzi_adjusted_quality_score(raw_score, stock)
            youzi_view = row.get("youzi_quality_view")
            if not youzi_view:
                youzi = ((stock.get("screening_logic") or {}).get("youzi_experience") or {})
                youzi_view = "；".join(str(x) for x in (youzi.get("notes") or [])[:3])
            stock = {
                **stock,
                "ai_quality_score": round(score, 1),
                "ai_quality_label": row.get("ai_quality_label") or row.get("priority") or "AI已评分",
                "youzi_quality_view": youzi_view,
                "ai_quality_reason": row.get("ai_quality_reason") or youzi_view or stock.get("reason", ""),
                "ai_quality_priority": row.get("priority") or ("review" if score >= 65 else "watch"),
            }
        else:
            stock = _fallback_quality_scores([stock], reason="该批次AI未返回该股，使用本地量化分补齐")[0]
        merged.append(stock)
    return sorted(merged, key=lambda x: _to_float(x.get("ai_quality_score"), _to_float(x.get("quality_score"))), reverse=True)


def _ai_quality_score_candidates(candidates: List[dict], strategy: str, scope: str, progress_callback=None) -> tuple[List[dict], dict]:
    candidates = sorted(candidates or [], key=lambda x: _to_float(x.get("quality_score") or x.get("score")), reverse=True)
    if not candidates:
        return [], {"ok": False, "used_ai": False, "batch_count": 0, "error": "候选池为空"}
    policy = ai_model_service.get_task_policy("ai_quality_scoring")
    batch_size = max(20, int(policy.get("max_context_events", 120) or 120))
    schema_hint = """{
  "summary": {"method": "AI分批质量打分说明"},
  "scores": [{
    "code": "股票代码",
    "ai_quality_score": 0-100,
    "ai_quality_label": "合格/观察/剔除",
    "priority": "review/watch/reject",
    "youzi_quality_view": "情绪周期/主线板块/龙头地位/盘口承接/仓位纪律判断",
    "ai_quality_reason": "必须综合新闻、财报/估值、成交量、K线、资金、板块、游资经验和风控风险"
  }]
}"""
    system_prompt = (
        "你是A股全候选质量评分模型。你不是最终下单模型，只负责对第二阶段候选池逐只打质量分。"
        "必须综合量价、K线、成交额、资金流、板块热度、新闻公告、估值财务缺口、风险等级。"
        "额外使用游资交割单经验评分：情绪周期、主线板块、龙头/次龙头地位、盘口承接、公告是否被板块确认、仓位赢面纪律。"
        "不要只按本地排名照抄，新闻/财报/资金/K线冲突时要主动降分。"
        "只返回输入候选中的股票，输出JSON。"
    )
    payloads = []
    system_prompt = (
        system_prompt
        + "必须额外评估个股主力/散户占比、大盘主力散户情绪、公告财报风险、相似规则历史回测有效性和youzi_experience。"
        + "若youzi_experience显示退潮、过热、缺少主线、公告缺少板块确认或仓位建议仅观察，应明显降分或设为watch/reject。"
    )
    meta = {
        "ok": True,
        "used_ai": False,
        "task_key": "ai_quality_scoring",
        "batch_size": batch_size,
        "batch_count": 0,
        "candidate_count": len(candidates),
        "max_workers": 0,
        "errors": [],
    }
    chunks = [(start, candidates[start:start + batch_size]) for start in range(0, len(candidates), batch_size)]
    max_workers = min(4, max(1, len(chunks)))
    meta["max_workers"] = max_workers
    meta["batch_total"] = len(chunks)
    if progress_callback:
        progress_callback({
            "stage": "ai_quality_scoring",
            "message": f"AI质量打分开始：共{len(candidates)}只候选，分{len(chunks)}批",
            "batch_done": 0,
            "batch_total": len(chunks),
            "candidate_count": len(candidates),
        })

    def call_batch(start: int, chunk: List[dict]) -> tuple[Optional[dict], dict]:
        compact = [_compact_quality_candidate(stock) for stock in chunk]
        return ai_model_service.chat_json(
            "ai_quality_scoring",
            system_prompt,
            {
                "strategy": strategy,
                "scope": "所有股票选股" if scope == "all" else "关注股票选股",
                "market_retail_institution_mood": _market_retail_institution_mood(),
                "batch_index": start // batch_size + 1,
                "batch_total": (len(candidates) + batch_size - 1) // batch_size,
                "candidates": compact,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            schema_hint=schema_hint,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(call_batch, start, chunk) for start, chunk in chunks]
        for future in as_completed(futures):
            payload, call_meta = future.result()
            meta["batch_count"] += 1
            meta["used_ai"] = bool(meta["used_ai"] or (call_meta or {}).get("used_ai"))
            if payload:
                payloads.append(payload)
            else:
                meta["errors"].append((call_meta or {}).get("error") or "AI质量打分批次无有效返回")
            if progress_callback:
                progress_callback({
                    "stage": "ai_quality_scoring",
                    "message": f"AI质量打分进行中：已完成{meta['batch_count']}/{len(chunks)}批",
                    "batch_done": meta["batch_count"],
                    "batch_total": len(chunks),
                    "candidate_count": len(candidates),
                    "used_ai": meta["used_ai"],
                    "errors": meta["errors"][-3:],
                })
    ranked = _merge_quality_scores(candidates, payloads)
    meta["ai_scored_count"] = len(ranked)
    meta["ok"] = bool(payloads) or not ai_model_service.is_ready()
    if not payloads:
        meta["used_ai"] = False
        meta["error"] = meta["errors"][0] if meta["errors"] else "AI质量打分未返回，已降级"
    return ranked, meta


def _persist_ai_error_result(
    message: str,
    *,
    strategy: str = "short",
    scope: str = "focus",
    focus_codes: Optional[List[str]] = None,
    candidate_source: Optional[List[dict]] = None,
    quality_meta: Optional[dict] = None,
    ai_meta: Optional[dict] = None,
    candidate_count: int = 0,
) -> dict:
    focus_codes = focus_codes or []
    candidate_source = candidate_source or []
    quality_meta = quality_meta or {}
    ai_meta = ai_meta or {"ok": False, "used_ai": False, "error": message}
    result = {
        "error": message,
        "recommendations": [],
        "reviewed_candidates": [],
        "reviewed_count": 0,
        "filtered_wait_count": 0,
        "summary": {
            "market_view": message,
            "method": "AI未完成，本次不生成推荐结果",
        },
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": strategy,
        "scope": scope,
        "scope_label": "所有股票选股" if scope == "all" else "关注股票选股",
        "focus_count": len(focus_codes),
        "market_scan_count": len(state_store.get_stock_universe() or {}) if scope == "all" else len(focus_codes),
        "eligible_count": len(candidate_source),
        "ai_scored_count": quality_meta.get("ai_scored_count", 0),
        "candidate_count": candidate_count,
        "quality_scoring_meta": quality_meta,
        "ai_meta": ai_meta,
        "signal_count": 0,
    }
    existing = [s for s in state_store.get_signals() if not s.get("ai_recommendation")]
    state_store.set_signals(existing)
    state_store.set_ai_recommendations(result)
    return _json_safe(result)


def run_ai_stock_picking(
    strategy: str = "short",
    limit: int = 8,
    universe_limit: int = 20,
    scope: str = "focus",
    focus_codes: Optional[List[str]] = None,
    progress_callback=None,
) -> dict:
    if not ai_model_service.is_ready():
        return _persist_ai_error_result(
            "AI模型尚未配置或未启用。请先在系统配置里填写接口地址、密钥，并选择默认模型。",
            strategy=strategy,
            scope=scope,
            focus_codes=focus_codes,
            ai_meta={"ok": False, "used_ai": False, "error": "AI模型尚未配置或未启用"},
        )
    scope = "all" if scope == "all" else "focus"
    if scope == "all":
        limit = min(max(int(limit or 3), 1), 3)
    focus_codes = _normalize_focus_codes(focus_codes)
    if progress_callback:
        progress_callback({"stage": "prepare", "message": "正在准备股票池与行情缓存"})
    screening = state_store.get_screening_results()
    if not state_store.get_stock_universe():
        stocks = data_fetcher.read_stock_universe_cache() or DEMO_FALLBACK_STOCKS
        state_store.update_stock_universe(stocks)
        codes = [s.get("code") for s in stocks[: min(len(stocks), 80)] if s.get("code")]
        if codes:
            try:
                data_fetcher.fetch_realtime_batch(codes[:50])
            except Exception:
                pass
    if scope == "all":
        if progress_callback:
            progress_callback({"stage": "quant_screening", "message": "正在扫描全市场并执行第二阶段量化筛选"})
        screening = stock_screener.run_screening(limit=50, return_all=True, strategy=strategy)
    elif not screening:
        if progress_callback:
            progress_callback({"stage": "quant_screening", "message": "正在执行关注池量化筛选"})
        screening = stock_screener.run_screening(strategy=strategy)
    if not screening:
        demo = []
        realtime = state_store.get_all_realtime()
        for stock in DEMO_FALLBACK_STOCKS:
            merged = {**stock, **(realtime.get(stock["code"]) or {})}
            merged.setdefault("score", 55)
            merged.setdefault("quality_score", 55)
            merged.setdefault("score_detail", {})
            merged.setdefault("screening_logic", {})
            merged.setdefault("signal_type", "watch")
            merged.setdefault("risk_level", "medium")
            merged.setdefault("reason", "股票池为空时的演示候选，需等待真实行情缓存补齐")
            demo.append(merged)
        screening = demo
    if scope == "focus" and focus_codes:
        candidate_source = _build_focus_candidates(focus_codes, screening)
    elif scope == "focus":
        candidate_source = screening[: min(len(screening), universe_limit)]
    else:
        candidate_source = screening
    if progress_callback:
        progress_callback({
            "stage": "candidate_ready",
            "message": f"第二阶段候选完成：{len(candidate_source)}只，准备交给AI分批质量打分",
            "eligible_count": len(candidate_source),
            "market_scan_count": len(state_store.get_stock_universe() or {}) if scope == "all" else len(focus_codes),
        })
    quality_ranked, quality_meta = _ai_quality_score_candidates(candidate_source, strategy, scope, progress_callback=progress_callback)
    if scope == "all" and not quality_ranked:
        return _persist_ai_error_result(
            "短线猎人没有找到符合“震荡回落到支撑位、低位、不过热”的股票。原因通常是当前K线缓存不足，或当日市场没有满足形态的低吸票；本次不会把数据待确认股票交给AI硬选。",
            strategy=strategy,
            scope=scope,
            focus_codes=focus_codes,
            candidate_source=candidate_source,
            quality_meta=quality_meta,
            ai_meta={"ok": False, "used_ai": False, "error": "短线支撑池为空"},
        )
    if not quality_meta.get("used_ai") or quality_meta.get("errors"):
        error_text = quality_meta.get("error") or "AI质量打分未完成"
        if quality_meta.get("errors"):
            error_text = quality_meta["errors"][0]
        return _persist_ai_error_result(
            f"AI响应超时或质量打分失败：{error_text}。建议：1. 稍后重试；2. 将第一轮质量打分切到更快模型；3. 降低全候选质量打分的单批上下文；4. 检查网络或第三方网关限速。",
            strategy=strategy,
            scope=scope,
            focus_codes=focus_codes,
            candidate_source=candidate_source,
            quality_meta=quality_meta,
            ai_meta={"ok": False, "used_ai": False, "error": error_text},
        )
    review_pool_size = max(20, int(universe_limit or 20)) if scope == "all" else max(1, int(universe_limit or 20))
    candidates = [
        stock for stock in quality_ranked
        if str(stock.get("ai_quality_priority") or "").lower() != "reject"
    ][:review_pool_size]
    if not candidates:
        candidates = quality_ranked[:review_pool_size]
    if progress_callback:
        progress_callback({
            "stage": "deep_review",
            "message": f"AI质量打分完成：{quality_meta.get('ai_scored_count', 0)}只，进入重点复核池{len(candidates)}只",
            "ai_scored_count": quality_meta.get("ai_scored_count", 0),
            "candidate_count": len(candidates),
            "batch_done": quality_meta.get("batch_count", 0),
            "batch_total": quality_meta.get("batch_total", quality_meta.get("batch_count", 0)),
        })
    evidence_items = [_candidate_evidence(stock, strategy) for stock in candidates]

    schema_hint = """{
  "summary": {"market_view": "一句话市场判断", "method": "筛选方法说明"},
  "recommendations": [{
    "code": "股票代码",
    "ai_rank_score": 0-100,
    "ai_action": "可小仓试单/等待回踩确认/暂不买入",
    "youzi_quality_view": "必须说明情绪周期、主线板块、龙头地位、盘口承接、仓位纪律",
    "ai_reason": "为什么买或为什么等待，必须引用K线、成交量、业绩/暴雷风险、资金、新闻和游资经验依据",
    "ai_risks": ["风险1", "风险2"],
    "trade_plan": {
      "suggested_buy_time": "建议买入时间",
      "suggested_buy_price": 0,
      "suggested_sell_price": 0,
      "stop_loss_price": 0
    },
    "probability_ladder": [{"range":"跌10%到跌9%","bucket":-10,"probability":0}]
  }]
}"""
    compact = []
    for item in evidence_items:
        compact.append({
            "code": item["code"],
            "name": item["name"],
            "ai_quality_score": item.get("ai_quality_score"),
            "ai_quality_label": item.get("ai_quality_label"),
            "ai_quality_reason": item.get("ai_quality_reason"),
            "quant_score": item.get("score_card", {}).get("final_score"),
            "screening_score": item.get("score"),
            "scores": item.get("score_card", {}).get("scores", {}),
            "decision": {
                "direction": item.get("decision", {}).get("direction"),
                "entry_condition": item.get("decision", {}).get("entry_condition"),
                "invalid_condition": item.get("decision", {}).get("invalid_condition"),
            },
            "risk": item.get("risk", {}).get("risk_report", {}),
            "trade_plan": item.get("trade_plan", {}),
            "probability_ladder": item.get("probability_ladder", []),
            "evidence": item.get("evidence", {}),
            "youzi_experience": item.get("youzi_experience", {}),
        })

    system_prompt = (
        "你是A股量化投研风控助手。只从给定候选中选择，不能编造不存在的数据。"
        "目标是小型低频猎人策略：优先高质量信号、支撑位低吸、资金和新闻确认、严格风控。"
        "必须使用游资经验字段复核：情绪周期、主线板块、龙头地位、盘口承接、公告是否被板块确认、仓位赢面建议。"
        "必须输出JSON，且每个推荐必须说明K线、成交量/成交额、公司业绩或暴雷风险、新闻公告、风控依据。"
        "真实下单默认禁止，结论只作为模拟盘信号。"
    )
    ai_payload, ai_meta = ai_model_service.chat_json(
        "trade_decision",
        system_prompt,
        {
            "strategy": strategy,
            "scope": "所有股票选股" if scope == "all" else "关注股票选股",
            "focus_codes": focus_codes,
            "quality_scoring": {
                "eligible_count": len(candidate_source),
                "ai_scored_count": quality_meta.get("ai_scored_count", 0),
                "batch_count": quality_meta.get("batch_count", 0),
                "used_ai": quality_meta.get("used_ai", False),
            },
            "market_retail_institution_mood": _market_retail_institution_mood(),
            "candidates": compact,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        schema_hint=schema_hint,
    )
    if progress_callback:
        progress_callback({
            "stage": "final_decision",
            "message": "最终交易建议模型已返回，正在整理推荐与信号",
            "used_ai": (ai_meta or {}).get("used_ai", False),
        })
    if not ai_payload:
        error_text = (ai_meta or {}).get("error") or "最终交易建议模型没有返回有效内容"
        return _persist_ai_error_result(
            f"AI响应超时或最终复核失败：{error_text}。建议：1. 稍后重试；2. 最终交易建议使用响应更快的模型；3. 降低复核池数量或上下文；4. 检查 DeepSeek 网关状态。",
            strategy=strategy,
            scope=scope,
            focus_codes=focus_codes,
            candidate_source=candidate_source,
            quality_meta=quality_meta,
            ai_meta=ai_meta,
            candidate_count=len(candidates),
        )
    reviewed_all = _merge_ai_review(evidence_items, ai_payload or {})
    for item in reviewed_all:
        item["analysis_type"] = "auto_ai_pick"
        item["recommend_buy"] = _is_buy_recommendation(item)
    reviewed = [item for item in reviewed_all if item.get("recommend_buy")][:limit]
    if scope == "all" and len(reviewed) < 2:
        existing_codes = {item.get("code") for item in reviewed}
        promoted = _force_best_buy_recommendations([item for item in reviewed_all if item.get("code") not in existing_codes], target=3 - len(reviewed))
        reviewed.extend(promoted)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    expires_at = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    signals = []
    for item in reviewed:
        rank_score = _to_float(item.get("ai_rank_score"))
        if not _is_buy_recommendation(item):
            continue
        action_text = item.get("ai_action") or ""
        if action_text == "风控未通过，暂不买入":
            continue
        if rank_score < 68 and "可小仓" not in action_text:
            continue
        plan = item.get("trade_plan", {})
        signals.append({
            "signal_id": f"AI_BUY_{item['code']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "type": "ai_buy",
            "code": item["code"],
            "name": item.get("name", ""),
            "price": plan.get("current_price"),
            "entry_price": plan.get("suggested_buy_price"),
            "target_price": plan.get("suggested_sell_price"),
            "stop_loss_price": plan.get("stop_loss_price"),
            "strength": "strong" if rank_score >= 75 else "medium",
            "score": rank_score,
            "reason": item.get("ai_reason", ""),
            "ai_recommendation": True,
            "generated_at": generated_at,
            "expires_at": expires_at,
        })
    existing = [s for s in state_store.get_signals() if not s.get("ai_recommendation")]
    state_store.set_signals(existing + signals)
    result = {
        "recommendations": reviewed,
        "reviewed_candidates": sorted(reviewed_all, key=lambda x: (1 if x.get("recommend_buy") else 0, _to_float(x.get("ai_rank_score"))), reverse=True)[: min(20, len(reviewed_all))],
        "reviewed_count": len(reviewed_all),
        "filtered_wait_count": len([item for item in reviewed_all if item.get("code") not in {row.get("code") for row in reviewed}]),
        "summary": (ai_payload or {}).get("summary") if isinstance(ai_payload, dict) else {
            "market_view": "AI接口未返回有效内容，已使用本地量化规则生成降级推荐。",
            "method": "量化选股Top候选 + 评分卡 + 决策 + 风控复核 + 概率分布",
        },
        "generated_at": generated_at,
        "strategy": strategy,
        "scope": scope,
        "scope_label": "所有股票选股" if scope == "all" else "关注股票选股",
        "focus_count": len(focus_codes),
        "market_scan_count": len(state_store.get_stock_universe() or {}) if scope == "all" else len(focus_codes),
        "eligible_count": len(candidate_source),
        "ai_scored_count": quality_meta.get("ai_scored_count", 0),
        "candidate_count": len(candidates),
        "quality_scoring_meta": quality_meta,
        "ai_meta": ai_meta,
        "signal_count": len(signals),
    }
    state_store.set_ai_recommendations(result)
    return _json_safe(result)


def analyze_single_stock(code: str, strategy: str = "short") -> dict:
    stock = state_store.get_stock_info(code) or {"code": code, "name": code}
    realtime = state_store.get_realtime(code) or data_fetcher.read_realtime_cache(code) or {}
    stock = {**stock, **realtime, "code": code}
    stock.setdefault("score", 50)
    stock.setdefault("quality_score", 50)
    stock.setdefault("score_detail", {})
    stock.setdefault("screening_logic", {})
    stock.setdefault("signal_type", "watch")
    stock.setdefault("risk_level", "medium")
    stock.setdefault("reason", "单股AI分析")

    item = _candidate_evidence(stock, strategy)
    schema_hint = """{
  "code": "股票代码",
  "ai_rank_score": 0-100,
  "ai_action": "推荐购买/短期观察/长期观察/不推荐购买",
  "holding_style": "短期/长期/短期和长期均不适合",
  "recommend_buy": true,
  "ai_reason": "必须引用K线、成交量、业绩/暴雷风险、资金、新闻和风控依据",
  "ai_risks": ["风险1", "风险2"],
  "trade_plan": {
    "suggested_buy_time": "建议买入时间",
    "suggested_buy_price": 0,
    "suggested_sell_price": 0,
    "stop_loss_price": 0
  },
  "probability_ladder": [{"range":"跌10%到跌9%","bucket":-10,"probability":0}]
}"""
    system_prompt = (
        "你是A股个股AI投研助手。只能基于给定数据分析，不能编造财务、公告或行情。"
        "要明确是否推荐购买，偏短期还是长期。若数据不足，要说明缺什么数据。"
        "真实下单默认禁止，结论只用于模拟盘和人工复核。必须输出JSON。"
    )
    compact = {
        "code": item["code"],
        "name": item["name"],
        "scores": item.get("score_card", {}).get("scores", {}),
        "final_score": item.get("score_card", {}).get("final_score"),
        "decision": item.get("decision", {}),
        "risk": item.get("risk", {}).get("risk_report", {}),
        "trade_plan": item.get("trade_plan", {}),
        "probability_ladder": item.get("probability_ladder", []),
        "evidence": item.get("evidence", {}),
    }
    ai_payload, ai_meta = ai_model_service.chat_json(
        "deep_analysis",
        system_prompt,
        {"strategy": strategy, "stock": compact, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        schema_hint=schema_hint,
    )
    if ai_payload:
        merged = _merge_ai_review([item], {"recommendations": [ai_payload]})[0]
        merged["holding_style"] = ai_payload.get("holding_style") or ("短期" if strategy == "short" else "长期")
        merged["recommend_buy"] = bool(ai_payload.get("recommend_buy", False))
    else:
        merged = _fallback_review([item])[0]
        merged["holding_style"] = "短期观察" if strategy == "short" else "长期观察"
        merged["recommend_buy"] = merged.get("ai_action") == "可小仓试单"
    merged["analysis_type"] = "single_stock"
    merged["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = {
        "analysis": merged,
        "ai_meta": ai_meta,
        "generated_at": merged["generated_at"],
        "strategy": strategy,
    }
    current = state_store.get_ai_recommendations()
    rows = [r for r in (current.get("recommendations") or []) if r.get("code") != code]
    rows.insert(0, merged)
    current.update({
        "recommendations": rows[:30],
        "generated_at": result["generated_at"],
        "strategy": strategy,
        "ai_meta": ai_meta,
        "summary": current.get("summary") or {"market_view": "单股AI分析列表", "method": "详情页触发"},
    })
    state_store.set_ai_recommendations(current)
    return _json_safe(result)
