"""
多因子选股引擎 - 5阶段筛选流程
Stage 1: 硬性过滤（剔除ST/暴雷/停牌等）
Stage 2: 量价因子评分
Stage 3: 资金因子评分
Stage 4: 技术因子评分
Stage 5: 综合评分与排序
"""
import time
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Optional
from loguru import logger

from app.services import (
    state_store,
    data_fetcher,
    technical_analysis,
    news_service,
    sector_service,
    disclosure_service,
    historical_rule_service,
)

# 默认选股权重配置
DEFAULT_WEIGHTS = {
    "eligibility": 0.08,
    "fundamental": 0.08,
    "volume_turnover": 0.14,
    "capital_flow": 0.15,
    "technical": 0.12,
    "support_pullback": 0.10,
    "sector": 0.12,
    "news": 0.07,
    "intraday": 0.04,
    "sector_momentum": 0.06,
    "leader_follow": 0.04,
    "historical_rule": 0.05,
    "youzi_experience": 0.05,
}

# 短线权重（侧重震荡支撑低吸，其次才是资金确认）
SHORT_TERM_WEIGHTS = {
    "eligibility": 0.06,
    "fundamental": 0.05,
    "volume_turnover": 0.13,
    "capital_flow": 0.15,
    "technical": 0.10,
    "support_pullback": 0.22,
    "sector": 0.08,
    "news": 0.05,
    "intraday": 0.05,
    "sector_momentum": 0.08,
    "leader_follow": 0.03,
    "historical_rule": 0.06,
    "youzi_experience": 0.08,
}

# 长线权重（侧重技术和情绪）
LONG_TERM_WEIGHTS = {
    "eligibility": 0.12,
    "fundamental": 0.16,
    "volume_turnover": 0.10,
    "capital_flow": 0.11,
    "technical": 0.18,
    "support_pullback": 0.07,
    "sector": 0.09,
    "news": 0.07,
    "intraday": 0.02,
    "sector_momentum": 0.04,
    "leader_follow": 0.04,
    "historical_rule": 0.05,
    "youzi_experience": 0.03,
}

# 事件驱动权重（侧重新闻-板块-个股链路）
EVENT_DRIVEN_WEIGHTS = {
    "eligibility": 0.05,
    "fundamental": 0.04,
    "volume_turnover": 0.11,
    "capital_flow": 0.14,
    "technical": 0.08,
    "support_pullback": 0.05,
    "sector": 0.15,
    "news": 0.13,
    "intraday": 0.05,
    "sector_momentum": 0.15,
    "leader_follow": 0.05,
    "historical_rule": 0.04,
    "youzi_experience": 0.08,
}


def get_screening_weights(style: Optional[str] = None) -> dict:
    """根据用户交易偏好动态返回选股权重"""
    if style is None:
        settings = state_store.get_user_settings()
        style = settings.get("trading_style", "short")
    if style == "long":
        return LONG_TERM_WEIGHTS
    elif style == "event_driven":
        return EVENT_DRIVEN_WEIGHTS
    elif style == "short":
        return SHORT_TERM_WEIGHTS
    return DEFAULT_WEIGHTS


def _get_trading_style() -> str:
    return state_store.get_user_settings().get("trading_style", "short")


