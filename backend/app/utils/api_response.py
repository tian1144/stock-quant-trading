"""Unified API response helpers for /api/v1 endpoints."""

from __future__ import annotations

import json

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


ERROR_MESSAGES = {
    400: ("BAD_REQUEST", "请求参数不正确。"),
    401: ("UNAUTHORIZED", "请先登录，或检查 API Key 是否正确。"),
    403: ("FORBIDDEN", "没有权限执行该操作。"),
    404: ("NOT_FOUND", "请求的数据不存在。"),
    408: ("REQUEST_TIMEOUT", "请求超时，请稍后重试。"),
    422: ("VALIDATION_ERROR", "请求参数格式不正确。"),
    429: ("RATE_LIMITED", "请求过于频繁，请稍后重试。"),
    500: ("INTERNAL_ERROR", "服务器内部异常，请稍后重试。"),
}


def api_code_for_status(status_code: int) -> str:
    return ERROR_MESSAGES.get(int(status_code or 500), ("HTTP_ERROR", "请求失败。"))[0]


def api_message_for_status(status_code: int) -> str:
    return ERROR_MESSAGES.get(int(status_code or 500), ("HTTP_ERROR", "请求失败。"))[1]


def error_code_from_message(message: str, status_code: int = 500) -> str:
    text = str(message or "").lower()
    if "http 401" in text or " 401" in text:
        return "UNAUTHORIZED"
    if "http 403" in text or " 403" in text:
        return "FORBIDDEN"
    if "http 429" in text or " 429" in text:
        return "RATE_LIMITED"
    if "http 500" in text or " 500" in text or "http 502" in text or "http 503" in text:
        return "UPSTREAM_SERVER_ERROR"
    if "api key" in text or "密钥" in text or "key缺失" in text:
        return "AI_API_KEY_MISSING"
    if "base url" in text or "url" in text or "地址" in text:
        return "AI_BASE_URL_ERROR"
    if "timeout" in text or "timed out" in text or "超时" in text:
        return "REQUEST_TIMEOUT"
    if "股票代码" in message and ("缺少" in message or "请输入" in message):
        return "MISSING_STOCK_CODE"
    if "不存在" in message:
        return "STOCK_NOT_FOUND"
    if "行情" in message:
        return "MARKET_API_ERROR"
    if "K线" in message or "k线" in text:
        return "KLINE_API_ERROR"
    return api_code_for_status(status_code)


def api_error(message: str, code: str = "", status_code: int = 400, data=None) -> JSONResponse:
    error_message = message or api_message_for_status(status_code)
    return JSONResponse(
        status_code=status_code,
        content={
            "ok": False,
            "success": False,
            "data": data,
            "message": error_message,
            "error": error_message,
            "code": code or error_code_from_message(error_message, status_code),
        },
    )


def _looks_like_error_code(value) -> bool:
    text = str(value or "")
    return bool(text) and text.upper() == text and "_" in text and not text.isdigit()


def normalize_api_payload(payload, status_code: int):
    if isinstance(payload, dict):
        if "success" in payload and "code" in payload and "message" in payload and "data" in payload:
            return payload
        failed = (
            status_code >= 400
            or payload.get("ok") is False
            or payload.get("success") is False
            or ("error" in payload and payload.get("ok") is not True and payload.get("success") is not True)
        )
        message = payload.get("error") or payload.get("detail") or payload.get("message")
        if failed:
            error_message = str(message or api_message_for_status(status_code))
            return {
                **payload,
                "ok": False,
                "success": False,
                "data": None,
                "message": error_message,
                "error": payload.get("error") or error_message,
                "code": payload.get("code") if _looks_like_error_code(payload.get("code")) else error_code_from_message(error_message, status_code),
            }
        data_value = payload["data"] if "data" in payload else payload
        return {
            **payload,
            "success": True,
            "data": data_value,
            "message": str(message or "ok"),
            "code": "OK",
        }
    if status_code >= 400:
        return {
            "success": False,
            "data": None,
            "message": api_message_for_status(status_code),
            "code": api_code_for_status(status_code),
        }
    return {"success": True, "data": payload, "message": "ok", "code": "OK"}


def install_api_response_handlers(app, logger):
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else json.dumps(exc.detail, ensure_ascii=False)
        return api_error(detail, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        missing_code = any((err.get("loc") or [])[-1] in ("code", "stock_code") for err in exc.errors())
        message = "缺少股票代码或请求参数格式不正确。" if missing_code else "请求参数格式不正确。"
        return api_error(message, code="MISSING_STOCK_CODE" if missing_code else "VALIDATION_ERROR", status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception("unhandled api exception: %s %s", request.method, request.url.path)
        return api_error("服务器内部异常，请稍后重试。", code="INTERNAL_ERROR", status_code=500)

    @app.middleware("http")
    async def api_response_format_middleware(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path or ""
        if path == "/api/v1/integrations/feishu/events":
            return response
        if not path.startswith("/api/v1/"):
            return response
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type.lower():
            return response
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            payload = json.loads(body.decode("utf-8") or "null")
        except Exception:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "data": None,
                    "message": "接口返回不是有效 JSON。",
                    "code": "INVALID_JSON_RESPONSE",
                },
            )
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return JSONResponse(status_code=response.status_code, content=normalize_api_payload(payload, response.status_code), headers=headers)
