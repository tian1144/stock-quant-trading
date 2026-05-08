import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime

from app.services import email_code_service, sms_code_service


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AUTH_DIR = os.path.join(BACKEND_ROOT, "data", "auth")
USERS_PATH = os.path.join(AUTH_DIR, "users.json")
SESSIONS_PATH = os.path.join(AUTH_DIR, "sessions.json")

ROLE_SUPER_ADMIN = "super_admin"
ROLE_SUB_ADMIN = "sub_admin"
ROLE_USER = "user"
ROLE_VISITOR = "visitor"

ROLE_LABELS = {
    ROLE_SUPER_ADMIN: "最高管理",
    ROLE_SUB_ADMIN: "次管理",
    ROLE_USER: "普通账号",
    ROLE_VISITOR: "访问账号",
}

ROLE_RANK = {
    ROLE_VISITOR: 0,
    ROLE_USER: 1,
    ROLE_SUB_ADMIN: 2,
    ROLE_SUPER_ADMIN: 3,
}

DEFAULT_USERS = [
    {"phone": "18800000001", "name": "最高管理1", "role": ROLE_SUPER_ADMIN, "password": "Admin@2026!"},
    {"phone": "18800000002", "name": "最高管理2", "role": ROLE_SUPER_ADMIN, "password": "Admin@2026!"},
    {"phone": "123123123", "name": "访问账号", "role": ROLE_VISITOR, "password": "123123@!"},
]

_lock = threading.Lock()

DEFAULT_USERS = [
    {"phone": "18800000001", "name": "Demo Admin 1", "role": ROLE_SUPER_ADMIN, "password": "Admin@2026!"},
    {"phone": "18800000002", "name": "Demo Admin 2", "role": ROLE_SUPER_ADMIN, "password": "Admin@2026!"},
    {"phone": "123123123", "name": "Demo Visitor", "role": ROLE_VISITOR, "password": "Visitor@2026!"},
]


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


def _hash_password(password: str, salt: str | None = None) -> dict:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt.encode("utf-8"), 120000)
    return {"salt": salt, "hash": digest.hex(), "scheme": "pbkdf2_sha256"}


def _verify_password(password: str, password_hash: dict) -> bool:
    if not password_hash:
        return False
    salt = password_hash.get("salt") or ""
    expected = password_hash.get("hash") or ""
    actual = _hash_password(password or "", salt).get("hash")
    return hmac.compare_digest(actual, expected)


def permissions_for_role(role: str) -> dict:
    rank = ROLE_RANK.get(role, 1)
    return {
        "can_view": True,
        "can_trade": rank >= ROLE_RANK[ROLE_USER],
        "can_connect_broker": rank >= ROLE_RANK[ROLE_USER],
        "can_modify_settings": rank >= ROLE_RANK[ROLE_USER],
        "can_modify_sensitive": rank >= ROLE_RANK[ROLE_SUB_ADMIN],
        "can_manage_accounts": rank >= ROLE_RANK[ROLE_SUB_ADMIN],
        "can_promote_sub_admin": rank >= ROLE_RANK[ROLE_SUPER_ADMIN],
        "readonly": role == ROLE_VISITOR,
    }


def _public_user(user: dict) -> dict:
    if not user:
        return {}
    return {
        "user_id": user.get("user_id"),
        "phone": user.get("phone"),
        "email": user.get("email"),
        "account": user.get("account") or user.get("phone"),
        "phone_bound": bool(user.get("phone_bound") or user.get("phone_verified")),
        "phone_verified": bool(user.get("phone_verified")),
        "email_bound": bool(user.get("email_bound") or user.get("email_verified")),
        "email_verified": bool(user.get("email_verified")),
        "name": user.get("name") or user.get("phone"),
        "role": user.get("role") or ROLE_USER,
        "role_label": ROLE_LABELS.get(user.get("role"), "普通账号"),
        "status": user.get("status", "active"),
        "invited_by": user.get("invited_by"),
        "created_by": user.get("created_by"),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
        "commission_rate_pct": float(user.get("commission_rate_pct") or 0),
        "commission_reserved": user.get("commission_reserved", {}),
        "permissions": permissions_for_role(user.get("role") or ROLE_USER),
    }


def _normalize_login_value(login_id: str) -> str:
    return str(login_id or "").strip().lower()


def _find_user_by_login(users: list, login_id: str) -> dict | None:
    login_id = _normalize_login_value(login_id)
    if not login_id:
        return None
    for user in users or []:
        if login_id in {
            str(user.get("phone") or "").strip().lower(),
            str(user.get("account") or "").strip().lower(),
            str(user.get("name") or "").strip().lower(),
            str(user.get("email") or "").strip().lower(),
        }:
            return user
    return None


