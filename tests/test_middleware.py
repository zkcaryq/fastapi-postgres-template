"""中间件：请求 ID 透传、请求体大小限制，以及真实完整 Middleware Stack 的集成测试。"""
# ↑ 模块 docstring：这是测试中间件行为的文件，重点测三个中间件组合起来是否正确。

# 导入 pytest。
import pytest

# 导入 FastAPI 和相关对象。
from fastapi import FastAPI, HTTPException, Request, Response

# 导入测试客户端。
from fastapi.testclient import TestClient

# 导入要测试的三个中间件。
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.errors import UnexpectedErrorMiddleware
from app.core.request_id import RequestIdMiddleware, _is_valid_request_id


def _build_app(
    # ↑ 辅助函数：构造一个最小测试应用。
    *,
    # ↑ 后面的参数只能用"关键字"方式传（不能按位置传）。
    max_bytes: int = 256,
    # ↑ 请求体上限，默认 256 字节。
    with_unexpected_error: bool = True,
    # ↑ 是否加"异常兜底"中间件。
    with_request_id: bool = True,
    # ↑ 是否加"请求 ID"中间件。
) -> tuple[FastAPI, list[int]]:
    # ↑ 返回应用和"记录路由收到的 body 大小"的列表。

    """构造一个最小 App，附带记录"路由是否被调用"与"路由收到的请求体大小"。

    顺序：最后 add 的最外层。所以参数顺序对应中间件从内到外：
    BodySizeLimit → UnexpectedError → RequestId。
    """
    # ↑ docstring：说明中间件顺序。
    received: list[int] = []
    # ↑ 用列表记录每次路由收到的 body 大小（列表可变，闭包里能改）。

    app = FastAPI()
    # ↑ 创建应用。

    @app.post("/echo")
    # ↑ 定义一个 POST /echo 接口，回显 body 大小。
    async def _echo(request: Request) -> dict[str, int]:
        # ↑ 处理函数。
        body = await request.body()
        # ↑ 读取完整请求体。
        received.append(len(body))
        # ↑ 记录 body 字节数（证明路由被调用了）。
        return {"size": len(body)}
        # ↑ 返回 body 大小。

    @app.get("/boom")
    # ↑ 定义一个会抛异常的接口。
    async def _boom() -> None:
        # ↑ 处理函数。
        raise RuntimeError("boom-should-not-leak")
        # ↑ 抛异常（用于测 500 兜底）。

    @app.get("/missing")
    # ↑ 定义一个抛 404 的接口。
    async def _missing() -> None:
        # ↑ 处理函数。
        raise HTTPException(status_code=404, detail="nope")
        # ↑ 抛 HTTPException（用于测 404 不被吞）。

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    # ↑ 加请求体限制中间件（最内层）。
    if with_unexpected_error:
        # ↑ 如果启用异常兜底……
        app.add_middleware(UnexpectedErrorMiddleware)
        # ↑ 加异常兜底中间件（中间层）。
    if with_request_id:
        # ↑ 如果启用请求 ID……
        app.add_middleware(RequestIdMiddleware)
        # ↑ 加请求 ID 中间件（最外层）。
    return app, received
    # ↑ 返回应用和记录列表。


# ---------------------------------------------------------------------------
# Request ID：合法/非法格式与透传行为
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测请求 ID 的格式校验。


@pytest.mark.parametrize(
    # ↑ 参数化：用多个值分别跑下面的测试。
    "value",
    # ↑ 参数名。
    ["中文-request-id", "line\nbreak", "tab\there", "a" * 65, ""],
    # ↑ 一组"非法"的请求 ID（中文、含换行/制表符、超长、空串）。
)
def test_invalid_request_id_is_replaced(value):
    # ↑ 测试：非法请求 ID 会被判定为不合法。

    assert _is_valid_request_id(value) is False
    # ↑ 断言这些值都不合法。


@pytest.mark.parametrize("value", ["abc-123", "gateway-trace-id", "a" * 64])
# ↑ 参数化：一组"合法"的请求 ID。
def test_valid_request_id_is_preserved(value):
    # ↑ 测试：合法请求 ID 会被保留。

    assert _is_valid_request_id(value) is True
    # ↑ 断言这些值都合法。


