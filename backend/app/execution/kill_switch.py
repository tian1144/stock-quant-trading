"""
熔断开关模块 - 紧急停止交易
"""
from datetime import datetime
from typing import Optional
from loguru import logger

_kill_switch_active = False
_kill_switch_reason = ""
_kill_switch_triggered_at = ""


def activate_kill_switch(reason: str = "手动触发") -> dict:
    global _kill_switch_active, _kill_switch_reason, _kill_switch_triggered_at
    _kill_switch_active = True
    _kill_switch_reason = reason
    _kill_switch_triggered_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.warning(f"熔断开关已激活: {reason}")
    return {"active": True, "reason": reason, "triggered_at": _kill_switch_triggered_at}


def deactivate_kill_switch() -> dict:
    global _kill_switch_active, _kill_switch_reason, _kill_switch_triggered_at
    _kill_switch_active = False
    _kill_switch_reason = ""
    _kill_switch_triggered_at = ""
    logger.info("熔断开关已关闭")
    return {"active": False, "reason": "", "triggered_at": ""}


def is_kill_switch_active() -> bool:
    return _kill_switch_active


def get_kill_switch_status() -> dict:
    return {
        "active": _kill_switch_active,
        "reason": _kill_switch_reason,
        "triggered_at": _kill_switch_triggered_at,
    }


def check_can_trade() -> tuple:
    if _kill_switch_active:
        return False, f"熔断开关已激活: {_kill_switch_reason}"
    return True, "可交易"
