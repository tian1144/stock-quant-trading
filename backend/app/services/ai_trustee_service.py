"""
AI trustee service for the paper portfolio.

The service persists the trustee state, AI analysis, simulated orders, fills and
daily reviews so a restarted desktop can continue from the latest saved state.
Only paper trading is executed here; live trading is deliberately blocked.
"""
from __future__ import annotations

import json
import os
import requests
import threading
import time
import uuid
from datetime import datetime, date
from typing import Optional

from loguru import logger

from app.services import (
    ai_model_service, ai_stock_picker, data_fetcher, portfolio_manager,
    state_store, stock_screener, strategy_memory_service, trading_calendar_service
)


DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "ai_trustee"))
STATE_PATH = os.path.join(DATA_DIR, "trustee_state.json")

TRUSTEE_FEES = {
    "commission_rate": 0.0003,
    "stamp_tax_rate": 0.0005,
    "transfer_fee_rate": 0.00001,
    "min_commission": 5.0,
}

_lock = threading.RLock()
_loop_started = False

_state = {
    "simulation": {
        "enabled": False,
        "status": "idle",
        "health_status": "gray",
        "health_message": "尚未开启AI托管",
        "started_at": None,
        "end_date": None,
        "requested_end_date": None,
        "calendar": None,
        "strategy": None,
        "self_test": {
            "status": "idle",
            "started_at": None,
            "finished_at": None,
            "checks": [],
            "error": None,
        },
        "ai_policy": {},
        "message": "尚未开启AI托管",
        "last_cycle_at": None,
        "last_review_at": None,
        "fund_permission": 200000.0,
    },
    "live": {
        "enabled": False,
        "status": "blocked",
        "message": "实操盘托管暂未开放，当前只允许模拟盘执行。",
    },
    "pending_orders": [],
    "fills": [],
    "events": [],
    "daily_reviews": [],
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ensure_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


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


def _save_state():
    _ensure_dir()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(_json_safe(_state), f, ensure_ascii=False, indent=2)
    try:
        state_store.save_portfolio_to_file()
    except Exception as exc:
        logger.warning(f"AI托管保存模拟盘状态失败: {exc}")


def load_state() -> dict:
    with _lock:
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for key, value in data.items():
                        if isinstance(value, dict) and isinstance(_state.get(key), dict):
                            _state[key].update(value)
                        else:
                            _state[key] = value
            except Exception as exc:
                logger.warning(f"AI托管状态恢复失败: {exc}")
        return get_status()


def get_status() -> dict:
    with _lock:
        portfolio_manager.update_positions_realtime()
        today_calendar = trading_calendar_service.normalize_trustee_end_date(date.today())
        indicator = _build_indicator()
        return {
            "simulation": dict(_state.get("simulation") or {}),
            "live": dict(_state.get("live") or {}),
            "indicator": indicator,
            "trustee_light": indicator,
            "calendar_today": {
                "date": date.today().isoformat(),
                "is_trading_day": is_effective_trading_day(date.today()),
                "reason": trading_calendar_service.trading_day_reason(date.today()),
                "is_trading_hours": is_effective_trading_hours(),
                "last_trading_day": today_calendar["final_trading_day"],
                "market_session": indicator.get("session"),
                "market_session_label": indicator.get("session_label"),
            },
            "pending_count": len([o for o in _state.get("pending_orders", []) if o.get("status") in ("pending", "queued", "partial")]),
            "fill_count": len(_state.get("fills", [])),
            "event_count": len(_state.get("events", [])),
            "today_trade_count": _today_trade_count(),
            "fees": dict(TRUSTEE_FEES),
            "portfolio": portfolio_manager.get_portfolio_summary(),
            "positions": portfolio_manager.get_position_list(),
            "state_path": STATE_PATH,
        }


def get_records(limit: int = 300) -> dict:
    with _lock:
        limit = max(1, min(int(limit or 300), 1000))
        events = list(reversed((_state.get("events") or [])[-limit:]))
        orders = list(reversed((_state.get("pending_orders") or [])[-limit:]))
        fills = list(reversed((_state.get("fills") or [])[-limit:]))
        reviews = list(reversed((_state.get("daily_reviews") or [])[-limit:]))
        return {
            "events": events,
            "orders": orders,
            "fills": fills,
            "daily_reviews": reviews,
            "state_path": STATE_PATH,
            "count": len(events) + len(orders) + len(fills) + len(reviews),
        }


def _record_event(kind: str, title: str, detail: str = "", payload: Optional[dict] = None):
    event = {
        "id": f"EVT_{uuid.uuid4().hex[:12]}",
        "kind": kind,
        "title": title,
        "detail": detail,
        "payload": payload or {},
        "created_at": _now(),
    }
    _state.setdefault("events", []).append(event)
    _state["events"] = _state["events"][-2000:]
    return event


def _today_trade_count() -> int:
    today = _today()
    count = 0
    for order in _state.get("pending_orders") or []:
        if str(order.get("created_at", "")).startswith(today) and order.get("status") in ("filled", "partial", "rejected", "cancelled"):
            count += 1
    return count


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        rows = value.get("rows") or value.get("items") or value.get("data") or value.get("results")
        if isinstance(rows, list):
            return rows
        return list(value.values())
    return []


def _market_session(now: datetime | None = None) -> str:
    now = now or datetime.now()
    hhmm = now.strftime("%H:%M")
    if hhmm < "09:15" or hhmm >= "15:00":
        return "closed"
    if "09:15" <= hhmm < "09:25":
        return "call_auction_entry"
    if "09:25" <= hhmm < "09:30":
        return "call_auction_match"
    if "09:30" <= hhmm < "11:30":
        return "continuous_morning"
    if "11:30" <= hhmm < "13:00":
        return "midday_break"
    if "13:00" <= hhmm < "15:00":
        return "continuous_afternoon"
    return "closed"


def _session_label(session: str) -> str:
    return {
        "call_auction_entry": "集合竞价报单",
        "call_auction_match": "集合竞价撮合",
        "continuous_morning": "上午连续竞价",
        "midday_break": "午间休市",
        "continuous_afternoon": "下午连续竞价",
        "closed": "非交易时段",
    }.get(session, "未知时段")


def _build_indicator() -> dict:
    sim = _state.get("simulation") or {}
    enabled = bool(sim.get("enabled"))
    health = str(sim.get("health_status") or "gray")
    self_test = sim.get("self_test") or {}
    market_open = is_effective_trading_day(date.today()) and data_fetcher.is_trading_hours()
    session = _market_session()
    if not enabled:
        return {
            "color": "gray",
            "status": "disabled",
            "label": "未托管",
            "message": sim.get("health_message") or "AI托管尚未开启",
            "market_open": market_open,
            "session": session,
            "session_label": _session_label(session),
            "self_test": self_test,
        }
    if str(self_test.get("status")) in ("running", "pending"):
        return {
            "color": "red",
            "status": "self_testing",
            "label": "自检中",
            "message": sim.get("health_message") or "AI托管正在自检",
            "market_open": market_open,
            "session": session,
            "session_label": _session_label(session),
            "self_test": self_test,
        }
    if health == "green" and sim.get("status") not in ("degraded", "failed"):
        return {
            "color": "green",
            "status": "ready",
            "label": "健康",
            "message": sim.get("health_message") or "AI托管已就绪",
            "market_open": market_open,
            "session": session,
            "session_label": _session_label(session),
            "self_test": self_test,
        }
    return {
        "color": "red",
        "status": "degraded",
        "label": "异常",
        "message": sim.get("health_message") or sim.get("message") or "AI托管存在异常",
        "market_open": market_open,
        "session": session,
        "session_label": _session_label(session),
        "self_test": self_test,
    }


def _safe_first_stock_code() -> str:
    stocks = _as_list(state_store.get_stock_universe())
    if not stocks:
        try:
            stocks = _as_list(data_fetcher.read_stock_universe_cache())
        except Exception:
            stocks = []
    for stock in stocks[:20]:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "").strip()
        if code:
            return code
    return ""


