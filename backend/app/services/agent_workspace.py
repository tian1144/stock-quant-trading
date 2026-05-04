"""
Agent workspace state and log helpers.

This is a lightweight local runtime for the H5 Agent desk. It does not start
real autonomous workers yet; it standardizes the state, logs, artifacts, and
future holaOS handoff points for each quant Agent.
"""
import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

from app.services import state_store, risk_manager
from app.execution.kill_switch import get_kill_switch_status


BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "agents")
MAX_MEMORY_LOGS = 80


AGENTS: Dict[str, dict] = {
    "data": {
        "name": "数据 Agent",
        "role": "行情、K线、分时、资金流和股票池供给",
        "artifact": "market_snapshot.json",
        "handoff": "agents/data/state.json",
        "guardrail": "只读数据接入，不允许下单",
    },
    "news": {
        "name": "新闻 Agent",
        "role": "新闻、公告、宏观事件、情绪事件流",
        "artifact": "event_stream.json",
        "handoff": "agents/news/state.json",
        "guardrail": "事件需带来源和时间，避免把未来新闻灌入历史回测",
    },
    "score": {
        "name": "评分 Agent",
        "role": "事件、情绪、K线、资金、回测评分",
        "artifact": "score_card.json",
        "handoff": "agents/score/state.json",
        "guardrail": "输出评分卡，不直接生成订单",
    },
    "decision": {
        "name": "决策 Agent",
        "role": "结构化交易建议、入场条件、失效条件",
        "artifact": "decision.json",
        "handoff": "agents/decision/state.json",
        "guardrail": "只给建议，必须交给风控复核",
    },
    "risk": {
        "name": "风控 Agent",
        "role": "仓位、熔断、一票否决、风险复核",
        "artifact": "risk_report.json",
        "handoff": "agents/risk/state.json",
        "guardrail": "风控拥有最终否决权",
    },
    "execution": {
        "name": "执行 Agent",
        "role": "模拟盘订单计划、成交流水、安全检查",
        "artifact": "paper_trade_log.csv",
        "handoff": "agents/execution/state.json",
        "guardrail": "真实交易 API 默认关闭，仅允许模拟交易",
    },
}

_logs: Dict[str, List[dict]] = {agent_id: [] for agent_id in AGENTS}
_started_at = time.time()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _agent_dir(agent_id: str) -> str:
    return os.path.join(BASE_DIR, agent_id)


def _state_path(agent_id: str) -> str:
    return os.path.join(_agent_dir(agent_id), "state.json")


def _log_path(agent_id: str) -> str:
    return os.path.join(_agent_dir(agent_id), "events.jsonl")


def _ensure_agent_dirs():
    for agent_id in AGENTS:
        os.makedirs(_agent_dir(agent_id), exist_ok=True)


