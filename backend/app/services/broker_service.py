import json
import os
import secrets
import threading
from datetime import datetime


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AUTH_DIR = os.path.join(BACKEND_ROOT, "data", "auth")
BROKERS_PATH = os.path.join(AUTH_DIR, "broker_accounts.json")

SUPPORTED_BROKERS = [
    {"id": "eastmoney", "name": "东方财富证券", "status": "reserved"},
    {"id": "ths", "name": "同花顺模拟/券商通道", "status": "reserved"},
    {"id": "htsc", "name": "华泰证券", "status": "reserved"},
    {"id": "csc", "name": "中信建投", "status": "reserved"},
    {"id": "custom", "name": "自定义券商接口", "status": "reserved"},
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


def _mask(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}****{text[-2:]}"


def _public_account(row: dict) -> dict:
    return {
        "account_id": row.get("account_id"),
        "owner_user_id": row.get("owner_user_id"),
        "broker_id": row.get("broker_id"),
        "broker_name": row.get("broker_name"),
        "account_no_masked": row.get("account_no_masked"),
        "status": row.get("status", "reserved"),
        "sync_status": row.get("sync_status", "not_connected"),
        "last_sync_at": row.get("last_sync_at"),
        "created_at": row.get("created_at"),
        "message": row.get("message", "券商接入已预留，等待真实 SDK/API 适配。"),
        "positions": row.get("positions", []),
        "assets": row.get("assets", {}),
    }


def list_supported_brokers() -> dict:
    return {"ok": True, "brokers": SUPPORTED_BROKERS}


def list_accounts(user: dict) -> dict:
    doc = _read_json(BROKERS_PATH, {"accounts": []})
    if user.get("role") in ("super_admin", "sub_admin"):
        rows = doc.get("accounts", [])
    else:
        rows = [r for r in doc.get("accounts", []) if r.get("owner_user_id") == user.get("user_id")]
    return {"ok": True, "accounts": [_public_account(r) for r in rows], "brokers": SUPPORTED_BROKERS}


def connect_account(user: dict, payload: dict) -> dict:
    broker_id = (payload or {}).get("broker_id") or "custom"
    broker = next((b for b in SUPPORTED_BROKERS if b["id"] == broker_id), SUPPORTED_BROKERS[-1])
    account_no = str((payload or {}).get("account_no") or "").strip()
    if not account_no:
        return {"ok": False, "error": "请填写券商资金账号或客户号。"}
    row = {
        "account_id": secrets.token_hex(8),
        "owner_user_id": user.get("user_id"),
        "owner_phone": user.get("phone"),
        "broker_id": broker["id"],
        "broker_name": broker["name"],
        "account_no_masked": _mask(account_no),
        "status": "reserved",
        "sync_status": "not_connected",
        "last_sync_at": None,
        "created_at": _now(),
        "message": "已保存券商接入占位信息；真实资金、持仓、成交同步等待券商 SDK/API 接入后启用。",
        "positions": [],
        "assets": {},
    }
    with _lock:
        doc = _read_json(BROKERS_PATH, {"accounts": []})
        doc.setdefault("accounts", []).append(row)
        doc["updated_at"] = _now()
        _write_json(BROKERS_PATH, doc)
    return {"ok": True, "account": _public_account(row)}


def sync_account(user: dict, account_id: str) -> dict:
    doc = _read_json(BROKERS_PATH, {"accounts": []})
    row = next((r for r in doc.get("accounts", []) if r.get("account_id") == account_id), None)
    if not row:
        return {"ok": False, "error": "券商账号不存在。"}
    if user.get("role") not in ("super_admin", "sub_admin") and row.get("owner_user_id") != user.get("user_id"):
        return {"ok": False, "error": "不能同步其他人的券商账号。"}
    row["sync_status"] = "reserved"
    row["last_sync_at"] = _now()
    row["message"] = "同步接口已预留；接入券商 API 后这里会返回真实资产、持仓、委托和成交详情。"
    with _lock:
        _write_json(BROKERS_PATH, doc)
    return {"ok": True, "account": _public_account(row)}