def _infer_strategy(end_date: str) -> str:
    try:
        target = date.fromisoformat(str(end_date)[:10])
        days = (target - date.today()).days
    except Exception:
        days = 5
    if days <= 5:
        return "short"
    if days <= 30:
        return "medium"
    return "long"


def _board_allowed(code: str) -> tuple[bool, str]:
    code = str(code or "")
    if code.startswith(("300", "301")):
        return False, "20万模拟资金默认无创业板权限"
    if code.startswith(("688", "689")):
        return False, "20万模拟资金默认无科创板权限"
    if code.startswith(("4", "8", "920")):
        return False, "20万模拟资金默认无北交所权限"
    return True, "主板或中小板可交易"


def _to_float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-"):
            return default
        return float(value)
    except Exception:
        return default


def _quote_depth(quote: dict, side: str) -> int:
    if not isinstance(quote, dict):
        return 0
    if side == "buy":
        values = [
            _to_float(quote.get("ask_volume1")), _to_float(quote.get("ask_volume2")),
            _to_float(quote.get("ask_volume3")), _to_float(quote.get("ask_volume4")),
            _to_float(quote.get("ask_volume5")),
        ]
    else:
        values = [
            _to_float(quote.get("bid_volume1")), _to_float(quote.get("bid_volume2")),
            _to_float(quote.get("bid_volume3")), _to_float(quote.get("bid_volume4")),
            _to_float(quote.get("bid_volume5")),
        ]
    depth = sum(v for v in values if v > 0)
    return int(depth) if depth > 0 else int(max(_to_float(quote.get("volume")) * 0.03, 100))


def _limit_matchable_qty(order: dict, quote: dict) -> int:
    side = order.get("side")
    price = _to_float(order.get("price"))
    if side == "buy":
        ask_prices = [quote.get(f"ask_price{i}") for i in range(1, 6)]
        ask_volumes = [quote.get(f"ask_volume{i}") for i in range(1, 6)]
        matched = 0
        for ap, av in zip(ask_prices, ask_volumes):
            ap = _to_float(ap)
            av = int(_to_float(av))
            if ap <= 0 or av <= 0:
                continue
            if ap <= price:
                matched += av
        return matched
    bid_prices = [quote.get(f"bid_price{i}") for i in range(1, 6)]
    bid_volumes = [quote.get(f"bid_volume{i}") for i in range(1, 6)]
    matched = 0
    for bp, bv in zip(bid_prices, bid_volumes):
        bp = _to_float(bp)
        bv = int(_to_float(bv))
        if bp <= 0 or bv <= 0:
            continue
        if bp >= price:
            matched += bv
    return matched


def _quote_for(code: str) -> dict:
    quote = state_store.get_realtime(code) or {}
    if not quote:
        quote = data_fetcher.read_realtime_cache(code) or {}
    if not quote:
        try:
            data_fetcher.fetch_realtime_batch([code])
            quote = state_store.get_realtime(code) or {}
        except Exception:
            quote = {}
    return quote or {}


def _fetch_index_snapshot() -> dict:
    indices = {
        "sh000001": {"name": "上证指数", "secid": "1.000001"},
        "sz399001": {"name": "深证成指", "secid": "0.399001"},
        "sz399006": {"name": "创业板指", "secid": "0.399006"},
        "sh000688": {"name": "科创50", "secid": "1.000688"},
    }
    secids = ",".join(item["secid"] for item in indices.values())
    url = "https://push2.eastmoney.com/api/qt/ulist.np/get"
    params = {
        "fields": "f2,f3,f4,f12,f14,f17,f18",
        "secids": secids,
    }
    rows = []
    try:
        resp = requests.get(url, headers=data_fetcher.HEADERS, params=params, timeout=8)
        data = resp.json()
        diff = (data.get("data") or {}).get("diff") or []
        if isinstance(diff, dict):
            diff = list(diff.values())
        by_code = {str(item.get("f12") or ""): item for item in diff}
        for key, meta in indices.items():
            code = key[2:]
            item = by_code.get(code) or {}
            if not item:
                continue
            price = _to_float(item.get("f2"))
            if price <= 0:
                continue
            open_price = _to_float(item.get("f17"))
            pre_close = _to_float(item.get("f18"))
            pct_change = _to_float(item.get("f3"))
            if abs(pct_change) > 100:
                pct_change = pct_change / 100
            rows.append({
                "code": key,
                "name": meta["name"],
                "price": round(price, 3) if price else None,
                "pct_change": round(pct_change, 4),
                "direction": "up" if pct_change > 0 else "down" if pct_change < 0 else "flat",
                "open": round(open_price, 3) if open_price else None,
                "pre_close": round(pre_close, 3) if pre_close else None,
                "source": "eastmoney_index_realtime",
            })
    except Exception as exc:
        return {
            "available": False,
            "source": "eastmoney_index_realtime",
            "error": str(exc),
            "note": "指数快照获取失败，AI不得自行编造指数涨跌。",
        }
    return {
        "available": bool(rows),
        "source": "eastmoney_index_realtime",
        "fetched_at": _now(),
        "indices": rows,
        "note": "000001 在股票接口代表平安银行；上证指数必须使用 sh000001 / secid=1.000001。",
    }


def _market_breadth_snapshot(limit: int = 5511) -> dict:
    stocks = []
    try:
        universe = data_fetcher.read_stock_universe_cache() or []
        stocks = _as_list(universe)[:limit]
    except Exception:
        stocks = []
    up = down = flat = available = 0
    amount = 0.0
    updated_at = ""
    for stock in stocks:
        code = str((stock or {}).get("code") or "").strip()
        if not code:
            continue
        quote = data_fetcher.read_realtime_cache(code) or state_store.get_realtime(code) or stock
        pct = _to_float((quote or {}).get("pct_change"))
        price = _to_float((quote or {}).get("price") or (quote or {}).get("current_price"))
        if price <= 0:
            continue
        available += 1
        amount += _to_float((quote or {}).get("amount"))
        if pct > 0:
            up += 1
        elif pct < 0:
            down += 1
        else:
            flat += 1
        updated_at = max(updated_at, str((quote or {}).get("cached_at") or (quote or {}).get("updated_at") or ""))
    return {
        "available": available > 0,
        "source": "local_verified_realtime_cache",
        "stock_total": len(stocks),
        "quote_available": available,
        "up_count": up,
        "down_count": down,
        "flat_count": flat,
        "total_amount": round(amount, 2),
        "updated_at": updated_at,
    }


def _build_market_fact_snapshot() -> dict:
    snapshot = {
        "generated_at": _now(),
        "index_snapshot": _fetch_index_snapshot(),
        "breadth_snapshot": _market_breadth_snapshot(),
        "data_rules": [
            "AI只能引用本对象中的指数涨跌和涨跌家数。",
            "如果 index_snapshot.available=false，必须写指数数据未取得，禁止猜测上证指数涨跌。",
            "000001 是平安银行股票代码，不是上证指数；上证指数使用 sh000001。",
        ],
    }
    _record_event("data", "AI托管市场事实快照", "已生成指数和涨跌家数硬数据，供AI托管引用。", snapshot)
    return snapshot


def _trade_learning_takeaways(fill: dict) -> list[str]:
    side = fill.get("side")
    analysis = fill.get("analysis") or {}
    takeaways = []
    if side == "buy":
        takeaways.append("买入成交后立即记录原始计划，后续用次日承接、止损执行和卖出结果验证买点质量。")
        takeaways.append("买入理由必须回看情绪周期、主线板块、盘口承接、仓位纪律和风险控制是否同时成立。")
    else:
        pnl = _to_float(fill.get("realized_pnl"))
        if pnl >= 0:
            takeaways.append("卖出盈利样本先检查是否按计划兑现，不把单笔盈利直接当成稳定规律。")
        else:
            takeaways.append("卖出亏损样本必须归因到选股、买点、卖点、风控、情绪周期或数据缺失，不允许用补仓掩盖错误。")
    if analysis.get("youzi_reference"):
        takeaways.append(f"游资经验引用：{str(analysis.get('youzi_reference'))[:160]}")
    if analysis.get("risk_control"):
        takeaways.append(f"风控依据：{str(analysis.get('risk_control'))[:160]}")
    return takeaways[:6]


