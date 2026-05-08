"""
Executable task layer for the built-in site AI assistant.

The assistant intentionally exposes a small allow-list of site tasks.  It can
collect local site state, ask the configured model for a concise summary,
write artifacts, and optionally send mail when SMTP is configured.
"""
import json
import os
import re
import smtplib
import threading
import uuid
from datetime import datetime
from email.message import EmailMessage
from typing import Optional

from app.services import (
    ai_model_service,
    agent_workspace,
    data_fetcher,
    news_service,
    portfolio_manager,
    risk_manager,
    sector_service,
    state_store,
    strategy_memory_service,
)
from app.execution.kill_switch import get_kill_switch_status


BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ai_tasks")
ARTIFACT_DIR = os.path.join(BASE_DIR, "artifacts")
JOBS: dict = {}
JOBS_LOCK = threading.Lock()
JOBS_LOADED = False
JOB_THREADS: set[str] = set()
SITE_TASK_AI_WAIT_SECONDS = 60
SITE_TASK_COLLECT_STEP_SECONDS = 3


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_job(job: dict) -> dict:
    data = dict(job or {})
    payload = dict(data.get("payload") or {})
    if payload.get("email"):
        payload["email"] = _mask_email(payload.get("email"))
    data["payload"] = payload
    return data


def _mask_email(email: str) -> str:
    email = _extract_email(str(email or "")) or str(email or "")
    email = str(email or "")
    if "@" not in email:
        return email
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        return f"{name[:1]}***@{domain}"
    return f"{name[:2]}***@{domain}"


