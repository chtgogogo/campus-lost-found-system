"""认证路由（§3.1）：注册 / 登录 / 刷新 / 发短信 / 绑手机 / 登出。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
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
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=StandardResponse)
def register(body: UserCreate, db: Session = Depends(get_db)):
    """注册（需短信 OTP）。返回用户信息与令牌。"""
    user, access, refresh = AuthService(db).register(body)
    return success(
        data={
            "user": UserOut.from_model(user),
            "token": Token(access_token=access, refresh_token=refresh),
        }
    )


@router.post("/login", response_model=StandardResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """登录（student_no + password）。返回令牌。"""
    _, access, refresh = AuthService(db).login(body.student_no, body.password)
    return success(data=Token(access_token=access, refresh_token=refresh))


@router.post("/refresh", response_model=StandardResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    """刷新令牌（旋转旧 refresh）。"""
    _, access, new_refresh = AuthService(db).refresh(body.refresh_token)
    return success(data=Token(access_token=access, refresh_token=new_refresh))


@router.post("/send-sms", response_model=StandardResponse)
def send_sms(body: SendSmsRequest, db: Session = Depends(get_db)):
    """发送短信（Mock：控制台输出）。DEBUG 模式响应附带 dev_code 便于联调。"""
    code = AuthService(db).send_sms(body.phone, body.purpose)
    data: dict = {"sent": True}
    if settings.DEBUG:
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