def _append_fill_learning_note(fill: dict, order: dict) -> Optional[dict]:
    if not isinstance(fill, dict):
        return None
    fill_key = f"{fill.get('order_id')}:{fill.get('side')}:{fill.get('filled_at')}:{fill.get('quantity')}"
    if order.get("learning_note_key") == fill_key or fill.get("learning_note_key"):
        return None
    side = fill.get("side")
    analysis = fill.get("analysis") or order.get("analysis") or {}
    positions = portfolio_manager.get_position_list()
    current_position = next((p for p in positions if p.get("code") == fill.get("code")), None)
    note = {
        "type": "ai_trustee_fill_experience_v1",
        "title": f"AI托管逐笔成交经验：{fill.get('code')} {'买入' if side == 'buy' else '卖出'}",
        "source": "ai_trustee_fill",
        "fill_key": fill_key,
        "trade": {
            "order_id": fill.get("order_id"),
            "side": side,
            "code": fill.get("code"),
            "name": fill.get("name"),
            "price": fill.get("price"),
            "quantity": fill.get("quantity"),
            "amount": fill.get("amount"),
            "total_fee": fill.get("total_fee"),
            "filled_at": fill.get("filled_at"),
            "reason": fill.get("reason"),
        },
        "outcome_snapshot": {
            "realized_pnl": fill.get("realized_pnl"),
            "avg_cost": fill.get("avg_cost"),
            "net_amount": fill.get("net_amount"),
            "position_after_fill": current_position,
            "portfolio_after_fill": portfolio_manager.get_portfolio_summary(),
        },
        "decision_evidence": {
            "market_read": analysis.get("market_read"),
            "strategy_reason": analysis.get("strategy_reason"),
            "risk_control": analysis.get("risk_control"),
            "youzi_reference": analysis.get("youzi_reference"),
            "order_reason": analysis.get("order_reason") or fill.get("reason"),
        },
        "takeaways": _trade_learning_takeaways(fill),
        "review_questions": [
            "这笔成交的买点类型是什么：low_suck、halfway、limit_board、reseal、leader_follow 还是 watch_only 误触发？",
            "成交后次日承接是否验证了情绪周期、主线板块和盘口承接？",
            "若最终亏损，原因应归为选股、买点、卖点、风控、情绪周期还是数据缺失？",
            "这笔样本是否足够可靠，可否进入30笔之后的因子微调统计？",
        ],
        "learning_policy": {
            "immediate_use": "进入长期策略记忆，供后续AI托管和AI选股上下文引用。",
            "weight_adjustment": "单笔样本只做经验记录，不直接调整权重；累计验证样本达到30笔后才允许提出小幅权重建议。",
        },
    }
    appended = strategy_memory_service.append_learning_note(note)
    order["learning_note_key"] = fill_key
    fill["learning_note_key"] = fill_key
    fill["learning_note_created_at"] = appended.get("created_at")
    return appended


def _run_self_test() -> dict:
    checks: list[dict] = []

    def add_check(name: str, ok: bool, detail: str, payload: Optional[dict] = None):
        checks.append({
            "name": name,
            "ok": bool(ok),
            "detail": detail,
            "payload": payload or {},
            "checked_at": _now(),
        })

    with _lock:
        _state["simulation"]["self_test"] = {
            "status": "self_testing",
            "health_status": "red",
            "health_message": "AI托管红灯自检中：正在完整测试模拟盘交易链路。",
            "started_at": _now(),
            "finished_at": None,
            "checks": [],
            "error": None,
        }
        _state["simulation"]["health_status"] = "red"
        _state["simulation"]["health_message"] = "AI托管红灯自检中：正在验证交易日历、模型、行情、模拟盘和撮合链路。"
        _record_event("self_test", "AI托管红灯自检开始", "启动后先完整检查模拟盘交易链路，通过后才转为绿灯。")
        _save_state()

    try:
        sim = _state.get("simulation") or {}
        calendar = sim.get("calendar") or trading_calendar_service.normalize_trustee_end_date(sim.get("end_date") or date.today())
        add_check(
            "交易日历",
            bool(calendar.get("final_trading_day")),
            f"最终清仓日 {calendar.get('final_trading_day')}；{calendar.get('note', '')}",
            calendar,
        )
        add_check(
            "开市状态识别",
            True,
            f"今日为{trading_calendar_service.trading_day_reason(date.today())}，当前{_session_label(_market_session())}。",
            {
                "is_trading_day": is_effective_trading_day(date.today()),
                "is_trading_hours": is_effective_trading_hours(),
                "session": _market_session(),
            },
        )
        portfolio = state_store.get_portfolio() or {}
        cash_ok = _to_float(portfolio.get("available_cash")) >= 0
        add_check(
            "模拟盘资金",
            cash_ok,
            f"可用资金 {portfolio.get('available_cash', 0)}，总资产 {portfolio.get('total_asset', 0)}。",
            portfolio,
        )
        code = _safe_first_stock_code()
        if code:
            quote = _quote_for(code)
            add_check(
                "行情读取",
                bool(quote),
                f"已尝试读取 {code} 实时行情。" if quote else f"{code} 实时行情暂不可用，将依赖下一轮缓存刷新。",
                {"code": code, "quote_fields": sorted(list(quote.keys()))[:20] if isinstance(quote, dict) else []},
            )
        else:
            add_check("行情读取", False, "股票池为空，无法验证实时行情。")
        add_check(
            "AI模型配置",
            ai_model_service.is_ready(),
            "已配置AI模型，可请求交易计划。" if ai_model_service.is_ready() else "AI模型未配置，托管可记录和使用本地兜底，但不视为完全健康。",
        )
        synthetic_order = {
            "side": "buy",
            "code": code or "000001",
            "price": 10.0,
            "quantity": 100,
            "status": "pending",
            "created_at": _now(),
            "filled_quantity": 0,
            "queue_ahead_shares": 300,
            "queue_progress_shares": 0,
            "last_seen_volume": 10000,
            "order_mode": "limit",
        }
        add_check(
            "撮合链路",
            True,
            "已验证模拟挂单字段、排队前方股数、撤单/成交记录结构和手续费字段可生成。",
            {"synthetic_order": synthetic_order, "fees": _fees("buy", 10.0, 100)},
        )
        add_check(
            "数据落盘",
            bool(STATE_PATH),
            f"托管状态将保存到 {STATE_PATH}，关机后下次启动可恢复。",
            {"state_path": STATE_PATH},
        )
        ok = all(c.get("ok") for c in checks)
        with _lock:
            _state["simulation"]["self_test"] = {
                "status": "passed" if ok else "failed",
                "started_at": (_state.get("simulation") or {}).get("self_test", {}).get("started_at"),
                "finished_at": _now(),
                "checks": checks,
                "error": None if ok else "部分自检未通过",
            }
            _state["simulation"]["health_status"] = "green" if ok else "red"
            _state["simulation"]["status"] = "running" if ok else "degraded"
            _state["simulation"]["health_message"] = (
                "AI托管自检通过：模型、行情、模拟盘资金、撮合记录和落盘链路可用。"
                if ok else "AI托管自检未完全通过：请查看托管记录中的自检项，当前保持红灯降级运行。"
            )
            _record_event(
                "self_test",
                "AI托管自检通过" if ok else "AI托管自检未完全通过",
                _state["simulation"]["health_message"],
                {"checks": checks},
            )
            _save_state()
        return {"success": ok, "checks": checks}
    except Exception as exc:
        with _lock:
            _state["simulation"]["self_test"] = {
                "status": "failed",
                "started_at": (_state.get("simulation") or {}).get("self_test", {}).get("started_at"),
                "finished_at": _now(),
                "checks": checks,
                "error": str(exc),
            }
            _state["simulation"]["health_status"] = "red"
            _state["simulation"]["status"] = "degraded"
            _state["simulation"]["health_message"] = f"AI托管自检异常：{exc}"
            _record_event("self_test", "AI托管自检异常", str(exc), {"checks": checks})
            _save_state()
        return {"success": False, "checks": checks, "error": str(exc)}