def _find_user_by_email(users: list, email: str) -> dict | None:
    email = _normalize_login_value(email)
    if not email:
        return None
    return next((u for u in users or [] if str(u.get("email") or "").strip().lower() == email), None)


def init_auth_store():
    with _lock:
        users = _read_json(USERS_PATH, {"users": []})
        existing = {u.get("phone"): u for u in users.get("users", [])}
        for seed in DEFAULT_USERS:
            if seed["phone"] in existing:
                row = existing[seed["phone"]]
                row["account"] = row.get("account") or seed["phone"]
                row["phone_bound"] = True
                row["phone_verified"] = True
                row["updated_at"] = row.get("updated_at") or _now()
                continue
            users.setdefault("users", []).append({
                "user_id": secrets.token_hex(8),
                "phone": seed["phone"],
                "name": seed["name"],
                "role": seed["role"],
                "status": "active",
                "password_hash": _hash_password(seed["password"]),
                "phone_bound": True,
                "phone_verified": True,
                "email_bound": False,
                "email_verified": False,
                "invited_by": None,
                "created_by": "system",
                "commission_rate_pct": 0.0,
                "commission_reserved": {
                    "enabled": False,
                    "description": "预留：后续收益抽成接口",
                    "settlement_mode": "profit_after_close",
                },
                "created_at": _now(),
                "updated_at": _now(),
            })
        users["roles"] = ROLE_LABELS
        users["updated_at"] = _now()
        _write_json(USERS_PATH, users)
        if not os.path.exists(SESSIONS_PATH):
            _write_json(SESSIONS_PATH, {"sessions": []})


def list_users(actor: dict) -> dict:
    if not permissions_for_role(actor.get("role")).get("can_manage_accounts"):
        return {"ok": False, "error": "当前账号没有账号管理权限。"}
    users = _read_json(USERS_PATH, {"users": []}).get("users", [])
    return {"ok": True, "users": [_public_user(u) for u in users], "roles": ROLE_LABELS}


def _issue_session(user: dict) -> dict:
    token = secrets.token_urlsafe(32)
    session = {
        "token": token,
        "user_id": user.get("user_id"),
        "phone": user.get("phone"),
        "created_at": _now(),
        "last_seen_at": _now(),
        "expires_at": time.time() + 7 * 86400,
    }
    with _lock:
        sessions = _read_json(SESSIONS_PATH, {"sessions": []})
        sessions["sessions"] = [s for s in sessions.get("sessions", []) if s.get("expires_at", 0) > time.time()]
        sessions["sessions"].append(session)
        _write_json(SESSIONS_PATH, sessions)
    return {"ok": True, "token": token, "user": _public_user(user)}


def authenticate(phone: str, password: str) -> dict:
    init_auth_store()
    users_doc = _read_json(USERS_PATH, {"users": []})
    user = _find_user_by_login(users_doc.get("users", []), phone)
    if not user:
        return {"ok": False, "error": "账号不存在。"}
    if user.get("status") != "active":
        return {"ok": False, "error": "账号已停用。"}
    if not _verify_password(password or "", user.get("password_hash") or {}):
        return {"ok": False, "error": "密码错误。"}
    return _issue_session(user)


def authenticate_by_sms(phone: str, code: str) -> dict:
    init_auth_store()
    users_doc = _read_json(USERS_PATH, {"users": []})
    user = next((u for u in users_doc.get("users", []) if u.get("phone") == str(phone).strip() and u.get("phone_verified")), None)
    if not user or user.get("status") != "active":
        return {"ok": False, "error": "该手机号未绑定可登录账号。"}
    verified = sms_code_service.verify_code(phone, "login", code)
    if not verified.get("ok"):
        return verified
    return _issue_session(user)


def authenticate_by_email(phone: str, code: str) -> dict:
    init_auth_store()
    users_doc = _read_json(USERS_PATH, {"users": []})
    user = _find_user_by_login(users_doc.get("users", []), phone)
    if not user or user.get("status") != "active":
        return {"ok": False, "error": "该账号未绑定可用邮箱。"}
    if not user.get("email_verified") or not user.get("email"):
        return {"ok": False, "error": "该账号未绑定可用邮箱。"}
    verified = email_code_service.verify_code(user.get("email") or "", "login", code)
    if not verified.get("ok"):
        return verified
    return _issue_session(user)


def email_for_login_phone(phone: str) -> dict:
    init_auth_store()
    phone = _normalize_login_value(phone)
    users_doc = _read_json(USERS_PATH, {"users": []})
    user = _find_user_by_login(users_doc.get("users", []), phone)
    if not user or user.get("status") != "active":
        return {"ok": False, "error": "该账号未绑定可用邮箱。"}
    if not user.get("email_verified") or not user.get("email"):
        return {"ok": False, "error": "该账号未绑定可用邮箱。"}
    return {"ok": True, "email": user.get("email"), "user": _public_user(user)}