def test_request_id_echoes_upstream_value():
    # ↑ 测试：客户端传来的合法请求 ID 会被原样回传。

    app, _ = _build_app()
    # ↑ 构造应用（丢弃记录列表）。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.get("/echo", headers={"X-Request-ID": "upstream-42"})
        # ↑ 请求 /echo（注意是 GET，但 /echo 是 POST，会 405），带请求 ID。
    # 405 因为 /echo 是 POST；我们只要响应头。
    # ↑ 说明：这里故意用 GET 触发 405，只为了看响应头。
    assert response.headers["X-Request-ID"] == "upstream-42"
    # ↑ 断言响应头的请求 ID 等于上游传来的值。


def test_request_id_is_generated_when_missing():
    # ↑ 测试：没传请求 ID 时，会自动生成一个 32 位的。

    app, _ = _build_app()
    # ↑ 构造应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post("/echo", content=b"x")
        # ↑ 正常 POST（不带头）。
    rid = response.headers["X-Request-ID"]
    # ↑ 取出响应头的请求 ID。
    assert len(rid) == 32
    # ↑ 断言长度 32。
    int(rid, 16)  # 32 位 hex
    # ↑ 断言它是十六进制（能转成 int 即证明是 hex 字符；不是则抛异常）。


def test_oversized_upstream_request_id_is_regenerated():
    # ↑ 测试：超长的请求 ID 会被丢弃并重新生成。

    app, _ = _build_app()
    # ↑ 构造应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post("/echo", content=b"x", headers={"X-Request-ID": "x" * 200})
        # ↑ 传一个 200 字符的超长请求 ID。
    assert response.headers["X-Request-ID"] != "x" * 200
    # ↑ 断言响应 ID 不再是那个超长值。
    assert len(response.headers["X-Request-ID"]) == 32
    # ↑ 断言重新生成了 32 位的。


def test_request_id_header_is_forced_by_middleware():
    # ↑ 测试：即使内层代码写了别的 X-Request-ID，外层中间件也会强制覆盖。

    """即使内层代码塞了别的 X-Request-ID，外层 RequestIdMiddleware 也会覆盖。"""
    # ↑ docstring。
    app = FastAPI()
    # ↑ 创建应用。

    @app.get("/fake-id")
    # ↑ 定义接口。
    async def _fake_id() -> Response:
        # ↑ 处理函数。
        # 内层 Response 显式写一个 X-Request-ID，外层 middleware 应强制覆盖。
        # ↑ 说明。
        return Response(
            # ↑ 返回一个响应。
            content=b"ok",
            # ↑ 内容。
            headers={"X-Request-ID": "fake-id-set-by-inner"},
            # ↑ 内层故意写一个假请求 ID。
        )

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=256)
    # ↑ 加请求体限制。
    app.add_middleware(UnexpectedErrorMiddleware)
    # ↑ 加异常兜底。
    app.add_middleware(RequestIdMiddleware)
    # ↑ 加请求 ID（最外层）。

    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.get("/fake-id", headers={"X-Request-ID": "real-upstream-id"})
        # ↑ 请求，带真实上游 ID。
    assert response.status_code == 200
    # ↑ 断言 200。
    # 外层 RequestIdMiddleware 用 contextvar 里的值（"real-upstream-id"）覆盖。
    # 内层设的 "fake-id-set-by-inner" 不应该出现。
    # ↑ 说明。
    assert response.headers["X-Request-ID"] == "real-upstream-id"
    # ↑ 断言最终请求 ID 是上游传来的真实值（内层的假值被覆盖）。
    assert "fake-id-set-by-inner" not in response.headers.get("X-Request-ID", "")
    # ↑ 断言内层的假值没出现。
    # 且响应里有且只有一个 X-Request-ID 头（替换而非追加）。
    # ↑ 说明。
    assert response.headers.get_list("X-Request-ID") == ["real-upstream-id"]
    # ↑ 断言只有一个请求 ID 头（是替换，不是追加两个）。


# ---------------------------------------------------------------------------
# BodySizeLimit：单独跑，确认未引入回归
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面单独测请求体限制中间件。


