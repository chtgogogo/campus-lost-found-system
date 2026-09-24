"""认证路由（§3.1）：注册 / 登录 / 刷新 / 发短信 / 绑手机 / 登出。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.ratelimit import check_rate_limit
from app.models.user import User
from app.routers.deps import get_current_user
from app.schemas.common import StandardResponse, success
from app.schemas.user import (
    BindPhoneRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    SendSmsRequest,
    Token,
    UserCreate,
    UserOut,
)
from app.services import audit_service
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def _ip(request: Request) -> str:
    """取客户端 IP（限流键；反向代理场景生产应改为取 X-Forwarded-For 首段）。"""
    return request.client.host if request.client else "unknown"


@router.get("/public-config", response_model=StandardResponse)
def public_config():
    """前端公开配置（v18）：演示模式标志，控制注册表单是否隐藏手机号/验证码。

    仅暴露一个 boolean，无敏感信息、无需鉴权；DEMO_MODE 只能在 .env/代码切换，
    此接口是只读投影，不提供任何修改入口（安检口径：一个开关只管一件事）。
    """
    return success(data={"demo_mode": settings.DEMO_MODE})


@router.post("/demo-login", response_model=StandardResponse)
def demo_random_login(request: Request, db: Session = Depends(get_db)):
    """v18 演示随机登录：从 10 个预置「演示随机账号」中随机取一个直接登录。

    **仅 DEMO_MODE=true 可用**（false 时 404，生产不暴露该口子）；
    无凭据发令牌 → 每次调用写审计（demo_random_login）留痕；
    账号池幂等确保（首次调用时自动播种，学号/密码均为 1234567 随机组合）。
    """
    if not settings.DEMO_MODE:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Not Found")
    check_rate_limit(f"auth:demo-login:ip:{_ip(request)}", settings.RATE_LIMIT_AUTH_PER_MIN)
    user, access, refresh = AuthService(db).demo_random_login()
    audit_service.write_audit(
        db,
        user_id=user.id,
        action="demo_random_login",
        target_type="user",
        target_id=user.id,
        ip=_ip(request),
        ua=request.headers.get("user-agent"),
        detail=f"student_no={user.student_no}",
    )
    db.commit()  # write_audit 不自带提交（无凭据发令牌的留痕必须落库）
    return success(
        data={
            "user": UserOut.from_model(user),
            "token": Token(access_token=access, refresh_token=refresh),
        }
    )


@router.post("/register", response_model=StandardResponse)
def register(request: Request, body: UserCreate, db: Session = Depends(get_db)):
    """注册（需短信 OTP）。返回用户信息与令牌。"""
    check_rate_limit(f"auth:register:ip:{_ip(request)}", settings.RATE_LIMIT_AUTH_STRICT_PER_MIN)
    user, access, refresh = AuthService(db).register(body)
    return success(
        data={
            "user": UserOut.from_model(user),
            "token": Token(access_token=access, refresh_token=refresh),
        }
    )


@router.post("/login", response_model=StandardResponse)
def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    """登录（student_no + password）。返回令牌。"""
    check_rate_limit(f"auth:login:ip:{_ip(request)}", settings.RATE_LIMIT_AUTH_STRICT_PER_MIN)
    _, access, refresh = AuthService(db).login(body.student_no, body.password)
    return success(data=Token(access_token=access, refresh_token=refresh))


@router.post("/refresh", response_model=StandardResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    """刷新令牌（旋转旧 refresh）。"""
    _, access, new_refresh = AuthService(db).refresh(body.refresh_token)
    return success(data=Token(access_token=access, refresh_token=new_refresh))


@router.post("/send-sms", response_model=StandardResponse)
def send_sms(request: Request, body: SendSmsRequest, db: Session = Depends(get_db)):
    """发送短信（Mock：控制台输出）。SHOW_SMS_CODE=True 时响应附带 dev_code 便于联调。

    安检 L1-3（2026-09-23）：显隐开关由 DEBUG 改为独立的 SHOW_SMS_CODE（默认 False），
    一个开关只管一件事 —— 开着 DEBUG 调试不再连带把验证码暴露给页面。
    """
    check_rate_limit(f"auth:send-sms:ip:{_ip(request)}", settings.RATE_LIMIT_AUTH_STRICT_PER_MIN)
    code = AuthService(db).send_sms(body.phone, body.purpose)
    data: dict = {"sent": True}
    if settings.SHOW_SMS_CODE:
        data["dev_code"] = code
    return success(data=data)


@router.post("/bind-phone", response_model=StandardResponse)
def bind_phone(
    body: BindPhoneRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """绑定手机（需短信 OTP）。"""
    updated = AuthService(db).bind_phone(user, body.phone, body.sms_code)
    return success(data=UserOut.from_model(updated))


@router.post("/logout", response_model=StandardResponse)
def logout(
    body: LogoutRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """登出（吊销 refresh token）。"""
    AuthService(db).logout(body.refresh_token)
    return success(data={"ok": True})
