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
    news_service,
    portfolio_manager,
    risk_manager,
    sector_service,
    state_store,
    stock_screener,
    strategy_memory_service,
)
from app.execution.kill_switch import get_kill_switch_status


BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ai_tasks")
ARTIFACT_DIR = os.path.join(BASE_DIR, "artifacts")
JOBS: dict = {}
JOBS_LOCK = threading.Lock()


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


def classify_task(message: str) -> dict:
    text = str(message or "").strip()
    email_match = re.search(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    top_count_match = re.search(r"([一二三四五六七八九十\d]+)\s*(?:支|只|个)?\s*(?:股票|标的|票)", text)
    target_count = _cn_number(top_count_match.group(1)) if top_count_match else 3
    wants_stock_pick = any(key in text for key in ["最值得投资", "值得投资", "支股票", "只股票", "个股票", "股票推荐", "选出", "挑出", "推荐"]) and any(
        key in text for key in ["股票", "标的", "投资", "买", "关注"]
    )
    wants_report = any(key in text for key in ["报告", "总结", "汇总", "复盘", "PDF", "pdf", "邮件", "邮箱", "发送"])
    wants_send = any(key in text for key in ["邮件", "邮箱", "发送", "发给", "email", "mail"])
    wants_pdf = any(key in text for key in ["PDF", "pdf", "报告", "总结", "汇总", "复盘"])
    if wants_send and email_match and any(key in text for key in ["股票", "投资", "标的", "买入", "关注"]):
        wants_stock_pick = True
    if wants_stock_pick:
        return {
            "task_type": "investment_report",
            "can_execute": True,
            "requires_email": wants_send,
            "email": email_match.group(0) if email_match else "",
            "missing": "email" if wants_send and not email_match else "",
            "title": "自主投研选股报告",
            "target_count": max(1, min(10, target_count or 3)),
        }
    if wants_report or wants_pdf or wants_send:
        return {
            "task_type": "site_report",
            "can_execute": True,
            "requires_email": wants_send,
            "email": email_match.group(0) if email_match else "",
            "missing": "email" if wants_send and not email_match else "",
            "title": "站内信息汇总报告",
            "target_count": max(1, min(10, target_count or 3)),
        }
    return {
        "task_type": "chat",
        "can_execute": False,
        "requires_email": False,
        "email": "",
        "missing": "",
        "title": "",
    }


def _cn_number(text: str) -> int:
    text = str(text or "").strip()
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
        JOBS[job_id] = job

    agent_workspace.start_task(
        "decision",
        "site_ai_executable_task",
        intent.get("title") or "站内AI可执行任务",
        payload={"job_id": job_id, "task_type": intent["task_type"]},
        task_id=job_id,
        related_agents=["data", "news", "technical", "capital", "sentiment", "risk", "review"],
    )
    threading.Thread(target=_run_site_report_task, args=(job_id,), daemon=True).start()
    return {"ok": True, "job": _safe_job(job), "intent": intent}


def get_job(job_id: str) -> dict:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return {"ok": False, "error": "任务不存在或服务已重启。", "job_id": job_id}
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
        JOBS[job_id] = job
    agent_workspace.finish_task(job_id, status="done" if status == "done" else "failed", message=message, result=result, error=error)


def _run_site_report_task(job_id: str):
    try:
        _update_job(job_id, "collecting", "正在收集站内行情、选股、AI推荐、持仓、新闻和风控信息。", 1)
        context = collect_site_context()
        _write_artifact(job_id, "context.json", context)

        _update_job(job_id, "summarizing", "正在调用站内AI生成任务报告摘要。", 2)
        with JOBS_LOCK:
            job_payload = (JOBS.get(job_id, {}).get("payload") or {})
            task_type = JOBS.get(job_id, {}).get("task_type", "site_report")
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


def collect_site_context() -> dict:
    screening = state_store.get_screening_results()[:30]
    if not screening:
        try:
            screening = stock_screener.run_screening(limit=60, return_all=False, strategy="short")[:30]
        except Exception:
            screening = []
    ai_recs = state_store.get_ai_recommendations() or {}
    sectors = []
    try:
        sectors = sector_service.get_sector_rankings()[:12]
    except Exception:
        sectors = []
    sentiment = {}
    try:
        sentiment = news_service.get_market_sentiment()
    except Exception:
        sentiment = {}
    return _json_safe({
        "generated_at": _now(),
        "universe_count": len(state_store.get_stock_universe()),
        "realtime_count": len(state_store.get_all_realtime()),
        "daily_kline_count": len(state_store.get_all_daily_bars()),
        "portfolio": portfolio_manager.get_portfolio_summary(),
        "positions": portfolio_manager.get_position_list()[:20],
        "orders_tail": state_store.get_orders()[-20:],
        "signals": state_store.get_signals()[:30],
        "screening_top": screening,
        "investment_candidates": _build_investment_candidates(screening),
        "ai_recommendations": {
            "summary": ai_recs.get("summary", {}),
            "generated_at": ai_recs.get("generated_at"),
            "recommendations": (ai_recs.get("recommendations") or [])[:20],
            "reviewed_candidates": (ai_recs.get("reviewed_candidates") or [])[:20],
        },
        "sector_rankings": sectors,
        "market_sentiment": sentiment,
        "news": state_store.get_news()[:20],
        "risk_status": risk_manager.get_risk_status(),
        "risk_config": risk_manager.get_risk_config(),
        "kill_switch": get_kill_switch_status(),
        "strategy_memory": strategy_memory_service.get_model_memory_context("deep_analysis"),
        "system_state": state_store.get_system_state(),
    })


def _build_investment_candidates(screening: list) -> list:
    rows = []
    ai_recs = state_store.get_ai_recommendations() or {}
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
    target_count = int(job_payload.get("target_count", 3) or 3)
    user_task = job_payload.get("user_message") or "请汇总站内关键状态。"
    if task_type == "investment_report":
        system_prompt = (
            "你是量化智能猎人的任务型AI投研助手。请根据站内上下文完成用户的投研任务，"
            f"从 investment_candidates 中自主筛出最值得重点关注的 {target_count} 只股票。"
            "如果用户提到今年6月，请按2026年6月这个未来月份做计划，不能假装已经发生。"
            "必须输出：结论名单、每只股票的站内证据、6月关注逻辑、买入前置条件、止损/风控、"
            "不推荐或暂缓理由、下一步执行清单。不要泄露API密钥或本地敏感配置。"
            "所有买卖内容仅供研究和模拟盘参考，不能跳过风控复核。"
        )
    else:
        system_prompt = (
            "你是量化智能猎人的任务型AI助手。请根据站内上下文生成一份可执行投研任务报告，"
            "必须用中文，结构清晰，包含：一页摘要、市场状态、选股和AI推荐、持仓和模拟盘、"
            "新闻/板块/情绪、主要风险、下一步任务清单。不要泄露任何API密钥或本地敏感配置。"
            "涉及交易必须声明这只是研究和模拟盘参考，不能跳过风控复核。"
        )
    user_message = f"用户任务：{user_task}\n请直接完成任务并生成可发送报告正文。"
    answer, meta = ai_model_service.chat_text("industry_report", system_prompt, user_message, context)
    if not meta.get("ok"):
        answer = _fallback_markdown_report(context, meta.get("error", "AI未完成"), target_count=target_count, task_type=task_type)
    markdown = answer.strip()
    if not markdown.startswith("#"):
        markdown = "# 量化智能猎人站内AI任务报告\n\n" + markdown
    return markdown, meta


def _fallback_markdown_report(context: dict, reason: str, target_count: int = 3, task_type: str = "site_report") -> str:
    portfolio = context.get("portfolio") or {}
    risk = context.get("risk_status") or {}
    ai_recs = ((context.get("ai_recommendations") or {}).get("recommendations") or [])
    screening = context.get("screening_top") or []
    title = "量化智能猎人自主投研选股报告" if task_type == "investment_report" else "量化智能猎人站内AI任务报告"
    lines = [
        f"# {title}",
        "",
        f"生成时间：{context.get('generated_at')}",
        f"说明：大模型总结未完成，已使用本地结构化摘要兜底。原因：{reason}",
        "",
        "## 一页摘要",
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
        lines.append("- 当前没有可直接买入的AI推荐。")
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
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

        font_path = _find_chinese_font()
        font_name = "SiteChinese"
        if font_path:
            pdfmetrics.registerFont(TTFont(font_name, font_path))
        else:
            font_name = "Helvetica"
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
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return ""


def send_email_with_attachment(to_email: str, subject: str, body: str, attachment_path: str) -> dict:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "465") or 465)
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", user)
    use_tls = str(os.getenv("SMTP_USE_TLS", "1")).lower() not in {"0", "false", "no"}
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