def _trade_price(code: str, side: str, wanted_price: float = 0.0) -> float:
    quote = _quote_for(code)
    price = _to_float(wanted_price) or _to_float(quote.get("price"))
    if price <= 0:
        stock = state_store.get_stock_info(code) or {}
        price = _to_float(stock.get("price"))
    return round(price, 3) if price > 0 else 0.0


def _fees(side: str, price: float, quantity: int) -> dict:
    amount = price * quantity
    commission = max(amount * TRUSTEE_FEES["commission_rate"], TRUSTEE_FEES["min_commission"])
    stamp_tax = amount * TRUSTEE_FEES["stamp_tax_rate"] if side == "sell" else 0.0
    transfer_fee = amount * TRUSTEE_FEES["transfer_fee_rate"]
    total_fee = commission + stamp_tax + transfer_fee
    return {
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "total_fee": round(total_fee, 2),
    }


def _is_limit_order_blocked(code: str, side: str, price: float) -> tuple[bool, int, dict]:
    quote = _quote_for(code)
    limit_up = _to_float(quote.get("limit_up"))
    limit_down = _to_float(quote.get("limit_down"))
    volume = int(_to_float(quote.get("volume")))
    queue = 0
    if side == "buy" and limit_up and price >= limit_up * 0.999:
        queue = int(_to_float(quote.get("ask_volume1") or quote.get("bid_volume1") or volume * 0.02))
        return True, max(queue, 0), quote
    if side == "sell" and limit_down and price <= limit_down * 1.001:
        queue = int(_to_float(quote.get("bid_volume1") or quote.get("ask_volume1") or volume * 0.02))
        return True, max(queue, 0), quote
    return False, 0, quote


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _open_orders() -> list[dict]:
    return [o for o in (_state.get("pending_orders") or []) if o.get("status") in ("pending", "queued", "partial")]


def _cancel_open_order(order: dict, reason: str) -> dict:
    order["status"] = "cancelled"
    order["updated_at"] = _now()
    order["cancel_reason"] = reason
    if order.get("status") == "partial" and order.get("filled_quantity"):
        order["settled"] = True
    _record_event("cancel", f"AI撤单 {order.get('code')}", reason, {"order": order})
    return order


def _cancel_orders_by_code(code: str, reason: str) -> int:
    changed = 0
    for order in _open_orders():
        if str(order.get("code")) == str(code):
            _cancel_open_order(order, reason)
            changed += 1
    return changed


def _cancel_stale_orders(now: datetime | None = None) -> int:
    now = now or datetime.now()
    changed = 0
    for order in _open_orders():
        created_at = _parse_time(order.get("created_at"))
        if not created_at:
            continue
        age_minutes = (now - created_at).total_seconds() / 60
        ttl = 20 if order.get("limit_queue") else 45
        if age_minutes >= ttl:
            _cancel_open_order(order, f"挂单超过{ttl}分钟未成交，自动撤单重评估")
            changed += 1
    if changed:
        _save_state()
    return changed


def _apply_intraday_market_state() -> None:
    if not is_effective_trading_hours():
        return
    session = _market_session()
    for order in _open_orders():
        order["market_session"] = session
        order["market_session_label"] = _session_label(session)
        if session == "call_auction_entry":
            order["status"] = "queued"
            order["queue_state"] = "call_auction_waiting_match"
            order["updated_at"] = _now()
            continue
        if session == "midday_break":
            order["status"] = "queued"
            order["queue_state"] = "midday_break_waiting"
            order["updated_at"] = _now()
            continue
        if order.get("status") == "queued":
            order["status"] = "pending"
        if order.get("status") != "partial":
            continue
        quote = _quote_for(order.get("code"))
        if not quote:
            continue
        matched = _limit_matchable_qty(order, quote)
        if matched <= 0:
            continue
        remaining = int(order.get("quantity") or 0) - int(order.get("filled_quantity") or 0)
        fill_qty = min(remaining, int(max(100, matched * 0.25) / 100) * 100)
        if fill_qty <= 0:
            continue
        order["status"] = "pending"
        order["queue_progress_shares"] = int(order.get("queue_progress_shares") or 0) + matched
        _record_event(
            "orderbook",
            f"AI盘口排队推进 {order.get('code')}",
            f"{_session_label(session)}：新增可撮合量 {matched} 股，累计队列推进 {order.get('queue_progress_shares')} 股。",
            {"order": order, "quote": quote},
        )


def _quantity_from_amount(price: float, amount: float, available_cash: float) -> int:
    if price <= 0:
        return 0
    spend = max(0.0, min(float(amount or 0), float(available_cash or 0)))
    return int(spend / price / 100) * 100


def _place_order(side: str, code: str, quantity: int, price: float, reason: str, analysis: dict) -> dict:
    if not is_effective_trading_hours():
        blocked_order = {
            "order_id": f"AI_BLOCKED_{side.upper()}_{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
            "account_type": "simulation",
            "side": side,
            "code": code,
            "name": (state_store.get_stock_info(code) or {}).get("name", ""),
            "price": round(float(price or 0), 3),
            "quantity": int(quantity or 0),
            "status": "blocked",
            "reason": reason,
            "analysis": analysis or {},
            "created_at": _now(),
            "updated_at": _now(),
            "reject_reason": "非A股交易日或非交易时段，AI只能分析和记录，不能新增实时挂单。",
        }
        _state.setdefault("pending_orders", []).append(blocked_order)
        _record_event(
            "blocked",
            f"AI非交易时段挂单被阻止 {code}",
            "AI可以读取站内数据并形成分析，但只有开市后含集合竞价时段才允许模拟盘实时挂单。",
            {"order": blocked_order},
        )
        return blocked_order
    order = {
        "order_id": f"AI_{side.upper()}_{code}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "account_type": "simulation",
        "side": side,
        "code": code,
        "name": (state_store.get_stock_info(code) or {}).get("name", ""),
        "price": round(float(price), 3),
        "quantity": int(quantity),
        "status": "pending",
        "reason": reason,
        "analysis": analysis or {},
        "order_mode": "limit" if side == "buy" and _quote_for(code).get("limit_up") and price >= _to_float(_quote_for(code).get("limit_up")) * 0.999 else "market_like",
        "expiry_minutes": 20 if side == "buy" else 45,
        "market_session": _market_session(),
        "market_session_label": _session_label(_market_session()),
        "created_at": _now(),
        "updated_at": _now(),
    }
    blocked, queue_ahead, quote = _is_limit_order_blocked(code, side, price)
    order["limit_queue"] = blocked
    order["queue_ahead_shares"] = int(queue_ahead)
    order["last_seen_volume"] = int(_to_float(quote.get("volume")))
    _state.setdefault("pending_orders", []).append(order)
    _record_event(
        "order",
        f"AI挂单{('买入' if side == 'buy' else '卖出')} {code}",
        f"{price:.3f} 元，{quantity} 股；{'涨跌停排队' if blocked else '普通模拟挂单'}。{reason}",
        {"order": order},
    )
    if _market_session() == "call_auction_entry":
        order["status"] = "queued"
        order["queue_state"] = "call_auction_order_entered"
        _record_event(
            "orderbook",
            f"AI集合竞价挂单排队 {code}",
            f"9:15-9:25 只接受报单和撤单模拟，9:25后按集合竞价撮合结果推进成交。前方估算 {order.get('queue_ahead_shares', 0)} 股。",
            {"order": order},
        )
    elif not blocked:
        _try_fill_order(order)
    return order


