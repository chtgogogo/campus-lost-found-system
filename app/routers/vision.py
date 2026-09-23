"""视觉预识别路由（支撑前端发布页 AI 识别结果卡片，P0-04）。

POST /api/v1/vision/predict：读取首图字节 → `get_vision_service().predict()`
→ 返回 `{category_id, label, confidence, categories}`。
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.ratelimit import check_rate_limit
from app.models.category import Category
from app.models.user import User
from app.routers.deps import get_current_user
from app.schemas.vision import VisionCategory, VisionPredictResponse
from app.services.vision_service import get_vision_service
from app.utils.image_validator import validate_images

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/predict", response_model=VisionPredictResponse)
async def predict(
    image: UploadFile = File(..., description="待识别图片"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """发布前预识别：返回 AI 识别的类别 / 标签 / 置信度，及可选分类列表（供手动纠偏）。"""
    check_rate_limit(f"user:{user.id}", 30)
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片内容为空")
    validate_images([(image.filename or "img.jpg", data)])
    # 卡7（安检 P3）：YOLO 推理为秒级同步重活，移出事件循环（线程池执行），
    # 避免阻塞整个 asyncio loop（期间登录等所有请求排队）。
    result = await asyncio.to_thread(get_vision_service().predict, data)
    # 活跃分类列表（供前端手动改类下拉）
    cats = (
        db.query(Category.id, Category.name)
        .filter(Category.is_active == 1)
        .order_by(Category.id)
        .all()
    )
    categories = [VisionCategory(id=c.id, name=c.name) for c in cats]
    return VisionPredictResponse(
        category_id=result["category_id"],
        label=result["label"],
        confidence=result["confidence"],
        categories=categories,
    )