def test_small_body_is_forwarded():
    # ↑ 测试：小 body 正常放行。

    app, received = _build_app(max_bytes=256)
    # ↑ 构造应用（上限 256 字节）。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post("/echo", content=b"x" * 10)
        # ↑ 发 10 字节 body。
    assert response.status_code == 200
    # ↑ 断言 200。
    assert response.json() == {"size": 10}
    # ↑ 断言返回 body 大小。
    assert received == [10]
    # ↑ 断言路由被调用，且收到的就是 10 字节。


def test_declared_oversized_body_is_rejected_before_reading():
    # ↑ 测试：声明超限的 body 直接 413，且路由不被调用。

    app, received = _build_app(max_bytes=256)
    # ↑ 构造应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post("/echo", content=b"x" * 1024)
        # ↑ 发 1024 字节（超过 256）。
    assert response.status_code == 413
    # ↑ 断言 413。
    # 关键：路由没被调用，body 没有被读入业务代码。
    # ↑ 说明。
    assert received == []
    # ↑ 断言路由没被调用（记录列表为空）。


def test_chunked_body_without_content_length_is_counted():
    # ↑ 测试：chunked 传输（无 Content-Length）超限也能被拦截。

    app, received = _build_app(max_bytes=256)
    # ↑ 构造应用。

    def chunks():
        # ↑ 定义一个生成器，模拟分块传输。
        for _ in range(64):
            # ↑ 循环 64 次。
            yield b"x" * 16  # 合计 1024 字节
            # ↑ 每次产出 16 字节，总共 1024 字节。

    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post("/echo", content=chunks())
        # ↑ 用生成器作为内容（httpx 会走 chunked 传输）。
    assert response.status_code == 413
    # ↑ 断言 413。
    assert received == []
    # ↑ 断言路由没被调用。


def test_invalid_content_length_is_bad_request():
    # ↑ 测试：Content-Length 无法解析时返回 400。

    app, received = _build_app(max_bytes=256)
    # ↑ 构造应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post(
            # ↑ 发请求。
            "/echo",
            content=b"x" * 4,
            headers={"Content-Length": "not-a-number"},
            # ↑ 声明一个非数字的 Content-Length。
        )
    assert response.status_code == 400
    # ↑ 断言 400。
    assert received == []
    # ↑ 断言路由没被调用。


# ---------------------------------------------------------------------------
# 真实完整 Middleware Stack：RequestId + UnexpectedError + BodySizeLimit
# 这是这次修复的核心——保证三者共存时行为正确。
# ---------------------------------------------------------------------------
# ↑ 分隔注释：下面测三个中间件组合起来的行为（最关键的部分）。


def test_stack_normal_request_returns_200_with_request_id():
    # ↑ 测试：完整栈下正常请求返回 200 且带请求 ID。

    app, received = _build_app()
    # ↑ 构造完整栈应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post("/echo", content=b"hi", headers={"X-Request-ID": "stack-1"})
        # ↑ 正常请求。
    assert response.status_code == 200
    # ↑ 断言 200。
    assert response.json() == {"size": 2}
    # ↑ 断言返回大小 2。
    assert received == [2]
    # ↑ 断言路由收到 2 字节。
    assert response.headers["X-Request-ID"] == "stack-1"
    # ↑ 断言请求 ID 正确。


def test_stack_declared_oversized_body_returns_413_with_request_id():
    # ↑ 测试：完整栈下超限 body 返回 413 且带请求 ID。

    app, received = _build_app(max_bytes=64)
    # ↑ 构造应用（上限 64）。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post("/echo", content=b"x" * 1024, headers={"X-Request-ID": "stack-413a"})
        # ↑ 发 1024 字节（超 64），带请求 ID。
    assert response.status_code == 413
    # ↑ 断言 413。
    assert received == []
    # ↑ 断言路由没被调用。
    # 关键：413 响应必须仍然带 X-Request-ID。
    # ↑ 说明。
    assert response.headers["X-Request-ID"] == "stack-413a"
    # ↑ 断言 413 响应也带请求 ID。
    assert response.json() == {"detail": "Request body too large"}
    # ↑ 断言响应体。


