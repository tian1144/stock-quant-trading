import json
import os
import smtplib
import ssl
import secrets
import string
import threading
import time
from datetime import datetime
from email.message import EmailMessage


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AUTH_DIR = os.path.join(BACKEND_ROOT, "data", "auth")
EMAIL_CODES_PATH = os.path.join(AUTH_DIR, "email_codes.json")
EMAIL_CONFIG_PATH = os.path.join(AUTH_DIR, "email_config.json")
EMAIL_LOG_PATH = os.path.join(AUTH_DIR, "email_dev.log")

CODE_TTL_SECONDS = 5 * 60
SEND_INTERVAL_SECONDS = 60
MAX_EMAIL_PER_HOUR = 5
MAX_EMAIL_PER_DAY = 10
MAX_IP_PER_HOUR = 40
MAX_PAIR_PER_HOUR = 3

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dir():
    os.makedirs(AUTH_DIR, exist_ok=True)


def _read_json(path: str, default):
    _ensure_dir()
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path: str, data):
    _ensure_dir()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def _cleanup(doc: dict) -> dict:
    now = time.time()
    cutoff_day = now - 86400
    doc["codes"] = [c for c in doc.get("codes", []) if c.get("expires_at", 0) > now and c.get("used_at") is None]
    doc["sends"] = [s for s in doc.get("sends", []) if s.get("ts", 0) > cutoff_day]
    return doc


def _generate_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _same_hour(ts: float) -> bool:
    return ts > time.time() - 3600


def _same_day(ts: float) -> bool:
    return ts > time.time() - 86400


def _mask_email(email: str) -> str:
    email = str(email or "")
    if "@" not in email:
        return "***"
    name, domain = email.split("@", 1)
    if len(name) <= 2:
        masked = name[:1] + "***"
    else:
        masked = name[:2] + "***" + name[-1:]
    return f"{masked}@{domain}"


def _valid_email(email: str) -> bool:
    email = str(email or "").strip()
    return 5 <= len(email) <= 120 and "@" in email and "." in email.rsplit("@", 1)[-1]


def save_config(sender_email: str, auth_code: str, sender_name: str = "账号邮箱") -> dict:
    config = {
        "enabled": True,
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "sender_email": str(sender_email or "").strip(),
        "sender_name": str(sender_name or "账号邮箱").strip(),
        "auth_code": str(auth_code or "").strip(),
        "updated_at": _now(),
    }
    _write_json(EMAIL_CONFIG_PATH, config)
    return get_public_config()


def get_config() -> dict:
    config = _read_json(EMAIL_CONFIG_PATH, {})
    sender_email = str(os.getenv("EMAIL_SENDER") or config.get("sender_email") or "").strip()
    auth_code = str(os.getenv("EMAIL_AUTH_CODE") or config.get("auth_code") or "").strip()
    return {
        "enabled": bool(config.get("enabled", True) and sender_email and auth_code),
        "smtp_host": str(os.getenv("EMAIL_SMTP_HOST") or config.get("smtp_host") or "smtp.qq.com").strip(),
        "smtp_port": int(os.getenv("EMAIL_SMTP_PORT") or config.get("smtp_port") or 465),
        "sender_email": sender_email,
        "sender_name": str(config.get("sender_name") or "账号邮箱").strip(),
        "auth_code": auth_code,
    }


def get_public_config() -> dict:
    cfg = get_config()
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled")),
        "sender_masked": _mask_email(cfg.get("sender_email") or ""),
    }


def _send_email(to_email: str, code: str, purpose: str) -> dict:
    cfg = get_config()
    if not cfg.get("enabled"):
        return {"ok": False, "error": "邮箱发送器未配置。"}
    msg = EmailMessage()
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender_email']}>"
    msg["To"] = to_email
    msg["Subject"] = "验证码"
    msg.set_content(
        "\n".join([
            f"验证码：{code}",
            "",
            "验证码 5 分钟内有效，请勿泄露给他人。",
            f"用途：{purpose}",
        ])
    )
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], context=context, timeout=15) as smtp:
            smtp.login(cfg["sender_email"], cfg["auth_code"])
            smtp.send_message(msg)
    except Exception as exc:
        return {"ok": False, "error": f"邮箱验证码发送失败：{exc}"}
    return {"ok": True}


