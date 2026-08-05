"""脱敏工具（手机号 / 姓名）。"""
from __future__ import annotations


def desensitize_phone(phone: str | None) -> str:
    """手机号脱敏：138****8000。不足 11 位做简单掩码。"""
    if not phone:
        return ""
    s = str(phone)
    if len(s) >= 11:
        return f"{s[:3]}****{s[-4:]}"
    if len(s) >= 4:
        return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"
    return "*" * len(s)


def desensitize_name(name: str | None) -> str:
    """姓名脱敏：张**、欧阳**。单字保留首字加 *。"""
    if not name:
        return ""
    s = str(name).strip()
    if len(s) <= 1:
        return s + "*"
    return s[0] + "*" * (len(s) - 1)