def test_stack_chunked_oversized_body_returns_413_with_request_id():
    # ↑ 测试：完整栈下 chunked 超限也返回 413 且带请求 ID。

    app, received = _build_app(max_bytes=64)
    # ↑ 构造应用（上限 64）。

    def chunks():
        # ↑ 分块生成器。
        for _ in range(8):
            # ↑ 8 次。
            yield b"x" * 32  # 合计 256 字节
            # ↑ 每次 32 字节，共 256 字节。

    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post("/echo", content=chunks(), headers={"X-Request-ID": "stack-413b"})
        # ↑ chunked 请求，带请求 ID。
    assert response.status_code == 413
    # ↑ 断言 413。
    assert received == []
    # ↑ 断言路由没被调用。
    assert response.headers["X-Request-ID"] == "stack-413b"
    # ↑ 断言请求 ID。


def test_stack_invalid_content_length_returns_400_with_request_id():
    # ↑ 测试：完整栈下非法 Content-Length 返回 400 且带请求 ID。

    app, received = _build_app(max_bytes=64)
    # ↑ 构造应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post(
            # ↑ 请求。
            "/echo",
            content=b"x" * 4,
            headers={"Content-Length": "not-a-number", "X-Request-ID": "stack-400"},
            # ↑ 非法 Content-Length + 请求 ID。
        )
    assert response.status_code == 400
    # ↑ 断言 400。
    assert received == []
    # ↑ 断言路由没被调用。
    assert response.headers["X-Request-ID"] == "stack-400"
    # ↑ 断言请求 ID。


def test_stack_lying_content_length_is_caught_by_byte_counting():
    # ↑ 测试：谎报小的 Content-Length 但实际超限，仍要被拦截（第二道闸）。

    """伪造小 Content-Length 但实际 body 超限：仍必须 413。

    声明值 (10) ≤ 上限 (64) 会骗过第一道闸；转发阶段的真实字节计数
    (1024) 必须抓住它。这正是 chunked 计数逻辑的第二用途。
    """
    # ↑ docstring。
    app, received = _build_app(max_bytes=64)
    # ↑ 构造应用（上限 64）。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post(
            # ↑ 请求。
            "/echo",
            content=b"x" * 1024,
            # ↑ 实际 1024 字节。
            headers={"Content-Length": "10", "X-Request-ID": "stack-lie"},
            # ↑ 却谎报 Content-Length 为 10。
        )
    assert response.status_code == 413, response.text
    # ↑ 断言 413（如果失败，把响应文本打印出来便于排查）。
    assert received == []
    # ↑ 断言路由没被调用。
    assert response.headers["X-Request-ID"] == "stack-lie"
    # ↑ 断言请求 ID。


def test_stack_router_exception_returns_500_with_request_id():
    # ↑ 测试：路由抛异常时返回 500，且带请求 ID、不泄露异常文本。

    app, _ = _build_app()
    # ↑ 构造应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.get("/boom", headers={"X-Request-ID": "stack-500"})
        # ↑ 请求会抛异常的 /boom。
    assert response.status_code == 500
    # ↑ 断言 500。
    body = response.json()
    # ↑ 解析响应体。
    assert body["detail"] == "Internal server error"
    # ↑ 断言 detail 是固定文案。
    assert body["request_id"] == "stack-500"
    # ↑ 断言请求 ID。
    # 异常文本绝对不能进客户端响应。
    # ↑ 说明。
    assert "boom-should-not-leak" not in response.text
    # ↑ 断言异常文本没泄露。
    assert response.headers["X-Request-ID"] == "stack-500"
    # ↑ 断言响应头请求 ID。


def test_stack_http_exception_keeps_its_status():
    # ↑ 测试：404 不被吞成 500。

    app, _ = _build_app()
    # ↑ 构造应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.get("/missing", headers={"X-Request-ID": "stack-404"})
        # ↑ 请求不存在的路径。
    assert response.status_code == 404
    # ↑ 断言 404。
    assert response.json()["detail"] == "nope"
    # ↑ 断言 detail。
    # 404 仍然带 X-Request-ID。
    # ↑ 说明。
    assert response.headers["X-Request-ID"] == "stack-404"
    # ↑ 断言请求 ID。


