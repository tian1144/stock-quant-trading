"""Feishu/Lark bot integration for database-grounded customer-service AI."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

import requests

from app.services import feishu_answer_service, knowledge_base_service


FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
_token_cache = {"token": "", "expires_at": 0.0}
_token_lock = threading.RLock()


def config_public() -> dict:
    return {
        "enabled": bool(os.getenv("FEISHU_APP_ID") and os.getenv("FEISHU_APP_SECRET") and os.getenv("FEISHU_VERIFICATION_TOKEN")),
        "has_app_id": bool(os.getenv("FEISHU_APP_ID")),
        "has_app_secret": bool(os.getenv("FEISHU_APP_SECRET")),
        "has_verification_token": bool(os.getenv("FEISHU_VERIFICATION_TOKEN")),
        "has_encrypt_key": bool(os.getenv("FEISHU_ENCRYPT_KEY")),
    }


def _verify_token(payload: dict) -> bool:
    expected = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
    if not expected:
        return False
    token = payload.get("token") or ((payload.get("header") or {}).get("token"))
    return token == expected


def _tenant_access_token() -> str:
    now = time.time()
    with _token_lock:
        if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
            return _token_cache["token"]
        app_id = os.getenv("FEISHU_APP_ID", "")
        app_secret = os.getenv("FEISHU_APP_SECRET", "")
        if not app_id or not app_secret:
            raise RuntimeError("飞书机器人 APP_ID/APP_SECRET 未配置")
        res = requests.post(
            f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": app_id, "app_secret": app_secret},
            timeout=12,
        )
        data = res.json()
        token = data.get("tenant_access_token")
        if not token:
            raise RuntimeError(data.get("msg") or "飞书 tenant_access_token 获取失败")
        _token_cache["token"] = token
        _token_cache["expires_at"] = now + int(data.get("expire") or 7200)
        return token


def _extract_text(message: dict) -> str:
    raw = message.get("content") or ""
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        text = parsed.get("text") if isinstance(parsed, dict) else raw
    except Exception:
        text = raw
    text = re.sub(r"@\S+\s*", "", str(text or "")).strip()
    return text


def _should_answer(event: dict) -> bool:
    message = event.get("message") or {}
    chat_type = message.get("chat_type") or ""
    if chat_type == "p2p":
        return True
    mentions = message.get("mentions") or []
    return bool(mentions)


def _event_identity(payload: dict) -> tuple[str, str]:
    header = payload.get("header") or {}
    event = payload.get("event") or {}
    message = event.get("message") or {}
    event_id = header.get("event_id") or message.get("message_id") or ""
    event_type = header.get("event_type") or payload.get("type") or ""
    return str(event_id), str(event_type)


def _send_text(chat_id: str, text: str) -> dict:
    token = _tenant_access_token()
    res = requests.post(
        f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        timeout=15,
    )
    try:
        return res.json()
    except Exception:
        return {"code": res.status_code, "msg": res.text[:300]}


def _handle_message_async(payload: dict) -> None:
    event_id, _ = _event_identity(payload)
    event = payload.get("event") or {}
    message = event.get("message") or {}
    sender = event.get("sender") or {}
    chat_id = message.get("chat_id") or ""
    sender_id = ((sender.get("sender_id") or {}).get("open_id") or "")
    question = _extract_text(message)
    if not chat_id or not question:
        return
    try:
        result = feishu_answer_service.answer_for_feishu(question)
        answer = result.get("answer") or knowledge_base_service.NO_ANSWER_TEXT
        _send_text(chat_id, answer)
        knowledge_base_service.record_feishu_log(
            event_id,
            chat_id=chat_id,
            sender_id=sender_id,
            message_id=message.get("message_id") or "",
            question=question,
            answer=answer,
            matched_item_ids=result.get("matched_item_ids") or [],
            status="answered",
        )
    except Exception as exc:
        knowledge_base_service.record_feishu_log(
            event_id,
            chat_id=chat_id,
            sender_id=sender_id,
            message_id=message.get("message_id") or "",
            question=question,
            answer="",
            matched_item_ids=[],
            status="failed",
            error=str(exc),
        )
        try:
            _send_text(chat_id, "客服 AI 暂时不可用，请稍后再试。")
        except Exception:
            pass


def handle_event(payload: dict[str, Any]) -> dict:
    if payload.get("encrypt"):
        return {"ok": False, "error": "当前尚未启用飞书加密事件解密，请先关闭 Encrypt Key 或补充 FEISHU_ENCRYPT_KEY 解密实现。"}

    if payload.get("type") == "url_verification":
        if not _verify_token(payload):
            return {"ok": False, "error": "飞书 verification token 不匹配。"}
        return {"challenge": payload.get("challenge", "")}

    if not _verify_token(payload):
        return {"ok": False, "error": "飞书 verification token 不匹配。"}

    event_id, event_type = _event_identity(payload)
    if event_id and knowledge_base_service.has_event(event_id):
        return {"ok": True, "duplicate": True}
    if event_type != "im.message.receive_v1":
        return {"ok": True, "ignored": True, "event_type": event_type}
    event = payload.get("event") or {}
    message = event.get("message") or {}
    if message.get("message_type") != "text" or not _should_answer(event):
        return {"ok": True, "ignored": True}

    if event_id:
        knowledge_base_service.record_feishu_log(event_id, status="accepted")
    threading.Thread(target=_handle_message_async, args=(payload,), daemon=True).start()
    return {"ok": True, "accepted": True}
