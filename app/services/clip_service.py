"""CLIP 跨模态图像相似度服务（P0-③，独立模块，不改动 vision_service）。

封装 OpenAI CLIP（ViT-B/32）的余弦相似度计算，用于增强 ``match_service`` 的照片维度：
在双方均提供图片字节且 CLIP 可用时，与既有感知哈希按 0.5/0.5 混合。

兼容性铁律：
- 整个「导入 + 权重加载 + 推理」均被 try/except 保护；任何失败（CLIP 包缺失 /
  权重文件缺失 / OOM / 异常）一律返回 ``None``，由调用方（match_service）回退感知哈希，
  绝不因 CLIP 缺失导致 import 失败或测试崩溃。
- 权重文件：``weights/clip/ViT-B-32.pt``（约 353MB，已存在）；``clip.load`` 的
  ``download_root`` 指向该文件所在目录，命中即复用、不重复下载。
- 开关由模块内常量 ``CLIP_ENABLED`` 控制（主理人可置 False 完全禁用），依赖缺失时
  自动降级为不可用（image_similarity 返回 None）。
"""
from __future__ import annotations

import io
import os

from app.core.config import BASE_DIR

# ---------------- 模块内开关与路径（不改动 config.py） ----------------
# 主理人可改为 False 以完全禁用 CLIP 跨模态（调用方回退纯感知哈希）。
CLIP_ENABLED: bool = True
# CLIP 权重文件（已存在，约 353MB）：weights/clip/ViT-B-32.pt
CLIP_WEIGHT_PATH: str = os.path.join(BASE_DIR, "weights", "clip", "ViT-B-32.pt")
CLIP_DEVICE: str = "cpu"

# 运行时懒加载的模型句柄（首次成功推理后缓存，避免重复加载）。
_model = None
_preprocess = None


def _load_model() -> bool:
    """懒加载 CLIP 模型与预处理；任何异常 → 返回 False（调用方回退）。

    仅在首次需要推理时导入 ``clip`` / ``torch``（避免无谓的重量级依赖加载，
    保证未使用 CLIP 的路径（如单元测试）导入开销最小）。
    """
    global _model, _preprocess
    if not CLIP_ENABLED:
        return False
    if _model is not None:
        return True
    if not os.path.exists(CLIP_WEIGHT_PATH):
        return False
    try:
        import clip  # 仅在首次使用时导入，避免无谓的 torch 加载
        import torch
        from PIL import Image

        # download_root 指向权重目录：文件已存在则 clip.load 直接加载，不联网下载。
        model, preprocess = clip.load(
            "ViT-B/32",
            device=CLIP_DEVICE,
            download_root=os.path.dirname(CLIP_WEIGHT_PATH),
        )
        model.eval()
        _model = model
        _preprocess = preprocess
        return True
    except Exception:
        # 包缺失 / 权重损坏 / 设备异常等 → 标记不可用，后续调用直接回退。
        _model = None
        _preprocess = None
        return False


def image_similarity(bytes_a: bytes, bytes_b: bytes) -> float | None:
    """计算两图 CLIP 余弦相似度 ∈ [0,1]；不可用 / 异常 → None（回退感知哈希）。

    Args:
        bytes_a / bytes_b: 两张图片的原始字节（PNG/JPG 等）。

    Returns:
        归一化余弦相似度（clamp 到 [0,1]）；任一缺失 / 模型不可用 / 推理失败返回 ``None``。
    """
    if not CLIP_ENABLED:
        return None
    if not bytes_a or not bytes_b:
        return None
    if not _load_model():
        return None
    try:
        import torch
        from PIL import Image

        img_a = (
            _preprocess(Image.open(io.BytesIO(bytes_a)).convert("RGB"))
            .unsqueeze(0)
            .to(CLIP_DEVICE)
        )
        img_b = (
            _preprocess(Image.open(io.BytesIO(bytes_b)).convert("RGB"))
            .unsqueeze(0)
            .to(CLIP_DEVICE)
        )
        with torch.no_grad():
            feat_a = _model.encode_image(img_a)
            feat_b = _model.encode_image(img_b)
        feat_a = feat_a / feat_a.norm(dim=-1, keepdim=True)
        feat_b = feat_b / feat_b.norm(dim=-1, keepdim=True)
        cos = float((feat_a @ feat_b.T).item())
        return max(0.0, min(1.0, cos))
    except Exception:
        return None