def send_code(email: str, purpose: str, ip: str = "", phone: str = "") -> dict:
    email = str(email or "").strip().lower()
    purpose = str(purpose or "general").strip()[:40]
    ip = str(ip or "unknown")[:80]
    phone = str(phone or "").strip()[:40]
    if not _valid_email(email):
        return {"ok": False, "error": "请输入有效的邮箱地址。"}
    with _lock:
        doc = _cleanup(_read_json(EMAIL_CODES_PATH, {"codes": [], "sends": []}))
        now = time.time()
        sends = doc.get("sends", [])
        last = next((s for s in sorted(sends, key=lambda x: x.get("ts", 0), reverse=True) if s.get("email") == email and s.get("purpose") == purpose), None)
        if last and now - float(last.get("ts", 0)) < SEND_INTERVAL_SECONDS:
            wait = int(SEND_INTERVAL_SECONDS - (now - float(last.get("ts", 0))))
            return {"ok": False, "error": f"邮箱验证码发送过于频繁，请 {wait} 秒后再试。", "retry_after_seconds": wait}
        email_hour = [s for s in sends if s.get("email") == email and _same_hour(float(s.get("ts", 0)))]
        email_day = [s for s in sends if s.get("email") == email and _same_day(float(s.get("ts", 0)))]
        ip_hour = [s for s in sends if s.get("ip") == ip and _same_hour(float(s.get("ts", 0)))]
        pair_hour = [s for s in sends if s.get("email") == email and s.get("ip") == ip and _same_hour(float(s.get("ts", 0)))]
        if len(email_hour) >= MAX_EMAIL_PER_HOUR:
            return {"ok": False, "error": "该邮箱在一小时内请求验证码过多，请稍后再试。"}
        if len(email_day) >= MAX_EMAIL_PER_DAY:
            return {"ok": False, "error": "该邮箱今日验证码次数已达上限。"}
        if len(ip_hour) >= MAX_IP_PER_HOUR or len(pair_hour) >= MAX_PAIR_PER_HOUR:
            return {"ok": False, "error": "请求过于频繁，已触发防刷保护，请稍后再试。"}
        code = _generate_code()
        sent = _send_email(email, code, purpose)
        if not sent.get("ok"):
            return sent
        doc.setdefault("codes", []).append({
            "email": email,
            "purpose": purpose,
            "code": code,
            "phone": phone,
            "ip": ip,
            "created_at": _now(),
            "created_ts": now,
            "expires_at": now + CODE_TTL_SECONDS,
            "used_at": None,
            "attempts": 0,
        })
        doc.setdefault("sends", []).append({"email": email, "purpose": purpose, "phone": phone, "ip": ip, "ts": now, "created_at": _now()})
        _write_json(EMAIL_CODES_PATH, doc)
        with open(EMAIL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{_now()} email={email} purpose={purpose} phone={phone} ip={ip}\n")
    return {
        "ok": True,
        "message": "邮箱验证码已发送。",
        "email_masked": _mask_email(email),
        "expires_in_seconds": CODE_TTL_SECONDS,
        "retry_after_seconds": SEND_INTERVAL_SECONDS,
        "dev_mode": True,
        "dev_hint": "开发模式下，验证码已写入 backend/data/auth/email_dev.log。",
    }


def verify_code(email: str, purpose: str, code: str) -> dict:
    email = str(email or "").strip().lower()
    purpose = str(purpose or "general").strip()[:40]
    code = str(code or "").strip().upper()
    if not email or not code:
        return {"ok": False, "error": "请输入邮箱和验证码。"}
    with _lock:
        doc = _cleanup(_read_json(EMAIL_CODES_PATH, {"codes": [], "sends": []}))
        now = time.time()
        rows = [c for c in doc.get("codes", []) if c.get("email") == email and c.get("purpose") == purpose and c.get("used_at") is None]
        row = sorted(rows, key=lambda x: x.get("created_ts", 0), reverse=True)[0] if rows else None
        if not row or row.get("expires_at", 0) <= now:
            _write_json(EMAIL_CODES_PATH, doc)
            return {"ok": False, "error": "验证码不存在或已过期。"}
        row["attempts"] = int(row.get("attempts") or 0) + 1
        if row["attempts"] > 5:
            row["used_at"] = _now()
            _write_json(EMAIL_CODES_PATH, doc)
            return {"ok": False, "error": "验证码错误次数过多，请重新获取验证码。"}
        if row.get("code") != code:
            _write_json(EMAIL_CODES_PATH, doc)
            return {"ok": False, "error": "验证码错误。"}
        row["used_at"] = _now()
        _write_json(EMAIL_CODES_PATH, doc)
    return {"ok": True, "message": "验证码验证通过。"}
