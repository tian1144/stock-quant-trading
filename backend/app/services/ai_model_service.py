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
        "name": "OpenAI官方",
        "protocol": "openai_compatible",
        "mode": "official",
        "default_base_url": "https://api.openai.com/v1",
        "models_path": "/models",
        "auth": "bearer",
        "notes": "官方模式：OpenAI API，推荐 Base URL 为 https://api.openai.com/v1。",
    },
    "openai_compatible": {
        "name": "第三方中转/兼容网关",
        "protocol": "openai_compatible",
        "mode": "compatible",
        "default_base_url": "",
        "models_path": "/models",
        "auth": "bearer",
        "notes": "兼容模式：适配第三方中转站、OpenRouter、DeepSeek兼容接口和大多数 /v1/chat/completions 网关。",
    },
    "anthropic": {
        "name": "Claude官方",
        "protocol": "anthropic",
        "mode": "official",
        "default_base_url": "https://api.anthropic.com/v1",
        "models_path": "/models",
        "auth": "x_api_key",
        "notes": "官方模式：Claude Messages 接口，使用 x-api-key 和 anthropic-version 请求头。",
    },
    "gemini": {
        "name": "Gemini官方",
        "protocol": "gemini",
        "mode": "official",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "models_path": "/models",
        "auth": "query_key",
        "notes": "官方模式：Gemini generateContent 接口，密钥通过 key 查询参数传递。",
    },
    "custom": {
        "name": "自定义兼容接口",
        "protocol": "openai_compatible",
        "mode": "compatible",
        "default_base_url": "",
        "models_path": "/models",
        "auth": "bearer",
        "notes": "自定义兼容：用于其他支持 OpenAI 兼容格式的接口。",
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
        "description": "快速识别新闻中的利好、利空、板块归因和噪音。",
    },
    "deep_analysis": {
        "name": "深度研判",
        "temperature": 0.18,
        "timeout_seconds": 75,
        "max_context_events": 80,
        "description": "综合新闻、公告、行情、板块、资金和技术结构做高质量研判。",
    },
    "task_planning": {
        "name": "小窗任务规划",
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
        config["chat_assistant"] = {
            **_default_config().get("chat_assistant", {}),
            **((data or {}).get("chat_assistant") or {}),
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
        "chat_assistant": {
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
    assistant = public.get("chat_assistant") or {}
    if isinstance(assistant, dict):
        assistant_public = {k: v for k, v in assistant.items() if k != "api_key"}
        assistant_public["api_key_masked"] = mask_key(assistant.get("api_key", ""))
        assistant_public["has_api_key"] = bool(assistant.get("api_key"))
        assistant_provider = assistant.get("provider") or "openai_compatible"
        assistant_public["fallback_to_main"] = not bool(
            assistant.get("enabled")
            and assistant.get("api_key")
            and assistant.get("selected_model")
            and (assistant.get("base_url") or PROVIDERS.get(assistant_provider, {}).get("default_base_url"))
        )
        public["chat_assistant"] = assistant_public
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


def _profile_defaults(profile: str) -> dict:
    defaults = _default_config()
    if profile in ("risk_verifier", "chat_assistant"):
        return defaults.get(profile, {})
    return {
        "enabled": defaults.get("enabled", False),
        "provider": defaults.get("provider", ""),
        "provider_name": defaults.get("provider_name", ""),
        "base_url": defaults.get("base_url", ""),
        "api_key": defaults.get("api_key", ""),
        "selected_model": defaults.get("selected_model", ""),
        "available_models": defaults.get("available_models", []),
        "last_detected_at": defaults.get("last_detected_at"),
        "last_status": defaults.get("last_status", "not_configured"),
        "last_error": defaults.get("last_error", ""),
    }


def _get_profile_config(config: dict, profile: str = "main", fallback_main: bool = True) -> Tuple[dict, str]:
    if profile in ("risk_verifier", "chat_assistant"):
        entry = {**_profile_defaults(profile), **(config.get(profile) or {})}
        if _profile_ready(entry):
            return entry, profile
        if not fallback_main:
            return entry, profile
    main = {
        "enabled": config.get("enabled", False),
        "provider": config.get("provider") or "openai_compatible",
        "provider_name": config.get("provider_name") or PROVIDERS["openai_compatible"]["name"],
        "base_url": config.get("base_url", ""),
        "api_key": config.get("api_key", ""),
        "selected_model": config.get("selected_model", ""),
        "available_models": config.get("available_models", []),
        "last_detected_at": config.get("last_detected_at"),
        "last_status": config.get("last_status", "not_configured"),
        "last_error": config.get("last_error", ""),
    }
    return main, "main"


def _profile_ready(entry: dict) -> bool:
    provider = entry.get("provider") or "openai_compatible"
    has_url = bool(entry.get("base_url") or PROVIDERS.get(provider, {}).get("default_base_url"))
    return bool(entry.get("enabled") and entry.get("api_key") and entry.get("selected_model") and has_url)


def update_chat_assistant_config(
    provider: str = "",
    base_url: str = "",
    api_key: str = "",
    selected_model: str = "",
    enabled: Optional[bool] = None,
) -> dict:
    config = _read_config_raw()
    assistant = {**_default_config()["chat_assistant"], **(config.get("chat_assistant") or {})}
    provider_id = provider if provider in PROVIDERS else (assistant.get("provider") or "openai_compatible")
    normalized_url = (base_url or "").strip().rstrip("/")
    if normalized_url and not normalized_url.startswith(("http://", "https://")):
        normalized_url = "https://" + normalized_url
    if normalized_url.endswith("/models"):
        normalized_url = normalized_url[: -len("/models")]

    assistant["provider"] = provider_id
    assistant["provider_name"] = PROVIDERS[provider_id]["name"]
    if normalized_url:
        assistant["base_url"] = normalized_url
    elif not assistant.get("base_url"):
        assistant["base_url"] = ""
    if api_key and "..." not in api_key:
        assistant["api_key"] = api_key
    selected_model = (selected_model or "").strip()
    if selected_model:
        assistant["selected_model"] = selected_model
        models = assistant.get("available_models") or []
        known_ids = {m.get("id") for m in models if isinstance(m, dict)}
        if selected_model not in known_ids:
            models.append({
                "id": selected_model,
                "name": selected_model,
                "owned_by": "manual",
                "provider": provider_id,
            })
            assistant["available_models"] = models
    if enabled is not None:
        assistant["enabled"] = bool(enabled)
    assistant["updated_at"] = _now()
    config["chat_assistant"] = assistant
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


def _model_base_url_candidates(base_url: str, provider: str) -> List[str]:
    candidates = [base_url.rstrip("/")]
    protocol = PROVIDERS.get(provider, PROVIDERS["openai_compatible"]).get("protocol", "openai_compatible")
    parsed = urlparse(candidates[0])
    path = (parsed.path or "").rstrip("/")
    if protocol == "openai_compatible" and path in ("", "/"):
        candidates.append(f"{candidates[0]}/v1")
    unique = []
    for item in candidates:
        if item and item not in unique:
            unique.append(item)
    return unique


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


def _completion_url(base_url: str, provider: str, model: str = "", api_key: str = "") -> str:
    meta = PROVIDERS.get(provider, PROVIDERS["openai_compatible"])
    protocol = meta.get("protocol", "openai_compatible")
    value = (base_url or meta.get("default_base_url") or "").strip().rstrip("/")
    if not value:
        raise ValueError("请先配置模型接口地址")
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    if value.endswith("/models"):
        value = value[: -len("/models")]
    if protocol == "anthropic":
        return value if value.endswith("/messages") else f"{value}/messages"
    if protocol == "gemini":
        clean_model = (model or "").strip()
        if clean_model.startswith("models/"):
            clean_model = clean_model[len("models/") :]
        url = value if ":generateContent" in value else f"{value}/models/{clean_model}:generateContent"
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}key={api_key}"
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def _chat_request_json(
    provider: str,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float,
    json_mode: bool = False,
) -> dict:
    protocol = PROVIDERS.get(provider, PROVIDERS["openai_compatible"]).get("protocol", "openai_compatible")
    if protocol == "anthropic":
        prompt = user_content
        if json_mode:
            prompt += "\n\nReturn only a valid JSON object. Do not include markdown fences."
        return {
            "model": model,
            "max_tokens": 4096,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
    if protocol == "gemini":
        prompt = user_content
        if json_mode:
            prompt += "\n\nReturn only a valid JSON object. Do not include markdown fences."
        return {
            "generationConfig": {"temperature": temperature},
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
    payload = {
        "model": model,
        "temperature": temperature,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    return payload


def _chat_response_text(payload: dict, provider: str) -> str:
    protocol = PROVIDERS.get(provider, PROVIDERS["openai_compatible"]).get("protocol", "openai_compatible")
    if protocol == "anthropic":
        parts = payload.get("content") or []
        texts = []
        for part in parts:
            if isinstance(part, dict):
                text = part.get("text")
                if text:
                    texts.append(str(text))
        return "\n".join(texts).strip()
    if protocol == "gemini":
        candidates = payload.get("candidates") or []
        parts = (((candidates[0] if candidates else {}).get("content") or {}).get("parts") or [])
        return "\n".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
    return (((payload.get("choices") or [{}])[0].get("message") or {}).get("content", "") or "").strip()


def _post_chat_completion(
    entry: dict,
    task_key: str,
    system_prompt: str,
    user_content: str,
    temperature: float,
    timeout: int,
    json_mode: bool = False,
) -> Tuple[Optional[str], dict]:
    provider = entry.get("provider") or "openai_compatible"
    model = entry.get("selected_model") or ""
    try:
        response = requests.post(
            _completion_url(entry.get("base_url", ""), provider, model, entry.get("api_key", "")),
            headers={**_headers(provider, entry.get("api_key", "")), "Content-Type": "application/json"},
            json=_chat_request_json(provider, model, system_prompt, user_content, temperature, json_mode=json_mode),
            timeout=timeout,
        )
        if response.status_code >= 400:
            return None, {
                "ok": False,
                "used_ai": False,
                "provider": provider,
                "model": model,
                "task_key": task_key,
                "error": f"模型调用失败：HTTP {response.status_code} {response.text[:300]}",
            }
        try:
            payload = response.json()
        except ValueError:
            return None, {
                "ok": False,
                "used_ai": False,
                "provider": provider,
                "model": model,
                "task_key": task_key,
                "error": (
                    "Model endpoint returned non-JSON. Check whether the Base URL needs /v1. "
                    f"content-type={response.headers.get('content-type', 'unknown')}; "
                    f"preview={_response_preview(response)}"
                ),
            }
        text = _chat_response_text(payload, provider)
        return text, {
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


def chat_json(task_key: str, system_prompt: str, user_payload: dict, schema_hint: str = "", profile: str = "main") -> Tuple[Optional[dict], dict]:
    """Call a configured model profile and parse a JSON object."""
    config = _read_config_raw()
    entry, role = _get_profile_config(config, profile, fallback_main=True)
    if not _profile_ready(entry):
        return None, {"ok": False, "used_ai": False, "role": role, "error": "AI模型尚未配置或未启用"}

    provider = entry.get("provider") or "openai_compatible"
    model = entry.get("selected_model") or ""
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
        content += "\n\n请严格按这个 JSON 结构返回，不要输出解释文字：\n" + schema_hint

    try:
        message, meta = _post_chat_completion(entry, task_key, system_prompt, content, temperature, timeout, json_mode=True)
        meta["role"] = role
        if not meta.get("ok"):
            return None, meta
        return _extract_json_object(message or ""), meta
    except Exception as exc:
        return None, {
            "ok": False,
            "used_ai": False,
            "role": role,
            "provider": provider,
            "model": model,
            "task_key": task_key,
            "error": str(exc),
        }


def chat_text(task_key: str, system_prompt: str, user_message: str, context: Optional[dict] = None, profile: str = "main") -> Tuple[str, dict]:
    """Call a configured model profile for ordinary conversation."""
    config = _read_config_raw()
    entry, role = _get_profile_config(config, profile, fallback_main=True)
    if not _profile_ready(entry):
        return "当前还没有启用可用的大模型。请先在“智能模型”页面配置接口地址、密钥并选择模型。", {
            "ok": False,
            "used_ai": False,
            "role": role,
            "error": "AI模型尚未配置或未启用",
        }

    provider = entry.get("provider") or "openai_compatible"
    model = entry.get("selected_model") or ""
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
        answer, meta = _post_chat_completion(
            entry,
            task_key,
            system_prompt,
            f"站内上下文：\n{context_text}\n\n用户问题：\n{user_message}",
            temperature,
            timeout,
        )
        meta["role"] = role
        if not meta.get("ok"):
            return f"模型调用失败：{meta.get('error', '未知错误')}", meta
        return (answer or "").strip() or "模型没有返回有效内容。", meta
    except Exception as exc:
        return f"模型调用异常：{exc}", {
            "ok": False,
            "used_ai": False,
            "role": role,
            "provider": provider,
            "model": model,
            "task_key": task_key,
            "error": str(exc),
        }
def risk_verifier_ready() -> bool:
    verifier = (_read_config_raw().get("risk_verifier") or {})
    return _profile_ready(verifier)


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
        message, meta = _post_chat_completion(verifier, "risk_review", system_prompt, content, 0.03, 55, json_mode=True)
        meta["role"] = "risk_verifier"
        if not meta.get("ok"):
            return None, meta
        return _extract_json_object(message or ""), meta
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


def _model_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _resolve_model_id(selected_model: str, models: List[dict]) -> str:
    selected_model = (selected_model or "").strip()
    if not selected_model:
        return (models[0].get("id") if models else "") or ""
    known = [str(model.get("id") or "") for model in (models or []) if isinstance(model, dict)]
    if selected_model in known:
        return selected_model
    selected_key = _model_key(selected_model)
    for model_id in known:
        if _model_key(model_id) == selected_key:
            return model_id
    return selected_model


def _response_preview(response, limit: int = 180) -> str:
    text = (getattr(response, "text", "") or "").strip()
    if not text:
        return "empty response"
    return re.sub(r"\s+", " ", text)[:limit]


def _parse_models_response_json(response, label: str) -> Tuple[Optional[object], Optional[dict]]:
    try:
        return response.json(), None
    except ValueError:
        content_type = response.headers.get("content-type", "") or "unknown"
        return None, {
            "ok": False,
            "error": f"{label}检测接口返回的不是 JSON，可能该网关不支持 /models。你可以手动填写模型名后保存。",
            "models": [],
            "status_code": response.status_code,
            "content_type": content_type,
            "response_preview": _response_preview(response),
        }


def detect_models(provider: str, base_url: str, api_key: str, save: bool = True) -> dict:
    existing = _read_config_raw()
    api_key = (api_key or "").strip() or existing.get("api_key", "")
    if not api_key:
        return {"ok": False, "error": "请填写 API Key。", "models": []}

    provider_id = _guess_provider(provider, base_url or existing.get("base_url", ""))
    try:
        normalized_url = _normalize_base_url(base_url or existing.get("base_url", ""), provider_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "models": []}

    started = time.time()
    try:
        response = requests.get(_models_url(normalized_url, provider_id, api_key), headers=_headers(provider_id, api_key), timeout=TIMEOUT_SECONDS)
        if response.status_code >= 400:
            return {
                "ok": False,
                "error": f"模型检测失败：HTTP {response.status_code} {response.text[:300]}",
                "models": [],
                "provider": provider_id,
                "base_url": normalized_url,
                "latency_ms": int((time.time() - started) * 1000),
            }
        payload, parse_error = _parse_models_response_json(response, "模型")
        if parse_error:
            parse_error.update({"provider": provider_id, "base_url": normalized_url, "latency_ms": int((time.time() - started) * 1000)})
            return parse_error
        models = _extract_models(payload, provider_id)
        if not models:
            return {
                "ok": False,
                "error": "接口可访问，但没有解析到模型列表。请确认服务是否支持 /models，也可以手动填写模型名后保存。",
                "models": [],
                "provider": provider_id,
                "base_url": normalized_url,
                "latency_ms": int((time.time() - started) * 1000),
            }
        selected = models[0]["id"]
        detected_at = _now()
        result = {
            "ok": True,
            "provider": provider_id,
            "provider_name": PROVIDERS[provider_id]["name"],
            "base_url": normalized_url,
            "models": models,
            "selected_model": selected,
            "model_count": len(models),
            "latency_ms": int((time.time() - started) * 1000),
            "detected_at": detected_at,
            "api_key_masked": mask_key(api_key),
        }
        if save:
            config = _read_config_raw()
            config.update({
                "enabled": True,
                "provider": provider_id,
                "provider_name": PROVIDERS[provider_id]["name"],
                "base_url": normalized_url,
                "api_key": api_key,
                "selected_model": selected,
                "available_models": models,
                "last_detected_at": detected_at,
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
        models.append({"id": model_id, "name": model_id, "owned_by": "manual", "provider": provider or config.get("provider") or "openai_compatible"})
        config["available_models"] = models
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
        response = requests.get(_models_url(normalized_url, provider_id, api_key), headers=_headers(provider_id, api_key), timeout=TIMEOUT_SECONDS)
        if response.status_code >= 400:
            return {"ok": False, "error": f"风控模型检测失败：HTTP {response.status_code} {response.text[:300]}", "models": [], "provider": provider_id, "base_url": normalized_url}
        payload, parse_error = _parse_models_response_json(response, "风控模型")
        if parse_error:
            parse_error.update({"provider": provider_id, "base_url": normalized_url, "latency_ms": int((time.time() - started) * 1000)})
            return parse_error
        models = _extract_models(payload, provider_id)
        if not models:
            return {"ok": False, "error": "接口可访问，但没有解析到风控模型列表。", "models": [], "provider": provider_id, "base_url": normalized_url}
        selected = models[0]["id"]
        detected_at = _now()
        if save:
            verifier.update({
                "enabled": True,
                "provider": provider_id,
                "provider_name": PROVIDERS[provider_id]["name"],
                "base_url": normalized_url,
                "api_key": api_key,
                "selected_model": selected,
                "available_models": models,
                "last_detected_at": detected_at,
                "last_status": "ok",
                "last_error": "",
            })
            config["risk_verifier"] = verifier
            config["updated_at"] = _now()
            _write_config(config)
        return {"ok": True, "provider": provider_id, "provider_name": PROVIDERS[provider_id]["name"], "base_url": normalized_url, "models": models, "selected_model": selected, "model_count": len(models), "latency_ms": int((time.time() - started) * 1000), "detected_at": detected_at, "api_key_masked": mask_key(api_key)}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "风控模型检测超时，请检查 URL、网络或代理。", "models": [], "provider": provider_id, "base_url": normalized_url}
    except Exception as exc:
        return {"ok": False, "error": f"风控模型检测异常：{exc}", "models": [], "provider": provider_id, "base_url": normalized_url}


def select_risk_verifier_model(model_id: str, provider: Optional[str] = None) -> dict:
    config = _read_config_raw()
    verifier = {**_default_config()["risk_verifier"], **(config.get("risk_verifier") or {})}
    models = verifier.get("available_models") or []
    known_ids = {m.get("id") for m in models if isinstance(m, dict)}
    model_id = (model_id or "").strip()
    if not model_id:
        return {"ok": False, "error": "请选择风控复核模型。", "config": _public_config(config)}
    if provider and provider in PROVIDERS:
        verifier["provider"] = provider
        verifier["provider_name"] = PROVIDERS[provider]["name"]
    if model_id not in known_ids:
        models.append({"id": model_id, "name": model_id, "owned_by": "manual", "provider": verifier.get("provider") or provider or "openai_compatible"})
        verifier["available_models"] = models
    verifier["selected_model"] = model_id
    verifier["enabled"] = True
    verifier["updated_at"] = _now()
    config["risk_verifier"] = verifier
    config["updated_at"] = _now()
    _write_config(config)
    return {"ok": True, "message": "风控复核模型已保存。", "config": _public_config(config)}
def _save_manual_chat_assistant_model(config: dict, assistant: dict, provider_id: str, base_url: str, api_key: str, model_id: str) -> dict:
    models = assistant.get("available_models") or []
    known_ids = {m.get("id") for m in models if isinstance(m, dict)}
    if model_id not in known_ids:
        models.append({"id": model_id, "name": model_id, "owned_by": "manual", "provider": provider_id})
    assistant.update({
        "enabled": True,
        "provider": provider_id,
        "provider_name": PROVIDERS[provider_id]["name"],
        "base_url": base_url,
        "api_key": api_key,
        "selected_model": model_id,
        "available_models": models,
        "last_detected_at": _now(),
        "last_status": "manual_model",
        "last_error": "",
    })
    config["chat_assistant"] = assistant
    config["updated_at"] = _now()
    _write_config(config)
    return assistant


def _probe_chat_assistant_model(assistant: dict) -> dict:
    text, meta = _post_chat_completion(assistant, "task_planning", "你是连接测试助手。只回复 ok。", "ping", 0.01, 20)
    return {"ok": bool(meta.get("ok")), "answer": (text or "")[:80], "error": meta.get("error", "")}


def _manual_chat_assistant_detect_result(config: dict, assistant: dict, provider_id: str, base_url: str, api_key: str, selected_model: str, warning: str) -> dict:
    assistant = _save_manual_chat_assistant_model(config, assistant, provider_id, base_url, api_key, selected_model)
    probe = _probe_chat_assistant_model(assistant)
    return {"ok": True, "manual_model_saved": True, "probe": probe, "warning": warning, "provider": provider_id, "provider_name": PROVIDERS[provider_id]["name"], "base_url": base_url, "models": assistant.get("available_models") or [], "selected_model": selected_model, "model_count": 1, "detected_at": assistant.get("last_detected_at"), "api_key_masked": mask_key(api_key)}


def detect_chat_assistant_models(provider: str, base_url: str, api_key: str, selected_model: str = "", save: bool = True) -> dict:
    config = _read_config_raw()
    assistant = {**_default_config()["chat_assistant"], **(config.get("chat_assistant") or {})}
    api_key = (api_key or "").strip() or assistant.get("api_key", "")
    if not api_key:
        return {"ok": False, "error": "请填写小窗AI模型 API Key。", "models": []}
    selected_model = (selected_model or "").strip()
    provider_id = _guess_provider(provider or assistant.get("provider", ""), base_url or assistant.get("base_url", ""))
    try:
        normalized_url = _normalize_base_url(base_url or assistant.get("base_url", ""), provider_id)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "models": []}
    started = time.time()
    try:
        parse_error = None
        models = []
        for candidate_url in _model_base_url_candidates(normalized_url, provider_id):
            response = requests.get(_models_url(candidate_url, provider_id, api_key), headers=_headers(provider_id, api_key), timeout=TIMEOUT_SECONDS)
            if response.status_code >= 400:
                parse_error = {"ok": False, "error": f"Chat assistant model detect failed: HTTP {response.status_code} {_response_preview(response)}", "models": []}
                continue
            payload, parse_error = _parse_models_response_json(response, "Chat assistant model")
            if parse_error:
                continue
            models = _extract_models(payload, provider_id)
            if models:
                normalized_url = candidate_url
                break
        if not models:
            if selected_model and save:
                warning = "No model list was parsed from /models; saved the manual model name."
                if parse_error and parse_error.get("response_preview"):
                    warning = f"{warning} Last response preview: {parse_error.get('response_preview')}"
                return _manual_chat_assistant_detect_result(config, assistant, provider_id, normalized_url, api_key, selected_model, warning)
            if parse_error:
                parse_error.update({"provider": provider_id, "base_url": normalized_url, "latency_ms": int((time.time() - started) * 1000)})
                return parse_error
            return {"ok": False, "error": "The endpoint is reachable, but no chat assistant models were parsed.", "models": [], "provider": provider_id, "base_url": normalized_url}
        selected = _resolve_model_id(selected_model, models)
        detected_at = _now()
        if save:
            assistant.update({"enabled": True, "provider": provider_id, "provider_name": PROVIDERS[provider_id]["name"], "base_url": normalized_url, "api_key": api_key, "selected_model": selected, "available_models": models, "last_detected_at": detected_at, "last_status": "ok", "last_error": ""})
            config["chat_assistant"] = assistant
            config["updated_at"] = _now()
            _write_config(config)
        return {"ok": True, "provider": provider_id, "provider_name": PROVIDERS[provider_id]["name"], "base_url": normalized_url, "models": models, "selected_model": selected, "model_count": len(models), "latency_ms": int((time.time() - started) * 1000), "detected_at": detected_at, "api_key_masked": mask_key(api_key)}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "小窗AI模型检测超时，请检查 URL、网络或代理。", "models": [], "provider": provider_id, "base_url": normalized_url}
    except Exception as exc:
        return {"ok": False, "error": f"小窗AI模型检测异常：{exc}", "models": [], "provider": provider_id, "base_url": normalized_url}


def select_chat_assistant_model(model_id: str, provider: Optional[str] = None) -> dict:
    config = _read_config_raw()
    assistant = {**_default_config()["chat_assistant"], **(config.get("chat_assistant") or {})}
    models = assistant.get("available_models") or []
    known_ids = {m.get("id") for m in models if isinstance(m, dict)}
    model_id = (model_id or "").strip()
    if not model_id:
        return {"ok": False, "error": "请选择小窗AI模型。", "config": _public_config(config)}
    if provider and provider in PROVIDERS:
        assistant["provider"] = provider
        assistant["provider_name"] = PROVIDERS[provider]["name"]
    if model_id not in known_ids:
        models.append({
            "id": model_id,
            "name": model_id,
            "owned_by": "manual",
            "provider": assistant.get("provider") or provider or "openai_compatible",
        })
        assistant["available_models"] = models
    assistant["selected_model"] = model_id
    assistant["enabled"] = True
    assistant["updated_at"] = _now()
    config["chat_assistant"] = assistant
    config["updated_at"] = _now()
    _write_config(config)
    return {"ok": True, "message": "小窗AI模型已保存。", "config": _public_config(config)}


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
