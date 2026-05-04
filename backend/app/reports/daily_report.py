"""
报告生成模块 - 日报/回测报告/模拟交易记录
"""
import json
import os
import csv
from datetime import datetime
from typing import Dict, List, Optional
from loguru import logger

from app.services import state_store, portfolio_manager, risk_manager, news_service
from app.analysis.decision_schema import generate_score_card


REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "backtest")
REPORT_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "reports")
PAPER_TRADE_LOG_PATH = os.path.join(REPORT_ROOT, "paper_trade_log.csv")


def generate_daily_report() -> dict:
    portfolio = portfolio_manager.get_portfolio_summary()
    positions = portfolio_manager.get_position_list()
    orders = state_store.get_orders()
    news = state_store.get_news()[:20]
    sentiment = news_service.get_market_sentiment()
    risk_status = risk_manager.get_risk_status()
    system_state = state_store.get_system_state()

    today = datetime.now().strftime("%Y-%m-%d")
    today_orders = [o for o in orders if o.get("created_at", "").startswith(today)]

    market_status = {
        "date": today,
        "sentiment": sentiment,
        "northbound": state_store.get_northbound_flow(),
    }

    events_summary = []
    for item in news[:10]:
        from app.analysis.event_scoring import score_event
        scored = score_event(
            item.get("title", ""),
            item.get("content", item.get("brief", "")),
            item.get("source", "")
        )
        events_summary.append({
            "title": item.get("title", ""),
            "impact_level": scored["impact_level"],
            "credibility": scored["credibility"],
            "direction": scored["direction"],
            "related_symbols": scored.get("related_symbols", []),
        })

    score_cards = []
    for pos in positions[:10]:
        code = pos.get("code", "")
        try:
            card = generate_score_card(code)
            score_cards.append(card)
        except Exception:
            pass

    report = {
        "report_type": "daily",
        "date": today,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_status": market_status,
        "events_summary": events_summary,
        "portfolio": portfolio,
        "positions": positions,
        "today_orders": today_orders,
        "score_cards": score_cards,
        "risk_status": risk_status,
        "system_state": {
            "startup_time": system_state.get("startup_time"),
            "auto_trade_enabled": system_state.get("auto_trade_enabled", False),
        },
    }

    _save_report(report, f"daily_{today}.json")
    return report


def generate_backtest_report(backtest_result: dict) -> dict:
    symbol = backtest_result.get("symbol", "")
    metrics = backtest_result.get("metrics", {})
    trades = backtest_result.get("trades", [])

    buy_trades = [t for t in trades if t["type"] == "buy"]
    sell_trades = [t for t in trades if t["type"] == "sell"]

    completed_trades = []
    for sell in sell_trades:
        entry = next((b for b in buy_trades if b.get("symbol") == sell.get("symbol")), None)
        completed_trades.append({
            "symbol": sell.get("symbol", ""),
            "entry_time": sell.get("entry_time", ""),
            "entry_price": sell.get("entry_price", 0),
            "exit_time": sell.get("exit_time", ""),
            "exit_price": sell.get("exit_price", 0),
            "pnl": sell.get("pnl", 0),
            "pnl_pct": sell.get("pnl_pct", 0),
            "reason": sell.get("reason", ""),
        })

    report = {
        "report_type": "backtest",
        "symbol": symbol,
        "strategy": backtest_result.get("strategy", ""),
        "initial_cash": backtest_result.get("initial_cash", 200000),
        "final_equity": backtest_result.get("final_equity", 200000),
        "metrics": metrics,
        "trade_count": len(trades),
        "buy_count": len(buy_trades),
        "sell_count": len(sell_trades),
        "completed_trade_count": len(completed_trades),
        "completed_trades": completed_trades,
        "context_summary": backtest_result.get("context_summary", metrics.get("context_summary", {})),
        "context_samples": backtest_result.get("context_samples", []),
        "sample_note": metrics.get("sample_note", ""),
        "lookahead_check": metrics.get("lookahead_check", {}),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    _save_report(report, f"backtest_{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    return report


def generate_paper_trade_log() -> list:
    orders = state_store.get_orders()
    log = []
    for order in orders:
        log.append({
            "order_id": order.get("order_id", ""),
            "type": order.get("type", ""),
            "symbol": order.get("code", ""),
            "name": order.get("name", ""),
            "price": order.get("price", 0),
            "quantity": order.get("quantity", 0),
            "amount": order.get("amount", 0),
            "commission": order.get("commission", 0),
            "stamp_tax": order.get("stamp_tax", 0),
            "total_fee": order.get("total_fee", 0),
            "pnl": order.get("realized_pnl", 0),
            "reason": order.get("reason", ""),
            "created_at": order.get("created_at", ""),
        })
    _save_paper_trade_csv(log)
    return log


def get_paper_trade_log_path() -> str:
    return PAPER_TRADE_LOG_PATH


def generate_weekly_report() -> dict:
    daily = generate_daily_report()
    orders = state_store.get_orders()
    positions = portfolio_manager.get_position_list()
    report = {
        "report_type": "weekly",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "portfolio": daily.get("portfolio", {}),
        "position_count": len(positions),
        "order_count": len(orders),
        "risk_status": daily.get("risk_status", {}),
        "market_status": daily.get("market_status", {}),
        "todo": [
            "接入稳定财报/公告源后补充业绩雷与公告风险周度统计",
            "接入真实Level2后补充盘口异常与撤单风险周度统计",
        ],
    }
    _save_report(report, f"weekly_{datetime.now().strftime('%Y-%m-%d')}.json")
    return report


def _save_paper_trade_csv(rows: list):
    os.makedirs(os.path.dirname(PAPER_TRADE_LOG_PATH), exist_ok=True)
    fields = [
        "order_id", "type", "symbol", "name", "price", "quantity", "amount",
        "commission", "stamp_tax", "total_fee", "pnl", "reason", "created_at",
    ]
    with open(PAPER_TRADE_LOG_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def _save_report(report: dict, filename: str):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    filepath = os.path.join(REPORTS_DIR, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"报告已保存: {filepath}")
    except Exception as e:
        logger.error(f"报告保存失败: {e}")