def test_stack_405_is_not_converted_to_500():
    # ↑ 测试：405 不被吞成 500。

    app, _ = _build_app()
    # ↑ 构造应用。
    with TestClient(app) as client:
        # ↑ 创建客户端。
        # /echo 是 POST；用 GET 触发 405
        # ↑ 说明。
        response = client.get("/echo", headers={"X-Request-ID": "stack-405"})
        # ↑ 用 GET 请求 POST 接口，触发 405。
    assert response.status_code == 405
    # ↑ 断言 405。
    assert response.headers["X-Request-ID"] == "stack-405"
    # ↑ 断言请求 ID。


def test_stack_422_validation_error_is_not_converted_to_500():
    # ↑ 测试：Pydantic 的 422 校验错误不被吞成 500。

    """FastAPI / Pydantic 的 422 必须保持状态码，不被 UnexpectedError 吞成 500。"""
    # ↑ docstring。
    from pydantic import BaseModel
    # ↑ 函数内导入 Pydantic。

    app = FastAPI()
    # ↑ 创建应用。

    class Payload(BaseModel):
        # ↑ 定义一个请求体模型。
        name: str  # required
        # ↑ name 字段，必填。

    @app.post("/strict", response_model=None)
    # ↑ 定义接口。
    async def _strict(payload: Payload):  # type: ignore[valid-type]
        # ↑ 处理函数，接收 Payload。
        return {"name": payload.name}
        # ↑ 返回。

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=1024)
    # ↑ 加请求体限制。
    app.add_middleware(UnexpectedErrorMiddleware)
    # ↑ 加异常兜底。
    app.add_middleware(RequestIdMiddleware)
    # ↑ 加请求 ID。

    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.post(
            # ↑ 请求。
            "/strict",
            json={},  # 缺 name
            # ↑ 空请求体（缺必填的 name，触发 422）。
            headers={"X-Request-ID": "stack-422"},
            # ↑ 请求 ID。
        )
    assert response.status_code == 422, response.text
    # ↑ 断言 422（不是 500）。
    assert response.headers["X-Request-ID"] == "stack-422"
    # ↑ 断言请求 ID。


def test_stack_streaming_response_keeps_single_request_id_header():
    # ↑ 测试：流式响应也带且只带一个请求 ID。

    """StreamingResponse 同样带且只带一个 X-Request-ID；body 完整到达。

    RequestId 中间件工作在 ``http.response.start`` 消息层，
    与 body 是一次性还是分块流式无关。
    """
    # ↑ docstring。
    from fastapi.responses import StreamingResponse
    # ↑ 函数内导入流式响应。

    app = FastAPI()
    # ↑ 创建应用。

    @app.get("/stream")
    # ↑ 定义接口。
    async def _stream() -> StreamingResponse:
        # ↑ 处理函数。
        async def gen():
            # ↑ 异步生成器（分块产出内容）。
            for chunk in (b"part-1;", b"part-2;", b"part-3"):
                # ↑ 遍历三块内容。
                yield chunk
                # ↑ 逐块产出。

        return StreamingResponse(gen(), media_type="text/plain")
        # ↑ 用生成器创建流式响应。

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=1024)
    # ↑ 加请求体限制。
    app.add_middleware(UnexpectedErrorMiddleware)
    # ↑ 加异常兜底。
    app.add_middleware(RequestIdMiddleware)
    # ↑ 加请求 ID。

    with TestClient(app) as client:
        # ↑ 创建客户端。
        response = client.get("/stream", headers={"X-Request-ID": "stream-rid"})
        # ↑ 请求流式接口。

    assert response.status_code == 200
    # ↑ 断言 200。
    assert response.text == "part-1;part-2;part-3"
    # ↑ 断言内容完整到达（三块拼接）。
    # httpx 把同名头合并为逗号分隔值；只有一个头时值就是它本身。
    # ↑ 说明。
    assert response.headers["X-Request-ID"] == "stream-rid"
    # ↑ 断言请求 ID。
    raw_values = response.headers.get_list("X-Request-ID")
    # ↑ 取所有同名的请求 ID 头（原始列表）。
    assert raw_values == ["stream-rid"], raw_values
    # ↑ 断言只有一个请求 ID 头（如果断言失败，打印 raw_values）。