def _json_safe(value):
    try:
        return ai_model_service._json_safe(value)
    except Exception:
        if isinstance(value, dict):
            return {str(k): _json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [_json_safe(v) for v in value]
        return str(value)


def _call_with_timeout(label: str, func, default=None, timeout_seconds: int = SITE_TASK_COLLECT_STEP_SECONDS):
    box = {"done": False, "value": default}

    def runner():
        try:
            box["value"] = func()
        except Exception:
            box["value"] = default
        finally:
            box["done"] = True

    thread = threading.Thread(target=runner, daemon=True, name=f"site-ai-collect-{label}")
    thread.start()
    thread.join(timeout_seconds)
    if not box.get("done"):
        return default
    return box.get("value", default)


def _jobs_path() -> str:
    return os.path.join(BASE_DIR, "jobs.json")


def _smtp_config_path() -> str:
    return os.path.join(BASE_DIR, "smtp_config.json")


def _read_smtp_config() -> dict:
    path = _smtp_config_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_jobs_unlocked():
    global JOBS_LOADED, JOBS
    if JOBS_LOADED:
        return
    path = _jobs_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                rows = json.load(f)
            if isinstance(rows, dict):
                rows = list(rows.values())
            JOBS = {str(item.get("job_id")): item for item in (rows or []) if item.get("job_id")}
        except Exception:
            JOBS = {}
    JOBS_LOADED = True


def _persist_jobs_unlocked():
    os.makedirs(BASE_DIR, exist_ok=True)
    rows = sorted(JOBS.values(), key=lambda x: x.get("updated_at", ""), reverse=True)[:100]
    path = _jobs_path()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _ensure_job_thread(job_id: str):
    with JOBS_LOCK:
        _load_jobs_unlocked()
        job = JOBS.get(job_id)
        if not job or job.get("status") != "running" or job_id in JOB_THREADS:
            return
        JOB_THREADS.add(job_id)
    threading.Thread(target=_run_site_report_task_thread, args=(job_id,), daemon=True).start()


def _run_site_report_task_thread(job_id: str):
    try:
        _run_site_report_task(job_id)
    finally:
        with JOBS_LOCK:
            JOB_THREADS.discard(job_id)


def classify_task(message: str) -> dict:
    llm_intent = _classify_task_with_model(message)
    if llm_intent:
        return llm_intent
    return _classify_task_fallback(message)


def _classify_task_with_model(message: str) -> Optional[dict]:
    text = str(message or "").strip()
    if not text:
        return None
    email = _extract_email(text)
    system_prompt = (
        "你是量化智能猎人的任务规划器。你的工作不是回答用户，而是理解用户这句话要不要触发站内可执行任务。"
        "你必须主动理解语义、上下文和隐含动作，不要只做关键词匹配。"
        "可执行任务只有两类："
        "1) site_report：总结/复盘/整理站内信息、AI交易情况、持仓、风控、新闻、板块、模拟盘、任务状态，并可生成PDF或邮件发送。"
        "2) investment_report：围绕股票/标的/投资/买入/关注/某月机会/推荐若干只股票做投研筛选报告，并可生成PDF或邮件发送。"
        "普通闲聊、概念解释、单纯问功能在哪里、没有要求你执行或整理站内信息的问题，返回 chat。"
        "如果用户给了邮箱，通常表示希望生成内容并发送；如果用户说发我、发过去、邮件、邮箱，也表示需要邮件，但没有邮箱时 missing=email。"
        "如果用户没有明确说PDF，但说报告/总结/复盘/整理/发送，也可以执行任务。"
        "只输出JSON，不要解释。"
    )
    payload = {
        "message": text,
        "extracted_email": email,
        "allowed_task_types": ["chat", "site_report", "investment_report"],
        "current_date": datetime.now().strftime("%Y-%m-%d"),
        "site_capabilities": [
            "读取站内行情、板块、新闻、AI推荐、模拟盘、持仓、交易记录、风控、策略记忆",
            "生成Markdown/PDF报告",
            "使用SMTP发送邮件",
            "围绕站内候选和策略记忆做投研选股报告",
        ],
    }
    schema = """{
  "task_type": "chat|site_report|investment_report",
  "can_execute": true,
  "requires_email": false,
  "email": "",
  "missing": "",
  "title": "简短中文任务标题",
  "target_count": 3,
  "intent_reason": "一句话说明你理解到的真实意图",
  "confidence": 0.0
}"""
    parsed, meta = ai_model_service.chat_json("task_planning", system_prompt, payload, schema)
    if not parsed or not meta.get("ok"):
        return None
    task_type = str(parsed.get("task_type") or "chat").strip()
    if task_type not in {"chat", "site_report", "investment_report"}:
        return None
    confidence = float(parsed.get("confidence") or 0)
    if confidence < 0.55:
        return None
    requires_email = bool(parsed.get("requires_email"))
    model_email = _extract_email(parsed.get("email") or "") or email
    if email:
        model_email = email
        requires_email = True
    if task_type == "chat":
        fallback = _classify_task_fallback(message)
        if fallback.get("can_execute") and (fallback.get("email") or fallback.get("requires_email")):
            fallback["planner"] = "fallback_after_model_chat"
            fallback["model_intent_reason"] = parsed.get("intent_reason") or ""
            return fallback
        return {
            "task_type": "chat",
            "can_execute": False,
            "requires_email": False,
            "email": "",
            "missing": "",
            "title": "",
            "target_count": 3,
            "intent_reason": parsed.get("intent_reason") or "模型判断为普通对话。",
            "confidence": confidence,
            "planner": "model",
        }
    target_count = _coerce_count(parsed.get("target_count"), default=3)
    return {
        "task_type": task_type,
        "can_execute": True,
        "requires_email": requires_email,
        "email": model_email,
        "missing": "email" if requires_email and not model_email else str(parsed.get("missing") or ""),
        "title": str(parsed.get("title") or ("自主投研选股报告" if task_type == "investment_report" else "站内信息汇总报告")),
        "target_count": max(1, min(10, target_count)),
        "intent_reason": parsed.get("intent_reason") or "模型已理解为可执行站内任务。",
        "confidence": confidence,
        "planner": "model",
    }


def _classify_task_fallback(message: str) -> dict:
    """Infer whether a chat message should become an executable site task.

    Fallback only.  The primary path is model-based planning above.
    """
    text = str(message or "").strip()
    compact = re.sub(r"\s+", "", text.lower())
    email = _extract_email(text)
    target_count = _extract_target_count(text)

    delivery_intent = bool(email) or _contains_any(compact, [
        "发邮箱", "发送邮箱", "发到邮箱", "发邮件", "发送邮件", "邮件给", "邮箱发",
        "发给我", "发送给我", "email", "mail",
    ])
    artifact_intent = _contains_any(compact, [
        "pdf", "报告", "研报", "总结", "汇总", "复盘", "整理", "导出", "生成",
        "日报", "周报", "发送", "发给", "发到",
    ])
    site_info_intent = _contains_any(compact, [
        "今天", "今日", "站内", "本网站", "ai", "交易情况", "交易记录", "操作",
        "思路", "持仓", "模拟盘", "风控", "选股", "候选", "推荐池", "复核池",
    ])
    stock_intent = _contains_any(compact, [
        "股票", "个股", "标的", "票", "投资", "买入", "关注", "推荐", "选出",
        "挑出", "值得", "最值得", "六月", "6月", "下个月", "主线", "板块",
    ])
    ranking_intent = _contains_any(compact, [
        "三只", "三支", "3只", "3支", "前3", "前三", "top3", "top", "几只",
        "推荐", "选出", "挑出", "值得投资", "重点关注",
    ])
    review_intent = _contains_any(compact, [
        "交易情况", "交易复盘", "操作复盘", "今天ai", "今日ai", "ai思路",
        "它的思路", "为什么买", "为什么卖", "买入理由", "卖出理由",
    ])

    wants_stock_pick = stock_intent and (ranking_intent or delivery_intent or artifact_intent)
    wants_site_report = artifact_intent or review_intent or delivery_intent

    if wants_stock_pick:
        return {
            "task_type": "investment_report",
            "can_execute": True,
            "requires_email": delivery_intent,
            "email": email,
            "missing": "email" if delivery_intent and not email else "",
            "title": "自主投研选股报告",
            "target_count": max(1, min(10, target_count or 3)),
            "intent_reason": "识别到股票/投资对象，并包含推荐、数量、报告或发送意图。",
        }
    if wants_site_report and (site_info_intent or artifact_intent):
        return {
            "task_type": "site_report",
            "can_execute": True,
            "requires_email": delivery_intent,
            "email": email,
            "missing": "email" if delivery_intent and not email else "",
            "title": "站内信息汇总报告",
            "target_count": max(1, min(10, target_count or 3)),
            "intent_reason": "识别到站内信息、复盘、报告或发送任务。",
        }
    return {
        "task_type": "chat",
        "can_execute": False,
        "requires_email": False,
        "email": "",
        "missing": "",
        "title": "",
        "intent_reason": "未识别到需要执行的站内任务，按普通对话处理。",
    }


def _contains_any(text: str, keys: list[str]) -> bool:
    return any(key.lower() in text for key in keys)


def _extract_email(text: str) -> str:
    match = re.search(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", str(text or ""))
    return match.group(0) if match else ""


def _extract_target_count(text: str) -> int:
    text = str(text or "")
    patterns = [
        r"(?:推荐|选出|挑出|关注|投资)?\s*([一二两三四五六七八九十\d]+)\s*(?:支|只|个)?\s*(?:股票|个股|标的|票)",
        r"(?:top|前)\s*([一二两三四五六七八九十\d]+)",
        r"([一二两三四五六七八九十\d]+)\s*(?:支|只|个)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _cn_number(match.group(1))
    return 3


def _coerce_count(value, default: int = 3) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    return _cn_number(str(value or default))


def _cn_number(text: str) -> int:
    text = str(text or "").strip().lower()
    if text.isdigit():
        return int(text)
    mapping = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if text in mapping:
        return mapping[text]
    if text.startswith("十") and len(text) == 2:
        return 10 + mapping.get(text[1], 0)
    if text.endswith("十") and len(text) == 2:
        return mapping.get(text[0], 1) * 10
    if "十" in text:
        left, right = text.split("十", 1)
        return mapping.get(left, 1) * 10 + mapping.get(right, 0)
    return 3


def start_task(message: str, payload: Optional[dict] = None) -> dict:
    payload = payload or {}
    intent = classify_task(message)
    if not intent.get("can_execute"):
        return {"ok": False, "error": "当前消息更像普通问答，不需要启动执行任务。", "intent": intent}
    if intent.get("missing") == "email":
        return {
            "ok": False,
            "error": "你要发送邮件，但我没有识别到邮箱地址。请在指令里写明收件邮箱。",
            "intent": intent,
        }

    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    job_id = f"site-task-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    job = {
        "job_id": job_id,
        "task_type": intent["task_type"],
        "status": "running",
        "stage": "queued",
        "message": "任务已启动。",
        "created_at": _now(),
        "updated_at": _now(),
        "finished_at": None,
        "payload": {
            "user_message": message,
            "email": intent.get("email", ""),
            "page": payload.get("page"),
            "active_strategy": payload.get("active_strategy"),
            "target_count": intent.get("target_count", 3),
        },
        "progress": {"current": 0, "total": 5},
        "artifacts": [],
        "result": {},
        "error": "",
    }
    with JOBS_LOCK:
        _load_jobs_unlocked()
        JOBS[job_id] = job
        _persist_jobs_unlocked()

    agent_workspace.start_task(
        "decision",
        "site_ai_executable_task",
        intent.get("title") or "站内AI可执行任务",
        payload={"job_id": job_id, "task_type": intent["task_type"]},
        task_id=job_id,
        related_agents=["data", "news", "technical", "capital", "sentiment", "risk", "review"],
    )
    _ensure_job_thread(job_id)
    return {"ok": True, "job": _safe_job(job), "intent": intent}


def get_job(job_id: str) -> dict:
    with JOBS_LOCK:
        _load_jobs_unlocked()
        job = JOBS.get(job_id)
    if not job:
        return {"ok": False, "error": "任务不存在或服务已重启。", "job_id": job_id}
    if job.get("status") == "running":
        _ensure_job_thread(job_id)
        with JOBS_LOCK:
            job = JOBS.get(job_id) or job
    return {"ok": True, "job": _safe_job(job)}


def _update_job(job_id: str, stage: str, message: str, current: int):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["stage"] = stage
        job["message"] = message
        job["updated_at"] = _now()
        job["progress"] = {"current": current, "total": 5}
        JOBS[job_id] = job
        _persist_jobs_unlocked()
    agent_workspace.update_task(job_id, stage=stage, message=message, progress={"current": current, "total": 5})


def _finish_job(job_id: str, status: str, message: str, result: Optional[dict] = None, error: str = ""):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["status"] = status
        job["stage"] = status
        job["message"] = message
        job["finished_at"] = _now()
        job["updated_at"] = job["finished_at"]
        job["result"] = result or {}
        job["error"] = error
        job["progress"] = {"current": 5, "total": 5}
        JOBS[job_id] = job
        _persist_jobs_unlocked()
    agent_workspace.finish_task(job_id, status="done" if status == "done" else "failed", message=message, result=result, error=error)


def _run_site_report_task(job_id: str):
    try:
        with JOBS_LOCK:
            job_payload = (JOBS.get(job_id, {}).get("payload") or {})
            task_type = JOBS.get(job_id, {}).get("task_type", "site_report")
        _update_job(job_id, "planning", "正在理解任务目标、选择站内工具和输出要求。", 1)
        agent_plan = plan_site_task(job_payload, task_type)

        _update_job(job_id, "collecting", "正在按计划收集行情、板块、选股、AI推荐、持仓、新闻和风控信息。", 1)
        context = collect_site_context(agent_plan)
        context["agent_plan"] = agent_plan
        _write_artifact(job_id, "context.json", context)

        _update_job(job_id, "summarizing", "正在按任务目标生成直接回答，并检查是否漏答。", 2)
        markdown, ai_meta = summarize_site_context(context, job_payload, task_type)

        _update_job(job_id, "writing", "正在写入 Markdown 与 PDF 产物。", 3)
        md_path = _write_text_artifact(job_id, "site_report.md", markdown)
        pdf_path = _write_pdf_artifact(job_id, "site_report.pdf", markdown)

        _update_job(job_id, "email", "正在检查是否需要发送邮件。", 4)
        with JOBS_LOCK:
            email = (JOBS.get(job_id, {}).get("payload") or {}).get("email", "")
        mail_result = {"requested": bool(email), "sent": False, "message": "未请求发送邮件。"}
        if email:
            mail_result = send_email_with_attachment(email, "量化智能猎人站内AI任务报告", markdown, pdf_path)

        result = {
            "summary": _extract_brief(markdown),
            "task_type": task_type,
            "markdown_path": md_path,
            "pdf_path": pdf_path,
            "pdf_url": f"/api/v1/ai/tasks/artifact/{job_id}/site_report.pdf",
            "email": mail_result,
            "ai_meta": ai_meta,
        }
        _finish_job(job_id, "done", "站内AI任务已完成。", result=result)
    except Exception as exc:
        _finish_job(job_id, "failed", f"站内AI任务失败：{exc}", error=str(exc))


def plan_site_task(job_payload: dict, task_type: str) -> dict:
    user_message = str((job_payload or {}).get("user_message") or "").strip()
    target_count = int((job_payload or {}).get("target_count") or 3)
    fallback_tools = ["portfolio", "risk", "news"]
    if task_type == "investment_report":
        fallback_tools = ["sectors", "sector_money_flow", "candidate_stocks", "ai_recommendations", "risk", "news"]
    fallback = {
        "objective": user_message or "完成站内AI任务",
        "answer_style": "direct",
        "tools": fallback_tools,
        "required_outputs": ["直接回答用户问题", "原因和证据", "风险和替代方案"],
        "target_count": target_count,
        "no_answer_policy": "不能只拒绝；没有确定答案时给观察条件、次选方案或下一步执行路径。",
        "planner": "fallback",
    }
    system_prompt = (
        "你是站内AI执行任务的规划器。你的工作不是回答用户，而是像真实助手一样理解目标，"
        "决定需要调用哪些站内工具、必须回答哪些点、以及回答风格。不要做关键词触发，要做语义规划。"
        "可用工具只有：sectors, sector_money_flow, candidate_stocks, realtime_quotes, ai_recommendations, "
        "portfolio, orders, news, risk, strategy_memory, pdf, email。"
        "如果用户问板块、资金流、涨得猛、热门方向，必须包含 sectors 和 sector_money_flow。"
        "如果用户问推荐股票、潜力股、买不买，必须包含 candidate_stocks、risk，并要求给原因、条件和次选。"
        "如果用户要求发送或给了邮箱，必须包含 pdf 和 email。"
        "输出必须是JSON。"
    )
    payload = {
        "user_message": user_message,
        "task_type": task_type,
        "target_count": target_count,
        "page": (job_payload or {}).get("page"),
        "active_strategy": (job_payload or {}).get("active_strategy"),
    }
    schema = """{
  "objective": "一句话说明真实目标",
  "answer_style": "direct|report|brief",
  "tools": ["sectors"],
  "required_outputs": ["必须回答的要点"],
  "target_count": 3,
  "no_answer_policy": "没有确定答案时如何给替代方案",
  "self_check": ["回复前检查项"]
}"""
    parsed, meta = ai_model_service.chat_json("task_planning", system_prompt, payload, schema)
    if not parsed or not meta.get("ok"):
        return fallback
    tools = [str(x) for x in (parsed.get("tools") or []) if str(x) in {
        "sectors", "sector_money_flow", "candidate_stocks", "realtime_quotes", "ai_recommendations",
        "portfolio", "orders", "news", "risk", "strategy_memory", "pdf", "email",
    }]
    if not tools:
        tools = fallback_tools
    return {
        "objective": str(parsed.get("objective") or fallback["objective"]),
        "answer_style": str(parsed.get("answer_style") or "direct"),
        "tools": tools,
        "required_outputs": [str(x) for x in (parsed.get("required_outputs") or fallback["required_outputs"])][:10],
        "target_count": max(1, min(10, _coerce_count(parsed.get("target_count"), target_count))),
        "no_answer_policy": str(parsed.get("no_answer_policy") or fallback["no_answer_policy"]),
        "self_check": [str(x) for x in (parsed.get("self_check") or [])][:8],
        "planner": "model",
    }


def collect_site_context(agent_plan: Optional[dict] = None) -> dict:
    agent_plan = agent_plan or {}
    tools = set(agent_plan.get("tools") or [])
    screening = (_call_with_timeout("screening", state_store.get_screening_results, []) or [])[:30]
    screening_source = "cached_screening_results"
    sector_limit = 12 if ("sectors" in tools or "sector_money_flow" in tools or not tools) else 6
    sectors = _collect_sector_rankings_for_task(limit=sector_limit)
    if not screening:
        screening_source = "realtime_cache_fast_sample"
        screening = _call_with_timeout("realtime_sample", lambda: _build_realtime_screening_sample(limit=30), []) or []
    if not screening:
        screening_source = "sector_resource_candidate_sample"
        screening = _build_sector_candidate_sample(sectors, limit=30)
    ai_recs = _call_with_timeout("ai_recommendations", state_store.get_ai_recommendations, {}) or {}
    sentiment = _call_with_timeout("sentiment", news_service.get_market_sentiment, {}) or {}
    stock_universe = _call_with_timeout("stock_universe", state_store.get_stock_universe, []) or []
    realtime = _call_with_timeout("realtime", state_store.get_all_realtime, {}) or {}
    daily_bars = _call_with_timeout("daily_bars", state_store.get_all_daily_bars, {}) or {}
    portfolio = _call_with_timeout("portfolio", portfolio_manager.get_portfolio_summary, {}) or {}
    positions = (_call_with_timeout("positions", portfolio_manager.get_position_list, []) or [])[:20]
    orders = _call_with_timeout("orders", state_store.get_orders, []) or []
    signals = (_call_with_timeout("signals", state_store.get_signals, []) or [])[:30]
    news = (_call_with_timeout("news", state_store.get_news, []) or [])[:20]
    risk_status = _call_with_timeout("risk_status", risk_manager.get_risk_status, {}) or {}
    risk_config = _call_with_timeout("risk_config", risk_manager.get_risk_config, {}) or {}
    kill_switch = _call_with_timeout("kill_switch", get_kill_switch_status, {}) or {}
    strategy_memory = _call_with_timeout("strategy_memory", lambda: strategy_memory_service.get_model_memory_context("deep_analysis"), "") or ""
    system_state = _call_with_timeout("system_state", state_store.get_system_state, {}) or {}
    return _json_safe({
        "generated_at": _now(),
        "universe_count": len(stock_universe),
        "realtime_count": len(realtime),
        "daily_kline_count": len(daily_bars),
        "portfolio": portfolio,
        "positions": positions,
        "orders_tail": orders[-20:],
        "signals": signals,
        "screening_top": screening,
        "screening_source": screening_source,
        "investment_candidates": _build_investment_candidates(screening, ai_recs=ai_recs),
        "ai_recommendations": {
            "summary": ai_recs.get("summary", {}),
            "generated_at": ai_recs.get("generated_at"),
            "recommendations": (ai_recs.get("recommendations") or [])[:20],
            "reviewed_candidates": (ai_recs.get("reviewed_candidates") or [])[:20],
        },
        "sector_rankings": sectors,
        "market_sentiment": sentiment,
        "news": news,
        "risk_status": risk_status,
        "risk_config": risk_config,
        "kill_switch": kill_switch,
        "strategy_memory": strategy_memory,
        "system_state": system_state,
    })


def _collect_sector_rankings_for_task(limit: int = 12) -> list:
    sectors = _call_with_timeout("sector_rankings_cached", sector_service.get_sector_rankings, [], timeout_seconds=8) or []
    if sectors:
        return sectors[:limit]
    _call_with_timeout("sector_refresh", sector_service.refresh_sector_data, [], timeout_seconds=18)
    sectors = _call_with_timeout("sector_rankings_after_refresh", sector_service.get_sector_rankings, [], timeout_seconds=8) or []
    if sectors:
        return sectors[:limit]
    rows = []
    for sector_type in ("industry", "concept"):
        listed = _call_with_timeout(f"sector_list_{sector_type}", lambda t=sector_type: data_fetcher.fetch_sector_list(t), [], timeout_seconds=12) or []
        flows = _call_with_timeout(f"sector_flow_{sector_type}", lambda t=sector_type: data_fetcher.fetch_sector_money_flow(t), [], timeout_seconds=12) or []
        flow_map = {item.get("code"): item for item in flows if item.get("code")}
        for item in listed:
            flow = flow_map.get(item.get("code"), {})
            rows.append({
                **item,
                "main_net_inflow": _to_float(flow.get("main_net_inflow")),
                "main_net_pct": _to_float(flow.get("main_net_pct")),
                "super_large_inflow": _to_float(flow.get("super_large_inflow")),
                "large_inflow": _to_float(flow.get("large_inflow")),
                "flow_direction": "inflow" if _to_float(flow.get("main_net_inflow")) > 0 else "outflow",
                "data_source": f"eastmoney_{sector_type}_direct",
            })
    return sorted(rows, key=lambda x: (_to_float(x.get("main_net_inflow")), _to_float(x.get("pct_change"))), reverse=True)[:limit]


def _build_realtime_screening_sample(limit: int = 30) -> list:
    """Build a quick candidate sample from cached quotes only.

    Site AI tasks run in a background chat flow, so they should not launch a
    full synchronous market-wide screening pass while the user is waiting.
    """
    rows = []
    realtime = state_store.get_all_realtime() or {}
    for code, quote in realtime.items():
        if not isinstance(quote, dict):
            continue
        stock = state_store.get_stock_info(str(code)) or {}
        name = quote.get("name") or stock.get("name") or ""
        price = _to_float(quote.get("price") or quote.get("current_price") or quote.get("close"))
        pct = _to_float(quote.get("pct_change") or quote.get("change_pct") or quote.get("pct_chg"))
        amount = _to_float(quote.get("amount"))
        volume_ratio = _to_float(quote.get("volume_ratio"))
        turnover = _to_float(quote.get("turnover_rate") or quote.get("turnover"))
        if price <= 0:
            continue
        score = 50.0
        score += max(-8.0, min(10.0, pct * 1.2))
        if amount >= 1_000_000_000:
            score += 8
        elif amount >= 300_000_000:
            score += 5
        elif amount >= 80_000_000:
            score += 2
        if 1.0 <= volume_ratio <= 3.5:
            score += 4
        elif volume_ratio > 5:
            score -= 3
        if 1.0 <= turnover <= 8.0:
            score += 3
        elif turnover > 15:
            score -= 4
        rows.append({
            "code": str(code),
            "name": name,
            "score": round(score, 2),
            "final_score": round(score, 2),
            "price": price,
            "pct_change": pct,
            "amount": amount,
            "volume_ratio": volume_ratio,
            "turnover_rate": turnover,
            "reason": f"来自实时行情缓存：涨跌幅 {pct:.2f}%，成交额 {amount:.0f}，量比 {volume_ratio:.2f}，换手 {turnover:.2f}%。",
            "screening_logic": "站内AI任务快速样本，不触发全市场同步筛选。",
        })
    return sorted(rows, key=lambda x: x.get("score", 0), reverse=True)[:limit]


def _build_sector_candidate_sample(sectors: list, limit: int = 30) -> list:
    rows = []
    for sector in (sectors or [])[:6]:
        sector_name = sector.get("name") or ""
        leader_code = str(sector.get("leader_code") or "").strip()
        leader_name = sector.get("leader_name") or ""
        if leader_code:
            rows.append(_sector_candidate_row(leader_code, leader_name, sector, source="板块领涨股"))
        detail = _call_with_timeout(
            f"sector_detail_{sector.get('code')}",
            lambda code=sector.get("code"): data_fetcher.fetch_sector_detail(code),
            [],
            timeout_seconds=10,
        ) or []
        for stock in detail[:4]:
            rows.append(_sector_candidate_row(stock.get("code"), stock.get("name"), sector, stock=stock, source="板块成分股"))
    seen = {}
    for row in rows:
        code = row.get("code")
        if code and (code not in seen or row.get("score", 0) > seen[code].get("score", 0)):
            seen[code] = row
    return sorted(seen.values(), key=lambda x: x.get("score", 0), reverse=True)[:limit]


def _sector_candidate_row(code: str, name: str, sector: dict, stock: Optional[dict] = None, source: str = "板块候选") -> dict:
    stock = stock or {}
    pct = _to_float(stock.get("pct_change"), _to_float(sector.get("leader_pct_change")))
    amount = _to_float(stock.get("amount"))
    volume_ratio = _to_float(stock.get("volume_ratio"))
    sector_pct = _to_float(sector.get("pct_change"))
    main_net = _to_float(sector.get("main_net_inflow"))
    score = 58 + min(14, max(-8, pct * 1.5)) + min(10, max(-4, sector_pct * 1.2))
    if main_net > 0:
        score += min(12, main_net / 1_000_000_000 * 2)
    if amount >= 500_000_000:
        score += 4
    if 1 <= volume_ratio <= 4:
        score += 3
    return _json_safe({
        "code": str(code or ""),
        "name": name or "",
        "score": round(score, 2),
        "final_score": round(score, 2),
        "pct_change": pct,
        "amount": amount,
        "volume_ratio": volume_ratio,
        "reason": (
            f"{source}，所属板块 {sector.get('name', '')} 涨幅 {sector_pct:.2f}%，"
            f"板块主力净流入 {main_net:.0f}，个股涨幅 {pct:.2f}%。"
        ),
        "screening_logic": {
            "sector": {
                "matched": [{
                    "name": sector.get("name"),
                    "pct_change": sector_pct,
                    "main_net_inflow": main_net,
                    "leader_name": sector.get("leader_name"),
                    "leader_pct_change": sector.get("leader_pct_change"),
                }],
                "data_status": "sector_resource_sample",
            }
        },
    })


def _to_float(value) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _build_investment_candidates(screening: list, ai_recs: Optional[dict] = None) -> list:
    rows = []
    ai_recs = ai_recs or {}
    for item in (ai_recs.get("recommendations") or []):
        rows.append(_candidate_row(item, source="AI推荐购买", boost=8))
    for item in (ai_recs.get("reviewed_candidates") or []):
        rows.append(_candidate_row(item, source="AI重点复核池", boost=4))
    for item in screening or []:
        rows.append(_candidate_row(item, source="智能筛选", boost=0))
    seen = {}
    for row in rows:
        code = row.get("code")
        if not code:
            continue
        old = seen.get(code)
        if not old or row.get("rank_score", 0) > old.get("rank_score", 0):
            seen[code] = row
    return sorted(seen.values(), key=lambda x: x.get("rank_score", 0), reverse=True)[:20]


def _candidate_row(item: dict, source: str, boost: float = 0) -> dict:
    detail = item.get("score_detail") if isinstance(item.get("score_detail"), dict) else {}
    scores = [
        item.get("ai_quality_score"),
        item.get("final_score"),
        item.get("score"),
        detail.get("youzi_experience"),
        detail.get("historical_rule"),
    ]
    numeric = [float(v) for v in scores if isinstance(v, (int, float))]
    score = (sum(numeric) / len(numeric)) if numeric else 50.0
    stock = state_store.get_stock_info(str(item.get("code", ""))) or {}
    return _json_safe({
        "code": item.get("code") or item.get("symbol"),
        "name": item.get("name") or stock.get("name"),
        "source": source,
        "rank_score": round(score + boost, 2),
        "final_score": item.get("final_score") or item.get("score"),
        "ai_quality_score": item.get("ai_quality_score"),
        "youzi_experience": detail.get("youzi_experience"),
        "historical_rule": detail.get("historical_rule"),
        "reason": item.get("ai_reason") or item.get("reason") or item.get("conclusion") or item.get("screening_logic"),
        "risk": item.get("risk_level") or item.get("risk"),
    })


def summarize_site_context(context: dict, job_payload: dict, task_type: str) -> tuple[str, dict]:
    plan = context.get("agent_plan") or {}
    target_count = int(plan.get("target_count") or job_payload.get("target_count", 3) or 3)
    user_task = job_payload.get("user_message") or "请汇总站内关键状态。"
    plan_brief = {
        "objective": plan.get("objective"),
        "answer_style": plan.get("answer_style"),
        "tools": plan.get("tools"),
        "required_outputs": plan.get("required_outputs"),
        "no_answer_policy": plan.get("no_answer_policy"),
        "self_check": plan.get("self_check"),
    }
    if task_type == "investment_report":
        system_prompt = (
            "你是量化智能猎人的任务型AI投研助手。请根据站内上下文完成用户的投研任务，"
            "你必须先遵守 agent_plan：按 objective 作答，覆盖 required_outputs，使用 tools 对应数据证据。"
            f"从 investment_candidates 中自主筛出最值得重点关注的 {target_count} 只股票。"
            "必须按用户问题直接作答，不要先套一页摘要模板；用户问板块就先回答板块，问股票就直接给股票。"
            "如果用户问当前哪些板块涨得疯狂或资金进入较大，必须使用 sector_rankings 输出3个强势板块，写清涨幅、主力净流入、龙头股和入手条件。"
            "如果用户提到今年6月，请按2026年6月这个未来月份做计划，不能假装已经发生。"
            "必须输出：结论名单、每只股票的站内证据、6月关注逻辑、买入前置条件、止损/风控、"
            "不推荐或暂缓理由、下一步执行清单。不要泄露API密钥或本地敏感配置。"
            "禁止只说没有推荐或直接拒绝。若确实没有值得直接买入的标的，必须写明“暂时不推荐购买”，"
            f"并继续给出 {target_count} 只次选观察/被迫购买时的小仓方案，说明为什么只能作为次选、触发条件、仓位上限和止损。"
            "所有买卖内容仅供研究和模拟盘参考，不能跳过风控复核。"
        )
    else:
        system_prompt = (
            "你是量化智能猎人的任务型AI助手。请根据站内上下文生成一份可执行投研任务报告，"
            "你必须先遵守 agent_plan：按 objective 作答，覆盖 required_outputs，使用 tools 对应数据证据。"
            "必须按用户问题直接作答，不要套固定摘要模板；问什么答什么，并带上原因、证据和下一步方案。"
            "必须用中文，结构清晰，包含：一页摘要、市场状态、选股和AI推荐、持仓和模拟盘、"
            "新闻/板块/情绪、主要风险、下一步任务清单。不要泄露任何API密钥或本地敏感配置。"
            "不要只拒绝用户请求；如果当前没有确定答案，必须说明暂不建议直接执行，并给出可执行的替代方案、观察条件或自选方案。"
            "涉及交易必须声明这只是研究和模拟盘参考，不能跳过风控复核。"
        )
    user_message = (
        f"用户任务：{user_task}\n"
        f"agent_plan：{json.dumps(plan_brief, ensure_ascii=False)}\n"
        "请直接完成任务并生成可发送报告正文。最后自检：用户问到的每个点是否都回答了；如果没有数据，要写已尝试的资源和替代方案。"
    )
    answer, meta = _chat_text_with_task_timeout("industry_report", system_prompt, user_message, context)
    if not meta.get("ok"):
        answer = _fallback_markdown_report(context, meta.get("error", "AI未完成"), target_count=target_count, task_type=task_type)
    markdown = answer.strip()
    if not markdown.startswith("#"):
        markdown = "# 量化智能猎人站内AI任务报告\n\n" + markdown
    markdown = verify_site_task_answer(markdown, context, job_payload, task_type)
    return markdown, meta


def verify_site_task_answer(markdown: str, context: dict, job_payload: dict, task_type: str) -> str:
    plan = context.get("agent_plan") or {}
    required = " ".join(plan.get("required_outputs") or [])
    user_task = str((job_payload or {}).get("user_message") or "")
    text = markdown or ""
    additions = []
    need_sector = ("板块" in required or "板块" in user_task or "资金流" in user_task) and "## 当前强势板块" not in text
    if need_sector:
        sectors = context.get("sector_rankings") or []
        additions.append("## 当前强势板块")
        if sectors:
            for item in sectors[:3]:
                additions.append(
                    f"- {item.get('name', '')}：涨幅 {_to_float(item.get('pct_change')):.2f}%，"
                    f"主力净流入 {_to_float(item.get('main_net_inflow')):.0f}，"
                    f"龙头 {item.get('leader_name') or '--'} {_to_float(item.get('leader_pct_change')):.2f}%。"
                )
        else:
            additions.append("- 已尝试读取/刷新板块资源，但当前未拿到有效板块榜单；建议稍后重试或先刷新板块资金流。")
    need_alt = ("暂时不推荐购买" not in text and "没有可直接买入" in text) or ("次选" in required and "次选" not in text)
    if task_type == "investment_report" and need_alt:
        candidates = context.get("investment_candidates") or []
        additions.append("## 次选方案")
        additions.append("- 暂时不推荐直接购买；如果必须参与，只能按观察/小仓试单处理。")
        for item in candidates[: int(plan.get("target_count") or 3)]:
            additions.append(
                f"- {item.get('code')} {item.get('name', '')}：综合排序 {item.get('rank_score')}，"
                f"理由：{item.get('reason', '')}。条件：板块资金继续净流入、个股不破关键支撑、风控未触发。"
            )
    if additions:
        return (text.rstrip() + "\n\n" + "\n".join(additions)).strip()
    return text


def _chat_text_with_task_timeout(task_key: str, system_prompt: str, user_message: str, context: dict) -> tuple[str, dict]:
    box = {"done": False, "answer": "", "meta": {}}

    def runner():
        try:
            answer, meta = ai_model_service.chat_text(task_key, system_prompt, user_message, context)
            box.update({"done": True, "answer": answer, "meta": meta})
        except Exception as exc:
            box.update({"done": True, "answer": "", "meta": {"ok": False, "used_ai": False, "error": str(exc)}})

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(SITE_TASK_AI_WAIT_SECONDS)
    if not box.get("done"):
        return "", {
            "ok": False,
            "used_ai": False,
            "task_key": task_key,
            "error": f"站内任务报告AI总结超过 {SITE_TASK_AI_WAIT_SECONDS} 秒，已改用本地结构化报告兜底。",
            "timeout_seconds": SITE_TASK_AI_WAIT_SECONDS,
        }
    return box.get("answer") or "", box.get("meta") or {}


def _fallback_markdown_report(context: dict, reason: str, target_count: int = 3, task_type: str = "site_report") -> str:
    portfolio = context.get("portfolio") or {}
    risk = context.get("risk_status") or {}
    ai_recs = ((context.get("ai_recommendations") or {}).get("recommendations") or [])
    screening = context.get("screening_top") or []
    sectors = context.get("sector_rankings") or []
    title = "量化智能猎人自主投研选股报告" if task_type == "investment_report" else "量化智能猎人站内AI任务报告"
    if task_type == "investment_report":
        lines = [
            f"# {title}",
            "",
            f"生成时间：{context.get('generated_at')}",
            f"说明：大模型总结未完成，已使用站内数据和外部行情资源兜底。原因：{reason}",
            "",
            "## 当前强势板块",
        ]
        if sectors:
            for item in sectors[:3]:
                lines.append(
                    f"- {item.get('name', '')}：涨幅 {_to_float(item.get('pct_change')):.2f}%，"
                    f"主力净流入 {_to_float(item.get('main_net_inflow')):.0f}，"
                    f"龙头 {item.get('leader_name') or '--'} {_to_float(item.get('leader_pct_change')):.2f}%。"
                    "入手条件：板块资金继续净流入、龙头不炸板/不破分时均线、跟风股不大面积回落。"
                )
        else:
            lines.append("- 当前没有拿到有效板块榜单。建议先刷新板块资金流；系统会优先尝试东方财富板块接口，后续可继续补腾讯证券资源。")
        lines.extend(["", "## 3只股票建议"])
    else:
        lines = [
            f"# {title}",
            "",
            f"生成时间：{context.get('generated_at')}",
            f"说明：大模型总结未完成，已使用本地结构化摘要兜底。原因：{reason}",
            "",
            "## 直接回答",
            f"- 股票池：{context.get('universe_count', 0)} 只，实时缓存：{context.get('realtime_count', 0)} 只，K线缓存：{context.get('daily_kline_count', 0)} 只。",
            f"- 账户总资产：{portfolio.get('total_asset', 0)}，可用资金：{portfolio.get('available_cash', 0)}，总收益率：{portfolio.get('total_profit_pct', 0)}%。",
            f"- 当前持仓：{len(context.get('positions') or [])} 只，AI推荐购买：{len(ai_recs)} 只，智能筛选Top样本：{len(screening)} 只。",
            f"- 风控状态：{risk.get('risk_level', risk.get('status', 'unknown'))}，熔断：{(context.get('kill_switch') or {}).get('active')}",
            "",
            "## AI推荐与筛选",
        ]
    candidates = context.get("investment_candidates") or []
    if task_type == "investment_report":
        lines.append(f"本地兜底筛选出的前 {target_count} 只重点关注股票：")
        for item in candidates[:target_count]:
            lines.append(f"- {item.get('code')} {item.get('name', '')}：综合排序 {item.get('rank_score')}，来源 {item.get('source')}，理由：{item.get('reason', '')}")
    for item in ai_recs[:8]:
        lines.append(f"- {item.get('code')} {item.get('name', '')}：{item.get('ai_reason') or item.get('reason') or item.get('conclusion', '')}")
    if not ai_recs:
        lines.append("- 当前没有可直接买入的AI推荐，暂时不推荐购买。")
        alt_count = max(1, target_count)
        if candidates:
            lines.append(f"- 如果用户仍然需要一个次选方案，只建议从下面 {alt_count} 只里小仓观察，不能按强买信号处理：")
            for item in candidates[:alt_count]:
                lines.append(
                    f"  - {item.get('code')} {item.get('name', '')}：综合排序 {item.get('rank_score')}，"
                    f"来源 {item.get('source')}。次选理由：{item.get('reason', '')}。"
                    "执行条件：交易时段刷新行情和资金流后仍保持强势，且风控未触发；仓位建议不超过模拟盘单票上限的三分之一，跌破关键支撑立即止损。"
                )
        else:
            lines.append("- 当前连次选股票池也不足。建议先添加自选股或运行智能筛选，等系统生成重点复核池后，再从自选/复核池里给出3只备选。")
    lines.extend([
        "",
        "## 下一步任务",
        "- 若处于交易时段，先刷新行情和资金流，再运行智能筛选后台任务。",
        "- 对AI推荐股逐只查看详情、评分卡和风控复核。",
        "- 模拟盘执行前确认仓位上限、止损价和熔断状态。",
        "",
        "免责声明：本报告仅用于研究和模拟盘参考，不构成真实交易建议。",
    ])
    return "\n".join(lines)


def _extract_brief(markdown: str) -> str:
    text = re.sub(r"[#*_>`-]+", "", markdown or "").strip()
    text = re.sub(r"\n{2,}", "\n", text)
    return text[:700]


def _artifact_path(job_id: str, filename: str) -> str:
    safe_job = re.sub(r"[^A-Za-z0-9_.-]+", "_", job_id)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename)
    path = os.path.join(ARTIFACT_DIR, safe_job)
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, safe_name)