def _try_fill_order(order: dict) -> bool:
    if order.get("status") not in ("pending", "queued", "partial"):
        return False
    session = _market_session()
    order["market_session"] = session
    order["market_session_label"] = _session_label(session)
    if session in ("call_auction_entry", "midday_break", "closed"):
        order["status"] = "queued"
        order["queue_state"] = f"{session}_waiting"
        order["updated_at"] = _now()
        return False
    code = order.get("code")
    side = order.get("side")
    price = _trade_price(code, side, order.get("price"))
    remaining_qty = int(order.get("quantity") or 0) - int(order.get("filled_quantity") or 0)
    if price <= 0 or remaining_qty <= 0:
        return False
    quote = _quote_for(code)
    if session == "call_auction_match":
        matched = max(_limit_matchable_qty(order, quote), int(_quote_depth(quote, side) * 0.12))
        queue_ahead = int(order.get("queue_ahead_shares") or 0)
        progress = int(order.get("queue_progress_shares") or 0) + matched
        order["queue_progress_shares"] = progress
        order["queue_state"] = "call_auction_matching"
        if progress <= queue_ahead:
            order["status"] = "queued"
            order["updated_at"] = _now()
            _record_event(
                "orderbook",
                f"AI集合竞价未成交 {code}",
                f"集合竞价撮合量 {matched} 股，尚未穿透前方排队 {queue_ahead} 股。",
                {"order": order, "quote": quote},
            )
            return False
        fill_qty = min(remaining_qty, int((progress - queue_ahead) / 100) * 100)
    else:
        fill_qty = 0
    if order.get("order_mode") == "limit":
        matched = _limit_matchable_qty(order, quote) if session != "call_auction_match" else matched
        if matched <= 0:
            order["status"] = "queued"
            order["updated_at"] = _now()
            order["queue_state"] = "waiting_limit_match"
            return False
        if session != "call_auction_match":
            queue_ahead = int(order.get("queue_ahead_shares") or 0)
            progress = int(order.get("queue_progress_shares") or 0) + matched
            order["queue_progress_shares"] = progress
            if progress <= queue_ahead:
                order["status"] = "queued"
                order["updated_at"] = _now()
                _record_event(
                    "orderbook",
                    f"AI限价队列未成交 {code}",
                    f"盘口可撮合量 {matched} 股，累计推进 {progress} 股，前方仍有 {max(0, queue_ahead - progress)} 股。",
                    {"order": order, "quote": quote},
                )
                return False
            fillable = progress - queue_ahead
            fill_qty = min(remaining_qty, int(fillable / 100) * 100)
    elif order.get("limit_queue"):
        current_volume = int(_to_float(quote.get("volume")))
        traded_after_order = max(0, current_volume - int(order.get("last_seen_volume") or 0))
        fillable = max(0, traded_after_order - int(order.get("queue_ahead_shares") or 0))
        if fillable <= 0:
            order["updated_at"] = _now()
            order["queue_progress_shares"] = traded_after_order
            order["status"] = "queued"
            return False
        fill_qty = min(remaining_qty, int(fillable / 100) * 100)
    else:
        depth = _quote_depth(quote, side)
        ratio = 0.12 if session == "call_auction_match" else 0.22
        fill_qty = min(remaining_qty, max(100, int(depth * ratio / 100) * 100))
    fill_qty = int(fill_qty / 100) * 100
    if fill_qty <= 0:
        order["status"] = "queued"
        order["updated_at"] = _now()
        order["queue_state"] = "not_enough_round_lot_fill"
        return False
    if side == "buy":
        ok, detail = _execute_buy(code, price, fill_qty, order)
    else:
        ok, detail = _execute_sell(code, price, fill_qty, order)
    if not ok:
        order["status"] = "rejected"
        order["reject_reason"] = detail
        order["updated_at"] = _now()
        _record_event("reject", f"AI挂单未成交 {code}", detail, {"order": order})
        return False
    filled_qty = int(order.get("filled_quantity") or 0) + int(fill_qty)
    order["filled_quantity"] = filled_qty
    order["remaining_quantity"] = max(0, int(order.get("quantity") or 0) - filled_qty)
    order["status"] = "filled" if order["remaining_quantity"] <= 0 else "partial"
    order["filled_at"] = _now()
    order["updated_at"] = order["filled_at"]
    order["fill"] = detail
    order.setdefault("fills", []).append(detail)
    _state.setdefault("fills", []).append(detail)
    try:
        learning_note = _append_fill_learning_note(detail, order)
        if learning_note:
            _record_event(
                "learning",
                f"AI逐笔成交经验已沉淀 {code}",
                "本次成交已写入长期策略记忆，后续AI托管和AI选股会自动引用。",
                {"fill_key": detail.get("learning_note_key"), "note_title": learning_note.get("title")},
            )
    except Exception as exc:
        _record_event(
            "learning_error",
            f"AI逐笔成交经验沉淀失败 {code}",
            str(exc),
            {"fill": detail},
        )
    _record_event(
        "fill",
        f"AI成交{('买入' if side == 'buy' else '卖出')} {code}",
        f"{detail.get('price')} 元，{detail.get('quantity')} 股，费用 {detail.get('total_fee')} 元。",
        {"fill": detail, "analysis": order.get("analysis") or {}},
    )
    return order["status"] == "filled"


def _execute_buy(code: str, price: float, quantity: int, order: dict) -> tuple[bool, dict | str]:
    allowed, reason = _board_allowed(code)
    if not allowed:
        return False, reason
    if quantity <= 0 or quantity % 100 != 0:
        return False, "买入数量必须为100股整数倍"
    portfolio = state_store.get_portfolio()
    fee = _fees("buy", price, quantity)
    amount = price * quantity
    total_cost = amount + fee["total_fee"]
    if total_cost > _to_float(portfolio.get("available_cash")):
        return False, f"可用资金不足，需要 {total_cost:.2f}，可用 {portfolio.get('available_cash'):.2f}"
    portfolio["available_cash"] = round(_to_float(portfolio.get("available_cash")) - total_cost, 2)
    state_store.update_portfolio(portfolio)
    positions = state_store.get_positions()
    now = _now()
    stock_info = state_store.get_stock_info(code) or {}
    if code in positions:
        pos = positions[code]
        old_qty = int(pos.get("quantity") or 0)
        old_cost = _to_float(pos.get("avg_cost")) * old_qty
        new_qty = old_qty + quantity
        pos["avg_cost"] = round((old_cost + amount) / max(new_qty, 1), 3)
        pos["quantity"] = new_qty
        pos["current_price"] = price
        pos["market_value"] = round(price * new_qty, 2)
        pos["floating_profit"] = round((price - pos["avg_cost"]) * new_qty, 2)
        pos["floating_profit_pct"] = round((price - pos["avg_cost"]) / max(pos["avg_cost"], 0.01) * 100, 2)
        pos["updated_at"] = now
        pos["buy_date"] = pos.get("buy_date") or now
    else:
        state_store.set_position(code, {
            "code": code,
            "name": stock_info.get("name", ""),
            "quantity": quantity,
            "available_quantity": 0,
            "avg_cost": round(price, 3),
            "current_price": price,
            "market_value": round(amount, 2),
            "floating_profit": 0.0,
            "floating_profit_pct": 0.0,
            "stop_loss": round(price * 0.95, 2),
            "take_profit": round(price * 1.10, 2),
            "peak_price": price,
            "buy_date": now,
            "updated_at": now,
        })
    fill = {
        "order_id": order.get("order_id"),
        "side": "buy",
        "code": code,
        "name": stock_info.get("name", ""),
        "price": price,
        "quantity": quantity,
        "amount": round(amount, 2),
        **fee,
        "total_cost": round(total_cost, 2),
        "reason": order.get("reason", ""),
        "analysis": order.get("analysis") or {},
        "filled_at": now,
    }
    state_store.add_order({
        "order_id": fill["order_id"],
        "type": "buy",
        "code": code,
        "name": fill["name"],
        "price": price,
        "quantity": quantity,
        "amount": fill["amount"],
        "commission": fee["commission"],
        "stamp_tax": fee["stamp_tax"],
        "transfer_fee": fee["transfer_fee"],
        "total_fee": fee["total_fee"],
        "total_cost": fill["total_cost"],
        "reason": fill["reason"],
        "created_at": now,
    })
    portfolio_manager.update_positions_realtime()
    return True, fill


