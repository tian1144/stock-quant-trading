import json
import os
import secrets
import string
import threading
import time
from datetime import datetime


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AUTH_DIR = os.path.join(BACKEND_ROOT, "data", "auth")
SMS_PATH = os.path.join(AUTH_DIR, "sms_codes.json")
SMS_LOG_PATH = os.path.join(AUTH_DIR, "sms_dev.log")

CODE_TTL_SECONDS = 5 * 60
SEND_INTERVAL_SECONDS = 60
MAX_PHONE_PER_HOUR = 5
MAX_PHONE_PER_DAY = 10
MAX_IP_PER_HOUR = 30
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


def _mask_phone(phone: str) -> str:
    if len(phone) <= 4:
        return "*" * len(phone)
    return f"{phone[:3]}****{phone[-4:]}"


def send_code(phone: str, purpose: str, ip: str = "") -> dict:
    phone = str(phone or "").strip()
    purpose = str(purpose or "general").strip()[:40]
    ip = str(ip or "unknown")[:80]
    if len(phone) < 6 or len(phone) > 20:
        return {"ok": False, "error": "Please enter a valid phone number."}
    with _lock:
        doc = _cleanup(_read_json(SMS_PATH, {"codes": [], "sends": []}))
        now = time.time()
        sends = doc.get("sends", [])
        last = next((s for s in sorted(sends, key=lambda x: x.get("ts", 0), reverse=True) if s.get("phone") == phone and s.get("purpose") == purpose), None)
        if last and now - float(last.get("ts", 0)) < SEND_INTERVAL_SECONDS:
            wait = int(SEND_INTERVAL_SECONDS - (now - float(last.get("ts", 0))))
            return {"ok": False, "error": f"SMS code requests are too frequent. Try again in {wait} seconds.", "retry_after_seconds": wait}
        phone_hour = [s for s in sends if s.get("phone") == phone and _same_hour(float(s.get("ts", 0)))]
        phone_day = [s for s in sends if s.get("phone") == phone and _same_day(float(s.get("ts", 0)))]
        ip_hour = [s for s in sends if s.get("ip") == ip and _same_hour(float(s.get("ts", 0)))]
        pair_hour = [s for s in sends if s.get("phone") == phone and s.get("ip") == ip and _same_hour(float(s.get("ts", 0)))]
        if len(phone_hour) >= MAX_PHONE_PER_HOUR:
            return {"ok": False, "error": "This phone number has requested too many SMS codes in the last hour. Please try later."}
        if len(phone_day) >= MAX_PHONE_PER_DAY:
            return {"ok": False, "error": "This phone number has reached today's SMS code limit."}
        if len(ip_hour) >= MAX_IP_PER_HOUR or len(pair_hour) >= MAX_PAIR_PER_HOUR:
            return {"ok": False, "error": "Too many requests. Anti-abuse protection is active; please try again later."}
        code = _generate_code()
        doc.setdefault("codes", []).append({
            "phone": phone,
            "purpose": purpose,
            "code": code,
            "ip": ip,
            "created_at": _now(),
            "created_ts": now,
            "expires_at": now + CODE_TTL_SECONDS,
            "used_at": None,
            "attempts": 0,
        })
        doc.setdefault("sends", []).append({"phone": phone, "purpose": purpose, "ip": ip, "ts": now, "created_at": _now()})
        _write_json(SMS_PATH, doc)
        _ensure_dir()
        with open(SMS_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{_now()} phone={phone} purpose={purpose} code={code} ip={ip}\n")
    return {
        "ok": True,
        "message": "SMS code has been sent.",
        "phone_masked": _mask_phone(phone),
        "expires_in_seconds": CODE_TTL_SECONDS,
        "retry_after_seconds": SEND_INTERVAL_SECONDS,
        "dev_mode": True,
        "dev_hint": "Development mode: the SMS code is written to backend/data/auth/sms_dev.log. After connecting a real SMS provider, plaintext codes will no longer be returned or logged.",
    }


def verify_code(phone: str, purpose: str, code: str) -> dict:
    phone = str(phone or "").strip()
    purpose = str(purpose or "general").strip()[:40]
    code = str(code or "").strip().upper()
    if not phone or not code:
        return {"ok": False, "error": "Please enter both phone number and SMS code."}
    with _lock:
        doc = _cleanup(_read_json(SMS_PATH, {"codes": [], "sends": []}))
        now = time.time()
        rows = [c for c in doc.get("codes", []) if c.get("phone") == phone and c.get("purpose") == purpose and c.get("used_at") is None]
        row = sorted(rows, key=lambda x: x.get("created_ts", 0), reverse=True)[0] if rows else None
        if not row or row.get("expires_at", 0) <= now:
            _write_json(SMS_PATH, doc)
            return {"ok": False, "error": "SMS code does not exist or has expired."}
        row["attempts"] = int(row.get("attempts") or 0) + 1
        if row["attempts"] > 5:
            row["used_at"] = _now()
            _write_json(SMS_PATH, doc)
            return {"ok": False, "error": "Too many incorrect SMS code attempts. Please request a new code."}
        if row.get("code") != code:
            _write_json(SMS_PATH, doc)
            return {"ok": False, "error": "Incorrect SMS code."}
        row["used_at"] = _now()
        _write_json(SMS_PATH, doc)
    return {"ok": True, "message": "SMS code verified."}
