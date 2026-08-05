"""视觉预识别路由（支撑前端发布页 AI 识别结果卡片，P0-04）。

POST /api/v1/vision/predict：读取首图字节 → `get_vision_service().predict()`
→ 返回 `{category_id, label, confidence, categories}`。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.category import Category
from app.routers.deps import get_current_user
from app.schemas.vision import VisionCategory, VisionPredictResponse
from app.services.vision_service import get_vision_service

router = APIRouter(prefix="/vision", tags=["vision"])


@router.post("/predict", response_model=VisionPredictResponse)
async def predict(
    image: UploadFile = File(..., description="待识别图片"),
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """发布前预识别：返回 AI 识别的类别 / 标签 / 置信度，及可选分类列表（供手动纠偏）。"""
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="图片内容为空")
    result = get_vision_service().predict(data)
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
