"""
AI model provider configuration and model discovery.

The service keeps API keys in a local private JSON file and only returns masked
keys to the H5 UI. It supports OpenAI-compatible providers first because most
domestic and third-party model gateways expose /v1/models.
"""
import json
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from app.services import strategy_memory_service


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "ai")
CONFIG_PATH = os.path.join(DATA_DIR, "model_config.json")
TIMEOUT_SECONDS = 12


PROVIDERS: Dict[str, dict] = {
    "openai": {
        "name": "OpenAI 官方",
        "protocol": "openai_compatible",
        "default_base_url": "https://api.openai.com/v1",
        "models_path": "/models",
        "auth": "bearer",
        "notes": "官方 OpenAI API，推荐填 https://api.openai.com/v1。",
    },
    "openai_compatible": {
        "name": "OpenAI 兼容网关",
        "protocol": "openai_compatible",
        "default_base_url": "",
        "models_path": "/models",
        "auth": "bearer",
        "notes": "适配 DeepSeek、通义千问、Moonshot、智谱、OpenRouter、硅基流动、火山方舟等兼容 /v1/models 的服务。",
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "protocol": "anthropic",
        "default_base_url": "https://api.anthropic.com/v1",
        "models_path": "/models",
        "auth": "x_api_key",
        "notes": "Claude 官方接口，检测时使用 x-api-key 与 anthropic-version 请求头。",
    },
    "gemini": {
        "name": "Google Gemini",
        "protocol": "gemini",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models_path": "/models",
        "auth": "query_key",
        "notes": "Gemini 官方接口，密钥通过 key 查询参数检测模型列表。",
    },
    "custom": {
        "name": "自定义",
        "protocol": "openai_compatible",
        "default_base_url": "",
        "models_path": "/models",
        "auth": "bearer",
        "notes": "用于其他兼容服务；如果检测失败，可先确认服务是否支持 GET /models。",
    },
}


COMMON_PROVIDER_HINTS = [
    ("api.openai.com", "openai"),
    ("anthropic.com", "anthropic"),
    ("generativelanguage.googleapis.com", "gemini"),
    ("openrouter.ai", "openai_compatible"),
    ("deepseek.com", "openai_compatible"),
    ("dashscope.aliyuncs.com", "openai_compatible"),
    ("moonshot.cn", "openai_compatible"),
    ("bigmodel.cn", "openai_compatible"),
    ("siliconflow.cn", "openai_compatible"),
    ("volces.com", "openai_compatible"),
]