def _write_json(path: str, payload: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def record_event(agent_id: str, action: str, message: str, level: str = "info", payload: Optional[dict] = None) -> dict:
    """Record a compact event for an Agent and append it to its local JSONL log."""
    if agent_id not in AGENTS:
        agent_id = "data"
    _ensure_agent_dirs()
    event = {
        "time": _now(),
        "ts": _iso(),
        "agent_id": agent_id,
        "level": level,
        "action": action,
        "message": message,
        "payload": payload or {},
    }
    logs = _logs.setdefault(agent_id, [])
    logs.append(event)
    if len(logs) > MAX_MEMORY_LOGS:
        del logs[:-MAX_MEMORY_LOGS]
    try:
        with open(_log_path(agent_id), "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return event


def _load_tail(agent_id: str, limit: int) -> List[dict]:
    memory = _logs.get(agent_id, [])
    if len(memory) >= limit:
        return memory[-limit:]
    path = _log_path(agent_id)
    if not os.path.exists(path):
        return memory[-limit:]
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = [json.loads(line) for line in f.readlines()[-limit:] if line.strip()]
        return rows[-limit:]
    except Exception:
        return memory[-limit:]


def _status_level(has_data: bool, blocked: bool = False, stale: bool = False) -> str:
    if blocked:
        return "blocked"
    if stale:
        return "stale"
    return "running" if has_data else "idle"


def _age_seconds(ts: Optional[float]) -> Optional[int]:
    if not ts:
        return None
    return max(0, int(time.time() - ts))


def _agent_metrics(agent_id: str) -> dict:
    if agent_id == "data":
        realtime_count = len(state_store.get_all_realtime())
        universe_count = len(state_store.get_stock_universe())
        kline_count = len(state_store.get_daily_bars_codes())
        return {
            "股票池": universe_count,
            "实时行情": realtime_count,
            "K线缓存": kline_count,
            "行情延迟秒": _age_seconds(state_store.get_realtime_updated_at()),
        }
    if agent_id == "news":
        news = state_store.get_news()
        return {
            "事件数": len(news),
            "负面池": len(state_store.get_negative_news()),
            "最近刷新秒": _age_seconds(state_store.get_news_updated_at()),
        }
    if agent_id == "score":
        return {
            "候选数": len(state_store.get_screening_results()),
            "信号历史": len(state_store.get_signal_history()),
            "最近选股秒": _age_seconds(state_store.get_screening_updated_at()),
        }
    if agent_id == "decision":
        system = state_store.get_system_state()
        return {
            "今日信号": system.get("total_signals_today", 0),
            "买卖信号": len(state_store.get_signals()),
            "自动交易": "开" if system.get("auto_trade_enabled") else "关",
        }
    if agent_id == "risk":
        risk = risk_manager.get_risk_status()
        kill = get_kill_switch_status()
        return {
            "总仓位": f"{risk.get('exposure_pct', 0)}%",
            "今日交易": risk.get("today_trade_count", 0),
            "熔断": "是" if kill.get("active") else "否",
        }
    if agent_id == "execution":
        return {
            "持仓数": len(state_store.get_positions()),
            "订单数": len(state_store.get_orders()),
            "可用资金": round(state_store.get_portfolio().get("available_cash", 0), 2),
        }
    return {}


def _agent_status(agent_id: str) -> dict:
    meta = AGENTS[agent_id]
    metrics = _agent_metrics(agent_id)
    kill = get_kill_switch_status()
    blocked = agent_id in {"decision", "execution"} and bool(kill.get("active"))
    if agent_id == "data":
        has_data = metrics.get("股票池", 0) > 0 or metrics.get("实时行情", 0) > 0
        stale = bool(metrics.get("行情延迟秒") and metrics["行情延迟秒"] > 900)
    elif agent_id == "news":
        has_data = metrics.get("事件数", 0) > 0
        stale = bool(metrics.get("最近刷新秒") and metrics["最近刷新秒"] > 3600)
    elif agent_id == "score":
        has_data = metrics.get("候选数", 0) > 0
        stale = False
    elif agent_id == "decision":
        has_data = metrics.get("今日信号", 0) > 0 or metrics.get("买卖信号", 0) > 0
        stale = False
    elif agent_id == "risk":
        has_data = True
        stale = False
    else:
        has_data = metrics.get("订单数", 0) > 0 or metrics.get("持仓数", 0) > 0
        stale = False

    status = _status_level(has_data, blocked=blocked, stale=stale)
    logs = _load_tail(agent_id, 6)
    last_log = logs[-1] if logs else None
    return {
        "id": agent_id,
        **meta,
        "status": status,
        "status_text": {
            "running": "运行中",
            "idle": "待触发",
            "stale": "需刷新",
            "blocked": "被风控阻断",
        }.get(status, status),
        "metrics": metrics,
        "last_event": last_log,
        "state_file": _state_path(agent_id),
        "log_file": _log_path(agent_id),
        "logs": logs,
    }


def snapshot_all(reason: str = "manual") -> dict:
    """Write each Agent state file for holaOS-style future handoff."""
    _ensure_agent_dirs()
    agents = []
    for agent_id in AGENTS:
        status = _agent_status(agent_id)
        state = {
            "agent": {k: status[k] for k in ("id", "name", "role", "artifact", "handoff", "guardrail")},
            "status": status["status"],
            "status_text": status["status_text"],
            "metrics": status["metrics"],
            "last_event": status["last_event"],
            "updated_at": _iso(),
            "snapshot_reason": reason,
        }
        _write_json(_state_path(agent_id), state)
        agents.append({**status, "state": state})
    return {
        "updated_at": _now(),
        "runtime": "local_h5_agent_workspace",
        "uptime_seconds": int(time.time() - _started_at),
        "holaos_ready": True,
        "agents": agents,
        "pipeline": [
            "数据采集",
            "新闻理解",
            "评分归因",
            "结构化决策",
            "风控否决",
            "模拟执行",
        ],
        "storage_root": BASE_DIR,
    }


def get_workspace_state() -> dict:
    return snapshot_all(reason="read")


def get_agent_logs(agent_id: Optional[str] = None, limit: int = 50) -> dict:
    if agent_id:
        return {"agent_id": agent_id, "logs": _load_tail(agent_id, limit)}
    logs = []
    for aid in AGENTS:
        logs.extend(_load_tail(aid, limit))
    logs.sort(key=lambda x: x.get("ts", ""))
    return {"logs": logs[-limit:]}


def bootstrap_logs():
    if any(_logs.values()):
        return
    record_event("data", "startup", "Agent 工作台已启动，等待行情与股票池刷新。")
    record_event("news", "startup", "新闻 Agent 已就绪，等待事件流刷新。")
    record_event("risk", "startup", "风控 Agent 已就绪，真实交易接口保持关闭。")
