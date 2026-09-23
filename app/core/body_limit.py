"""请求体大小护栏（安检 L1，2026-09-23）：超限直接 413，防超大包打满内存。

设计要点：
- **轻量**：只检查 ``Content-Length`` 请求头（预读即判，不消耗请求体），
  不引入流式截断等复杂机制；无 Content-Length 的分块上传不在本护栏范围内
  （uvicorn 对超大分块请求另有缓冲上限，属部署层配置）。
- **默认值**：``settings.REQUEST_BODY_MAX_MB``（100MB），与上传能力上限联动
  （IMG_MAX_COUNT=9 × IMG_MAX_SIZE_MB=10 = 90MB + multipart 开销）。
- **响应形状**：与全局异常处理器的 ``ErrorResponse`` 信封一致
  （``{"code": 413, "message": ..., "data": null}``）。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """按 Content-Length 拒绝超限请求体（413 Payload Too Large）。"""

    def __init__(self, app, max_body_mb: int) -> None:
        super().__init__(app)
        self.max_bytes = max(1, int(max_body_mb)) * 1024 * 1024
        self.max_mb = int(max_body_mb)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        content_length = request.headers.get("content-length", "")
        if content_length.isdigit() and int(content_length) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "code": 413,
                    "message": f"请求体过大（上限 {self.max_mb}MB），请压缩或减少图片数量",
                    "data": None,
                },
            )
        return await call_next(request)
