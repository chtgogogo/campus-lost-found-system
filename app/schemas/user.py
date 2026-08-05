"""用户相关 Schema（§3.1 / §3.2）。"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas.common import UserRole, UserStatus


class UserCreate(BaseModel):
    """注册请求体。"""

    student_no: str = Field(..., min_length=1, max_length=32, description="学号/工号")
    phone: str = Field(..., min_length=5, max_length=20, description="手机号")
    sms_code: str = Field(..., min_length=1, description="短信验证码")
    password: str = Field(..., min_length=6, max_length=64, description="密码")
    real_name: Optional[str] = Field(None, max_length=50, description="真实姓名（选填）")
    # v10（变更 C）：管理员邀请码。命中 settings.ADMIN_APPLY_CODE → 静默升为 role=1。
    # ⚠️ 刻意**不加** min_length / pattern / 任何校验器：错码必须与不填走完全相同的响应体，
    #    否则可由响应差异探测出「邀请码机制存在」（AC-C9）。
    admin_code: Optional[str] = Field(None, max_length=128, description="管理员邀请码（选填）")


class LoginRequest(BaseModel):
    """登录请求体。"""

    student_no: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1, max_length=64)


class RefreshRequest(BaseModel):
    """刷新令牌请求体。"""

    refresh_token: str = Field(..., description="refresh token")


class SendSmsRequest(BaseModel):
    """发送短信请求体。"""

    phone: str = Field(..., min_length=5, max_length=20)
    purpose: str = Field(..., description="register | bind | login")


class BindPhoneRequest(BaseModel):
    """绑定手机请求体。"""

    phone: str = Field(..., min_length=5, max_length=20)
    sms_code: str = Field(..., min_length=1)


class LogoutRequest(BaseModel):
    """登出请求体。"""

    refresh_token: str = Field(..., description="待吊销的 refresh token")


class Token(BaseModel):
    """令牌响应。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 120 * 60  # 秒


class UserOut(BaseModel):
    """用户输出（手机号脱敏）。"""

    id: int
    student_no: str
    phone: str
    real_name: Optional[str] = None
    role: int
    credit_score: int
    status: int
    created_at: datetime

    @classmethod
    def from_model(cls, user) -> "UserOut":
        """由 ORM 模型构造，手机号脱敏。"""
        from app.utils.desensitize import desensitize_phone

        return cls(
            id=user.id,
            student_no=user.student_no,
            phone=desensitize_phone(user.phone),
            real_name=user.real_name,
            role=int(user.role),
            credit_score=int(user.credit_score),
            status=int(user.status),
            created_at=user.created_at,
        )


class AdminUserOut(BaseModel):
    """管理后台用户输出（v10 变更 D1）。

    ⚠️ 与 `UserOut` 的唯一实质差异：**手机号明文回传**（取证/联系需要）。
    因此**禁止**复用 `UserOut.from_model` —— 后者会调用 `desensitize_phone` 脱敏。
    本 Schema 仅可由 `require_admin` 守卫的接口使用，前端后台需展示合规提示。
    """

    id: int
    student_no: str
    phone: str          # 明文，不脱敏
    real_name: Optional[str] = None
    role: int
    credit_score: int
    status: int
    created_at: datetime

    @classmethod
    def from_model(cls, user) -> "AdminUserOut":
        """由 ORM 模型构造（手机号保持明文）。"""
        return cls(
            id=int(user.id),
            student_no=user.student_no,
            phone=user.phone,
            real_name=user.real_name,
            role=int(user.role),
            credit_score=int(user.credit_score),
            status=int(user.status),
            created_at=user.created_at,
        )


class CreditLogOut(BaseModel):
    """信誉流水输出。"""

    id: int
    delta: int
    reason: str
    ref_type: Optional[str] = None
    ref_id: Optional[int] = None
    created_at: datetime


class CreditOut(BaseModel):
    """信誉查询输出。"""

    credit_score: int
    logs: list[CreditLogOut]