DEFAULT_TASK_POLICIES = {
    "news_filter": {
        "name": "新闻粗筛",
        "temperature": 0.2,
        "timeout_seconds": 25,
        "max_context_events": 30,
        "description": "快速识别两周新闻中的利好、利空、板块归因和噪音。",
    },
    "deep_analysis": {
        "name": "深度研判",
        "temperature": 0.18,
        "timeout_seconds": 75,
        "max_context_events": 80,
        "description": "综合新闻、公告、行情、板块、资金和技术结构做高质量研判。",
    },
    "task_planning": {
        "name": "任务理解",
        "temperature": 0.03,
        "timeout_seconds": 18,
        "max_context_events": 20,
        "description": "理解用户自然语言意图，判断是否要执行站内任务、生成报告、选股或发送邮件。",
    },
    "risk_review": {
        "name": "风控复核",
        "temperature": 0.05,
        "timeout_seconds": 45,
        "max_context_events": 45,
        "description": "做真伪校验、黑盒复核、一票否决和仓位上限控制。",
    },
    "ai_quality_scoring": {
        "name": "全候选质量打分",
        "temperature": 0.1,
        "timeout_seconds": 120,
        "max_context_events": 500,
        "description": "对第二阶段候选池分批做AI质量评分，先筛出复核池，再进入最终交易建议。",
    },
    "trade_decision": {
        "name": "最终交易建议",
        "temperature": 0.08,
        "timeout_seconds": 90,
        "max_context_events": 80,
        "description": "输出结构化买卖建议、建议时间、挂单价格、概率和失效条件。",
    },
    "industry_report": {
        "name": "行业深度报告",
        "temperature": 0.25,
        "timeout_seconds": 120,
        "max_context_events": 120,
        "description": "生成深度行业、政策、产业链和板块机会分析。",
    },
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_safe(value):
    """Convert pandas/numpy scalar values into ordinary JSON-safe objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def _read_config_raw() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return _default_config()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        config = {**_default_config(), **(data or {})}
        config["usage_policy"] = {
            **_default_config().get("usage_policy", {}),
            **((data or {}).get("usage_policy") or {}),
        }
        config["usage_policy"]["task_policies"] = _merge_task_policies(
            config["usage_policy"].get("task_policies")
        )
        config["risk_verifier"] = {
            **_default_config().get("risk_verifier", {}),
            **((data or {}).get("risk_verifier") or {}),
        }
        return config
    except Exception:
        return _default_config()


def _write_config(config: dict):
    _ensure_data_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _default_config() -> dict:
    return {
        "enabled": False,
        "provider": "",
        "provider_name": "",
        "base_url": "",
        "api_key": "",
        "selected_model": "",
        "available_models": [],
        "last_detected_at": None,
        "last_status": "not_configured",
        "last_error": "",
        "usage_policy": {
            "default_temperature": 0.15,
            "timeout_seconds": 60,
            "max_context_events": 80,
            "allow_live_trading_decision": False,
            "require_risk_review": True,
            "task_policies": _merge_task_policies(),
        },
        "risk_verifier": {
            "enabled": False,
            "provider": "openai_compatible",
            "provider_name": PROVIDERS["openai_compatible"]["name"],
            "base_url": "",
            "api_key": "",
            "selected_model": "",
            "available_models": [],
            "last_detected_at": None,
            "last_status": "not_configured",
            "last_error": "",
        },
    }


def _merge_task_policies(value: Optional[dict] = None) -> dict:
    merged = {}
    for key, defaults in DEFAULT_TASK_POLICIES.items():
        current = (value or {}).get(key) or {}
        merged[key] = {**defaults, **current}
    return merged


def mask_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}...{api_key[-4:]}"


def _public_config(config: Optional[dict] = None) -> dict:
    raw = config or _read_config_raw()
    public = {k: v for k, v in raw.items() if k != "api_key"}
    public["api_key_masked"] = mask_key(raw.get("api_key", ""))
    public["has_api_key"] = bool(raw.get("api_key"))
    verifier = public.get("risk_verifier") or {}
    if isinstance(verifier, dict):
        verifier_public = {k: v for k, v in verifier.items() if k != "api_key"}
        verifier_public["api_key_masked"] = mask_key(verifier.get("api_key", ""))
        verifier_public["has_api_key"] = bool(verifier.get("api_key"))
        public["risk_verifier"] = verifier_public
    public["config_path"] = CONFIG_PATH
    return public


def get_provider_catalog() -> dict:
    return {
        "providers": [
            {"id": provider_id, **meta}
            for provider_id, meta in PROVIDERS.items()
        ],
        "config": _public_config(),
    }


def get_config_public() -> dict:
    return _public_config()


def update_connection_config(provider: str = "", base_url: str = "", api_key: str = "") -> dict:
    existing = _read_config_raw()
    provider_id = provider if provider in PROVIDERS else (existing.get("provider") or "openai_compatible")
    normalized_url = (base_url or "").strip().rstrip("/")
    if normalized_url and not normalized_url.startswith(("http://", "https://")):
        normalized_url = "https://" + normalized_url
    if normalized_url.endswith("/models"):
        normalized_url = normalized_url[: -len("/models")]

    config = _read_config_raw()
    config["provider"] = provider_id
    config["provider_name"] = PROVIDERS[provider_id]["name"]
    if normalized_url:
        config["base_url"] = normalized_url
    elif not config.get("base_url"):
        config["base_url"] = ""
    if api_key and "..." not in api_key:
        config["api_key"] = api_key
    config["updated_at"] = _now()
    _write_config(config)
    return {"ok": True, "config": _public_config(config)}


def update_risk_verifier_config(
    provider: str = "",
    base_url: str = "",
    api_key: str = "",
    selected_model: str = "",
    enabled: Optional[bool] = None,
) -> dict:
    config = _read_config_raw()
    verifier = {**_default_config()["risk_verifier"], **(config.get("risk_verifier") or {})}
    provider_id = provider if provider in PROVIDERS else (verifier.get("provider") or "openai_compatible")
    normalized_url = (base_url or "").strip().rstrip("/")
    if normalized_url and not normalized_url.startswith(("http://", "https://")):
        normalized_url = "https://" + normalized_url
    if normalized_url.endswith("/models"):
        normalized_url = normalized_url[: -len("/models")]

    verifier["provider"] = provider_id
    verifier["provider_name"] = PROVIDERS[provider_id]["name"]
    if normalized_url:
        verifier["base_url"] = normalized_url
    elif not verifier.get("base_url"):
        verifier["base_url"] = ""
    if api_key and "..." not in api_key:
        verifier["api_key"] = api_key
    selected_model = (selected_model or "").strip()
    if selected_model:
        verifier["selected_model"] = selected_model
    else:
        selected_model = verifier.get("selected_model", "")
    if selected_model:
        models = verifier.get("available_models") or []
        known_ids = {m.get("id") for m in models if isinstance(m, dict)}
        if selected_model not in known_ids:
            models.append({
                "id": selected_model,
                "name": selected_model,
                "owned_by": "manual",
                "provider": provider_id,
            })
            verifier["available_models"] = models
    if enabled is not None:
        verifier["enabled"] = bool(enabled)
    verifier["updated_at"] = _now()
    config["risk_verifier"] = verifier
    config["updated_at"] = _now()
    _write_config(config)
    return {"ok": True, "config": _public_config(config)}


def _guess_provider(provider: str, base_url: str) -> str:
    if provider and provider in PROVIDERS:
        return provider
    host = urlparse(base_url).netloc.lower()
    for needle, provider_id in COMMON_PROVIDER_HINTS:
        if needle in host:
            return provider_id
    return "openai_compatible"


def _normalize_base_url(base_url: str, provider: str) -> str:
    meta = PROVIDERS.get(provider, PROVIDERS["openai_compatible"])
    value = (base_url or meta.get("default_base_url") or "").strip().rstrip("/")
    if not value:
        raise ValueError("请填写 API Base URL。")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    if value.endswith("/models"):
        value = value[: -len("/models")]
    return value.rstrip("/")


def _models_url(base_url: str, provider: str, api_key: str) -> str:
    meta = PROVIDERS.get(provider, PROVIDERS["openai_compatible"])
    path = meta.get("models_path", "/models")
    url = base_url if base_url.endswith(path) else f"{base_url}{path}"
    if meta.get("auth") == "query_key":
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}key={api_key}"
    return url


def _headers(provider: str, api_key: str) -> dict:
    meta = PROVIDERS.get(provider, PROVIDERS["openai_compatible"])
    headers = {"Accept": "application/json", "User-Agent": "lianghua-ai-model-detector/1.0"}
    if meta.get("auth") == "bearer":
        headers["Authorization"] = f"Bearer {api_key}"
    elif meta.get("auth") == "x_api_key":
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
    return headers


def _chat_url(base_url: str, provider: str) -> str:
    meta = PROVIDERS.get(provider, PROVIDERS["openai_compatible"])
    value = (base_url or meta.get("default_base_url") or "").strip().rstrip("/")
    if not value:
        raise ValueError("请先配置模型接口地址")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    if value.endswith("/models"):
        value = value[: -len("/models")]
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def get_task_policy(task_key: str) -> dict:
    config = _read_config_raw()
    policy = config.get("usage_policy") or {}
    task_policies = _merge_task_policies(policy.get("task_policies"))
    task = task_policies.get(task_key, {})
    return {
        **policy,
        **task,
        "task_key": task_key,
        "task_name": task.get("name", task_key),
    }


def is_ready() -> bool:
    config = _read_config_raw()
    return bool(config.get("enabled") and config.get("api_key") and config.get("selected_model"))


def _extract_json_object(text: str):
    if not text:
        raise ValueError("模型没有返回内容")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned, flags=re.I).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"(\{.*\})", cleaned, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(1))


def chat_json(task_key: str, system_prompt: str, user_payload: dict, schema_hint: str = "") -> Tuple[Optional[dict], dict]:
    """Call the configured OpenAI-compatible model and parse a JSON object.

    Returns (parsed_json, meta). The caller should provide a deterministic
    fallback because live model calls can fail or be disabled during preview.
    """
    config = _read_config_raw()
    if not is_ready():
        return None, {"ok": False, "used_ai": False, "error": "AI模型尚未配置或未启用"}

    provider = config.get("provider") or "openai_compatible"
    model = config.get("selected_model") or ""
    policy = get_task_policy(task_key)
    temperature = float(policy.get("temperature", policy.get("default_temperature", 0.15)) or 0.15)
    timeout = int(policy.get("timeout_seconds", 60) or 60)
    max_events = int(policy.get("max_context_events", 80) or 80)

    memory_context = strategy_memory_service.get_model_memory_context(task_key)
    if memory_context:
        system_prompt = f"{system_prompt}\n\n【站内策略记忆】\n{memory_context}"

    safe_payload = _json_safe(dict(user_payload or {}))
    safe_payload.setdefault("strategy_memory_version", strategy_memory_service.get_strategy_memory().get("version"))
    if isinstance(safe_payload.get("candidates"), list):
        safe_payload["candidates"] = safe_payload["candidates"][:max_events]
    if isinstance(safe_payload.get("news"), list):
        safe_payload["news"] = safe_payload["news"][:max_events]

    content = json.dumps(safe_payload, ensure_ascii=False)
    if schema_hint:
        content += "\n\n请严格按这个JSON结构返回，不要输出解释文字：\n" + schema_hint

    try:
        response = requests.post(
            _chat_url(config.get("base_url", ""), provider),
            headers={**_headers(provider, config.get("api_key", "")), "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=timeout,
        )
        if response.status_code >= 400:
            return None, {
                "ok": False,
                "used_ai": False,
                "provider": provider,
                "model": model,
                "error": f"模型调用失败：HTTP {response.status_code} {response.text[:300]}",
            }
        payload = response.json()
        message = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        parsed = _extract_json_object(message)
        return parsed, {
            "ok": True,
            "used_ai": True,
            "provider": provider,
            "model": model,
            "task_key": task_key,
            "temperature": temperature,
            "timeout_seconds": timeout,
        }
    except Exception as exc:
        return None, {
            "ok": False,
            "used_ai": False,
            "provider": provider,
            "model": model,
            "task_key": task_key,
            "error": str(exc),
        }


def chat_text(task_key: str, system_prompt: str, user_message: str, context: Optional[dict] = None) -> Tuple[str, dict]:
    """Call the configured model for ordinary conversation."""
    config = _read_config_raw()
    if not is_ready():
        return "当前还没有启用可用的大模型。请先在“智能模型”页面配置接口地址、密钥并选择默认模型。", {
            "ok": False,
            "used_ai": False,
            "error": "AI模型尚未配置或未启用",
        }

    provider = config.get("provider") or "openai_compatible"
    model = config.get("selected_model") or ""
    policy = get_task_policy(task_key)
    temperature = float(policy.get("temperature", policy.get("default_temperature", 0.15)) or 0.15)
    timeout = int(policy.get("timeout_seconds", 60) or 60)
    memory_context = strategy_memory_service.get_model_memory_context(task_key)
    if memory_context:
        system_prompt = f"{system_prompt}\n\n【站内策略记忆】\n{memory_context}"
    context_payload = _json_safe(context or {})
    if isinstance(context_payload, dict):
        context_payload.setdefault("strategy_memory", strategy_memory_service.get_strategy_memory())
    context_text = json.dumps(context_payload, ensure_ascii=False)

    try:
        response = requests.post(
            _chat_url(config.get("base_url", ""), provider),
            headers={**_headers(provider, config.get("api_key", "")), "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"站内上下文：\n{context_text}\n\n用户问题：\n{user_message}"},
                ],
            },
            timeout=timeout,
        )
        if response.status_code >= 400:
            return f"模型调用失败：HTTP {response.status_code}", {
                "ok": False,
                "used_ai": False,
                "provider": provider,
                "model": model,
                "error": response.text[:300],
            }
        payload = response.json()
        answer = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return answer.strip() or "模型没有返回有效内容。", {
            "ok": True,
            "used_ai": True,
            "provider": provider,
            "model": model,
            "task_key": task_key,
            "temperature": temperature,
            "timeout_seconds": timeout,
        }
    except Exception as exc:
        return f"模型调用异常：{exc}", {
            "ok": False,
            "used_ai": False,
            "provider": provider,
            "model": model,
            "task_key": task_key,
            "error": str(exc),
        }


def risk_verifier_ready() -> bool:
    verifier = (_read_config_raw().get("risk_verifier") or {})
    return bool(verifier.get("enabled") and verifier.get("api_key") and verifier.get("selected_model") and verifier.get("base_url"))


def chat_json_with_risk_verifier(system_prompt: str, user_payload: dict, schema_hint: str = "") -> Tuple[Optional[dict], dict]:
    config = _read_config_raw()
    verifier = {**_default_config()["risk_verifier"], **(config.get("risk_verifier") or {})}
    if not risk_verifier_ready():
        return None, {"ok": False, "used_ai": False, "role": "risk_verifier", "error": "风控复核模型尚未配置或未启用"}

    provider = verifier.get("provider") or "openai_compatible"
    model = verifier.get("selected_model") or ""
    memory_context = strategy_memory_service.get_model_memory_context("risk_review")
    if memory_context:
        system_prompt = f"{system_prompt}\n\n【站内策略记忆】\n{memory_context}"
    content = json.dumps(_json_safe(dict(user_payload or {})), ensure_ascii=False)
    if schema_hint:
        content += "\n\n请严格按这个 JSON 结构返回，不要输出解释文字：\n" + schema_hint
    try:
        response = requests.post(
            _chat_url(verifier.get("base_url", ""), provider),
            headers={**_headers(provider, verifier.get("api_key", "")), "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.03,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=55,
        )
        if response.status_code >= 400:
            return None, {"ok": False, "used_ai": False, "role": "risk_verifier", "provider": provider, "model": model, "error": f"HTTP {response.status_code} {response.text[:300]}"}
        payload = response.json()
        message = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return _extract_json_object(message), {"ok": True, "used_ai": True, "role": "risk_verifier", "provider": provider, "model": model}
    except Exception as exc:
        return None, {"ok": False, "used_ai": False, "role": "risk_verifier", "provider": provider, "model": model, "error": str(exc)}


def _extract_models(payload, provider: str) -> List[dict]:
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []

    models = []
    for row in rows:
        if isinstance(row, str):
            model_id = row
            owned_by = ""
        elif isinstance(row, dict):
            model_id = row.get("id") or row.get("name") or row.get("model") or ""
            owned_by = row.get("owned_by") or row.get("owner") or row.get("publisher") or provider
        else:
            continue
        if not model_id:
            continue
        models.append({
            "id": model_id,
            "name": model_id,
            "owned_by": owned_by,
            "provider": provider,
        })

    unique = {}
    for model in models:
        unique[model["id"]] = model
    return sorted(unique.values(), key=lambda x: x["id"])


def _response_preview(response, limit: int = 180) -> str:
    text = (getattr(response, "text", "") or "").strip()
    if not text:
        return "空响应"
    return re.sub(r"\s+", " ", text)[:limit]


def _parse_models_response_json(response, label: str) -> Tuple[Optional[object], Optional[dict]]:
    try:
        return response.json(), None
    except ValueError:
        content_type = response.headers.get("content-type", "") or "unknown"
        return None, {
            "ok": False,
            "error": (
                f"{label}检测接口返回的不是 JSON，可能该网关不支持 /models。"
                f"你可以手动填写模型名后直接保存。"
            ),
            "models": [],
            "status_code": response.status_code,
            "content_type": content_type,
            "response_preview": _response_preview(response),
        }


def detect_models(provider: str, base_url: str, api_key: str, save: bool = True) -> dict:
    existing = _read_config_raw()
    api_key = (api_key or "").strip()
    if not api_key:
        api_key = existing.get("api_key", "")
    if not api_key:
        return {"ok": False, "error": "请填写 API Key。", "models": []}

    provider_id = _guess_provider(provider, base_url or existing.get("base_url", ""))
    try:
        normalized_url = _normalize_base_url(base_url or existing.get("base_url", ""), provider_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "models": []}

    started = time.time()
    try:
        response = requests.get(
            _models_url(normalized_url, provider_id, api_key),
            headers=_headers(provider_id, api_key),
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            text = response.text[:300]
            return {
                "ok": False,
                "error": f"模型检测失败：HTTP {response.status_code} {text}",
                "models": [],
                "provider": provider_id,
                "base_url": normalized_url,
                "latency_ms": int((time.time() - started) * 1000),
            }
        payload, parse_error = _parse_models_response_json(response, "模型")
        if parse_error:
            parse_error.update({
                "provider": provider_id,
                "base_url": normalized_url,
                "latency_ms": int((time.time() - started) * 1000),
            })
            return parse_error
        models = _extract_models(payload, provider_id)
        if not models:
            return {
                "ok": False,
                "error": "接口可访问，但没有解析到模型列表。请确认该服务是否支持 /models。",
                "models": [],
                "provider": provider_id,
                "base_url": normalized_url,
                "latency_ms": int((time.time() - started) * 1000),
            }

        selected = models[0]["id"]
        result = {
            "ok": True,
            "provider": provider_id,
            "provider_name": PROVIDERS[provider_id]["name"],
            "base_url": normalized_url,
            "models": models,
            "selected_model": selected,
            "model_count": len(models),
            "latency_ms": int((time.time() - started) * 1000),
            "detected_at": _now(),
            "api_key_masked": mask_key(api_key),
        }
        if save:
            config = _read_config_raw()
            stored_base_url = (base_url or existing.get("base_url", "") or "").strip().rstrip("/")
            if stored_base_url and not stored_base_url.startswith(("http://", "https://")):
                stored_base_url = "https://" + stored_base_url
            if stored_base_url.endswith("/models"):
                stored_base_url = stored_base_url[: -len("/models")]
            config.update({
                "enabled": True,
                "provider": provider_id,
                "provider_name": PROVIDERS[provider_id]["name"],
                "base_url": stored_base_url,
                "api_key": api_key,
                "selected_model": selected,
                "available_models": models,
                "last_detected_at": result["detected_at"],
                "last_status": "ok",
                "last_error": "",
            })
            _write_config(config)
        return result
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "模型检测超时，请检查 URL、网络或代理。", "models": [], "provider": provider_id, "base_url": normalized_url}
    except Exception as exc:
        return {"ok": False, "error": f"模型检测异常：{exc}", "models": [], "provider": provider_id, "base_url": normalized_url}


def select_model(model_id: str, provider: Optional[str] = None) -> dict:
    config = _read_config_raw()
    models = config.get("available_models") or []
    known_ids = {m.get("id") for m in models if isinstance(m, dict)}
    model_id = (model_id or "").strip()
    if not model_id:
        return {"ok": False, "error": "请选择模型。", "config": _public_config(config)}
    if known_ids and model_id not in known_ids:
        return {"ok": False, "error": "该模型不在最近检测列表中，请重新检测。", "config": _public_config(config)}
    if provider and provider in PROVIDERS:
        config["provider"] = provider
        config["provider_name"] = PROVIDERS[provider]["name"]
    config["selected_model"] = model_id
    config["enabled"] = True
    config["updated_at"] = _now()
    _write_config(config)
    return {"ok": True, "message": "默认模型已保存。", "config": _public_config(config)}


def detect_risk_verifier_models(provider: str, base_url: str, api_key: str, save: bool = True) -> dict:
    config = _read_config_raw()
    verifier = {**_default_config()["risk_verifier"], **(config.get("risk_verifier") or {})}
    api_key = (api_key or "").strip() or verifier.get("api_key", "")
    if not api_key:
        return {"ok": False, "error": "请填写风控复核模型 API Key。", "models": []}
    provider_id = _guess_provider(provider or verifier.get("provider", ""), base_url or verifier.get("base_url", ""))
    try:
        normalized_url = _normalize_base_url(base_url or verifier.get("base_url", ""), provider_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "models": []}
    started = time.time()
    try:
        response = requests.get(
            _models_url(normalized_url, provider_id, api_key),
            headers=_headers(provider_id, api_key),
            timeout=TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            return {"ok": False, "error": f"风控模型检测失败：HTTP {response.status_code} {response.text[:300]}", "models": [], "provider": provider_id, "base_url": normalized_url}
        payload, parse_error = _parse_models_response_json(response, "风控模型")
        if parse_error:
            parse_error.update({
                "provider": provider_id,
                "base_url": normalized_url,
                "latency_ms": int((time.time() - started) * 1000),
            })
            return parse_error
        models = _extract_models(payload, provider_id)
        if not models:
            return {"ok": False, "error": "接口可访问，但没有解析到模型列表。", "models": [], "provider": provider_id, "base_url": normalized_url}
        selected = models[0]["id"]
        if save:
            verifier.update({
                "enabled": True,
                "provider": provider_id,
                "provider_name": PROVIDERS[provider_id]["name"],
                "base_url": normalized_url,
                "api_key": api_key,
                "selected_model": selected,
                "available_models": models,
                "last_detected_at": _now(),
                "last_status": "ok",
                "last_error": "",
            })
            config["risk_verifier"] = verifier
            config["updated_at"] = _now()
            _write_config(config)
        return {
            "ok": True,
            "provider": provider_id,
            "provider_name": PROVIDERS[provider_id]["name"],
            "base_url": normalized_url,
            "models": models,
            "selected_model": selected,
            "model_count": len(models),
            "latency_ms": int((time.time() - started) * 1000),
            "detected_at": _now(),
            "api_key_masked": mask_key(api_key),
        }
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "风控模型检测超时，请检查 URL、网络或代理。", "models": [], "provider": provider_id, "base_url": normalized_url}
    except Exception as exc:
        return {"ok": False, "error": f"风控模型检测异常：{exc}", "models": [], "provider": provider_id, "base_url": normalized_url}


def select_risk_verifier_model(model_id: str, provider: Optional[str] = None) -> dict:
    config = _read_config_raw()
    verifier = {**_default_config()["risk_verifier"], **(config.get("risk_verifier") or {})}
    models = verifier.get("available_models") or []
    known_ids = {m.get("id") for m in models if isinstance(m, dict)}
    if not model_id:
        return {"ok": False, "error": "请选择风控复核模型。", "config": _public_config(config)}
    if provider and provider in PROVIDERS:
        verifier["provider"] = provider
        verifier["provider_name"] = PROVIDERS[provider]["name"]
    if model_id not in known_ids:
        models.append({
            "id": model_id,
            "name": model_id,
            "owned_by": "manual",
            "provider": verifier.get("provider") or provider or "openai_compatible",
        })
        verifier["available_models"] = models
    verifier["selected_model"] = model_id
    verifier["enabled"] = True
    verifier["updated_at"] = _now()
    config["risk_verifier"] = verifier
    config["updated_at"] = _now()
    _write_config(config)
    return {"ok": True, "message": "风控复核模型已保存。", "config": _public_config(config)}


def update_usage_policy(updates: dict) -> dict:
    config = _read_config_raw()
    policy = config.get("usage_policy") or {}
    allowed = {
        "default_temperature",
        "timeout_seconds",
        "max_context_events",
        "allow_live_trading_decision",
        "require_risk_review",
    }
    for key, value in (updates or {}).items():
        if key in allowed:
            policy[key] = value
    if isinstance((updates or {}).get("task_policies"), dict):
        task_policies = _merge_task_policies(policy.get("task_policies"))
        for task_key, task_updates in updates["task_policies"].items():
            if task_key not in task_policies or not isinstance(task_updates, dict):
                continue
            for field in ("temperature", "timeout_seconds", "max_context_events"):
                if field in task_updates:
                    task_policies[task_key][field] = task_updates[field]
        policy["task_policies"] = _merge_task_policies(task_policies)
    config["usage_policy"] = policy
    config["updated_at"] = _now()
    _write_config(config)
    return {"ok": True, "config": _public_config(config)}


def clear_config() -> dict:
    config = _default_config()
    config["updated_at"] = _now()
    _write_config(config)
    return {"ok": True, "config": _public_config(config)}
