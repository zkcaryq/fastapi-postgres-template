"""请求 ID：让客户端报错时可以关联到具体一条日志。

生产环境里客户端经常只看到"500 错误，请联系管理员"。
把 ID 同时写进响应头 ``X-Request-ID`` 与每条日志，运维只需要这一个 ID
就能 grep 到完整调用链。

实现为纯 ASGI 中间件，不继承 ``BaseHTTPMiddleware``：后者会新建 Task
并多一次消息通道往返，对 SSE / WebSocket / BackgroundTask 也有边缘行为差异。
纯 ASGI 只在 ASGI 消息层面工作，不碰 FastAPI 内部结构，也不需要 Starlette
的 Request / Response 对象。
"""
# ↑ 模块 docstring：解释这个文件的作用（给每个请求一个唯一 ID，串联日志），
#   以及为什么用"纯 ASGI 中间件"而不是 Starlette 的 BaseHTTPMiddleware。

# 导入 contextvars 标准库：提供 ContextVar，用于在异步任务间安全地传递"当前上下文"变量。
import contextvars

# 导入 uuid 标准库：用于生成全局唯一的 ID。
import uuid

# 从 Starlette（FastAPI 底层依赖的 Web 框架）导入 ASGI 相关的类型标注。
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# ↑ ASGIApp：ASGI 应用；Message：ASGI 消息；Receive/Send：收发消息的函数类型；
#   Scope：请求的元信息字典（类型、路径、请求头等）。

REQUEST_ID_HEADER = "X-Request-ID"
# ↑ 定义请求 ID 的响应头名称常量（字符串 "X-Request-ID"）。
_ENCODED_HEADER = REQUEST_ID_HEADER.lower().encode("latin-1")
# ↑ 把请求头名转小写并编码成字节。ASGI 里请求头都是"小写字节串"形式，
#   所以要预先转好，方便后面做对比。

# ContextVar 在 async 上下文自动传递；中途切换线程/任务也不会丢。
# ↑ 设计说明：ContextVar 是"上下文变量"，在异步代码里切换任务时值不会串。
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
# ↑ 创建一个 ContextVar，名字叫 "request_id"，默认值是 "-"。
#   它用来存放"当前请求的 ID"，每个请求进来时会被覆盖成自己的值。


def current_request_id() -> str:
    # ↑ 读取"当前请求的 ID"的函数（日志模块会调用它）。

    """读取当前请求的 ID；非请求上下文返回 '-'。"""
    return _request_id_var.get()
    # ↑ 从 ContextVar 里取值。如果不在请求上下文里，返回默认值 "-"。


def set_request_id(value: str) -> None:
    # ↑ 设置当前请求 ID 的函数。
    _request_id_var.set(value)
    # ↑ 把传入的值写进 ContextVar。


def reset_request_id(token: contextvars.Token[str]) -> None:
    # ↑ 恢复请求 ID 的函数。参数 token 是 set() 时返回的"令牌"。
    _request_id_var.reset(token)
    # ↑ 用令牌把 ContextVar 恢复到 set 之前的值（请求结束后清理用）。


