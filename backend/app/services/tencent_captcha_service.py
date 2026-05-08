import hashlib
import hmac
import json
import os
import time
from datetime import datetime

import requests


BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
AUTH_DIR = os.path.join(BACKEND_ROOT, "data", "auth")
CAPTCHA_CONFIG_PATH = os.path.join(AUTH_DIR, "captcha_config.json")


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


def get_config() -> dict:
    config = _read_json(CAPTCHA_CONFIG_PATH, {})
    app_id = str(os.getenv("TENCENT_CAPTCHA_APP_ID") or config.get("app_id") or "").strip()
    app_secret_key = str(os.getenv("TENCENT_CAPTCHA_APP_SECRET_KEY") or config.get("app_secret_key") or "").strip()
    secret_id = str(os.getenv("TENCENT_SECRET_ID") or config.get("secret_id") or "").strip()
    secret_key = str(os.getenv("TENCENT_SECRET_KEY") or config.get("secret_key") or "").strip()
    enabled = bool(config.get("enabled", True) and app_id and app_secret_key)
    return {
        "enabled": enabled,
        "app_id": app_id,
        "app_secret_key": app_secret_key,
        "secret_id": secret_id,
        "secret_key": secret_key,
        "region": str(config.get("region") or os.getenv("TENCENT_CAPTCHA_REGION") or "ap-guangzhou"),
    }


def get_public_config() -> dict:
    cfg = get_config()
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled")),
        "app_id": cfg.get("app_id") or "",
        "server_verify_ready": bool(cfg.get("secret_id") and cfg.get("secret_key")),
    }


def save_config(app_id: str, app_secret_key: str, secret_id: str = "", secret_key: str = "") -> dict:
    data = {
        "enabled": True,
        "app_id": str(app_id or "").strip(),
        "app_secret_key": str(app_secret_key or "").strip(),
        "secret_id": str(secret_id or "").strip(),
        "secret_key": str(secret_key or "").strip(),
        "region": "ap-guangzhou",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_json(CAPTCHA_CONFIG_PATH, data)
    return get_public_config()


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _authorization(secret_id: str, secret_key: str, service: str, payload: str, timestamp: int) -> str:
    algorithm = "TC3-HMAC-SHA256"
    date = time.strftime("%Y-%m-%d", time.gmtime(timestamp))
    canonical_request = "\n".join([
        "POST",
        "/",
        "",
        f"content-type:application/json; charset=utf-8\nhost:{service}.tencentcloudapi.com\n",
        "content-type;host",
        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    ])
    credential_scope = f"{date}/{service}/tc3_request"
    string_to_sign = "\n".join([
        algorithm,
        str(timestamp),
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    secret_date = _sign(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = hmac.new(secret_date, service.encode("utf-8"), hashlib.sha256).digest()
    secret_signing = hmac.new(secret_service, b"tc3_request", hashlib.sha256).digest()
    signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    return (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        "SignedHeaders=content-type;host, "
        f"Signature={signature}"
    )


def verify_ticket(ticket: str, randstr: str, user_ip: str) -> dict:
    cfg = get_config()
    if not cfg.get("enabled"):
        return {"ok": True, "skipped": True, "message": "腾讯验证码未启用。"}
    if not ticket or not randstr:
        return {"ok": False, "error": "请先完成腾讯验证码验证。"}
    if not cfg.get("secret_id") or not cfg.get("secret_key"):
        return {
            "ok": False,
            "error": "腾讯验证码服务端校验缺少 SecretId/SecretKey，请先补齐。",
            "missing_secret": True,
        }

    service = "captcha"
    payload_obj = {
        "CaptchaType": 9,
        "Ticket": str(ticket),
        "UserIp": str(user_ip or ""),
        "Randstr": str(randstr),
        "CaptchaAppId": int(cfg["app_id"]),
        "AppSecretKey": cfg["app_secret_key"],
    }
    payload = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":"))
    timestamp = int(time.time())
    headers = {
        "Authorization": _authorization(cfg["secret_id"], cfg["secret_key"], service, payload, timestamp),
        "Content-Type": "application/json; charset=utf-8",
        "Host": f"{service}.tencentcloudapi.com",
        "X-TC-Action": "DescribeCaptchaResult",
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Version": "2019-07-22",
        "X-TC-Region": cfg.get("region") or "ap-guangzhou",
    }
    try:
        resp = requests.post(f"https://{service}.tencentcloudapi.com", data=payload.encode("utf-8"), headers=headers, timeout=10)
        data = resp.json()
    except Exception as exc:
        return {"ok": False, "error": f"腾讯验证码校验请求失败：{exc}"}

    response = data.get("Response") or {}
    if response.get("Error"):
        err = response.get("Error") or {}
        return {"ok": False, "error": f"腾讯验证码校验失败：{err.get('Message') or err.get('Code')}"}
    code = response.get("CaptchaCode")
    msg = response.get("CaptchaMsg") or ""
    passed = code in (1, "1") or str(msg).lower() in ("ok", "success")
    if not passed:
        return {"ok": False, "error": f"人机验证未通过：{msg or code}"}
    return {"ok": True, "message": "人机验证通过。", "captcha": response}
