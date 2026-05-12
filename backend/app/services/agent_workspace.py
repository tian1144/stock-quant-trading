"""
Agent workspace state and log helpers.

This is a lightweight local runtime for the H5 Agent desk. It does not start
real autonomous workers yet; it standardizes the state, logs, artifacts, and
future holaOS handoff points for each quant Agent.
"""
import json
import os
import re
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from app.services import state_store, risk_manager
from app.execution.kill_switch import get_kill_switch_status


BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "agents")
MAX_MEMORY_LOGS = 80
MAX_TASKS = 200


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
    "technical": {
        "name": "技术 Agent",
        "role": "K线形态、支撑压力、趋势、量价结构分析",
        "artifact": "technical_view.json",
        "handoff": "agents/technical/state.json",
        "guardrail": "只输出技术证据，不单独决定买卖",
    },
    "capital": {
        "name": "资金 Agent",
        "role": "主力资金、板块资金、龙虎榜、游资行为归因",
        "artifact": "capital_flow.json",
        "handoff": "agents/capital/state.json",
        "guardrail": "资金信号必须与结构、风控共同确认",
    },
    "sentiment": {
        "name": "情绪 Agent",
        "role": "情绪周期、涨跌停温度、主线板块和仓位温度",
        "artifact": "sentiment_phase.json",
        "handoff": "agents/sentiment/state.json",
        "guardrail": "情绪过热时只能降级，不能放大仓位",
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
    "review": {
        "name": "复盘 Agent",
        "role": "模拟盘盈亏复盘、策略记忆沉淀、权重调整建议",
        "artifact": "review_notes.json",
        "handoff": "agents/review/state.json",
        "guardrail": "复盘建议需回测或人工确认后才能进入生产权重",
    },
}

_logs: Dict[str, List[dict]] = {agent_id: [] for agent_id in AGENTS}
_tasks: Dict[str, dict] = {}
_started_at = time.time()

AGENT_TOOL_POOLS: Dict[str, List[str]] = {
    "data": ["realtime_quotes", "stock_universe", "daily_kline", "intraday", "market_snapshot"],
    "news": ["news", "announcements", "disclosure_risk", "sentiment_events"],
    "technical": ["daily_kline", "intraday", "technical_indicators", "limit_moves"],
    "capital": ["sector_money_flow", "money_flow", "sector_rankings", "limit_moves"],
    "sentiment": ["market_sentiment", "limit_moves", "sector_heat", "news"],
    "score": ["candidate_stocks", "ai_recommendations", "score_card", "backtest_summary"],
    "decision": ["task_planning", "ai_recommendations", "portfolio", "risk", "strategy_memory"],
    "risk": ["risk", "kill_switch", "risk_config", "disclosure_risk"],
    "execution": ["portfolio", "orders", "paper_trade", "email", "pdf"],
    "review": ["strategy_memory", "orders", "portfolio", "trade_review"],
}

TOOL_AGENT_MAP: Dict[str, List[str]] = {}
for _agent_id, _tools in AGENT_TOOL_POOLS.items():
    AGENTS.setdefault(_agent_id, {})["tool_pool"] = list(_tools)
    for _tool in _tools:
        TOOL_AGENT_MAP.setdefault(_tool, []).append(_agent_id)


def get_agent_tool_catalog() -> dict:
    """Return the tool pools that the site AI orchestrator may route work to."""
    return {
        "agents": [
            {
                "id": agent_id,
                "name": meta.get("name"),
                "role": meta.get("role"),
                "tools": list(AGENT_TOOL_POOLS.get(agent_id, [])),
                "artifact": meta.get("artifact"),
                "guardrail": meta.get("guardrail"),
            }
            for agent_id, meta in AGENTS.items()
        ],
        "tool_to_agents": {tool: list(agent_ids) for tool, agent_ids in TOOL_AGENT_MAP.items()},
    }


def agents_for_tools(tools: List[str]) -> List[str]:
    """Infer the minimum ordered Agent route for a requested tool list."""
    ordered: List[str] = []
    for tool in tools or []:
        for agent_id in TOOL_AGENT_MAP.get(str(tool), []):
            if agent_id not in ordered:
                ordered.append(agent_id)
    if not ordered:
        ordered = ["data", "decision", "risk"]
    return [agent_id for agent_id in ordered if agent_id in AGENTS]


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


def _artifact_dir(agent_id: str) -> str:
    return os.path.join(_agent_dir(agent_id), "artifacts")


def _tasks_path() -> str:
    return os.path.join(BASE_DIR, "tasks.json")