def _remember_artifact(job_id: str, path: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is not None and path not in job["artifacts"]:
            job["artifacts"].append(path)
            JOBS[job_id] = job


def _write_artifact(job_id: str, filename: str, payload: dict) -> str:
    path = _artifact_path(job_id, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _remember_artifact(job_id, path)
    return path


def _write_text_artifact(job_id: str, filename: str, text: str) -> str:
    path = _artifact_path(job_id, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text or "")
    _remember_artifact(job_id, path)
    return path


def _write_pdf_artifact(job_id: str, filename: str, markdown: str) -> str:
    path = _artifact_path(job_id, filename)
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        font_path = _find_chinese_font()
        if font_path:
            font_name = "SiteChinese"
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        else:
            font_name = "STSong-Light"
            pdfmetrics.registerFont(UnicodeCIDFont(font_name))
        styles = getSampleStyleSheet()
        normal = ParagraphStyle("cn-normal", parent=styles["BodyText"], fontName=font_name, fontSize=10.5, leading=16, spaceAfter=6)
        h1 = ParagraphStyle("cn-h1", parent=styles["Heading1"], fontName=font_name, fontSize=18, leading=24, spaceAfter=10)
        h2 = ParagraphStyle("cn-h2", parent=styles["Heading2"], fontName=font_name, fontSize=14, leading=20, spaceBefore=8, spaceAfter=8)
        story = []
        for raw in (markdown or "").splitlines():
            line = raw.strip()
            if not line:
                story.append(Spacer(1, 4))
                continue
            style = normal
            if line.startswith("# "):
                line = line[2:].strip()
                style = h1
            elif line.startswith("## "):
                line = line[3:].strip()
                style = h2
            elif line.startswith("- "):
                line = "• " + line[2:].strip()
            story.append(Paragraph(_escape_pdf_text(line), style))
        doc = SimpleDocTemplate(path, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm, topMargin=18 * mm, bottomMargin=18 * mm)
        doc.build(story)
    except Exception:
        # Keep a deterministic artifact even if PDF rendering dependencies fail.
        with open(path, "wb") as f:
            f.write(b"%PDF-1.4\n% Site report PDF generation failed; see Markdown artifact.\n%%EOF\n")
    _remember_artifact(job_id, path)
    return path


def _escape_pdf_text(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _find_chinese_font() -> str:
    candidates = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simfang.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/arphic/uming.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def send_email_with_attachment(to_email: str, subject: str, body: str, attachment_path: str) -> dict:
    original_to_email = str(to_email or "")
    to_email = _extract_email(original_to_email)
    if not to_email:
        return {
            "requested": True,
            "sent": False,
            "message": "PDF已生成，但没有识别到有效收件邮箱。请检查邮箱地址。",
        }
    smtp_config = _read_smtp_config()
    host = os.getenv("SMTP_HOST", "") or str(smtp_config.get("host") or "")
    port = int(os.getenv("SMTP_PORT", "") or smtp_config.get("port") or 465)
    user = os.getenv("SMTP_USER", "") or str(smtp_config.get("user") or "")
    password = os.getenv("SMTP_PASSWORD", "") or str(smtp_config.get("password") or "")
    sender = os.getenv("SMTP_FROM", "") or str(smtp_config.get("sender") or user)
    use_tls = str(os.getenv("SMTP_USE_TLS", "") or smtp_config.get("use_tls", "1")).lower() not in {"0", "false", "no"}
    if not (host and user and password and sender):
        return {
            "requested": True,
            "sent": False,
            "message": "PDF已生成，但SMTP_HOST/SMTP_USER/SMTP_PASSWORD/SMTP_FROM未配置，未发送邮件。",
        }
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.set_content((body or "")[:4000])
    with open(attachment_path, "rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(attachment_path))
    try:
        if use_tls:
            with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                smtp.starttls()
                smtp.login(user, password)
                smtp.send_message(msg)
        return {"requested": True, "sent": True, "message": f"已发送到 {_mask_email(to_email)}。"}
    except smtplib.SMTPRecipientsRefused:
        return {
            "requested": True,
            "sent": False,
            "message": f"PDF已生成，但收件邮箱 {_mask_email(to_email)} 被邮件服务器拒收。请检查邮箱地址是否存在、是否拼写正确。",
        }
    except smtplib.SMTPAuthenticationError:
        return {
            "requested": True,
            "sent": False,
            "message": "PDF已生成，但发件邮箱认证失败。请检查SMTP授权码是否过期或被重置。",
        }
    except smtplib.SMTPException as exc:
        return {
            "requested": True,
            "sent": False,
            "message": f"PDF已生成，但邮件发送失败：{_friendly_smtp_error(exc)}",
        }
    except Exception as exc:
        return {
            "requested": True,
            "sent": False,
            "message": f"PDF已生成，但邮件发送异常：{_friendly_smtp_error(exc)}",
        }


def _friendly_smtp_error(exc: Exception) -> str:
    text = str(exc or "")
    lowered = text.lower()
    if "recipient may contain a non-existent account" in lowered or "recipient" in lowered and "non-existent" in lowered:
        return "收件邮箱可能不存在，请检查邮箱地址。"
    if "authentication" in lowered or "auth" in lowered:
        return "发件邮箱认证失败，请检查SMTP授权码。"
    if "timed out" in lowered or "timeout" in lowered:
        return "连接邮件服务器超时，请稍后重试。"
    if "connection" in lowered:
        return "连接邮件服务器失败，请检查网络或SMTP配置。"
    return text[:180] or "未知邮件错误。"
