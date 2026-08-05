"""路由层共享依赖：当前用户解析、管理员校验。"""
from __future__ import annotations

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import (
    AdminRequiredError,
    PermissionError,
    TokenExpiredError,
    UnauthorizedError,
)
from app.core.security import decode_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """解析 Bearer JWT，返回当前用户（封禁态拒绝）。"""
    if creds is None or not creds.credentials:
        raise UnauthorizedError()
    try:
        payload = decode_token(creds.credentials)
    except jwt.ExpiredSignatureError:
        raise TokenExpiredError()
    except jwt.PyJWTError:
        raise UnauthorizedError()

    user = db.get(User, int(payload.get("sub")))
    if not user:
        raise UnauthorizedError()
    if int(user.status) == 1:  # 封禁
        raise PermissionError("账号已被封禁，无法操作")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """要求管理员角色。"""
    if int(user.role) != 1:
        raise AdminRequiredError()
    return user
