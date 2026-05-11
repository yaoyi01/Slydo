"""
API 路由 — Slide 页面管理
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.database import async_session_factory
from app.models.slide import Slide
from app.models.deck import Deck

router = APIRouter(prefix="/api/slides", tags=["页面管理"])


def _slide_to_dict(slide: Slide) -> dict:
    return {
        "id": str(slide.id),
        "deck_id": str(slide.deck_id),
        "slide_index": slide.slide_index,
        "title": slide.title or "",
        "body_text": (slide.body_text or "")[:200],
        "semantic_role": slide.semantic_role or "",
        "semantic_summary": slide.semantic_summary or "",
        "semantic_tags": slide.semantic_tags or [],
        "layout_type": slide.layout_type or "",
        "visual_desc": slide.visual_desc or "",
        "thumbnail_path": slide.thumbnail_path or "",
        "usage_count": slide.usage_count,
        "quality_score": slide.quality_score,
        "created_at": slide.created_at.isoformat() if slide.created_at else "",
    }


@router.get("/{slide_id}")
async def api_get_slide(slide_id: str):
    """
    获取页面详情。

    - slide_id: Slide UUID 或 Qdrant point ID（推荐引擎返回的 ID）
    """
    # 支持两种 ID 格式：UUID 或 Qdrant point ID（数字字符串）
    async with async_session_factory() as session:
        stmt = select(Slide).options(joinedload(Slide.deck))

        try:
            uid = uuid.UUID(slide_id)
            stmt = stmt.where(Slide.id == uid)
        except ValueError:
            # 不是 UUID 格式，尝试按 qdrant_point_id 或 id::text 查询
            stmt = stmt.where(Slide.qdrant_point_id == slide_id)

        result = await session.execute(stmt)
        slide = result.scalar_one_or_none()

    if slide is None:
        raise HTTPException(status_code=404, detail=f"Slide {slide_id} 不存在")

    data = _slide_to_dict(slide)
    data["deck_title"] = slide.deck.title if slide.deck else ""

    return {"status": "ok", "data": data}
