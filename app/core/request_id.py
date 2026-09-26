"""请求 ID：让客户端报错时可以关联到具体一条日志。

生产环境里客户端经常只看到"500 错误，请联系管理员"。
把 ID 同时写进响应头 X-Request-ID 与每条日志，运维只需要这一个 ID 就能 grep 到完整调用链。

实现为纯 ASGI 中间件，不继承 BaseHTTPMiddleware：后者会新建 Task 并多一次消息通道往返，
对 SSE / WebSocket / BackgroundTask 也有边缘行为差异。纯 ASGI 只在 ASGI 消息层面工作，
不碰 FastAPI 内部结构，也不需要 Starlette 的 Request / Response 对象。
"""

import contextvars
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_ENCODED_HEADER = REQUEST_ID_HEADER.lower().encode("latin-1")

# ContextVar 在 async 上下文自动传递；中途切换线程/任务也不会丢。
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def current_request_id() -> str:
    """读取当前请求的 ID；非请求上下文返回 '-'。"""
    return _request_id_var.get()


def set_request_id(value: str) -> None:
    _request_id_var.set(value)


def reset_request_id(token: contextvars.Token[str]) -> None:
    _request_id_var.reset(token)


class RequestIdMiddleware:
    """优先信任上游网关 / 客户端传入的 X-Request-ID，便于跨服务串联。

    没有或不可信则生成 32 位 hex；响应总是回写同一个值。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # 非 HTTP（lifespan / websocket）没有响应头可写，原样透传。
            await self.app(scope, receive, send)
            return

        incoming = _header(scope.get("headers"), _ENCODED_HEADER)
        rid = incoming if _is_trusted(incoming) else uuid.uuid4().hex
        token = _request_id_var.set(rid)
        try:
            await self.app(scope, receive, _patch_response(send, rid))
        finally:
            _request_id_var.reset(token)


def _patch_response(send: Send, rid: str) -> Send:
    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            # 应用可能自己写过 X-Request-ID；已有同名头时不覆盖。
            keys = {bytes(key).lower() for key, _ in message.get("headers") or ()}
            if _ENCODED_HEADER not in keys:
                message["headers"] = [
                    *(message.get("headers") or []),
                    (REQUEST_ID_HEADER.encode("latin-1"), rid.encode("latin-1")),
                ]
        await send(message)

    return send_wrapper


def _header(headers, wanted: bytes) -> str:
    if not headers:
        return ""
    for key, value in headers:
        if bytes(key).lower() == wanted:
            return value.decode("latin-1")
    return ""


def _is_trusted(value: str) -> bool:
    """防止上游伪造超长或非 ASCII 字符撑爆日志；最多保留 64 字节可见 ASCII。"""
    if not value or len(value) > 64:
        return False
    # 仅可见 ASCII；中文 / 控制字符 / 不可见字符一律丢弃后重新生成。
    return all(0x21 <= ord(char) <= 0x7E for char in value)
