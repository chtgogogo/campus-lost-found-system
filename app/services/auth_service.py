"""认证服务（注册 / 登录 / 刷新 / 短信 / 绑手机 / 登出）。

双因子：注册与绑手机需短信 OTP（Redis/内存计数限流）；登录用 student_no + password。
 Refresh Token 的 jti 存入 KV（Redis 优先），支持吊销与旋转。
"""
from __future__ import annotations

import logging
import secrets
from typing import Optional

from sqlalchemy.orm import Session

from app.core import redis_client
from app.core.config import settings
from app.core.exceptions import (
    BizError,
    CredentialError,
    OtpError,
    PermissionError,
    RateLimitError,
    RefreshInvalidError,
    TokenExpiredError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    is_refresh_token_valid,
    revoke_refresh_token,
    verify_password,
)
from app.models.user import User
from app.schemas.user import UserCreate

logger = logging.getLogger(__name__)


class AuthService:
    """认证相关业务。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------------- 短信（Mock 控制台输出） ----------------
    def send_sms(self, phone: str, purpose: str) -> str:
        # 重发间隔限流
        if redis_client.kv.get(f"sms_t:{phone}"):
            raise RateLimitError("短信发送过于频繁，请稍后再试")
        redis_client.kv.set(f"sms_t:{phone}", "1", ttl_sec=settings.SMS_RESEND_INTERVAL_SEC)

        code = f"{secrets.randbelow(1_000_000):06d}"
        redis_client.kv.set(f"sms:{phone}", code, ttl_sec=300)
        # Mock：日志输出（生产替换为真实短信网关）。审查 P1（2026-09-24）：
        # print 直打 stdout 在生产会把手机号+验证码带进采集管道，改走 logging 统一治理。
        logger.info("[MOCK SMS] phone=%s purpose=%s code=%s", phone, purpose, code)
        return code

    # ---------------- 管理员邀请码 ----------------
    @staticmethod
    def _resolve_role(admin_code: Optional[str]) -> bool:
        """v10（变更 C）：判定注册请求是否命中管理员邀请码。

        安全要点（三条，缺一不可）：
        1. **常量时间比较**：用 ``secrets.compare_digest`` 而非 ``==``，防止按字符提前返回
           造成的时序侧信道，使邀请码可被逐位爆破。
        2. **空口令护栏**：``bool(expected)`` 必须先判 —— 若运维把 ``ADMIN_APPLY_CODE``
           配成空串，缺少该护栏时「不填邀请码」会与空串相等 → **全员管理员**，严重越权。
        3. **静默降级**：不命中一律返回 False（role=0），绝不抛异常、绝不改变响应体，
           使错码与不填从外部完全不可区分（AC-C9）。

        Args:
            admin_code: 注册请求体中的邀请码（可为 None）。

        Returns:
            True 表示应升为管理员（role=1），False 表示普通用户（role=0）。
        """
        supplied = (admin_code or "").strip()
        expected = (settings.ADMIN_APPLY_CODE or "").strip()
        if not expected:
            return False
        return secrets.compare_digest(supplied, expected)

    def _demo_placeholder_phone(self) -> str:
        """v18 演示模式：生成唯一占位手机号（demo- + 8 位 hex，13 字符 < String(20)）。

        phone 列有唯一约束，随机碰撞（2^-32）时重试至多 5 次；穷尽视为服务异常。
        """
        for _ in range(5):
            candidate = f"demo-{secrets.token_hex(4)}"
            if not self.db.query(User).filter(User.phone == candidate).first():
                return candidate
        raise BizError(9001, "演示注册繁忙，请稍后重试", http_status=503)

    # ---------------- 注册 ----------------
    def register(self, data: UserCreate) -> tuple[User, str, str]:
        # v18（2026-09-24）DEMO_MODE 分叉：是否需要手机号/验证码在此裁决（schema 层已放宽）。
        # 真实模式：两者必填（schema 缺失时在此补拦，响应语义与旧版 422 一致）+ OTP 校验；
        # 演示模式：跳过 OTP（服务器无真实短信通道，收不到码），未填手机号自动生成
        # 唯一占位号（demo-8位hex，String(20) 内；脱敏函数对非数字串按短掩码处理，不会崩）。
        if settings.DEMO_MODE:
            if not data.phone:
                data.phone = self._demo_placeholder_phone()
        else:
            if not data.phone or not data.sms_code:
                raise BizError(9001, "手机号与验证码必填", http_status=422)
            stored = redis_client.kv.get(f"sms:{data.phone}")
            # 审查 P1（2026-09-24）：OTP 比对改恒时比较（encode 规避非 ASCII TypeError），
            # 与邀请码/交接码的恒时比较标准对齐。
            if not stored or not secrets.compare_digest(
                stored.encode("utf-8"), data.sms_code.encode("utf-8")
            ):
                raise OtpError()

        if self.db.query(User).filter(User.student_no == data.student_no).first():
            raise BizError(9001, "学号已存在", http_status=409)
        if self.db.query(User).filter(User.phone == data.phone).first():
            raise BizError(9001, "手机号已存在", http_status=409)

        # v10：邀请码命中则静默升管理员；不命中（含不填 / 错码 / 空串配置）一律 role=0
        is_admin = self._resolve_role(getattr(data, "admin_code", None))

        user = User(
            student_no=data.student_no,
            phone=data.phone,
            real_name=data.real_name,
            password_hash=hash_password(data.password),
            role=1 if is_admin else 0,
            credit_score=100,
            status=0,
        )
        self.db.add(user)
        self.db.flush()
        redis_client.kv.delete(f"sms:{data.phone}")

        if is_admin:
            # 审计埋点之一（共四处）：write_audit 不自行 commit，随下方 commit 同事务落库
            from app.services import audit_service

            audit_service.write_audit(
                self.db,
                user_id=user.id,
                action="register_admin",
                target_type="user",
                target_id=user.id,
                detail=f"student_no={user.student_no}",
            )

        access = create_access_token(user.id, user.role)
        refresh = create_refresh_token(user.id, user.role)
        self.db.commit()
        self.db.refresh(user)
        return user, access, refresh

    # ---------------- 登录 ----------------
    def login(self, student_no: str, password: str) -> tuple[User, str, str]:
        user = self.db.query(User).filter(User.student_no == student_no).first()
        if not user or not verify_password(password, user.password_hash):
            raise CredentialError()
        if int(user.status) == 1:
            raise PermissionError("账号已被封禁")
        access = create_access_token(user.id, user.role)
        refresh = create_refresh_token(user.id, user.role)
        return user, access, refresh

    # ---------------- v18 演示随机登录 ----------------
    def demo_random_login(self) -> tuple[User, str, str]:
        """演示模式专用：从「演示随机账号」池随机取一个直接签发令牌（无凭据）。

        安全边界：仅 settings.DEMO_MODE=true 可达（路由层裁决，否则 404）；
        账号池由 seed_demo_random_accounts 幂等确保（启动时/调用时双保险）；
        每次发放写审计（无凭据发令牌必须留痕，安检口径）。
        """
        if not settings.DEMO_MODE:
            raise BizError(9001, "演示登录未开启", http_status=404)
        from app.core.seed import DEMO_RANDOM_ACCOUNT_MARK, seed_demo_random_accounts

        seed_demo_random_accounts(self.db)
        pool = (
            self.db.query(User)
            .filter(User.real_name == DEMO_RANDOM_ACCOUNT_MARK, User.status == 0)
            .all()
        )
        if not pool:
            raise BizError(9001, "演示账号池为空", http_status=503)
        user = secrets.choice(pool)
        access = create_access_token(user.id, user.role)
        refresh = create_refresh_token(user.id, user.role)
        return user, access, refresh

    # ---------------- 刷新 ----------------
    def refresh(self, refresh_token: str) -> tuple[User, str, str]:
        import jwt

        try:
            payload = jwt.decode(
                refresh_token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
            )
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError()
        except jwt.PyJWTError:
            raise RefreshInvalidError()

        # 审查 P0-2 配套（2026-09-24）：显式校验类型（纵深防御）。
        # 此前靠「access 的 jti 不入 KV」间接拦截，access token 传进来同样在此拒绝。
        if payload.get("type") != "refresh":
            raise RefreshInvalidError()

        jti = payload.get("jti")
        if not jti or not is_refresh_token_valid(jti):
            raise RefreshInvalidError()

        # 旋转：吊销旧 jti，签发新令牌
        revoke_refresh_token(jti)
        user = self.db.get(User, int(payload.get("sub")))
        if not user:
            raise RefreshInvalidError()
        if int(user.status) == 1:
            raise PermissionError("账号已被封禁")
        access = create_access_token(user.id, user.role)
        new_refresh = create_refresh_token(user.id, user.role)
        return user, access, new_refresh

    # ---------------- 绑手机 ----------------
    def bind_phone(self, user: User, phone: str, sms_code: str) -> User:
        stored = redis_client.kv.get(f"sms:{phone}")
        # 审查 P1（2026-09-24）：同 register，恒时比较
        if not stored or not secrets.compare_digest(
            stored.encode("utf-8"), sms_code.encode("utf-8")
        ):
            raise OtpError()
        if self.db.query(User).filter(User.phone == phone, User.id != user.id).first():
            raise BizError(9001, "手机号已被其他账号绑定", http_status=409)
        user.phone = phone
        redis_client.kv.delete(f"sms:{phone}")
        self.db.commit()
        self.db.refresh(user)
        return user

    # ---------------- 登出 ----------------
    def logout(self, refresh_token: str) -> None:
        import jwt

        try:
            payload = jwt.decode(
                refresh_token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
            )
            jti = payload.get("jti")
            if jti:
                revoke_refresh_token(jti)
        except jwt.PyJWTError:
            pass  # 无效令牌直接忽略