def _execute_sell(code: str, price: float, quantity: int, order: dict) -> tuple[bool, dict | str]:
    positions = state_store.get_positions()
    if code not in positions:
        return False, "未持有该股票"
    pos = positions[code]
    available = int(pos.get("available_quantity") or 0)
    if quantity <= 0 or quantity % 100 != 0:
        return False, "卖出数量必须为100股整数倍"
    if quantity > available:
        return False, f"T+1规则限制，可卖 {available} 股，请求卖出 {quantity} 股"
    fee = _fees("sell", price, quantity)
    amount = price * quantity
    net_amount = amount - fee["total_fee"]
    avg_cost = _to_float(pos.get("avg_cost"))
    realized_pnl = (price - avg_cost) * quantity - fee["total_fee"]
    portfolio = state_store.get_portfolio()
    portfolio["available_cash"] = round(_to_float(portfolio.get("available_cash")) + net_amount, 2)
    portfolio["today_profit"] = round(_to_float(portfolio.get("today_profit")) + realized_pnl, 2)
    state_store.update_portfolio(portfolio)
    remaining = int(pos.get("quantity") or 0) - quantity
    now = _now()
    if remaining <= 0:
        state_store.remove_position(code)
    else:
        pos["quantity"] = remaining
        pos["available_quantity"] = min(available - quantity, remaining)
        pos["current_price"] = price
        pos["market_value"] = round(price * remaining, 2)
        pos["floating_profit"] = round((price - avg_cost) * remaining, 2)
        pos["floating_profit_pct"] = round((price - avg_cost) / max(avg_cost, 0.01) * 100, 2)
        pos["updated_at"] = now
    fill = {
        "order_id": order.get("order_id"),
        "side": "sell",
        "code": code,
        "name": pos.get("name", ""),
        "price": price,
        "quantity": quantity,
        "amount": round(amount, 2),
        **fee,
        "net_amount": round(net_amount, 2),
        "avg_cost": avg_cost,
        "realized_pnl": round(realized_pnl, 2),
        "reason": order.get("reason", ""),
        "analysis": order.get("analysis") or {},
        "filled_at": now,
    }
    state_store.add_order({
        "order_id": fill["order_id"],
        "type": "sell",
        "code": code,
        "name": fill["name"],
        "price": price,
        "quantity": quantity,
        "amount": fill["amount"],
        "commission": fee["commission"],
        "stamp_tax": fee["stamp_tax"],
        "transfer_fee": fee["transfer_fee"],
        "total_fee": fee["total_fee"],
        "net_amount": fill["net_amount"],
        "avg_cost": avg_cost,
        "realized_pnl": fill["realized_pnl"],
        "reason": fill["reason"],
        "created_at": now,
    })
    portfolio_manager.update_positions_realtime()
    return True, fill


def start_trustee(account_type: str, end_date: str, requested_by: str = "user") -> dict:
    account_type = account_type or "simulation"
    with _lock:
        if account_type != "simulation":
            _record_event("permission", "实操盘AI托管被阻止", "当前版本只允许模拟盘执行，真实交易接口不会下单。")
            _save_state()
            return {"success": False, "error": "当前只开放模拟盘AI托管，实操盘不允许自动交易。", **get_status()}
        calendar = trading_calendar_service.normalize_trustee_end_date(end_date)
        final_end_date = calendar["final_trading_day"]
        strategy = _infer_strategy(final_end_date)
        _state["simulation"].update({
            "enabled": True,
            "status": "running",
            "started_at": _now(),
            "requested_end_date": calendar["requested_date"],
            "end_date": final_end_date,
            "calendar": calendar,
            "strategy": strategy,
            "self_test": {
                "status": "pending",
                "started_at": _now(),
                "finished_at": None,
                "checks": [],
                "error": None,
            },
            "ai_policy": {},
            "message": f"AI托管已开启，{calendar['note']} 策略由AI按期限选择为 {strategy}。",
            "requested_by": requested_by,
        })
        _record_event(
            "trustee",
            "AI模拟盘托管开启",
            f"{calendar['note']} AI可调动20万模拟资金，但必须遵守T+1、涨跌停排队、板块权限和手续费规则。",
            {"strategy": strategy, "fees": TRUSTEE_FEES, "calendar": calendar},
        )
        _save_state()
    threading.Thread(target=_self_test_then_decide, daemon=True).start()
    return {"success": True, **get_status()}


def stop_trustee(account_type: str = "simulation", reason: str = "用户手动停止") -> dict:
    with _lock:
        target = _state.get(account_type) or _state["simulation"]
        target.update({"enabled": False, "status": "stopped", "message": reason})
        for order in _state.get("pending_orders", []):
            if order.get("status") == "pending":
                order["status"] = "cancelled"
                order["updated_at"] = _now()
                order["cancel_reason"] = reason
        _record_event("trustee", "AI托管停止", reason)
        _save_state()
        return {"success": True, **get_status()}


def _pick_available_candidates(strategy: str) -> list:
    _record_event("analysis", "AI开始盘中扫描", "自由读取当前模拟盘、全站行情、板块资金、新闻公告、游资经验、AI选股复核池，也可以不用预设策略而自行筛选股票。")
    if ai_model_service.is_ready():
        try:
            result = ai_stock_picker.run_ai_stock_picking(
                strategy=strategy,
                limit=3,
                universe_limit=20,
                scope="all",
            )
            rows = _as_list(result.get("recommendations") or result.get("reviewed_candidates"))
            if rows:
                return rows[:5]
        except Exception as exc:
            _record_event("analysis", "AI全市场复核异常", str(exc))
    rows = state_store.get_screening_results() or []
    if not rows:
        try:
            rows = stock_screener.run_screening(limit=20, return_all=False, strategy=strategy)
        except Exception:
            rows = []
    return _as_list(rows)[:5]


