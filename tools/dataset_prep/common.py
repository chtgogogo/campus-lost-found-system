"""common.py — dataset_prep 管线共享工具。

单一事实来源（label_map.yaml）的读取与 YOLO 标注的校验/写入。
所有 convert / merge / extract 脚本均 import 本模块；运行任意脚本时
会自动将本文件所在目录加入 sys.path，因此不需要手动设置 PYTHONPATH。
"""

from __future__ import annotations

import os
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LABEL_MAP = os.path.join(HERE, "label_map.yaml")

# 固定统一 11 类（与 label_map.yaml 保持一致，仅作代码内兜底）。
FALLBACK_TARGET_CLASSES = [
    "phone", "wallet", "keys", "backpack", "suitcase", "laptop",
    "campus_card", "glasses", "notebook", "umbrella", "bottle",
]


def load_label_map(path: str = DEFAULT_LABEL_MAP) -> dict:
    """读取 label_map.yaml 并返回 dict。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_target_classes(lm: dict) -> list[str]:
    """从 label_map 取出有序的 11 类名称列表（索引 == class_id）。"""
    tc = lm.get("target_classes", {})
    if isinstance(tc, dict):
        n = len(tc)
        return [tc[str(i)] if str(i) in tc else tc[i] for i in range(n)]
    return list(tc)


def validate_yolo_line(cls: int, cx: float, cy: float, w: float, h: float) -> None:
    """校验单条 YOLO 标注：class_id 在 [0,10]，坐标归一化在 [0,1]，宽高为正。"""
    if not (0 <= cls <= 10):
        raise ValueError(f"class_id {cls} 超出 [0,10] 范围")
    for name, v in (("cx", cx), ("cy", cy), ("w", w), ("h", h)):
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"{name}={v} 未归一化到 [0,1]")
    if w <= 0 or h <= 0:
        raise ValueError(f"框尺寸非正: w={w}, h={h}")


def write_yolo_label(
    lines: list[tuple[int, float, float, float, float]],
    out_path: str,
) -> None:
    """将 [(cls, cx, cy, w, h), ...] 写成 YOLO txt（6 位小数，每行校验）。"""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for cls, cx, cy, w, h in lines:
            validate_yolo_line(cls, cx, cy, w, h)
            f.write(f"{int(cls)} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n")


def ensure_importable() -> None:
    """把本文件所在目录加入 sys.path，保证 `from common import ...` 可用。"""
    import sys

    if HERE not in sys.path:
        sys.path.insert(0, HERE)
