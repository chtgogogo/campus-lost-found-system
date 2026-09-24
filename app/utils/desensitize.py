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


def desensitize_student_no(no: str | None) -> str:
    """学号脱敏（审查 P1，2026-09-24）：前 2 后 2 保留，中间掩码；≤4 位保留首字符。"""
    if not no:
        return ""
    s = str(no).strip()
    if not s:
        return ""
    if len(s) <= 4:
        return s[0] + "*" * (len(s) - 1)
    return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"