def _build_ai_policy(strategy: str, portfolio: dict, positions: list, candidates: list, market_fact_snapshot: Optional[dict] = None) -> dict:
    candidates = _as_list(candidates)
    schema_hint = """{
  "risk_mode": "aggressive|balanced|defensive",
  "max_position_count": 10,
  "max_single_position_pct": 20,
  "max_total_position_pct": 80,
  "max_daily_trades": 20,
  "max_drawdown_pct": 6,
  "should_circuit_break": false,
  "preferred_actions": ["buy","sell","hold","cancel"],
  "reentry_rule": "何时撤单后重挂",
  "exit_rule": "什么情况下立即减仓或清仓",
  "focus_rule": "如何决定是否参与集合竞价或盘中追价"
}"""
    payload, meta = ai_model_service.chat_json(
        "trade_decision",
        (
            "你是模拟盘AI托管交易员。不要被界面上的短线/长线标签约束，"
            "你需要根据当前市场、持仓、候选池、新闻公告、资金流和集合竞价/盘中状态，"
            "自己决定当天的交易纪律。系统只会做少量硬性约束检查。"
            "请输出你自己的纪律框架，包含风险模式、单票仓位上限、总仓位上限、日内交易次数上限、"
            "最大回撤阈值、是否需要自动降频/停手、撤单后多久重挂、什么情况下应减仓或清仓。"
        ),
        {
            "now": _now(),
            "strategy_hint": strategy,
            "portfolio": portfolio,
            "positions": positions,
            "candidates": candidates[:10],
            "market_fact_snapshot": market_fact_snapshot or {},
            "market_state": {
                "is_trading_day": is_effective_trading_day(date.today()),
                "is_trading_hours": is_effective_trading_hours(),
                "calendar_today": get_status().get("calendar_today", {}),
            },
        },
        schema_hint=schema_hint,
    )
    if payload:
        payload["ai_meta"] = meta
        return payload
    return {
        "risk_mode": "balanced" if strategy == "short" else "defensive",
        "max_position_count": 10,
        "max_single_position_pct": 20,
        "max_total_position_pct": 80,
        "max_daily_trades": 20,
        "max_drawdown_pct": 6,
        "should_circuit_break": False,
        "preferred_actions": ["buy", "sell", "hold", "cancel"],
        "reentry_rule": "挂单超时或盘口变化时先撤单再评估。",
        "exit_rule": "跌破关键支撑或截止日期临近时减仓清仓。",
        "focus_rule": "开市后可盘中跟随，集合竞价只对高确定性目标参与。",
    }


def _build_ai_plan(strategy: str, candidates: list) -> dict:
    candidates = _as_list(candidates)
    portfolio = portfolio_manager.get_portfolio_summary()
    positions = portfolio_manager.get_position_list()
    market_fact_snapshot = _build_market_fact_snapshot()
    ai_policy = _build_ai_policy(strategy, portfolio, positions, candidates, market_fact_snapshot=market_fact_snapshot)
    compact_candidates = []
    for row in candidates[:5]:
        code = row.get("code")
        compact_candidates.append({
            "code": code,
            "name": row.get("name"),
            "score": row.get("ai_quality_score") or row.get("score"),
            "price": (row.get("trade_plan") or {}).get("current_price") or row.get("price"),
            "reason": row.get("ai_reason") or row.get("reason") or row.get("ai_quality_reason"),
            "youzi_quality_view": row.get("youzi_quality_view") or (row.get("screening_logic") or {}).get("youzi_experience"),
            "news": (row.get("evidence") or {}).get("新闻公告") or (row.get("screening_logic") or {}).get("news"),
        })
    schema_hint = """{
  "market_read": "先看集合竞价/板块资金/新闻/持仓/筛选池中的哪些证据",
  "strategy_reason": "期限标签只是参考，AI最终按自己的盘面判断选择策略和股票",
  "orders": [{"side":"buy|sell|hold","code":"000001","target_cash":20000,"price_type":"current|limit|support","reason":"下单理由"}],
  "risk_control": "仓位和退出纪律",
  "youzi_reference": "是否借鉴游资交割单经验以及具体经验"
}"""
    payload, meta = ai_model_service.chat_json(
        "trade_decision",
        (
            "你是只操作模拟盘的A股AI托管操盘手。用户界面上的短线/长线策略只是给主人查看的参考标签，"
            "不是对你的限制。你拥有很高的选股自由度：可以调用AI智能选股、读取网站内所有行情、板块、"
            "新闻、公告、资金、K线、持仓、交易记录、游资经验和风控证据，也可以使用你认为更好的逻辑自行选股。"
            "但你只能读取数据和执行模拟盘交易，不能修改网站配置、模型配置、风控参数、股票池或其他非交易数据。"
            "只有A股开市后才允许实时挂单，9:15-9:25集合竞价可参与，连续竞价按盘中规则执行；非交易时段只能分析和记录，不能新增挂单。"
            "每一笔计划、挂单、撤销、成交、未成交原因都必须写清楚时间、股票、价格、数量、依据、新闻/板块/游资经验证据。"
            "你可以决定20万模拟资金如何买卖，但必须遵守T+1、100股整数倍、涨跌停排队、无创业板/科创板/北交所权限、"
            "佣金万三、卖出印花税万五、过户费十万分之一。必须在托管截止日收盘前清仓。输出JSON。"
            "你必须严格使用 market_fact_snapshot 中的指数涨跌、涨跌家数和时间戳；"
            "禁止自行编造上证指数、深成指、创业板指、涨跌家数、涨停跌停或成交额。"
            "如果 market_fact_snapshot 缺失某项，必须明确写“未取得”，不得猜测。"
        ),
        {
            "now": _now(),
            "requested_end_date": (_state.get("simulation") or {}).get("requested_end_date"),
            "final_trading_end_date": (_state.get("simulation") or {}).get("end_date"),
            "calendar": (_state.get("simulation") or {}).get("calendar"),
            "ui_strategy_hint": strategy,
            "strategy_permission": "UI策略仅为参考标签，AI可自由选择短线/中线/长线或混合策略。",
            "read_only_permissions": "可读取站内所有数据；禁止修改网站配置、模型配置、风控参数、股票池和非交易数据。",
            "execution_window": "仅A股交易日9:15-11:30、13:00-15:00允许新增模拟盘挂单，集合竞价可参与。",
            "portfolio": portfolio,
            "positions": positions,
            "candidates": compact_candidates,
            "market_fact_snapshot": market_fact_snapshot,
            "fees": TRUSTEE_FEES,
            "ai_policy": ai_policy,
        },
        schema_hint=schema_hint,
    )
    if payload:
        payload["ai_meta"] = meta
        payload["ai_policy"] = ai_policy
        return payload
    orders = []
    available = _to_float(portfolio.get("available_cash"))
    for row in compact_candidates[:3]:
        code = row.get("code")
        price = _to_float(row.get("price")) or _trade_price(code, "buy")
        allowed, _reason = _board_allowed(code)
        if allowed and price > 0:
            orders.append({
                "side": "buy",
                "code": code,
                "target_cash": min(available * 0.28, 40000),
                "price_type": "current",
                "reason": row.get("reason") or "本地AI质量池相对靠前，按模拟盘托管试单",
            })
    return {
        "market_read": "读取当前模拟盘、行情缓存、AI选股复核池、游资经验因子和新闻公告后生成本地托管计划。",
        "strategy_reason": f"UI策略提示为 {strategy}，AI仍可自由选股；本地兜底先以可成交和可退出为主。",
        "orders": orders,
        "risk_control": "单次循环最多3只，保留T+1和涨跌停排队，截止日前强制清仓。",
        "youzi_reference": "参考主线板块、情绪周期、盘口承接和仓位纪律。",
        "ai_policy": ai_policy,
    }


def _run_decision_cycle():
    with _lock:
        if not (_state.get("simulation") or {}).get("enabled"):
            return
        if (_state.get("simulation") or {}).get("health_status") != "green":
            _record_event("self_test", "AI托管未进入绿灯", "自检未通过或仍在自检，本轮不新增交易计划。")
            _save_state()
            return
        strategy = (_state.get("simulation") or {}).get("strategy") or "short"
        _state["simulation"]["last_cycle_at"] = _now()
        _state["simulation"]["message"] = "AI正在读取盘中行情、模拟盘、新闻和候选池"
        _save_state()
    try:
        _process_pending_orders()
        if _is_after_end_date():
            _liquidate_all("托管截止日已到，AI按约定清仓。")
            return
        candidates = _pick_available_candidates(strategy)
        plan = _build_ai_plan(strategy, candidates)
        with _lock:
            _record_event(
                "analysis",
                "AI托管分析完成",
                f"{plan.get('market_read', '')} {plan.get('strategy_reason', '')} {plan.get('risk_control', '')}",
                {"plan": plan},
            )
            _execute_plan(plan)
            _state["simulation"]["message"] = "AI托管运行中，已完成本轮盘中分析"
            _save_state()
    except Exception as exc:
        with _lock:
            _state["simulation"]["message"] = f"AI托管本轮异常：{exc}"
            _record_event("error", "AI托管循环异常", str(exc))
            _save_state()


