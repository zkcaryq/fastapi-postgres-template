"""请求 ID：让客户端报错时可以关联到具体一条日志。

生产环境里客户端经常只看到"500 错误，请联系管理员"。
把 ID 同时写进响应头 ``X-Request-ID`` 与每条日志，运维只需要这一个 ID
就能 grep 到完整调用链。

实现为纯 ASGI 中间件，不继承 ``BaseHTTPMiddleware``：后者会新建 Task
并多一次消息通道往返，对 SSE / WebSocket / BackgroundTask 也有边缘行为差异。
纯 ASGI 只在 ASGI 消息层面工作，不碰 FastAPI 内部结构，也不需要 Starlette
的 Request / Response 对象。
"""

import contextvars
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
_ENCODED_HEADER = REQUEST_ID_HEADER.lower().encode("latin-1")

# ContextVar 在 async 上下文自动传递；中途切换线程/任务也不会丢。
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def current_request_id() -> str:
    """读取当前请求的 ID；非请求上下文返回 '-'。"""
    return _request_id_var.get()


def set_request_id(value: str) -> None:
    _request_id_var.set(value)


def reset_request_id(token: contextvars.Token[str]) -> None:
    _request_id_var.reset(token)


class RequestIdMiddleware:
    """生成或透传 ``X-Request-ID``，并保证日志/响应/上下文三者一致。

    任意公网客户端都可以自己提供合法格式的 ``X-Request-ID``，
    因此这里只做“格式合法”校验，不做信任判断：过滤掉超长或非可见 ASCII
    防止日志被污染，其余情况原样使用上游 ID 便于跨服务串联。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # 非 HTTP（lifespan / websocket）没有响应头可写，原样透传。
            await self.app(scope, receive, send)
            return

        incoming = _header(scope.get("headers"), _ENCODED_HEADER)
        rid = incoming if _is_valid_request_id(incoming) else uuid.uuid4().hex
        token = _request_id_var.set(rid)
        try:
            await self.app(scope, receive, _patch_response(send))
        finally:
            _request_id_var.reset(token)


def _patch_response(send: Send) -> Send:
    """在响应头上始终写入当前 contextvar 里的 request_id。

    这里**强制覆盖**而不是“已有同名头就不写”：业务代码可能写过自己的值，
    但运维关联日志只能依赖一个权威来源。contextvar 是这一来源，
    与 ``logger`` 的 ``request_id`` 字段、异常处理器的 ``request_id`` 字段
    一一对应。
    """

    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            rid = _request_id_var.get().encode("latin-1")
            headers = [
                (key, value)
                for key, value in (message.get("headers") or [])
                if bytes(key).lower() != _ENCODED_HEADER
            ]
            headers.append((REQUEST_ID_HEADER.encode("latin-1"), rid))
            message["headers"] = headers
        await send(message)

    return send_wrapper


def _header(headers, wanted: bytes) -> str:
    if not headers:
        return ""
    for key, value in headers:
        if bytes(key).lower() == wanted:
            return value.decode("latin-1")
    return ""


def _is_valid_request_id(value: str) -> bool:
    """格式合法即可：可见 ASCII，最长 64 字节。"""
    if not value or len(value) > 64:
        return False
    return all(0x21 <= ord(char) <= 0x7E for char in value)
