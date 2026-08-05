"""下载视觉推理权重到 models/weights/（项目内 E 盘，严禁 C 盘）。

用法：
    python scripts/download_models.py
    python scripts/download_models.py --coco yolov8n.pt --world yolov8s-world.pt

说明：
- 使用 ultralytics 的 YOLO 自动下载能力，落盘到 `settings.YOLO_MODEL_DIR`。
- 若目标文件已存在且非空，则跳过（支持重跑 / 断点）。
- 若本地无权重，app 启动时 VisionService 也会尝试自动下载（优雅降级）。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402


def _ensure_dir() -> str:
    d = settings.YOLO_MODEL_DIR
    os.makedirs(d, exist_ok=True)
    return d


def download(name: str, dest_dir: str) -> None:
    """下载单个权重到 dest_dir（已存在则跳过）。"""
    target = os.path.join(dest_dir, name)
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"[download] 已存在，跳过: {target}")
        return
    print(f"[download] 开始下载 {name} -> {dest_dir}")
    # 惰性导入：仅在本脚本真正下载时才引入 ultralytics / torch
    from ultralytics import YOLO  # type: ignore

    # 切到目标目录，使 ultralytics 把权重落到 models/weights 而非 CWD / 缓存
    prev = os.getcwd()
    try:
        os.chdir(dest_dir)
        YOLO(name)
    finally:
        os.chdir(prev)
    if os.path.exists(target) and os.path.getsize(target) > 0:
        print(f"[download] 完成: {target}")
    else:  # pragma: no cover - 极端情况下落到缓存
        print(f"[download] 警告：未在 {target} 找到权重，可能已落到 ultralytics 缓存目录")


def main() -> None:
    parser = argparse.ArgumentParser(description="下载 YOLO 权重")
    parser.add_argument("--coco", default=settings.YOLO_COCO_MODEL)
    parser.add_argument("--world", default=settings.YOLO_WORLD_MODEL)
    args = parser.parse_args()

    dest = _ensure_dir()
    download(args.coco, dest)
    download(args.world, dest)
    print(f"[download] 全部完成（权重位于 {dest}）")


if __name__ == "__main__":
    main()