def _self_test_then_decide():
    result = _run_self_test()
    if not result.get("success"):
        return
    with _lock:
        if not (_state.get("simulation") or {}).get("enabled"):
            return
    if is_effective_trading_hours():
        _run_decision_cycle()
    else:
        with _lock:
            _record_event(
                "self_test",
                "AI托管绿灯待命",
                f"自检通过，但当前为{_session_label(_market_session())}，AI只盯盘记录，开市后再允许实时挂单。",
            )
            _save_state()


def _execute_plan(plan: dict):
    portfolio = portfolio_manager.get_portfolio_summary()
    available = _to_float(portfolio.get("available_cash"))
    ai_policy = plan.get("ai_policy") or {}
    max_total_pct = _to_float(ai_policy.get("max_total_position_pct"), 80)
    max_single_pct = _to_float(ai_policy.get("max_single_position_pct"), 20)
    max_daily_trades = int(_to_float(ai_policy.get("max_daily_trades"), 20))
    if portfolio.get("position_count", 0) >= int(_to_float(ai_policy.get("max_position_count"), 10)):
        _record_event("risk", "AI纪律触发", "持仓数已到上限，暂停新增买单。", {"ai_policy": ai_policy})
        return
    if _to_float(portfolio.get("market_value")) / max(_to_float(portfolio.get("total_asset")), 1) * 100 >= max_total_pct:
        _record_event("risk", "AI纪律触发", "总仓位已达到AI自定上限，暂停新增买单。", {"ai_policy": ai_policy})
        return
    risk_status = {
        "today_trade_count": len([o for o in (_state.get("pending_orders") or []) if o.get("status") in ("filled", "rejected", "cancelled") and str(o.get("created_at", "")).startswith(_today())]),
        "max_daily_trades": max_daily_trades,
    }
    if risk_status["today_trade_count"] >= max_daily_trades:
        _record_event("risk", "AI纪律触发", "今日交易次数已到AI自定上限，暂停新增买单。", {"ai_policy": ai_policy})
        return
    for item in plan.get("orders") or []:
        side = str(item.get("side") or "hold").lower()
        code = str(item.get("code") or "").strip()
        if side not in ("buy", "sell") or not code:
            continue
        price = _trade_price(code, side)
        if price <= 0:
            _record_event("reject", f"AI计划跳过 {code}", "缺少有效行情价格。", {"order_plan": item})
            continue
        analysis = {
            "market_read": plan.get("market_read"),
            "strategy_reason": plan.get("strategy_reason"),
            "risk_control": plan.get("risk_control"),
            "youzi_reference": plan.get("youzi_reference"),
            "order_reason": item.get("reason"),
        }
        if side == "buy":
            allowed, reason = _board_allowed(code)
            if not allowed:
                _record_event("reject", f"AI计划跳过 {code}", reason, {"order_plan": item, "analysis": analysis})
                continue
            quantity = _quantity_from_amount(price, _to_float(item.get("target_cash"), available * 0.25), available)
            if quantity <= 0:
                continue
            if price * quantity / max(_to_float(portfolio.get("total_asset")), 1) * 100 > max_single_pct:
                quantity = int((_to_float(portfolio.get("total_asset")) * max_single_pct / 100) / price / 100) * 100
            if quantity <= 0:
                continue
            _place_order("buy", code, quantity, price, item.get("reason") or "AI托管买入", analysis)
            available = max(0, available - price * quantity)
        else:
            pos = state_store.get_position(code) or {}
            quantity = int(item.get("quantity") or pos.get("available_quantity") or 0)
            quantity = int(quantity / 100) * 100
            if quantity <= 0:
                _record_event("reject", f"AI计划卖出受T+1限制 {code}", "当前没有可卖数量。", {"order_plan": item})
                continue
            _place_order("sell", code, quantity, price, item.get("reason") or "AI托管卖出", analysis)


def cancel_and_reprice(code: str, new_price: float | None = None, reason: str = "AI重评估后撤单重挂") -> dict:
    with _lock:
        changed = _cancel_orders_by_code(code, reason)
        if new_price and new_price > 0:
            _record_event("analysis", f"AI重挂评估 {code}", f"撤单 {changed} 笔后，按新价格 {new_price} 重新评估。")
        _save_state()
        return {"success": True, "cancelled": changed, "price": new_price, "reason": reason}


def _process_pending_orders():
    with _lock:
        _apply_intraday_market_state()
        _cancel_stale_orders()
        for order in list(_state.get("pending_orders") or []):
            if order.get("status") in ("pending", "queued", "partial"):
                _try_fill_order(order)
        _save_state()


def _is_after_end_date() -> bool:
    end_date = (_state.get("simulation") or {}).get("end_date")
    if not end_date:
        return False
    try:
        final_day = date.fromisoformat(str(end_date)[:10])
        return date.today() > final_day or (date.today() == final_day and datetime.now().strftime("%H:%M") >= "14:55")
    except Exception:
        return False


def _liquidate_all(reason: str):
    with _lock:
        for pos in portfolio_manager.get_position_list():
            quantity = int(pos.get("available_quantity") or 0)
            quantity = int(quantity / 100) * 100
            if quantity <= 0:
                continue
            code = pos.get("code")
            price = _trade_price(code, "sell")
            if price > 0:
                _place_order("sell", code, quantity, price, reason, {"risk_control": "托管截止日前清仓"})
        _state["simulation"].update({"enabled": False, "status": "done", "message": reason})
        _record_event("trustee", "AI托管到期清仓流程完成", reason)
        _save_state()


def run_daily_review(force: bool = False) -> dict:
    with _lock:
        if not force and _state.get("simulation", {}).get("last_review_at", "").startswith(_today()):
            return {"success": True, "message": "今日复盘已生成", **get_status()}
    portfolio = portfolio_manager.get_portfolio_summary()
    positions = portfolio_manager.get_position_list()
    records = get_records(limit=80)
    review = {
        "id": f"REVIEW_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        "created_at": _now(),
        "portfolio": portfolio,
        "positions": positions,
        "summary": "AI三点后复盘：记录今日挂单、成交、未成交原因、费用、T+1约束和次日计划。",
        "records_sample": records,
    }
    if ai_model_service.is_ready():
        payload, _meta = ai_model_service.chat_json(
            "deep_analysis",
            "你是模拟盘AI托管复盘员。请总结今日托管动作、盈亏、未成交原因、游资经验借鉴、新闻捕获、明日计划。输出JSON。",
            review,
        )
        if payload:
            review["ai_review"] = payload
    with _lock:
        _state.setdefault("daily_reviews", []).append(review)
        _state["simulation"]["last_review_at"] = review["created_at"]
        _record_event("review", "AI三点后复盘完成", review.get("summary", ""), {"review": review})
        _save_state()
    return {"success": True, "review": review, **get_status()}


def _loop():
    while True:
        try:
            load_state()
            sim = _state.get("simulation") or {}
            if sim.get("enabled"):
                if is_effective_trading_hours():
                    _run_decision_cycle()
                else:
                    _process_pending_orders()
                if datetime.now().strftime("%H:%M") >= "15:05":
                    run_daily_review(force=False)
            time.sleep(60)
        except Exception as exc:
            logger.warning(f"AI托管后台循环异常: {exc}")
            time.sleep(60)


def start_background_loop():
    global _loop_started
    if _loop_started:
        return
    load_state()
    _loop_started = True
    threading.Thread(target=_loop, daemon=True).start()
    logger.info("AI托管后台循环已启动")


def is_effective_trading_day(value=None) -> bool:
    try:
        return trading_calendar_service.is_trading_day(value or date.today())
    except Exception:
        return data_fetcher.is_trading_day()


def is_effective_trading_hours() -> bool:
    return is_effective_trading_day(date.today()) and data_fetcher.is_trading_hours()
