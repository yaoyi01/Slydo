"""
API 路由 — 缩略图服务
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import settings
from app.database import async_session_factory
from app.routers.auth import get_current_user
from app.models.slide import Slide

router = APIRouter(prefix="/api/v1/thumbnails", tags=["缩略图"], dependencies=[Depends(get_current_user)])

# 缩略图根目录
_wiki_root = Path(settings.slydo_wiki_path).expanduser()
_thumb_root = _wiki_root / "thumbnails"


@router.get("/{slide_id}")
async def get_thumbnail(slide_id: str):
    """
    按 slide_id 查找并返回缩略图。

    通过 DB 查询 slide 记录获取 deck_id 和 slide_index，
    然后定位到 thumbnails/deck_{name}/slide_{index:03d}.png。
    """
    # 先查 DB 获取 slide 的 deck_id 和 slide_index
    async with async_session_factory() as session:
        try:
            uid = uuid.UUID(slide_id)
            stmt = select(Slide).where(Slide.id == uid).options(joinedload(Slide.deck))
        except ValueError:
            stmt = select(Slide).where(Slide.qdrant_point_id == slide_id).options(joinedload(Slide.deck))

        result = await session.execute(stmt)
        slide = result.scalar_one_or_none()

    if slide is None:
        raise HTTPException(status_code=404, detail="Slide 不存在")

    # DB 中已有 thumbnail_path，先用它
    if slide.thumbnail_path and Path(slide.thumbnail_path).exists():
        return FileResponse(str(Path(slide.thumbnail_path)), media_type="image/png")

    # 按 thumbnails/deck_{name}/slide_{index:03d}.png 格式查找
    deck_name = slide.deck.title if slide.deck else str(slide.deck_id)[:8]
    thumb_path = _thumb_root / f"deck_{deck_name}" / f"slide_{slide.slide_index:03d}.png"
    if thumb_path.exists():
        return FileResponse(str(thumb_path), media_type="image/png")

    raise HTTPException(status_code=404, detail="缩略图未找到")