def email_for_login(login_id: str) -> dict:
    init_auth_store()
    users_doc = _read_json(USERS_PATH, {"users": []})
    user = _find_user_by_login(users_doc.get("users", []), login_id)
    if not user:
        return {"ok": False, "error": "账号不存在。"}
    if user.get("status") != "active":
        return {"ok": False, "error": "账号已停用。"}
    if not user.get("email_verified") or not user.get("email"):
        return {"ok": False, "error": "该账号未绑定可用邮箱。"}
    return {"ok": True, "email": user.get("email"), "user": _public_user(user)}


def authenticate_by_email(login_id: str, code: str) -> dict:
    init_auth_store()
    users_doc = _read_json(USERS_PATH, {"users": []})
    user = _find_user_by_login(users_doc.get("users", []), login_id)
    if not user or user.get("status") != "active":
        return {"ok": False, "error": "该邮箱未绑定可登录账号。"}
    if not user.get("email_verified") or not user.get("email"):
        return {"ok": False, "error": "该邮箱未绑定可登录账号。"}
    verified = email_code_service.verify_code(user.get("email") or "", "login", code)
    if not verified.get("ok"):
        return verified
    return _issue_session(user)


def email_for_login(login_id: str) -> dict:
    init_auth_store()
    users_doc = _read_json(USERS_PATH, {"users": []})
    user = _find_user_by_login(users_doc.get("users", []), login_id)
    if not user:
        return {"ok": False, "error": "该邮箱未绑定可登录账号。"}
    if user.get("status") != "active":
        return {"ok": False, "error": "账号已停用。"}
    if not user.get("email_verified") or not user.get("email"):
        return {"ok": False, "error": "该邮箱未绑定可登录账号。"}
    return {"ok": True, "email": user.get("email"), "user": _public_user(user)}


def get_user_by_token(token: str) -> dict | None:
    if not token:
        return None
    init_auth_store()
    sessions = _read_json(SESSIONS_PATH, {"sessions": []}).get("sessions", [])
    session = next((s for s in sessions if hmac.compare_digest(s.get("token", ""), token)), None)
    if not session or session.get("expires_at", 0) <= time.time():
        return None
    users = _read_json(USERS_PATH, {"users": []}).get("users", [])
    user = next((u for u in users if u.get("user_id") == session.get("user_id")), None)
    if not user or user.get("status") != "active":
        return None
    return _public_user(user)


def logout(token: str) -> dict:
    with _lock:
        sessions = _read_json(SESSIONS_PATH, {"sessions": []})
        sessions["sessions"] = [s for s in sessions.get("sessions", []) if s.get("token") != token]
        _write_json(SESSIONS_PATH, sessions)
    return {"ok": True}


def create_user(actor: dict, payload: dict) -> dict:
    if not permissions_for_role(actor.get("role")).get("can_manage_accounts"):
        return {"ok": False, "error": "只有管理账号才能创建新账号。"}
    phone = str((payload or {}).get("phone") or "").strip()
    password = str((payload or {}).get("password") or "").strip()
    role = (payload or {}).get("role") or ROLE_USER
    email = str((payload or {}).get("email") or "").strip().lower()
    if not phone or len(phone) < 6:
        return {"ok": False, "error": "请输入有效手机号。"}
    if len(password) < 8:
        return {"ok": False, "error": "初始密码至少 8 位。"}
    if role not in ROLE_LABELS:
        return {"ok": False, "error": "账号角色无效。"}
    if ROLE_RANK.get(role, 0) >= ROLE_RANK[ROLE_SUB_ADMIN] and actor.get("role") != ROLE_SUPER_ADMIN:
        return {"ok": False, "error": "只有最高管理可以直接创建或提升次管理账号。"}
    with _lock:
        users_doc = _read_json(USERS_PATH, {"users": []})
        if any(u.get("phone") == phone for u in users_doc.get("users", [])):
            return {"ok": False, "error": "该手机号已存在。"}
        if email and any((u.get("email") or "").lower() == email for u in users_doc.get("users", [])):
            return {"ok": False, "error": "该邮箱已存在。"}
        user = {
            "user_id": secrets.token_hex(8),
            "phone": phone,
            "email": email,
            "account": (payload or {}).get("account") or phone,
            "name": (payload or {}).get("name") or phone,
            "role": role,
            "status": "active",
            "password_hash": _hash_password(password),
            "phone_bound": True,
            "phone_verified": True,
            "email_bound": bool(email),
            "email_verified": False,
            "invited_by": actor.get("user_id"),
            "created_by": actor.get("phone"),
            "commission_rate_pct": float((payload or {}).get("commission_rate_pct") or 0),
            "commission_reserved": {
                "enabled": False,
                "description": "预留：后续收益抽成接口",
                "settlement_mode": "profit_after_close",
            },
            "created_at": _now(),
            "updated_at": _now(),
        }
        users_doc.setdefault("users", []).append(user)
        users_doc["updated_at"] = _now()
        _write_json(USERS_PATH, users_doc)
    return {"ok": True, "user": _public_user(user)}