def _ensure_agent_dirs():
    for agent_id in AGENTS:
        os.makedirs(_agent_dir(agent_id), exist_ok=True)
        os.makedirs(_artifact_dir(agent_id), exist_ok=True)


def _write_json(path: str, payload: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _safe_payload(payload: Optional[dict]) -> dict:
    try:
        json.dumps(payload or {}, ensure_ascii=False)
        return payload or {}
    except Exception:
        return {"repr": repr(payload)}


def _load_tasks() -> Dict[str, dict]:
    global _tasks
    if _tasks:
        return _tasks
    path = _tasks_path()
    if not os.path.exists(path):
        return _tasks
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = json.load(f)
        if isinstance(rows, list):
            _tasks = {str(item.get("task_id")): item for item in rows if item.get("task_id")}
    except Exception:
        _tasks = {}
    return _tasks


def _persist_tasks():
    _ensure_agent_dirs()
    rows = sorted(_tasks.values(), key=lambda x: x.get("updated_at", ""), reverse=True)[:MAX_TASKS]
    _write_json(_tasks_path(), rows)


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
        "payload": _safe_payload(payload),
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


def start_task(
    agent_id: str,
    task_type: str,
    title: str,
    payload: Optional[dict] = None,
    task_id: Optional[str] = None,
    related_agents: Optional[List[str]] = None,
    requires_approval: bool = False,
) -> dict:
    """Create or replace a local orchestration task for traceable Agent work."""
    if agent_id not in AGENTS:
        agent_id = "data"
    _load_tasks()
    task_id = task_id or f"{task_type}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    now = _iso()
    task = {
        "task_id": task_id,
        "agent_id": agent_id,
        "task_type": task_type,
        "title": title,
        "status": "running",
        "stage": "start",
        "message": title,
        "created_at": now,
        "updated_at": now,
        "finished_at": None,
        "payload": _safe_payload(payload),
        "progress": {},
        "related_agents": [a for a in (related_agents or []) if a in AGENTS],
        "requires_approval": bool(requires_approval),
        "artifacts": [],
        "error": None,
    }
    _tasks[task_id] = task
    _persist_tasks()
    record_event(agent_id, f"{task_type}_start", title, payload={"task_id": task_id, **_safe_payload(payload)})
    return task.copy()


def update_task(
    task_id: str,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    message: Optional[str] = None,
    progress: Optional[dict] = None,
    agent_id: Optional[str] = None,
    payload: Optional[dict] = None,
) -> dict:
    _load_tasks()
    task = _tasks.get(task_id)
    if not task:
        task = start_task(agent_id or "data", "ad_hoc", f"恢复外部任务 {task_id}", task_id=task_id)
    if status:
        task["status"] = status
    if stage:
        task["stage"] = stage
    if message:
        task["message"] = message
    if progress is not None:
        task["progress"] = _safe_payload(progress)
    if payload is not None:
        merged = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        merged.update(_safe_payload(payload))
        task["payload"] = merged
    task["updated_at"] = _iso()
    _tasks[task_id] = task
    _persist_tasks()
    return task.copy()


def finish_task(task_id: str, status: str = "done", message: Optional[str] = None, result: Optional[dict] = None, error: Optional[str] = None) -> dict:
    _load_tasks()
    task = _tasks.get(task_id)
    if not task:
        task = start_task("data", "ad_hoc", f"完成外部任务 {task_id}", task_id=task_id)
    task["status"] = status
    task["stage"] = status
    task["message"] = message or task.get("message") or status
    task["result"] = _safe_payload(result)
    task["error"] = error
    task["finished_at"] = _iso()
    task["updated_at"] = task["finished_at"]
    _tasks[task_id] = task
    _persist_tasks()
    level = "error" if status == "failed" else ("warn" if status in {"blocked", "cancelled"} else "info")
    record_event(task.get("agent_id", "data"), f"{task.get('task_type', 'task')}_{status}", task["message"], level=level, payload={"task_id": task_id, "error": error, "result": _safe_payload(result)})
    return task.copy()


def write_artifact(agent_id: str, name: str, payload: dict, task_id: Optional[str] = None) -> str:
    if agent_id not in AGENTS:
        agent_id = "data"
    _ensure_agent_dirs()
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name or "artifact.json")
    if not safe_name.endswith(".json"):
        safe_name += ".json"
    path = os.path.join(_artifact_dir(agent_id), safe_name)
    _write_json(path, _safe_payload(payload))
    if task_id:
        _load_tasks()
        task = _tasks.get(task_id)
        if task is not None:
            artifacts = task.setdefault("artifacts", [])
            if path not in artifacts:
                artifacts.append(path)
            task["updated_at"] = _iso()
            _tasks[task_id] = task
            _persist_tasks()
    return path


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
    if agent_id == "technical":
        results = state_store.get_screening_results()
        support_count = sum(1 for item in results if ((item.get("screening_logic") or {}).get("support_pool") or {}).get("status") == "support_pool")
        return {
            "技术候选": len(results),
            "支撑池": support_count,
            "最近选股秒": _age_seconds(state_store.get_screening_updated_at()),
        }
    if agent_id == "capital":
        sectors = state_store.get_sector_list()
        return {
            "板块数": len(sectors),
            "资金流事件": len(state_store.get_sector_flow_history() if hasattr(state_store, "get_sector_flow_history") else []),
            "主力跟踪": len(state_store.get_screening_results()),
        }
    if agent_id == "sentiment":
        news = state_store.get_news()
        hot_news = [n for n in news if str(n.get("level") or n.get("importance") or "").lower() in {"major", "super_major"}]
        return {
            "情绪事件": len(news),
            "重要事件": len(hot_news),
            "候选温度": len(state_store.get_screening_results()),
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
    if agent_id == "review":
        memory = {}
        try:
            memory = state_store.get_ai_recommendations() or {}
        except Exception:
            memory = {}
        return {
            "复核池": len(memory.get("reviewed_candidates") or []),
            "推荐记录": len(memory.get("recommendations") or []),
            "学习入口": "已接入",
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
    elif agent_id in {"technical", "capital", "sentiment"}:
        has_data = any(v for v in metrics.values() if isinstance(v, (int, float)) and v > 0)
        stale = False
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

    active_task = _active_task_for_agent(agent_id)
    status = _status_level(has_data, blocked=blocked, stale=stale)
    if active_task and status != "blocked":
        status = "running"
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
        "active_task": active_task,
    }


def _active_task_for_agent(agent_id: str) -> Optional[dict]:
    tasks = _load_tasks()
    active = [
        task for task in tasks.values()
        if task.get("agent_id") == agent_id and task.get("status") in {"queued", "running"}
    ]
    active.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    if not active:
        return None
    task = active[0].copy()
    task.pop("result", None)
    return task


def snapshot_all(reason: str = "manual") -> dict:
    """Write each Agent state file for holaOS-style future handoff."""
    _ensure_agent_dirs()
    agents = []
    for agent_id in AGENTS:
        status = _agent_status(agent_id)
        state = {
            "agent": {k: status[k] for k in ("id", "name", "role", "tool_pool", "artifact", "handoff", "guardrail")},
            "status": status["status"],
            "status_text": status["status_text"],
            "metrics": status["metrics"],
            "last_event": status["last_event"],
            "active_task": status.get("active_task"),
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
        "orchestrator": {
            "runtime": "local_agent_orchestrator",
            "production_ready": False,
            "handoff_ready": True,
            "task_count": len(_load_tasks()),
            "active_task_count": len([t for t in _load_tasks().values() if t.get("status") in {"queued", "running"}]),
            "task_store": _tasks_path(),
            "agent_tool_catalog": get_agent_tool_catalog(),
        },
        "agents": agents,
        "pipeline": [
            "数据采集",
            "新闻理解",
            "技术结构",
            "资金归因",
            "情绪周期",
            "评分归因",
            "结构化决策",
            "风控否决",
            "模拟执行",
            "复盘学习",
        ],
        "tasks": get_tasks(limit=20)["tasks"],
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


def get_tasks(agent_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50) -> dict:
    tasks = list(_load_tasks().values())
    if agent_id:
        tasks = [task for task in tasks if task.get("agent_id") == agent_id]
    if status:
        tasks = [task for task in tasks if task.get("status") == status]
    tasks.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    compact = []
    for task in tasks[:limit]:
        row = task.copy()
        if isinstance(row.get("result"), dict):
            row["result_summary"] = {
                k: row["result"].get(k)
                for k in ("count", "signal_count", "recommendations", "error", "message")
                if k in row["result"]
            }
            row.pop("result", None)
        compact.append(row)
    return {"tasks": compact}


def bootstrap_logs():
    if any(_logs.values()):
        return
    record_event("data", "startup", "Agent 工作台已启动，等待行情与股票池刷新。")
    record_event("news", "startup", "新闻 Agent 已就绪，等待事件流刷新。")
    record_event("risk", "startup", "风控 Agent 已就绪，真实交易接口保持关闭。")
    record_event("execution", "startup", "本地编排器已就绪，执行 Agent 默认仅处理模拟盘。")
