"""
模拟交易模块 - Paper Trading记录
"""
import csv
import os
from datetime import datetime
from typing import List
from loguru import logger

from app.services import state_store, portfolio_manager, risk_manager
from app.execution.kill_switch import is_kill_switch_active

PAPER_TRADE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "backtest")


def execute_paper_buy(code: str, price: float, quantity: int, reason: str = "", decision: dict = None) -> dict:
    if is_kill_switch_active():
        return {"success": False, "error": "熔断开关已激活，禁止交易"}

    result = portfolio_manager.execute_buy(code, price, quantity, reason)
    if result["success"]:
        order = result["order"]
        order["paper_trade"] = True
        order["decision_snapshot"] = decision
        _append_paper_trade_log(order)

    return result


def execute_paper_sell(code: str, price: float, quantity: int, reason: str = "", decision: dict = None) -> dict:
    if is_kill_switch_active():
        return {"success": False, "error": "熔断开关已激活，禁止交易"}

    result = portfolio_manager.execute_sell(code, price, quantity, reason)
    if result["success"]:
        order = result["order"]
        order["paper_trade"] = True
        order["decision_snapshot"] = decision
        _append_paper_trade_log(order)

    return result


def get_paper_trade_log() -> List[dict]:
    filepath = os.path.join(PAPER_TRADE_DIR, "paper_trade_log.csv")
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception:
        return []


def _append_paper_trade_log(order: dict):
    os.makedirs(PAPER_TRADE_DIR, exist_ok=True)
    filepath = os.path.join(PAPER_TRADE_DIR, "paper_trade_log.csv")

    file_exists = os.path.exists(filepath)
    fieldnames = ["order_id", "type", "code", "name", "price", "quantity", "amount",
                  "commission", "stamp_tax", "total_fee", "reason", "created_at", "paper_trade"]

    try:
        with open(filepath, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            row = {k: order.get(k, "") for k in fieldnames}
            row["paper_trade"] = "true"
            writer.writerow(row)
    except Exception as e:
        logger.error(f"模拟交易日志写入失败: {e}")