def bind_account_with_email(user: dict, phone: str, email: str, code: str) -> dict:
    email = str(email or "").strip().lower()
    if not email:
        return {"ok": False, "error": "请输入邮箱地址。"}
    verified = email_code_service.verify_code(email, "bind_account", code)
    if not verified.get("ok"):
        return verified
    with _lock:
        users_doc = _read_json(USERS_PATH, {"users": []})
        if any((u.get("email") or "").lower() == email and u.get("user_id") != user.get("user_id") for u in users_doc.get("users", [])):
            return {"ok": False, "error": "该邮箱已绑定其他账号。"}
        row = next((u for u in users_doc.get("users", []) if u.get("user_id") == user.get("user_id")), None)
        if not row:
            return {"ok": False, "error": "账号不存在。"}
        row["email"] = email
        row["email_bound"] = True
        row["email_verified"] = True
        row["updated_at"] = _now()
        users_doc["updated_at"] = _now()
        _write_json(USERS_PATH, users_doc)
    return {"ok": True, "user": _public_user(row), "message": "邮箱已绑定。"}


def change_password(user: dict, old_password: str, new_password: str, code: str = "") -> dict:
    if len(new_password or "") < 8:
        return {"ok": False, "error": "新密码至少 8 位。"}
    with _lock:
        users_doc = _read_json(USERS_PATH, {"users": []})
        row = next((u for u in users_doc.get("users", []) if u.get("user_id") == user.get("user_id")), None)
        if not row:
            return {"ok": False, "error": "账号不存在。"}
        if row.get("email_verified") and row.get("email"):
            checked = email_code_service.verify_code(row.get("email") or "", "change_password", code)
            if not checked.get("ok"):
                return checked
        elif row.get("phone_verified") and row.get("phone"):
            checked = sms_code_service.verify_code(row.get("phone") or "", "change_password", code)
            if not checked.get("ok"):
                return checked
        elif not _verify_password(old_password or "", row.get("password_hash") or {}):
            return {"ok": False, "error": "旧密码错误。"}
        row["password_hash"] = _hash_password(new_password)
        row["updated_at"] = _now()
        users_doc["updated_at"] = _now()
        _write_json(USERS_PATH, users_doc)
    return {"ok": True, "message": "密码已更新。"}


def update_user_role(actor: dict, phone: str, role: str) -> dict:
    if actor.get("role") != ROLE_SUPER_ADMIN:
        return {"ok": False, "error": "只有最高管理可以调整角色。"}
    if role not in ROLE_LABELS or role == ROLE_SUPER_ADMIN:
        return {"ok": False, "error": "目标角色无效。"}
    with _lock:
        users_doc = _read_json(USERS_PATH, {"users": []})
        user = next((u for u in users_doc.get("users", []) if u.get("phone") == phone), None)
        if not user:
            return {"ok": False, "error": "账号不存在。"}
        user["role"] = role
        user["updated_at"] = _now()
        users_doc["updated_at"] = _now()
        _write_json(USERS_PATH, users_doc)
    return {"ok": True, "user": _public_user(user)}


def update_commission(actor: dict, phone: str, commission_rate_pct: float) -> dict:
    if actor.get("role") not in (ROLE_SUPER_ADMIN, ROLE_SUB_ADMIN):
        return {"ok": False, "error": "当前账号没有抽成配置权限。"}
    rate = max(0.0, min(100.0, float(commission_rate_pct or 0)))
    with _lock:
        users_doc = _read_json(USERS_PATH, {"users": []})
        user = next((u for u in users_doc.get("users", []) if u.get("phone") == phone), None)
        if not user:
            return {"ok": False, "error": "账号不存在。"}
        user["commission_rate_pct"] = rate
        user["commission_reserved"] = {
            **(user.get("commission_reserved") or {}),
            "enabled": rate > 0,
            "updated_by": actor.get("phone"),
            "updated_at": _now(),
        }
        user["updated_at"] = _now()
        users_doc["updated_at"] = _now()
        _write_json(USERS_PATH, users_doc)
    return {"ok": True, "user": _public_user(user), "message": "抽成比例已保存。"}
