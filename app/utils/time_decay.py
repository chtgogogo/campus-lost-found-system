"""时间衰减函数（§5.4）。

time_decay(Δt) = exp(-Δt / τ)，值域 (0, 1]。Δt 为天数，τ 默认 3 天（配置）。
"""
from __future__ import annotations

import math
from datetime import datetime


def delta_days(a: datetime | None, b: datetime | None) -> float:
    """计算两个时间点的绝对差（天）。任一为空返回 0.0。"""
    if a is None or b is None:
        return 0.0
    # 统一为可相减的 datetime（忽略时区差异，仅取绝对差）
    try:
        diff = abs((a - b).total_seconds())
    except TypeError:
        # 一个有 tz 一个没有：都转成无 tz 的 naive 比较
        def _strip(dt: datetime) -> datetime:
            return dt.replace(tzinfo=None) if dt.tzinfo else dt

        diff = abs((_strip(a) - _strip(b)).total_seconds())
    return diff / 86400.0


def time_decay(delta: float, tau: float) -> float:
    """指数时间衰减，值域 (0, 1]。"""
    if tau <= 0:
        raise ValueError("tau 必须为正数")
    value = math.exp(-max(delta, 0.0) / tau)
    return max(min(value, 1.0), 1e-9)