def get_screening_logic_summary() -> dict:
    """供前端展示当前智能选股逻辑。"""
    weights = get_screening_weights()
    style = _get_trading_style()
    return {
        "version": "support-pool-quality-v6-history",
        "weights": weights,
        "stages": [
            "资格过滤：剔除ST、停牌、涨停不可买、异常波动和用户黑名单板块。",
            "短线预选池：短线策略先筛出震荡箱体、回落支撑、未破位、不过热的低位支撑票。",
            "池内选优：只在支撑形态池内，再按资金、量价、技术、板块、新闻等剩余权重排序。",
            "估值财务：PE/PB/市值/现金流可用时加权，缺字段保持中性并标记待补。",
            "量价资金：量比、换手、成交额、主力/大单资金流和连续净流入。",
            "技术位置：均线、MACD、KDJ、RSI、布林带和支撑位接近度。",
            "震荡支撑低吸：优先选箱体震荡、回落到支撑位、未破位且不过热的股票。",
            "板块共振：行业/概念板块涨跌、主力净流入、新闻正负面归因。",
            "板块资金异动：比较最近两次板块资金快照，捕捉主力资金加速流入。",
            "龙头跟随：若板块龙头接近涨停，寻找未涨停但量价/资金确认的次龙头。",
            "新闻情绪：直接命中个股名称/代码的多源新闻影响分。",
            "短线形态：尾盘成交占比、尾盘收益、近5日下跌与支撑位。",
        ],
        "data_policy": "没有真实字段时不伪造结论，使用中性分并在 screening_logic 中标记 missing/partial。",
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


def _score_range(value: float, good_low: float, good_high: float, *, missing: float = 55.0) -> float:
    if value <= 0:
        return missing
    if good_low <= value <= good_high:
        center = (good_low + good_high) / 2
        width = max((good_high - good_low) / 2, 1e-9)
        return round(82 + (1 - abs(value - center) / width) * 18, 1)
    if value < good_low:
        return round(_clamp(70 - (good_low - value) / max(good_low, 1) * 30), 1)
    return round(_clamp(78 - (value - good_high) / max(good_high, 1) * 45), 1)


# ==================== Stage 1: 硬性过滤 ====================

def apply_hard_filters(stocks: list) -> list:
    """硬性过滤：剔除不符合条件的股票"""
    negative_news = state_store.get_negative_news()
    filtered = []

    for stock in stocks:
        code = stock.get("code", "")
        name = stock.get("name", "")
        price = _to_float(stock.get("price"))
        volume = _to_float(stock.get("volume"))
        pct_change = _to_float(stock.get("pct_change"))
        is_st = stock.get("is_st", False)

        # 1. 剔除ST
        if is_st or "ST" in name.upper():
            continue

        # 2. 剔除有负面新闻的
        if code in negative_news:
            continue

        # 3. 剔除停牌（价格为0或成交量为0）
        if price <= 0 or volume <= 0:
            continue

        # 4. 剔除涨跌幅异常（可能是新股或特殊情况）
        pct = abs(pct_change)
        if pct > 11:  # 超过涨跌停限制
            continue

        # 5. 剔除涨停股（无法买入）
        if pct_change >= 9.9:
            continue

        # 6. 板块开关过滤（根据用户偏好）
        settings = state_store.get_user_settings()
        board_allow = settings.get("board_allow", {})
        market = stock.get("market", "")
        if market == "创业板" and not board_allow.get("gem", True):
            continue
        if market == "科创板" and not board_allow.get("star", True):
            continue
        if market == "北交所" and not board_allow.get("bse", True):
            continue

        # 7. 板块黑名单过滤
        blocked = settings.get("blocked_sectors", [])
        industry = stock.get("industry", "")
        if industry and industry in blocked:
            continue

        filtered.append(stock)

    logger.info(f"硬性过滤: {len(stocks)} -> {len(filtered)}")
    return filtered


def score_eligibility(stock: dict) -> tuple[float, list]:
    """资格层评分：硬过滤之外，给可交易质量一个分数。"""
    score = 100.0
    notes = []
    market = stock.get("market", "")
    code = stock.get("code", "")
    pct = abs(_to_float(stock.get("pct_change")))
    amount = _to_float(stock.get("amount"))
    turnover = _to_float(stock.get("turnover_rate"))

    if market in ("北交所", "科创板"):
        score -= 10
        notes.append(f"{market}波动约束更高")
    if code.startswith(("8", "4")):
        score -= 10
        notes.append("北交所流动性折扣")
    if amount and amount < 5e7:
        score -= 18
        notes.append("成交额偏低")
    if turnover > 10:
        score -= 18
        notes.append("换手过热")
    elif 1 <= turnover <= 8:
        notes.append("换手适中")
    if pct > 7:
        score -= 10
        notes.append("日内波动偏大")

    return round(_clamp(score), 1), notes[:3]


def score_fundamental_health(stock: dict) -> tuple[float, dict]:
    """估值与财务健康层。缺真实字段时保持中性并明确标记。"""
    pe = _to_float(stock.get("pe_ttm") or stock.get("pe") or stock.get("pe_dynamic"))
    pb = _to_float(stock.get("pb"))
    market_cap = _to_float(
        stock.get("market_cap")
        or stock.get("total_market_cap")
        or stock.get("total_mv")
        or stock.get("total_value")
    )
    operating_cf = stock.get("operating_cash_flow")
    capex = stock.get("capital_expenditure") or stock.get("capex")
    free_cf = stock.get("free_cash_flow")

    parts = []
    notes = []
    missing = []

    if pe > 0:
        parts.append(_score_range(pe, 1, 20))
        notes.append(f"PE {pe:.1f}")
    else:
        missing.append("PE_TTM")
    if pb > 0:
        parts.append(_score_range(pb, 0.2, 2.0))
        notes.append(f"PB {pb:.1f}")
    else:
        missing.append("PB")

    if market_cap > 0:
        cap_yi = market_cap / 1e8
        parts.append(_score_range(cap_yi, 10, 100, missing=55))
        notes.append(f"市值{cap_yi:.0f}亿")
    else:
        missing.append("总市值")

    cash_scores = []
    for label, value in (("经营现金流", operating_cf), ("资本开支", capex), ("自由现金流", free_cf)):
        if value in (None, "", "-"):
            missing.append(label)
            continue
        val = _to_float(value)
        cash_scores.append(80 if val > 0 else 25)
        notes.append(f"{label}{'为正' if val > 0 else '为负'}")
    if cash_scores:
        parts.append(sum(cash_scores) / len(cash_scores))

    disclosure = disclosure_service.get_disclosure_risk_profile(stock.get("code", ""))
    disclosure_risk = _to_float(disclosure.get("risk_score"))
    if disclosure_risk >= 60:
        parts.append(15)
        notes.append("公告/财报高风险")
    elif disclosure_risk >= 25:
        parts.append(35)
        notes.append("公告/财报中等风险")
    elif disclosure.get("data_status") in ("formal", "news_keyword_only"):
        parts.append(65)

    score = sum(parts) / len(parts) if parts else 55.0
    return round(_clamp(score), 1), {
        "pe_ttm": pe or None,
        "pb": pb or None,
        "market_cap": market_cap or None,
        "disclosure_risk": {
            "risk_score": disclosure.get("risk_score"),
            "risk_level": disclosure.get("risk_level"),
            "risk_flags": disclosure.get("risk_flags", []),
            "data_status": disclosure.get("data_status"),
            "items": disclosure.get("items", [])[:3],
        },
        "missing": missing[:8],
        "notes": notes[:5],
        "data_status": "partial" if missing and parts else ("missing" if not parts else "ready"),
    }


def summarize_retail_institution_flow(code: str) -> dict:
    flow = state_store.get_money_flow(code) or {}
    if not flow:
        flow = data_fetcher.read_money_flow_cache(code) or {}
    flows = flow.get("flows") or []
    if not flows:
        return {
            "data_status": "missing",
            "main_net_inflow": 0,
            "large_net_inflow": 0,
            "retail_pressure": 50,
            "main_sentiment": "unknown",
            "retail_sentiment": "unknown",
            "notes": ["缺少资金流缓存"],
        }
    latest = flows[-1]
    main = _to_float(latest.get("main_net_inflow"))
    large = _to_float(latest.get("large_net_inflow")) + _to_float(latest.get("super_large_net_inflow"))
    small = _to_float(latest.get("small_net_inflow"))
    medium = _to_float(latest.get("medium_net_inflow"))
    amount_base = max(abs(main) + abs(large) + abs(small) + abs(medium), 1.0)
    main_ratio = round(main / amount_base * 100, 2)
    retail_ratio = round((small + medium) / amount_base * 100, 2)
    retail_pressure = _clamp(50 + retail_ratio * 0.45 - main_ratio * 0.35)
    return {
        "data_status": "ready",
        "main_net_inflow": main,
        "large_net_inflow": large,
        "small_medium_net_inflow": small + medium,
        "main_ratio_pct": main_ratio,
        "retail_ratio_pct": retail_ratio,
        "retail_pressure": round(retail_pressure, 1),
        "main_sentiment": "inflow" if main > 0 else "outflow" if main < 0 else "neutral",
        "retail_sentiment": "chasing" if retail_ratio > 15 and main_ratio < 0 else "leaving" if retail_ratio < -15 else "neutral",
        "notes": [
            f"主力占比{main_ratio:.1f}%",
            f"散户/中单压力{retail_ratio:.1f}%",
        ],
    }


def score_intraday_pattern(stock: dict, daily_df: Optional[pd.DataFrame]) -> tuple[float, dict]:
    """短线形态层：尾盘/价量/连续下跌接近支撑的可用版本。"""
    score = 50.0
    notes = []
    code = stock.get("code", "")
    minutes = state_store.get_intraday(code)

    if minutes and len(minutes) >= 20:
        total_volume = sum(_to_float(m.get("volume")) for m in minutes)
        tail = minutes[-30:] if len(minutes) >= 30 else minutes[-10:]
        tail_volume = sum(_to_float(m.get("volume")) for m in tail)
        first_price = _to_float(tail[0].get("price"))
        last_price = _to_float(tail[-1].get("price"))
        tail_ratio = tail_volume / total_volume if total_volume else 0
        tail_ret = (last_price - first_price) / first_price * 100 if first_price else 0
        if 0.12 <= tail_ratio <= 0.35 and tail_ret > 0:
            score += 18
            notes.append("尾盘温和放量上行")
        elif tail_ratio > 0.45:
            score -= 12
            notes.append("尾盘成交占比过高")
        if tail_ret > 2.5:
            score -= 8
            notes.append("尾盘急拉需防偷袭")
    else:
        notes.append("分时/集合竞价数据待接入")

    if daily_df is not None and len(daily_df) >= 20:
        recent = daily_df.tail(5)
        down_days = int((recent["pct_change"] < 0).sum()) if "pct_change" in recent else 0
        df = technical_analysis.calc_all_indicators(daily_df.copy())
        sr = technical_analysis.calc_support_resistance(df)
        supports = sr.get("support_levels", [])
        current_price = _to_float(df["close"].iloc[-1])
        if down_days >= 3:
            score += 8
            notes.append(f"近5日{down_days}天下跌")
        if supports and current_price:
            nearest_support = min(supports, key=lambda s: abs(s - current_price))
            distance = (current_price - nearest_support) / current_price
            if 0 <= distance <= 0.03:
                score += 14
                notes.append("接近下方支撑")
            elif distance < 0:
                score -= 8
                notes.append("跌破近期支撑")

    return round(_clamp(score), 1), {"notes": notes[:5], "has_intraday": bool(minutes)}


def score_support_pullback(stock: dict, daily_df: Optional[pd.DataFrame]) -> tuple[float, dict]:
    """震荡支撑低吸分：短线优先寻找箱体内回落到支撑位的股票。"""
    if daily_df is None or len(daily_df) < 20:
        pct = _to_float(stock.get("pct_change"))
        turnover = _to_float(stock.get("turnover_rate"))
        score = 55.0
        notes = ["K线不足，低吸形态待确认"]
        if -4 <= pct <= 1.5:
            score += 8
            notes.append("日内未追高")
        if 0.8 <= turnover <= 6:
            score += 5
            notes.append("换手适中")
        if pct > 4:
            score -= 18
            notes.append("短线涨幅偏高")
        return round(_clamp(score), 1), {"notes": notes, "data_status": "partial"}

    df = daily_df.copy().tail(60).reset_index(drop=True)
    if "close" not in df or "high" not in df or "low" not in df:
        return 55.0, {"notes": ["K线字段不足"], "data_status": "partial"}

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    current = _to_float(close.iloc[-1])
    if current <= 0:
        return 50.0, {"notes": ["价格无效"], "data_status": "invalid"}

    lookback = df.tail(20)
    box_high = _to_float(lookback["high"].max())
    box_low = _to_float(lookback["low"].min())
    box_mid = (box_high + box_low) / 2 if box_high and box_low else current
    box_width_pct = (box_high - box_low) / box_mid * 100 if box_mid else 0
    near_support_pct = (current - box_low) / current * 100 if current else 99
    drawdown_from_high_pct = (box_high - current) / box_high * 100 if box_high else 0
    ma10 = close.rolling(10).mean()
    ma20 = close.rolling(20).mean()
    ma20_now = _to_float(ma20.iloc[-1])
    ma20_prev = _to_float(ma20.iloc[-6]) if len(ma20.dropna()) >= 6 else ma20_now
    ma20_slope_pct = (ma20_now - ma20_prev) / ma20_prev * 100 if ma20_prev else 0
    pct_5 = (current - _to_float(close.iloc[-6])) / _to_float(close.iloc[-6]) * 100 if len(close) >= 6 and _to_float(close.iloc[-6]) else 0
    recent_down_days = int((lookback.tail(5)["pct_change"] < 0).sum()) if "pct_change" in lookback else 0
    latest_pct = _to_float(df.iloc[-1].get("pct_change")) if "pct_change" in df.columns else _to_float(stock.get("pct_change"))
    turnover = _to_float(stock.get("turnover_rate") or df.iloc[-1].get("turnover_rate"))

    score = 50.0
    notes = []
    if 6 <= box_width_pct <= 28:
        score += 18
        notes.append("20日箱体震荡")
    elif box_width_pct < 6:
        score += 6
        notes.append("窄幅震荡")
    else:
        score -= 8
        notes.append("波动过大")

    if -3 <= ma20_slope_pct <= 3:
        score += 12
        notes.append("中期均线平缓")
    elif ma20_slope_pct < -6:
        score -= 10
        notes.append("均线下行较快")

    if 0 <= near_support_pct <= 3.5:
        score += 22
        notes.append("贴近箱体支撑")
    elif 3.5 < near_support_pct <= 7:
        score += 10
        notes.append("靠近支撑")
    elif current < box_low:
        score -= 20
        notes.append("跌破箱体支撑")

    if 4 <= drawdown_from_high_pct <= 18:
        score += 10
        notes.append("从箱体高位回落")
    elif drawdown_from_high_pct < 2:
        score -= 10
        notes.append("仍在箱体高位")

    if -12 <= pct_5 <= -1:
        score += 10
        notes.append("近5日回调")
    elif pct_5 > 8:
        score -= 16
        notes.append("近5日涨幅偏高")

    if recent_down_days >= 2:
        score += 5
        notes.append(f"近5日{recent_down_days}天下跌")
    if -5 <= latest_pct <= 2:
        score += 6
        notes.append("当日不追高")
    elif latest_pct > 5:
        score -= 14
        notes.append("当日涨幅偏高")
    if 0.5 <= turnover <= 6:
        score += 5
        notes.append("换手适中")
    elif turnover > 10:
        score -= 8
        notes.append("换手偏热")

    return round(_clamp(score), 1), {
        "box_high": round(box_high, 2),
        "box_low": round(box_low, 2),
        "box_width_pct": round(box_width_pct, 2),
        "near_support_pct": round(near_support_pct, 2),
        "drawdown_from_high_pct": round(drawdown_from_high_pct, 2),
        "ma20_slope_pct": round(ma20_slope_pct, 2),
        "pct_5": round(pct_5, 2),
        "latest_pct": round(latest_pct, 2),
        "turnover": round(turnover, 2),
        "notes": notes[:6],
        "data_status": "ready",
    }


def build_sector_context(limit: int = 20) -> dict:
    """把板块资金流和新闻归因压成个股可用的映射。"""
    context = {"by_code": {}, "role_by_code": {}, "top_sectors": [], "coverage": 0}
    try:
        rankings = sector_service.get_sector_rankings()
    except Exception as e:
        logger.warning(f"板块上下文构建失败: {e}")
        return context

    ranked = []
    for sector in rankings:
        pct = _to_float(sector.get("pct_change"))
        main_pct = _to_float(sector.get("main_net_pct"))
        main_net = _to_float(sector.get("main_net_inflow"))
        main_delta = _to_float(sector.get("main_net_delta"))
        news_impact = _to_float(sector.get("news_impact_score"))
        positive = _to_float(sector.get("positive_news"))
        negative = _to_float(sector.get("negative_news"))
        score = _clamp(50 + pct * 3 + main_pct * 4 + news_impact * 6 + (positive - negative) * 4)
        momentum_score = _clamp(
            50
            + min(28, main_net / 1e8 * 5)
            + min(22, main_delta / 5e7 * 8)
            + pct * 2.5
            + main_pct * 2
        )
        ranked.append({
            **sector,
            "sector_score": round(score, 1),
            "sector_momentum_score": round(momentum_score, 1),
            "is_money_accelerating": main_delta > 0,
        })
    ranked.sort(key=lambda item: (item["sector_momentum_score"], item["sector_score"]), reverse=True)
    context["top_sectors"] = ranked[:limit]

    by_code: Dict[str, list] = {}
    role_by_code: Dict[str, list] = {}
    for sector in context["top_sectors"]:
        sector_code = sector.get("code")
        if not sector_code:
            continue
        if sector.get("leader_code"):
            by_code.setdefault(sector["leader_code"], []).append(sector)
        detail = state_store.get_sector_detail(sector_code)
        stocks = (detail or {}).get("stocks")
        if stocks is None:
            try:
                stocks = data_fetcher.fetch_sector_detail(sector_code)[:80]
            except Exception:
                stocks = []
        ranked_stocks = sorted(stocks or [], key=lambda x: _to_float(x.get("pct_change")), reverse=True)
        leader_code = sector.get("leader_code") or (ranked_stocks[0].get("code") if ranked_stocks else "")
        leader = next((item for item in ranked_stocks if item.get("code") == leader_code), ranked_stocks[0] if ranked_stocks else {})
        leader_pct = _to_float(leader.get("pct_change") or sector.get("leader_pct_change"))
        leader_limit_signal = leader_pct >= 9.5
        for item in stocks or []:
            code = item.get("code")
            if code:
                by_code.setdefault(code, []).append(sector)
                rank = next((idx + 1 for idx, row in enumerate(ranked_stocks) if row.get("code") == code), 999)
                pct = _to_float(item.get("pct_change"))
                amount = _to_float(item.get("amount"))
                role = "leader" if code == leader_code else ("second_leader" if rank <= 5 else "member")
                role_by_code.setdefault(code, []).append({
                    "sector_code": sector_code,
                    "sector_name": sector.get("name"),
                    "role": role,
                    "rank": rank,
                    "pct_change": pct,
                    "amount": amount,
                    "turnover_rate": _to_float(item.get("turnover_rate")),
                    "volume_ratio": _to_float(item.get("volume_ratio")),
                    "leader_code": leader_code,
                    "leader_name": leader.get("name") or sector.get("leader_name"),
                    "leader_pct_change": leader_pct,
                    "leader_limit_signal": leader_limit_signal,
                    "sector_momentum_score": sector.get("sector_momentum_score"),
                    "sector_score": sector.get("sector_score"),
                    "main_net_inflow": sector.get("main_net_inflow"),
                    "main_net_delta": sector.get("main_net_delta"),
                })

    context["by_code"] = by_code
    context["role_by_code"] = role_by_code
    context["coverage"] = len(by_code)
    return context


def score_sector_heat(stock: dict, sector_context: dict) -> tuple[float, dict]:
    """板块层评分：行业/概念资金流、涨跌幅、新闻热度共同决定。"""
    matches = list(sector_context.get("by_code", {}).get(stock.get("code", ""), []))
    industry = stock.get("industry", "")
    if industry:
        matches.extend([s for s in sector_context.get("top_sectors", []) if industry in s.get("name", "")])
    if not matches:
        return 50.0, {"matched": [], "data_status": "unmatched"}

    matches = sorted(matches, key=lambda s: _to_float(s.get("sector_score")), reverse=True)[:3]
    score = sum(_to_float(s.get("sector_score"), 50) for s in matches) / len(matches)
    return round(_clamp(score), 1), {
        "matched": [
            {
                "code": s.get("code"),
                "name": s.get("name"),
                "score": s.get("sector_score"),
                "momentum_score": s.get("sector_momentum_score"),
                "main_net_inflow": s.get("main_net_inflow"),
                "main_net_delta": s.get("main_net_delta"),
                "news_impact_score": s.get("news_impact_score"),
                "positive_news": s.get("positive_news"),
                "negative_news": s.get("negative_news"),
            }
            for s in matches
        ],
        "data_status": "matched",
    }


def score_sector_momentum(stock: dict, sector_context: dict) -> tuple[float, dict]:
    """板块资金异动分：捕捉主力资金加速流入的板块。"""
    matches = list(sector_context.get("by_code", {}).get(stock.get("code", ""), []))
    if not matches:
        return 50.0, {"matched": [], "data_status": "unmatched"}
    matches = sorted(matches, key=lambda s: _to_float(s.get("sector_momentum_score")), reverse=True)[:3]
    score = sum(_to_float(s.get("sector_momentum_score"), 50) for s in matches) / len(matches)
    if any(_to_float(s.get("main_net_delta")) > 5e7 for s in matches):
        score += 8
    if any(_to_float(s.get("main_net_inflow")) > 3e8 for s in matches):
        score += 6
    return round(_clamp(score), 1), {
        "matched": [
            {
                "code": s.get("code"),
                "name": s.get("name"),
                "momentum_score": s.get("sector_momentum_score"),
                "main_net_inflow": s.get("main_net_inflow"),
                "main_net_delta": s.get("main_net_delta"),
                "delta_direction": s.get("delta_direction"),
            }
            for s in matches
        ],
        "data_status": "matched",
    }


def score_leader_follow(stock: dict, sector_context: dict) -> tuple[float, dict]:
    """龙头跟随分：龙头接近涨停时，寻找有资金/量价确认的次龙头。"""
    roles = list(sector_context.get("role_by_code", {}).get(stock.get("code", ""), []))
    if not roles:
        return 50.0, {"roles": [], "data_status": "unmatched"}

    candidates = []
    stock_pct = _to_float(stock.get("pct_change"))
    stock_amount = _to_float(stock.get("amount"))
    stock_vr = _to_float(stock.get("volume_ratio"))
    stock_turnover = _to_float(stock.get("turnover_rate"))
    for role in roles:
        score = 50.0
        if role.get("leader_limit_signal"):
            score += 18
        leader_pct = _to_float(role.get("leader_pct_change"))
        if leader_pct >= 7:
            score += 8
        if role.get("role") == "second_leader":
            score += 12
        elif role.get("role") == "leader":
            score += 8
        if 1 <= stock_pct < 9.5:
            score += min(14, stock_pct * 1.8)
        if stock_vr >= 1.5:
            score += min(8, stock_vr * 2)
        if 1 <= stock_turnover <= 8:
            score += 6
        if stock_amount > 1e8:
            score += min(8, stock_amount / 1e8 * 2)
        if _to_float(role.get("main_net_delta")) > 0:
            score += 5
        if stock_pct >= 9.8:
            score -= 12  # 已接近涨停，可买性下降
        candidates.append({**role, "follow_score": round(_clamp(score), 1)})

    candidates = sorted(candidates, key=lambda x: x["follow_score"], reverse=True)[:3]
    score = sum(_to_float(item.get("follow_score"), 50) for item in candidates) / len(candidates)
    return round(_clamp(score), 1), {"roles": candidates, "data_status": "matched"}


def score_stock_news(stock: dict) -> tuple[float, dict]:
    """个股新闻评分：直接命中个股名称/代码的新闻优先。"""
    code = stock.get("code", "")
    name = stock.get("name", "")
    if not code and not name:
        return 50.0, {"count": 0, "items": []}

    score = 50.0
    matched = []
    for item in state_store.get_news()[:150]:
        text = f"{item.get('title', '')} {item.get('content', '')}"
        if (code and code in text) or (name and name in text):
            tags = sector_service.classify_news_for_sectors(item)
            source_boost = min(8, max(0, len(item.get("duplicate_sources", [])) - 1) * 2)
            impact = tags.get("impact_score", 0)
            score += impact * (12 + source_boost)
            matched.append({
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "sentiment": tags.get("sentiment", "neutral"),
                "time": item.get("time", ""),
            })
    if not matched:
        return 50.0, {"count": 0, "items": [], "data_status": "no_direct_news"}
    return round(_clamp(score), 1), {"count": len(matched), "items": matched[:5], "data_status": "matched"}


def score_youzi_experience(
    stock: dict,
    *,
    support_detail: dict,
    sector_detail: dict,
    sector_momentum_detail: dict,
    leader_follow_detail: dict,
    news_detail: dict,
    intraday_detail: dict,
    historical_rule_detail: dict,
    retail_flow: dict,
    market_sentiment_score: float,
) -> tuple[float, dict]:
    """游资交割单经验因子：情绪、主线、龙头、承接、公告确认和仓位纪律。"""
    score = 50.0
    notes = []

    market_phase = "neutral"
    if market_sentiment_score >= 62:
        score += 7
        market_phase = "repair_or_hot"
        notes.append("市场情绪偏修复/活跃")
    elif market_sentiment_score <= 42:
        score -= 10
        market_phase = "risk_off"
        notes.append("市场情绪偏退潮，短线降级")

    support_status = support_detail.get("data_status")
    near_support = _to_float(support_detail.get("near_support_pct"), 99)
    drawdown = _to_float(support_detail.get("drawdown_from_high_pct"), 0)
    if support_status == "ready" and near_support <= 4 and drawdown >= 5:
        score += 12
        notes.append("低位回落支撑更符合短线低吸")
    elif support_status == "ready" and near_support > 8:
        score -= 6
        notes.append("距离支撑偏远，买点执行性下降")

    sector_matches = (sector_detail or {}).get("matched") or []
    momentum_matches = (sector_momentum_detail or {}).get("matched") or []
    best_sector = sector_matches[0] if sector_matches else {}
    best_momentum = momentum_matches[0] if momentum_matches else {}
    sector_score = _to_float(best_sector.get("score"), 50)
    momentum_score = _to_float(best_momentum.get("momentum_score"), 50)
    sector_main_delta = _to_float(best_momentum.get("main_net_delta"))
    if sector_score >= 65 or momentum_score >= 65:
        score += 10
        notes.append("板块/主线强度较好")
    if sector_main_delta > 0:
        score += 5
        notes.append("板块资金边际改善")
    if not sector_matches and not momentum_matches:
        score -= 5
        notes.append("缺少明确主线或板块联动")

    leader_roles = (leader_follow_detail or {}).get("roles") or []
    best_role = leader_roles[0] if leader_roles else {}
    leader_status = best_role.get("role") or "unknown"
    if leader_status == "leader":
        score += 8
        notes.append("个股具备板块前排/龙头属性")
    elif leader_status == "second_leader":
        score += 6
        notes.append("个股具备次前排跟随属性")
    if best_role.get("leader_limit_signal"):
        score += 4
        notes.append("龙头涨停对板块有带动")

    volume_ratio = _to_float(stock.get("volume_ratio"))
    turnover = _to_float(stock.get("turnover_rate"))
    pct = _to_float(stock.get("pct_change"))
    tape_status = "neutral"
    if 1.1 <= volume_ratio <= 3.5 and 1 <= turnover <= 8 and pct < 8.5:
        score += 9
        tape_status = "accepted"
        notes.append("量比/换手/涨幅处在可承接区间")
    if pct >= 9 or volume_ratio >= 6 or turnover >= 18:
        score -= 12
        tape_status = "overheated"
        notes.append("涨幅、量比或换手过热，避免冲动追高")

    main_inflow = _to_float((retail_flow or {}).get("main_net_inflow"), _to_float(stock.get("main_net_inflow")))
    retail_pressure = _to_float((retail_flow or {}).get("retail_pressure"), 50)
    if main_inflow > 0 and retail_pressure <= 58:
        score += 8
        notes.append("主力边际占优且散户压力未过热")
    elif main_inflow < 0 and retail_pressure >= 60:
        score -= 10
        notes.append("主力流出且散户压力偏高")

    news_count = int(_to_float((news_detail or {}).get("count"), 0))
    if news_count:
        if sector_score >= 60 or momentum_score >= 60:
            score += 5
            notes.append("消息/公告有板块联动确认")
        else:
            score -= 5
            notes.append("消息缺少板块确认，防止利好兑现")

    history_score = _to_float((historical_rule_detail or {}).get("score"), 50)
    sample_count = int(_to_float((historical_rule_detail or {}).get("sample_count"), 0))
    if sample_count >= 30 and history_score >= 65:
        score += 7
        notes.append("历史相似规则有效性较好")
    elif sample_count >= 30 and history_score <= 45:
        score -= 7
        notes.append("历史相似规则表现偏弱")

    if intraday_detail and intraday_detail.get("data_status") not in (None, "missing", "unmatched"):
        score += 2

    win_probability = round(_clamp(score), 1)
    if win_probability < 60:
        position_advice = "空仓或仅观察"
    elif win_probability < 70:
        position_advice = "小仓模拟"
    elif win_probability < 80:
        position_advice = "中低仓模拟"
    else:
        position_advice = "高赢面仍需分批模拟验证"

    detail = {
        "market_phase": market_phase,
        "leader_status": leader_status,
        "tape_status": tape_status,
        "win_probability": win_probability,
        "position_advice": position_advice,
        "sector_confirmed": bool(sector_score >= 60 or momentum_score >= 60),
        "main_retail_confirmed": bool(main_inflow > 0 and retail_pressure <= 58),
        "news_confirmed_by_sector": bool(news_count and (sector_score >= 60 or momentum_score >= 60)),
        "notes": notes[:8],
        "data_status": "ready",
    }
    return round(_clamp(score), 1), detail


def _calc_weighted_score(score_detail: dict, weights: dict, *, exclude: set[str] | None = None) -> float:
    exclude = exclude or set()
    used = {k: v for k, v in weights.items() if k not in exclude}
    total_weight = sum(used.values()) or 1
    score = sum(_to_float(score_detail.get(k), 50) * weight for k, weight in used.items()) / total_weight
    return round(_clamp(score), 1)


def _support_pool_status(support_score: float, support_detail: dict) -> str:
    """短线两段式入池状态。"""
    status = support_detail.get("data_status")
    notes = support_detail.get("notes") or []
    if status != "ready":
        return "support_pending_data" if status == "partial" else "support_unmatched"
    near_support = _to_float(support_detail.get("near_support_pct"), 99)
    drawdown = _to_float(support_detail.get("drawdown_from_high_pct"), 0)
    box_width = _to_float(support_detail.get("box_width_pct"), 99)
    ma20_slope = abs(_to_float(support_detail.get("ma20_slope_pct"), 99))
    pct_5 = _to_float(support_detail.get("pct_5"), 99)
    latest_pct = _to_float(support_detail.get("latest_pct"), 99)
    turnover = _to_float(support_detail.get("turnover"), 0)
    rejected = any("跌破" in note or "涨幅偏高" in note or "仍在箱体高位" in note for note in notes)
    strict_shape = (
        0 <= near_support <= 4
        and 4 <= drawdown <= 18
        and 5 <= box_width <= 24
        and ma20_slope <= 4
        and -12 <= pct_5 <= 2
        and -5 <= latest_pct <= 2
        and 0.5 <= turnover <= 8
        and not rejected
    )
    watch_shape = (
        0 <= near_support <= 7
        and 2 <= drawdown <= 22
        and 4 <= box_width <= 28
        and ma20_slope <= 5
        and -14 <= pct_5 <= 4
        and -6 <= latest_pct <= 3
        and turnover <= 10
        and not rejected
    )
    if strict_shape and support_score >= 70:
        return "support_pool"
    if watch_shape and support_score >= 62:
        return "near_support_watch"
    if rejected:
        return "support_rejected"
    return "support_unmatched"


# ==================== Stage 2: 量价因子评分 ====================

def score_volume_turnover(stock: dict, daily_df: Optional[pd.DataFrame]) -> float:
    """量价因子评分 (0-100)"""
    score = 0.0

    volume_ratio = _to_float(stock.get("volume_ratio"))
    turnover_rate = _to_float(stock.get("turnover_rate"))
    amount = _to_float(stock.get("amount"))
    pct_change = _to_float(stock.get("pct_change"))

    # 1. 量比评分 (25%) - 1.5~5为健康区间
    if 1.5 <= volume_ratio <= 5:
        vr_score = min(volume_ratio / 3.0, 1.0) * 100
    elif volume_ratio > 5:
        vr_score = max(0, 100 - (volume_ratio - 5) * 20)  # 过高扣分
    elif volume_ratio > 0:
        vr_score = volume_ratio / 1.5 * 60
    else:
        vr_score = 0
    score += vr_score * 0.25

    # 2. 换手率趋势评分 (20%) - 温和放大为佳
    if 1.0 <= turnover_rate <= 8:
        tr_score = 80
    elif turnover_rate > 8:
        tr_score = max(0, 80 - (turnover_rate - 8) * 10)
    elif turnover_rate > 0.5:
        tr_score = turnover_rate / 1.0 * 60
    else:
        tr_score = 0
    score += tr_score * 0.20

    # 3. 量价配合度 (25%) - 涨放量/跌缩量为佳
    if daily_df is not None and len(daily_df) >= 5:
        recent = daily_df.tail(5)
        vol_changes = recent["volume"].pct_change().dropna()
        price_changes = recent["pct_change"].dropna()
        if len(vol_changes) >= 3 and len(price_changes) >= 3:
            # 正相关：涨时放量、跌时缩量
            corr = vol_changes.values[:len(price_changes)].tolist()
            price_vals = price_changes.values[:len(vol_changes)].tolist()
            if len(corr) == len(price_vals) and len(corr) > 0:
                correlation = np.corrcoef(corr, price_vals)[0, 1] if len(corr) > 1 else 0
                vp_score = max(0, (correlation + 1) / 2 * 100)
            else:
                vp_score = 50
        else:
            vp_score = 50
    else:
        # 没有日线数据时，用日内涨跌+量判断
        if pct_change > 0 and volume_ratio > 1:
            vp_score = 70
        elif pct_change > 0:
            vp_score = 50
        else:
            vp_score = 30
    score += vp_score * 0.25

    # 4. 成交额评分 (15%) - 越高越好（机构关注度）
    if amount > 5e8:      # >5亿
        amt_score = 100
    elif amount > 2e8:    # >2亿
        amt_score = 80
    elif amount > 1e8:    # >1亿
        amt_score = 60
    elif amount > 5e7:    # >5000万
        amt_score = 40
    else:
        amt_score = 20
    score += amt_score * 0.15

    # 5. 成交量稳定性 (15%)
    if daily_df is not None and len(daily_df) >= 10:
        vol_cv = daily_df["volume"].tail(10).std() / (daily_df["volume"].tail(10).mean() + 1e-10)
        stability_score = max(0, 100 - vol_cv * 50)
    else:
        stability_score = 50
    score += stability_score * 0.15

    return round(score, 1)


# ==================== Stage 3: 资金因子评分 ====================

def score_capital_flow(code: str) -> float:
    """资金因子评分 (0-100)"""
    score = 0.0
    flow = state_store.get_money_flow(code)

    if not flow or not flow.get("flows"):
        return 50.0  # 无数据时给中性分

    flows = flow["flows"]
    latest_main = flows[-1].get("main_net_inflow", 0) if flows else 0

    # 1. 主力净流入 (40%)
    if latest_main > 0:
        mf_score = min(100, 60 + latest_main / 1e7 * 10)  # 每千万加10分
    else:
        mf_score = max(0, 40 + latest_main / 1e7 * 10)
    score += mf_score * 0.40

    # 2. 大单+超大单占比 (30%)
    if flows:
        latest = flows[-1]
        large_inflow = latest.get("large_net_inflow", 0) + latest.get("super_large_net_inflow", 0)
        if large_inflow > 0:
            large_score = min(100, 60 + large_inflow / 1e7 * 10)
        else:
            large_score = max(0, 40 + large_inflow / 1e7 * 10)
    else:
        large_score = 50
    score += large_score * 0.30

    # 3. 连续净流入天数 (15%)
    consecutive = flow.get("consecutive_inflow_days", 0)
    consec_score = min(100, consecutive * 25)
    score += consec_score * 0.15

    # 4. 近3日趋势 (15%)
    if len(flows) >= 3:
        recent_3 = [f["main_net_inflow"] for f in flows[-3:]]
        if all(r > 0 for r in recent_3):
            trend_score = 100
        elif sum(1 for r in recent_3 if r > 0) >= 2:
            trend_score = 70
        elif recent_3[-1] > recent_3[-2]:
            trend_score = 50
        else:
            trend_score = 30
    else:
        trend_score = 50
    score += trend_score * 0.15

    structure = summarize_retail_institution_flow(code)
    if structure.get("data_status") == "ready":
        pressure = _to_float(structure.get("retail_pressure"), 50)
        score += (50 - pressure) * 0.12

    return round(_clamp(score), 1)


# ==================== Stage 4: 技术因子评分 ====================

def score_technical(daily_df: Optional[pd.DataFrame]) -> float:
    """技术因子评分 (0-100)"""
    if daily_df is None or len(daily_df) < 20:
        return 50.0

    df = technical_analysis.calc_all_indicators(daily_df.copy())
    score = 0.0

    # 1. 均线多头排列 (20%)
    if technical_analysis.is_ma_bullish_aligned(df):
        ma_score = 100
    elif len(df) >= 20 and df["ma5"].iloc[-1] > df["ma10"].iloc[-1]:
        ma_score = 70
    elif len(df) >= 20 and df["close"].iloc[-1] > df["ma20"].iloc[-1]:
        ma_score = 50
    else:
        ma_score = 20
    score += ma_score * 0.20

    # 2. MACD金叉 (20%)
    if technical_analysis.is_macd_golden_cross(df):
        macd_score = 100
    elif len(df) >= 2 and df["macd_hist"].iloc[-1] > df["macd_hist"].iloc[-2]:
        macd_score = 70  # MACD柱子变长
    elif len(df) >= 1 and df["macd_hist"].iloc[-1] > 0:
        macd_score = 50
    else:
        macd_score = 20
    score += macd_score * 0.20

    # 3. KDJ超卖回升 (15%)
    if technical_analysis.is_kdj_oversold_recovery(df):
        kdj_score = 100
    elif len(df) >= 1 and df["kdj_j"].iloc[-1] < 30:
        kdj_score = 70  # 超卖区域
    elif len(df) >= 1 and 30 <= df["kdj_j"].iloc[-1] <= 70:
        kdj_score = 50
    else:
        kdj_score = 30
    score += kdj_score * 0.15

    # 4. RSI健康区间 (15%)
    if technical_analysis.is_rsi_healthy(df):
        rsi_score = 80
    elif len(df) >= 1 and df["rsi_6"].iloc[-1] < 30:
        rsi_score = 90  # 超卖是机会
    elif len(df) >= 1 and df["rsi_6"].iloc[-1] > 80:
        rsi_score = 20  # 超买风险
    else:
        rsi_score = 50
    score += rsi_score * 0.15

    # 5. 布林带位置 (15%)
    if technical_analysis.is_price_near_boll_lower(df):
        boll_score = 90  # 下轨附近是机会
    elif len(df) >= 1 and df["boll_pctb"].iloc[-1] < 0.5:
        boll_score = 70
    elif len(df) >= 1 and df["boll_pctb"].iloc[-1] > 0.8:
        boll_score = 30  # 接近上轨
    else:
        boll_score = 50
    score += boll_score * 0.15

    # 6. 支撑位接近度 (15%)
    sr = technical_analysis.calc_support_resistance(df)
    supports = sr.get("support_levels", [])
    if supports and len(df) >= 1:
        current_price = df["close"].iloc[-1]
        nearest_support = min(supports, key=lambda s: abs(s - current_price))
        distance = (current_price - nearest_support) / current_price
        if 0 < distance < 0.02:
            sup_score = 90  # 接近支撑
        elif 0.02 <= distance < 0.05:
            sup_score = 70
        else:
            sup_score = 50
    else:
        sup_score = 50
    score += sup_score * 0.15

    return round(score, 1)


# ==================== Stage 5: 综合评分与排序 ====================

def run_screening(limit: int = 50, return_all: bool = False, strategy: Optional[str] = None, progress_callback=None) -> list:
    """执行完整选股流程"""
    start_time = time.time()
    universe = state_store.get_stock_universe()
    if not universe:
        logger.warning("股票宇宙为空，无法选股")
        return []

    stocks = list(universe.values())
    logger.info(f"开始选股，共 {len(stocks)} 只股票")

    realtime = state_store.get_all_realtime()
    stocks = [{**stock, **realtime.get(stock.get("code", ""), {})} for stock in stocks]

    # Stage 1: 硬性过滤
    filtered = apply_hard_filters(stocks)

    # 获取市场情绪
    sentiment = news_service.get_market_sentiment()
    sentiment_bonus = (sentiment.get("sentiment_score", 0) + 100) / 200 * 100  # 归一化到0-100
    sector_context = build_sector_context()
    style = strategy if strategy in ("short", "long", "event_driven") else _get_trading_style()
    weights = get_screening_weights(style)

    # Stage 2-4: 逐只评分
    scored_stocks = []
    for i, stock in enumerate(filtered):
        if progress_callback and (i == 0 or (i + 1) % 100 == 0 or i + 1 == len(filtered)):
            progress_callback({
                "stage": "screening",
                "done": i + 1,
                "total": len(filtered),
                "message": f"智能选股评分中：{i + 1}/{len(filtered)}",
            })
        code = stock["code"]
        daily_df = state_store.get_daily_bars(code)
        if daily_df is None:
            daily_df = data_fetcher.fetch_kline(code, period=101, days=80, allow_fallback=False, prefer_cache=True, force_refresh=False)
        if daily_df is None and len(filtered) <= 80:
            daily_df = data_fetcher.fetch_kline(code, period=101, days=80, allow_fallback=False)

        eligibility_score, eligibility_notes = score_eligibility(stock)
        fundamental_score, fundamental_detail = score_fundamental_health(stock)

        # Stage 2: 量价因子
        vt_score = score_volume_turnover(stock, daily_df)

        # Stage 3: 资金因子
        cf_score = score_capital_flow(code)

        # Stage 4: 技术因子
        tech_score = score_technical(daily_df)
        support_pullback_score, support_pullback_detail = score_support_pullback(stock, daily_df)
        sector_score, sector_detail = score_sector_heat(stock, sector_context)
        news_score, news_detail = score_stock_news(stock)
        intraday_score, intraday_detail = score_intraday_pattern(stock, daily_df)
        sector_momentum_score, sector_momentum_detail = score_sector_momentum(stock, sector_context)
        leader_follow_score, leader_follow_detail = score_leader_follow(stock, sector_context)
        pool_status = _support_pool_status(support_pullback_score, support_pullback_detail)
        pre_history_quality = _calc_weighted_score(
            {
                "eligibility": eligibility_score,
                "fundamental": fundamental_score,
                "volume_turnover": vt_score,
                "capital_flow": cf_score,
                "technical": tech_score,
                "sector": sector_score,
                "news": news_score,
                "intraday": intraday_score,
                "sector_momentum": sector_momentum_score,
                "leader_follow": leader_follow_score,
            },
            {k: v for k, v in weights.items() if k not in {"support_pullback", "historical_rule"}},
        )
        should_eval_history = (
            pool_status in ("support_pool", "near_support_watch")
            or pre_history_quality >= 66
            or return_all is False
        )
        if should_eval_history:
            historical_rule_detail = historical_rule_service.evaluate_similar_rule_effectiveness(
                {**stock, "support_pool_status": pool_status},
                daily_df,
                support_pullback_detail,
                strategy=style,
            )
        else:
            historical_rule_detail = historical_rule_service.neutral_effectiveness(code)
        historical_rule_score = _to_float(historical_rule_detail.get("score"), 50)
        retail_flow = summarize_retail_institution_flow(code)
        youzi_experience_score, youzi_experience_detail = score_youzi_experience(
            stock,
            support_detail=support_pullback_detail,
            sector_detail=sector_detail,
            sector_momentum_detail=sector_momentum_detail,
            leader_follow_detail=leader_follow_detail,
            news_detail=news_detail,
            intraday_detail=intraday_detail,
            historical_rule_detail=historical_rule_detail,
            retail_flow=retail_flow,
            market_sentiment_score=sentiment_bonus,
        )

        score_detail = {
            "volume_turnover": round(vt_score, 1),
            "capital_flow": round(cf_score, 1),
            "technical": round(tech_score, 1),
            "support_pullback": round(support_pullback_score, 1),
            "market_sentiment": round(sentiment_bonus, 1),
            "eligibility": round(eligibility_score, 1),
            "fundamental": round(fundamental_score, 1),
            "sector": round(sector_score, 1),
            "news": round(news_score, 1),
            "intraday": round(intraday_score, 1),
            "sector_momentum": round(sector_momentum_score, 1),
            "leader_follow": round(leader_follow_score, 1),
            "historical_rule": round(historical_rule_score, 1),
            "youzi_experience": round(youzi_experience_score, 1),
        }
        quality_score = _calc_weighted_score(score_detail, weights, exclude={"support_pullback"})

        # Stage 5: 综合评分。短线最终排序会先按支撑池过滤，再用 quality_score 选优。
        total_weight = sum(weights.values()) or 1
        total_score = (
            eligibility_score * weights["eligibility"] +
            fundamental_score * weights["fundamental"] +
            vt_score * weights["volume_turnover"] +
            cf_score * weights["capital_flow"] +
            tech_score * weights["technical"] +
            support_pullback_score * weights["support_pullback"] +
            sector_score * weights["sector"] +
            news_score * weights["news"] +
            intraday_score * weights["intraday"] +
            sector_momentum_score * weights["sector_momentum"] +
            leader_follow_score * weights["leader_follow"]
            + historical_rule_score * weights.get("historical_rule", 0)
            + youzi_experience_score * weights.get("youzi_experience", 0)
        ) / total_weight
        market_mood_adjust = (sentiment_bonus - 50) * 0.06
        total_score = _clamp(total_score + market_mood_adjust)

        # 生成推荐理由
        reasons = _generate_reasons(
            stock, daily_df, vt_score, cf_score, tech_score,
            sector_detail, news_detail, fundamental_detail, intraday_detail,
            sector_momentum_detail, leader_follow_detail, support_pullback_detail
        )

        # 判断信号类型
        signal_type = "watch"
        if total_score >= 78 and eligibility_score >= 65:
            signal_type = "buy_candidate"
        elif total_score >= 68:
            signal_type = "watch_priority"

        scored_stocks.append({
            "code": code,
            "name": stock.get("name", ""),
            "market": stock.get("market", ""),
            "score": round(total_score, 1),
            "quality_score": quality_score,
            "support_pool_status": pool_status,
            "score_detail": score_detail,
            "screening_logic": {
                "weights": weights,
                "selection_mode": "support_pool_then_quality" if style == "short" else "weighted_ranking",
                "quality_score": quality_score,
                "support_pool_status": pool_status,
                "eligibility_notes": eligibility_notes,
                "fundamental": fundamental_detail,
                "support_pullback": support_pullback_detail,
                "sector": sector_detail,
                "sector_momentum": sector_momentum_detail,
                "leader_follow": leader_follow_detail,
                "historical_rule": historical_rule_detail,
                "youzi_experience": youzi_experience_detail,
                "news": news_detail,
                "intraday": intraday_detail,
                "market_sentiment_adjust": round(market_mood_adjust, 2),
            },
            "price": stock.get("price", 0),
            "pct_change": stock.get("pct_change", 0),
            "volume_ratio": stock.get("volume_ratio", 0),
            "turnover_rate": stock.get("turnover_rate", 0),
            "amount": stock.get("amount", 0),
            "main_net_inflow": state_store.get_money_flow(code, ) and state_store.get_money_flow(code).get("latest_main_net_inflow", 0),
            "retail_institution_flow": retail_flow,
            "signal_type": signal_type,
            "reason": reasons,
            "risk_level": _assess_risk_level(total_score, stock),
            "screened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })

    # 短线先找形态池，再按剩余权重选优；非短线仍按综合分排序。
    if style == "short":
        strict_pool = [s for s in scored_stocks if s.get("support_pool_status") == "support_pool"]
        watch_pool = [s for s in scored_stocks if s.get("support_pool_status") == "near_support_watch"]
        if strict_pool:
            selected = strict_pool if return_all else strict_pool + watch_pool
            pool_mode = "support_pool"
        elif watch_pool:
            selected = watch_pool
            pool_mode = "near_support_watch"
        else:
            selected = []
            pool_mode = "no_support_pool"
        for item in selected:
            item["support_pool_mode"] = pool_mode
            item["score"] = item.get("quality_score", item.get("score", 0))
            item["screening_logic"]["support_pool_mode"] = pool_mode
            quality = _to_float(item.get("quality_score"))
            if pool_mode == "support_pool" and quality >= 78:
                item["signal_type"] = "buy_candidate"
            elif pool_mode in ("support_pool", "near_support_watch") and quality >= 68:
                item["signal_type"] = "watch_priority"
            else:
                item["signal_type"] = "watch"
            item["risk_level"] = _assess_risk_level(quality, item)
        selected.sort(
            key=lambda x: (
                _to_float(x.get("quality_score")),
                _to_float((x.get("score_detail") or {}).get("capital_flow")),
                _to_float((x.get("score_detail") or {}).get("volume_turnover")),
            ),
            reverse=True,
        )
        final_pool = selected
        top50 = selected[:limit]
    else:
        scored_stocks.sort(key=lambda x: x["score"], reverse=True)
        final_pool = scored_stocks
        top50 = scored_stocks[:limit]

    state_store.set_screening_results(top50)
    elapsed = time.time() - start_time
    logger.info(f"选股完成: 筛选出 {len(top50)} 只, 耗时 {elapsed:.1f}秒")

    return final_pool if return_all else top50


def _generate_reasons(
    stock: dict,
    daily_df: Optional[pd.DataFrame],
    vt_score: float,
    cf_score: float,
    tech_score: float,
    sector_detail: Optional[dict] = None,
    news_detail: Optional[dict] = None,
    fundamental_detail: Optional[dict] = None,
    intraday_detail: Optional[dict] = None,
    sector_momentum_detail: Optional[dict] = None,
    leader_follow_detail: Optional[dict] = None,
    support_pullback_detail: Optional[dict] = None,
) -> str:
    """生成推荐理由文字"""
    reasons = []

    # 量价理由
    vr = _to_float(stock.get("volume_ratio"))
    if vr > 1.5:
        reasons.append(f"量比{vr:.1f}放大")
    tr = _to_float(stock.get("turnover_rate"))
    if tr > 3:
        reasons.append(f"换手率{tr:.1f}%活跃")

    # 资金理由
    flow = state_store.get_money_flow(stock.get("code", ""))
    if flow:
        main_inflow = flow.get("latest_main_net_inflow", 0)
        if main_inflow > 0:
            reasons.append("主力净流入")
        consec = flow.get("consecutive_inflow_days", 0)
        if consec >= 3:
            reasons.append(f"连续{consec}日净流入")

    # 技术理由
    if daily_df is not None and len(daily_df) >= 20:
        df = technical_analysis.calc_all_indicators(daily_df.copy())
        if technical_analysis.is_ma_bullish_aligned(df):
            reasons.append("均线多头排列")
        if technical_analysis.is_macd_golden_cross(df):
            reasons.append("MACD金叉")
        if technical_analysis.is_kdj_oversold_recovery(df):
            reasons.append("KDJ超卖回升")

    pullback_notes = (support_pullback_detail or {}).get("notes") or []
    if any("贴近箱体支撑" in note for note in pullback_notes):
        reasons.append("震荡回落贴近支撑")
    elif any("靠近支撑" in note for note in pullback_notes):
        reasons.append("震荡回落靠近支撑")
    elif any("20日箱体震荡" in note for note in pullback_notes):
        reasons.append("20日箱体震荡")

    # 板块与新闻理由
    matched_sectors = (sector_detail or {}).get("matched") or []
    if matched_sectors:
        best = matched_sectors[0]
        reasons.append(f"板块热度:{best.get('name')}")

    momentum = (sector_momentum_detail or {}).get("matched") or []
    if momentum:
        best_momentum = momentum[0]
        delta = _to_float(best_momentum.get("main_net_delta"))
        if delta > 0:
            reasons.append(f"板块资金加速:{best_momentum.get('name')}")

    leader_roles = (leader_follow_detail or {}).get("roles") or []
    if leader_roles:
        role = leader_roles[0]
        if role.get("leader_limit_signal") and role.get("role") == "second_leader":
            reasons.append(f"龙头涨停带动次龙头:{role.get('sector_name')}")
        elif role.get("leader_limit_signal"):
            reasons.append(f"龙头接近涨停:{role.get('leader_name')}")

    news_count = (news_detail or {}).get("count", 0)
    if news_count:
        reasons.append(f"个股新闻命中{news_count}条")

    fundamental_status = (fundamental_detail or {}).get("data_status")
    if fundamental_status == "ready":
        reasons.append("估值财务通过")
    elif fundamental_status == "missing":
        reasons.append("估值财务待补")

    for note in (intraday_detail or {}).get("notes", []):
        if "支撑" in note or "尾盘" in note:
            reasons.append(note)
            break

    if not reasons:
        reasons.append("综合评分较高")

    return "+".join(reasons[:6])


def _assess_risk_level(score: float, stock: dict) -> str:
    """评估风险等级"""
    turnover_rate = _to_float(stock.get("turnover_rate"))
    pct_change = abs(_to_float(stock.get("pct_change")))
    if turnover_rate and turnover_rate > 12:
        return "high"
    if score >= 82 and pct_change < 3:
        return "low"
    elif score >= 68:
        return "medium"
    else:
        return "high"