class RequestIdMiddleware:
    # ↑ 请求 ID 中间件类。

    """生成或透传 ``X-Request-ID``，并保证日志/响应/上下文三者一致。

    任意公网客户端都可以自己提供合法格式的 ``X-Request-ID``，
    因此这里只做"格式合法"校验，不做信任判断：过滤掉超长或非可见 ASCII
    防止日志被污染，其余情况原样使用上游 ID 便于跨服务串联。
    """

    # ↑ 类 docstring：说明它要么生成新 ID、要么透传客户端给的合法 ID。

    def __init__(self, app: ASGIApp) -> None:
        # ↑ 初始化：ASGI 中间件的固定写法，接收"下一个要调用的应用"。
        self.app = app
        # ↑ 保存内层应用（可能是一层中间件，也可能是最终的路由）。

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # ↑ 让这个类的实例可以像函数一样被调用（ASGI 中间件的核心协议）。
        #   scope：请求信息；receive：收请求体；send：发响应。

        if scope["type"] != "http":
            # ↑ 如果不是 HTTP 请求（比如是 lifespan 启动事件或 websocket）……
            # 非 HTTP（lifespan / websocket）没有响应头可写，原样透传。
            await self.app(scope, receive, send)
            # ↑ 直接转给内层应用，不做任何处理。
            return
            # ↑ 提前结束，后面的 HTTP 逻辑不执行。

        incoming = _header(scope.get("headers"), _ENCODED_HEADER)
        # ↑ 从请求头里找有没有客户端自己带来的 X-Request-ID。
        rid = incoming if _is_valid_request_id(incoming) else uuid.uuid4().hex
        # ↑ 如果客户端给的 ID 合法，就用它；否则生成一个新的随机 ID（uuid4 的 hex 是 32 位十六进制）。
        token = _request_id_var.set(rid)
        # ↑ 把最终确定的 ID 写入 ContextVar，并保存 token（用于后面恢复）。
        try:
            # ↑ 开始真正处理请求。
            await self.app(scope, receive, _patch_response(send))
            # ↑ 调用内层应用，但把 send 换成"包装过的 send"（见 _patch_response），
            #   目的是在响应头上自动补上 X-Request-ID。
        finally:
            # ↑ 无论成功失败，最后都要执行。
            _request_id_var.reset(token)
            # ↑ 把 ContextVar 恢复成进入请求前的值，避免污染下一个请求。


def _patch_response(send: Send) -> Send:
    # ↑ 包装 send 函数，使得响应发出时自动带上 X-Request-ID 响应头。

    """在响应头上始终写入当前 contextvar 里的 request_id。

    这里**强制覆盖**而不是"已有同名头就不写"：业务代码可能写过自己的值，
    但运维关联日志只能依赖一个权威来源。contextvar 是这一来源，
    与 ``logger`` 的 ``request_id`` 字段、异常处理器的 ``request_id`` 字段
    一一对应。
    """
    # ↑ docstring：说明为什么是"强制覆盖"而不是"没有才写"。

    async def send_wrapper(message: Message) -> None:
        # ↑ 定义包装后的 send 函数（闭包），替换原 send。
        if message["type"] == "http.response.start":
            # ↑ 只有当消息是"响应开始"（此时才能写响应头）时才处理。
            rid = _request_id_var.get().encode("latin-1")
            # ↑ 取出当前请求 ID，编码成字节（响应头必须是字节）。
            headers = [
                # ↑ 重新构造响应头列表。
                (key, value)
                for key, value in (message.get("headers") or [])
                if bytes(key).lower() != _ENCODED_HEADER
                # ↑ 保留原有响应头，但把其中任何已存在的 X-Request-ID 过滤掉。
            ]
            headers.append((REQUEST_ID_HEADER.encode("latin-1"), rid))
            # ↑ 在末尾追加我们自己的 X-Request-ID（实现"强制覆盖"）。
            message["headers"] = headers
            # ↑ 把新响应头写回消息。
        await send(message)
        # ↑ 调用真正的 send 把消息发出去。

    return send_wrapper
    # ↑ 返回包装后的 send 函数给内层应用使用。


def _header(headers, wanted: bytes) -> str:
    # ↑ 辅助函数：从请求头列表里找指定名称的值，返回字符串；找不到返回空串。

    if not headers:
        # ↑ 如果请求头列表为空……
        return ""
        # ↑ 直接返回空字符串。
    for key, value in headers:
        # ↑ 遍历每个请求头（key=名称，value=值）。
        if bytes(key).lower() == wanted:
            # ↑ 如果名称（转小写字节）等于我们要找的……
            return value.decode("latin-1")
            # ↑ 把值解码成字符串返回。
    return ""
    # ↑ 遍历完没找到，返回空字符串。


def _is_valid_request_id(value: str) -> bool:
    # ↑ 校验请求 ID 是否"格式合法"。

    """格式合法即可：可见 ASCII，最长 64 字节。"""
    if not value or len(value) > 64:
        # ↑ 空值，或长度超过 64，都算非法。
        return False
        # ↑ 返回"不合法"。
    return all(0x21 <= ord(char) <= 0x7E for char in value)
    # ↑ 检查每个字符的 ASCII 码是否在 0x21~0x7E（可见字符，不含空格和控制字符）。
    #   all() 表示"全部满足才返回 True"。
