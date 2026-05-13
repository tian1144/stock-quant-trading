"""Feishu bot answers backed by live site data and optional knowledge base."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from app.execution.kill_switch import get_kill_switch_status
from app.services import (
    ai_model_service,
    data_fetcher,
    database_cache_service,
    knowledge_answer_service,
    knowledge_base_service,
    news_service,
    portfolio_manager,
    risk_manager,
    sector_service,
    state_store,
    trade_review_service,
)


CASUAL_PATTERNS = (
    r"^(你好|您好|hello|hi|嗨|在吗|在不在|早上好|中午好|下午好|晚上好|ping|ping\d*)[。！!？?\s]*$",
    r"^(谢谢|感谢|辛苦了|收到|好的|好|ok|OK)[。！!？?\s]*$",
)


def _json_safe(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return str(value)


def _is_casual(question: str) -> bool:
    text = str(question or "").strip()
    if not text:
        return True
    return any(re.match(pattern, text, flags=re.I) for pattern in CASUAL_PATTERNS)


def _site_ai_stock_universe() -> list[dict]:
    stocks = state_store.get_stock_universe() or []
    if isinstance(stocks, dict):
        stocks = list(stocks.values())
    if not stocks:
        stocks = data_fetcher.read_stock_universe_cache() or []
    if isinstance(stocks, dict):
        stocks = list(stocks.values())
    return [s for s in stocks if isinstance(s, dict)]


def _match_stocks(question: str, limit: int = 6) -> list[dict]:
    text = str(question or "")
    stocks = _site_ai_stock_universe()
    by_code = {str(s.get("code", "")): s for s in stocks if s.get("code")}
    matched: list[dict] = []
    seen: set[str] = set()

    def add(stock: dict | None) -> None:
        code = str((stock or {}).get("code", "")).strip()
        if code and code not in seen:
            matched.append(stock or {"code": code})
            seen.add(code)

    for code in re.findall(r"(?<!\d)(\d{6})(?!\d)", text):
        add(by_code.get(code) or state_store.get_stock_info(code) or {"code": code})

    for stock in stocks:
        name = str(stock.get("name", "")).strip()
        code = str(stock.get("code", "")).strip()
        if (name and name in text) or (code and code in text):
            add(stock)
        if len(matched) >= limit:
            break
    return matched[:limit]


def _tail_daily_bars(code: str, count: int = 8) -> list[dict]:
    df = state_store.get_daily_bars(code)
    if df is None:
        df = data_fetcher._read_kline_cache(code, 101, 260)
    rows: list[dict] = []
    try:
        if df is not None and len(df) > 0:
            for _, row in df.tail(count).iterrows():
                item = row.to_dict()
                rows.append({
                    "date": str(item.get("date", "")),
                    "open": item.get("open"),
                    "close": item.get("close"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "volume": item.get("volume"),
                    "amount": item.get("amount"),
                    "pct_change": item.get("pct_change"),
                })
    except Exception:
        return []
    return rows


def _stock_context(stock: dict, strategy: str) -> dict:
    code = str(stock.get("code", "")).strip()
    name = stock.get("name", "")
    realtime = data_fetcher.read_realtime_cache(code) or state_store.get_realtime(code) or {}
    daily_tail = _tail_daily_bars(code)
    stock_news = []
    for item in state_store.get_news()[:300]:
        title = str(item.get("title", ""))
        content = str(item.get("content", ""))
        if code in title or code in content or (name and (name in title or name in content)):
            stock_news.append(item)
        if len(stock_news) >= 8:
            break
    screening_hit = next(
        (item for item in (state_store.get_screening_results() or []) if str(item.get("code", "")) == code),
        None,
    )
    return _json_safe({
        "code": code,
        "name": name or realtime.get("name"),
        "basic": stock,
        "realtime": realtime,
        "recent_daily_kline": daily_tail,
        "screening_result": screening_hit,
        "ai_recommendation": next(
            (item for item in (state_store.get_ai_recommendations().get("recommendations") or []) if item.get("code") == code),
            None,
        ),
        "position": (state_store.get_positions() or {}).get(code),
        "related_news": stock_news,
    })


def _site_context(question: str) -> dict:
    strategy = state_store.get_user_settings().get("trading_style", "short")
    matched_stocks = _match_stocks(question)
    try:
        sector_rankings = sector_service.get_sector_rankings()[:12]
    except Exception:
        sector_rankings = []
    try:
        sentiment = news_service.get_market_sentiment()
    except Exception:
        sentiment = {}
    return _json_safe({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "project": "量化智能猎人",
        "strategy": strategy,
        "database_cache": database_cache_service.db_cache_status(),
        "stock_universe_count": len(_site_ai_stock_universe()),
        "realtime_count": len(state_store.get_all_realtime() or {}),
        "matched_stocks": [_stock_context(stock, strategy) for stock in matched_stocks],
        "screening_top": (state_store.get_screening_results() or [])[:12],
        "ai_recommendations": (state_store.get_ai_recommendations().get("recommendations") or [])[:12],
        "sector_rankings": sector_rankings,
        "market_sentiment": sentiment,
        "news_sample": (state_store.get_news() or [])[:12],
        "portfolio": portfolio_manager.get_portfolio_summary(),
        "positions": portfolio_manager.get_position_list()[:12],
        "risk_status": risk_manager.get_risk_status(),
        "risk_config": risk_manager.get_risk_config(),
        "kill_switch": get_kill_switch_status(),
        "trade_review_learning": trade_review_service.get_trade_review_candidates(limit=6),
        "system_state": state_store.get_system_state(),
    })


def _fallback_answer(question: str, context: dict) -> str:
    matched = context.get("matched_stocks") or []
    if matched:
        stock = matched[0]
        rt = stock.get("realtime") or {}
        kline = stock.get("recent_daily_kline") or []
        last = kline[-1] if kline else {}
        name = stock.get("name") or stock.get("code")
        lines = [f"{name}（{stock.get('code')}）当前站内可用信息："]
        price = rt.get("price") or rt.get("current_price") or rt.get("close") or last.get("close")
        pct = rt.get("pct_change") or rt.get("change_pct") or last.get("pct_change")
        if price not in (None, ""):
            lines.append(f"最新价/收盘价：{price}。")
        if pct not in (None, ""):
            lines.append(f"最新涨跌幅：{pct}%。")
        if last:
            lines.append(f"最近K线日期：{last.get('date')}。")
        lines.append("更细的原因需要模型总结站内行情、K线、风控和新闻后再给出。")
        lines.append("以上仅基于站内数据做研究参考，不构成真实交易建议。")
        return "\n".join(lines)
    return "我已经收到你的问题，但站内当前没有足够的实时缓存可以直接判断。你可以先在网站刷新行情/新闻/板块数据后再问我。"


def answer_for_feishu(question: str) -> dict:
    question = str(question or "").strip()
    if not question:
        return {"ok": False, "answer": "请先输入问题。", "mode": "empty", "matched_item_ids": []}

    if _is_casual(question):
        return {
            "ok": True,
            "answer": "你好，我在。你可以问我网站功能、当前行情、个股、板块、持仓、风控或让 我根据站内数据做简要分析。",
            "mode": "casual",
            "matched_item_ids": [],
        }

    knowledge_result = knowledge_answer_service.answer_from_knowledge(question)
    if knowledge_result.get("ok") and not knowledge_result.get("no_answer"):
        return {**knowledge_result, "mode": "knowledge"}

    context = _site_context(question)
    system_prompt = (
        "你是飞书里的量化智能猎人助手。你可以基于传入的站内数据库、缓存和运行状态回答用户。"
        "你必须只使用 context 里的站内数据，不要编造行情、价格、公告、承诺、联系方式或不存在的功能。"
        "如果 context 缺少某项数据，要直接说明当前站内未缓存或需要刷新，而不是说知识库未找到。"
        "用户寒暄时可以自然聊天；股票、板块、交易、投资问题必须说明数据来源边界和风险提示。"
        "回答要简洁，适合飞书聊天阅读。"
    )
    user_message = f"用户问题：{question}\n\n站内上下文：\n{json.dumps(context, ensure_ascii=False)}"
    answer, meta = ai_model_service.chat_text(
        "deep_analysis",
        system_prompt,
        user_message,
        context,
        profile="chat_assistant",
    )
    if not meta.get("ok") or not str(answer or "").strip():
        answer = _fallback_answer(question, context)
    return {
        "ok": True,
        "answer": str(answer or "").strip(),
        "mode": "site_data",
        "matched_item_ids": knowledge_result.get("matched_item_ids") or [],
        "site_context": {
            "matched_stock_count": len(context.get("matched_stocks") or []),
            "stock_universe_count": context.get("stock_universe_count"),
            "realtime_count": context.get("realtime_count"),
            "db_cache": context.get("database_cache"),
        },
        "ai_meta": meta,
    }
