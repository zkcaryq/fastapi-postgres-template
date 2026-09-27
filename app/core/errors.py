"""未捕获异常的统一出口：给客户端一个可追踪、但不泄密的 500 响应。

这里不用 @app.exception_handler(Exception)，因为 Starlette 会把 Exception 处理器
挂到 ServerErrorMiddleware——它在所有用户中间件的最外层，
拿不到 RequestIdMiddleware 设置的 request_id contextvar（实测只能读到 '-'）。
改成中间件后，只要它比 RequestIdMiddleware 更靠内层，500 响应里就有正确的 request_id。

HTTPException 由 Starlette 的 ExceptionMiddleware 处理成对应状态码，不会传播到这里；
能到达这里的都是真正的意外错误。
"""
# ↑ 模块 docstring：解释这个中间件是"兜底"——捕获所有没被处理的意外异常，
#   统一返回 500，同时带上 request_id 方便排障。还解释了为什么不用 FastAPI 的
#   exception_handler（那会拿不到 request_id）。

# 导入 logging 标准库：用于记录错误日志。
import logging

# 导入 uuid 标准库：用于给每次错误生成唯一 error_id。
import uuid

# 从 Starlette 导入 JSONResponse。
from starlette.responses import JSONResponse

# 从 Starlette 导入 ASGI 类型标注。
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# 从项目自己的模块导入请求 ID 相关的常量和函数。
from app.core.request_id import REQUEST_ID_HEADER, current_request_id

logger = logging.getLogger(__name__)
# ↑ 创建一个日志器，名字是当前模块名（app.core.errors）。


class UnexpectedErrorMiddleware:
    # ↑ 未捕获异常中间件类。

    def __init__(self, app: ASGIApp) -> None:
        # ↑ 初始化：保存内层应用。
        self.app = app
        # ↑ 保存内层应用。

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # ↑ ASGI 入口。

        if scope["type"] != "http":
            # ↑ 非 HTTP 请求……
            await self.app(scope, receive, send)
            # ↑ 直接透传。
            return
            # ↑ 结束。

        started = False
        # ↑ 标记响应是否已开始。

        async def tracking_send(message: Message) -> None:
            # ↑ 包装 send，跟踪响应是否开始。
            nonlocal started
            # ↑ 声明修改外层的 started。
            if message["type"] == "http.response.start":
                # ↑ 响应开始……
                started = True
                # ↑ 标记。
            await send(message)
            # ↑ 转发。

        try:
            # ↑ 尝试调用内层应用。
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # 捕获所有异常本来就是这里的目的。
            # ↑ 捕获一切异常（这就是兜底中间件存在的意义）。
            if started:
                # ↑ 如果响应已经开始了（状态码已发）……
                # 响应已经开始，状态码改不了；交给外层，不要伪造一个 500。
                raise
                # ↑ 往上抛，交给更外层处理。
            await error_response(scope, receive, send, exc)
            # ↑ 否则，用统一格式返回 500。


async def error_response(scope: Scope, receive: Receive, send: Send, exc: Exception) -> None:
    # ↑ 构造并发送 500 错误响应的函数。

    """响应里同时返回 error_id 与 request_id：error_id 是这一次的 UUID，
    request_id 与响应头 X-Request-ID 一致，便于客户端与日志双向关联。
    """
    # ↑ docstring 说明两个 ID 的用途。

    rid = current_request_id()
    # ↑ 取出当前请求 ID（对应 X-Request-ID 响应头）。
    error_id = uuid.uuid4().hex
    # ↑ 生成一个本次错误独有的 error_id（32 位十六进制）。

    logger.error(
        # ↑ 记录一条 ERROR 级别日志。
        "unhandled_error request_id=%s error_id=%s method=%s path=%s",
        # ↑ 日志模板：%s 是占位符，后面按顺序填入。
        rid,
        # ↑ 请求 ID。
        error_id,
        # ↑ 错误 ID。
        scope.get("method"),
        # ↑ HTTP 方法（GET/POST 等）。
        scope.get("path"),
        # ↑ 请求路径。
        exc_info=exc,
        # ↑ 把异常信息也附上（但日志格式化器只记类型和位置，不记异常值）。
    )
    response = JSONResponse(
        # ↑ 构造 JSON 响应。
        {"detail": "Internal server error", "error_id": error_id, "request_id": rid},
        # ↑ 响应体：固定的"服务器内部错误"提示 + error_id + request_id。
        #   注意：不返回任何异常细节，防止泄露内部信息。
        status_code=500,
        # ↑ 状态码 500。
        headers={REQUEST_ID_HEADER: rid},
        # ↑ 响应头带上 X-Request-ID。
    )
    await response(scope, receive, send)
    # ↑ 发出响应。
