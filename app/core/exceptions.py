"""业务异常与统一错误码映射。

- `BizError`：所有业务异常的基类，携带 `code` / `message` / `http_status`。
- `exception_handler`：FastAPI 全局处理器，统一包装为 `{code, message, data:null}`。
- 错误码表见 §5.2。
"""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.schemas.common import ErrorResponse


class BizError(Exception):
    """业务异常基类。"""

    def __init__(self, code: int, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# ---------------- 预定义业务异常 ----------------
class UnauthorizedError(BizError):
    def __init__(self, message: str = "未认证或令牌缺失", code: int = 1000) -> None:
        super().__init__(code, message, http_status=401)


class TokenExpiredError(BizError):
    def __init__(self, message: str = "令牌已过期", code: int = 1001) -> None:
        super().__init__(code, message, http_status=401)


class CredentialError(BizError):
    def __init__(self, message: str = "学号或密码错误", code: int = 1002) -> None:
        super().__init__(code, message, http_status=401)


class OtpError(BizError):
    def __init__(self, message: str = "手机号未绑定或验证码错误", code: int = 1003) -> None:
        super().__init__(code, message, http_status=400)


class RefreshInvalidError(BizError):
    def __init__(self, message: str = "刷新令牌无效", code: int = 1004) -> None:
        super().__init__(code, message, http_status=401)


class NotFoundError(BizError):
    def __init__(self, message: str = "物品不存在", code: int = 2001) -> None:
        super().__init__(code, message, http_status=404)


class CategoryError(BizError):
    def __init__(self, message: str = "分类不存在或未启用", code: int = 2002) -> None:
        super().__init__(code, message, http_status=400)


class PermissionError(BizError):
    def __init__(self, message: str = "无权操作该资源", code: int = 2003) -> None:
        super().__init__(code, message, http_status=403)


class ClaimReasonRequiredError(BizError):
    def __init__(self, message: str = "认领理由必填", code: int = 3002) -> None:
        super().__init__(code, message, http_status=400)


class MatchProcessedError(BizError):
    def __init__(self, message: str = "该匹配已处理", code: int = 3003) -> None:
        super().__init__(code, message, http_status=409)


class HandoverInvalidError(BizError):
    def __init__(self, message: str = "交接码无效", code: int = 4001) -> None:
        super().__init__(code, message, http_status=400)


class HandoverExpiredError(BizError):
    def __init__(self, message: str = "交接码已过期，请重新生成", code: int = 4002) -> None:
        super().__init__(code, message, http_status=400)


class HandoverConflictError(BizError):
    def __init__(self, message: str = "交接码已验证或待对方确认", code: int = 4003) -> None:
        super().__init__(code, message, http_status=409)


class YoloDegradedError(BizError):
    def __init__(self, message: str = "YOLO 服务不可用，已降级", code: int = 5000) -> None:
        super().__init__(code, message, http_status=200)


class RateLimitError(BizError):
    def __init__(self, message: str = "触发限流", code: int = 6001) -> None:
        super().__init__(code, message, http_status=429)


class AdminRequiredError(BizError):
    def __init__(self, message: str = "权限不足，需要管理员", code: int = 7001) -> None:
        super().__init__(code, message, http_status=403)


class InternalError(BizError):
    def __init__(self, message: str = "内部错误", code: int = 5001) -> None:
        super().__init__(code, message, http_status=500)


class ParamError(BizError):
    def __init__(self, message: str = "参数校验失败", code: int = 9001) -> None:
        super().__init__(code, message, http_status=422)


# ---------------- 处理器 ----------------
def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(BizError)
    async def _biz_handler(request: Request, exc: BizError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=ErrorResponse(code=exc.code, message=exc.message, data=None).model_dump(
                mode="json"
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                code=9001, message="参数校验失败", data=exc.errors()
            ).model_dump(mode="json"),
        )

    @app.exception_handler(HTTPException)
    async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(code=exc.status_code, message=str(exc.detail), data=None).model_dump(
                mode="json"
            ),
        )
