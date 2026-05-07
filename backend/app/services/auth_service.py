import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime
from app.services import sms_code_service


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
    {
        "phone": "18800000001",
        "name": "最高管理01",
        "role": ROLE_SUPER_ADMIN,
        "password": "Admin@2026!",
    },
    {
        "phone": "18800000002",
        "name": "最高管理02",
        "role": ROLE_SUPER_ADMIN,
        "password": "Admin@2026!",
    },
    {
        "phone": "123123123",
        "name": "只读访问账号",
        "role": ROLE_VISITOR,
        "password": "123123@!",
    },
]

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


def _public_user(user: dict) -> dict:
    if not user:
        return {}
    return {
        "user_id": user.get("user_id"),
        "phone": user.get("phone"),
        "account": user.get("account") or user.get("phone"),
        "phone_bound": bool(user.get("phone_bound") or user.get("phone_verified")),
        "phone_verified": bool(user.get("phone_verified")),
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


def init_auth_store():
    with _lock:
        users = _read_json(USERS_PATH, {"users": []})
        for user in users.get("users", []):
            if user.get("role") == ROLE_VISITOR and user.get("phone") != "123123123":
                user["phone"] = "123123123"
                user["name"] = "只读访问账号"
                user["password_hash"] = _hash_password("123123@!")
                user["updated_at"] = _now()
        existing = {u.get("phone"): u for u in users.get("users", [])}
        for seed in DEFAULT_USERS:
            row = existing.get(seed["phone"])
            if row:
                row["account"] = row.get("account") or seed["phone"]
                row["phone_bound"] = True
                row["phone_verified"] = True
                row["updated_at"] = row.get("updated_at") or _now()
        changed = False
        for seed in DEFAULT_USERS:
            if seed["phone"] in existing:
                continue
            password_hash = _hash_password(seed["password"])
            users.setdefault("users", []).append({
                "user_id": secrets.token_hex(8),
                "phone": seed["phone"],
                "account": seed.get("account") or seed["phone"],
                "name": seed["name"],
                "role": seed["role"],
                "status": "active",
                "password_hash": password_hash,
                "phone_bound": True,
                "phone_verified": True,
                "invited_by": None,
                "created_by": "system",
                "commission_rate_pct": 0.0,
                "commission_reserved": {
                    "enabled": False,
                    "description": "预留：每次交易完成后收益抽成，暂不计算。",
                    "settlement_mode": "profit_after_close",
                },
                "created_at": _now(),
                "updated_at": _now(),
            })
            changed = True
        users["roles"] = ROLE_LABELS
        users["updated_at"] = _now()
        if changed or not os.path.exists(USERS_PATH):
            _write_json(USERS_PATH, users)
        if not os.path.exists(SESSIONS_PATH):
            _write_json(SESSIONS_PATH, {"sessions": []})


def list_users(actor: dict) -> dict:
    if not permissions_for_role(actor.get("role")).get("can_manage_accounts"):
        return {"ok": False, "error": "当前账号没有账号管理权限。"}
    users = _read_json(USERS_PATH, {"users": []}).get("users", [])
    return {"ok": True, "users": [_public_user(u) for u in users], "roles": ROLE_LABELS}


def _find_user_by_login(users: list, login_id: str) -> dict | None:
    login_id = str(login_id or "").strip()
    return next(
        (
            u for u in users
            if u.get("phone") == login_id
            or u.get("account") == login_id
            or u.get("name") == login_id
        ),
        None,
    )


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
    if not user or user.get("status") != "active" or not _verify_password(password or "", user.get("password_hash") or {}):
        return {"ok": False, "error": "手机号或密码错误，或账号已停用。"}
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
        return {"ok": False, "error": "只有最高管理和次管理可以邀请注册账号。"}
    phone = str((payload or {}).get("phone") or "").strip()
    password = str((payload or {}).get("password") or "").strip()
    role = (payload or {}).get("role") or ROLE_USER
    if not phone or len(phone) < 6:
        return {"ok": False, "error": "请填写有效手机号。"}
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
        user = {
            "user_id": secrets.token_hex(8),
            "phone": phone,
            "account": (payload or {}).get("account") or phone,
            "name": (payload or {}).get("name") or phone,
            "role": role,
            "status": "active",
            "password_hash": _hash_password(password),
            "phone_bound": True,
            "phone_verified": True,
            "invited_by": actor.get("user_id"),
            "created_by": actor.get("phone"),
            "commission_rate_pct": float((payload or {}).get("commission_rate_pct") or 0),
            "commission_reserved": {
                "enabled": False,
                "description": "预留：每次交易完成后收益抽成，暂不计算。",
                "settlement_mode": "profit_after_close",
            },
            "created_at": _now(),
            "updated_at": _now(),
        }
        users_doc.setdefault("users", []).append(user)
        users_doc["updated_at"] = _now()
        _write_json(USERS_PATH, users_doc)
    return {"ok": True, "user": _public_user(user)}


def bind_phone(user: dict, phone: str, code: str) -> dict:
    verified = sms_code_service.verify_code(phone, "bind_phone", code)
    if not verified.get("ok"):
        return verified
    with _lock:
        users_doc = _read_json(USERS_PATH, {"users": []})
        if any(u.get("phone") == phone and u.get("user_id") != user.get("user_id") for u in users_doc.get("users", [])):
            return {"ok": False, "error": "该手机号已绑定其他账号。"}
        row = next((u for u in users_doc.get("users", []) if u.get("user_id") == user.get("user_id")), None)
        if not row:
            return {"ok": False, "error": "账号不存在。"}
        row["phone"] = phone
        row["phone_bound"] = True
        row["phone_verified"] = True
        row["updated_at"] = _now()
        users_doc["updated_at"] = _now()
        _write_json(USERS_PATH, users_doc)
    return {"ok": True, "user": _public_user(row), "message": "手机号已绑定。"}


def change_password(user: dict, old_password: str, new_password: str, sms_code: str = "") -> dict:
    if len(new_password or "") < 8:
        return {"ok": False, "error": "新密码至少 8 位。"}
    with _lock:
        users_doc = _read_json(USERS_PATH, {"users": []})
        row = next((u for u in users_doc.get("users", []) if u.get("user_id") == user.get("user_id")), None)
        if not row:
            return {"ok": False, "error": "账号不存在。"}
        if row.get("phone_verified"):
            checked = sms_code_service.verify_code(row.get("phone") or "", "change_password", sms_code)
            if not checked.get("ok"):
                return checked
        elif not _verify_password(old_password or "", row.get("password_hash") or {}):
            return {"ok": False, "error": "旧密码错误。"}
        row["password_hash"] = _hash_password(new_password)
        row["updated_at"] = _now()
        users_doc["updated_at"] = _now()
        _write_json(USERS_PATH, users_doc)
    return {"ok": True, "message": "密码已更新，请使用新密码登录。"}


def update_user_role(actor: dict, phone: str, role: str) -> dict:
    if actor.get("role") != ROLE_SUPER_ADMIN:
        return {"ok": False, "error": "只有最高管理可以提升或调整次管理权限。"}
    if role not in ROLE_LABELS or role == ROLE_SUPER_ADMIN:
        return {"ok": False, "error": "目标角色无效；最高管理账号不可通过接口增设。"}
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
    return {"ok": True, "user": _public_user(user), "message": "抽成比例已预留保存，暂不参与收益结算。"}
