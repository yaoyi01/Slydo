"""
API 路由 — 缩略图服务
"""
from __future__ import annotations

import uuid
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from PIL import Image
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

# 缩略图缩放尺寸（宽高自适应，保持比例）
THUMB_MAX_WIDTH = 400
THUMB_MAX_HEIGHT = 225

# 内存缓存：避免每次请求都查数据库和重新处理图片
# 键为 slide_id + 缩略图路径，值为缩放后的 PNG bytes
_thumb_cache: dict[str, bytes] = {}
_THUMB_CACHE_MAX = 500  # 最多缓存 500 张


def _resize_image(image_path: Path) -> bytes:
    """读取图片、等比缩放到 THUMB_MAX 尺寸，返回压缩后的 PNG bytes"""
    img = Image.open(image_path)
    img.thumbnail((THUMB_MAX_WIDTH, THUMB_MAX_HEIGHT), Image.LANCZOS if hasattr(Image, 'LANCZOS') else Image.ANTIALIAS)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _get_cached_thumbnail(image_path: Path) -> bytes:
    """带 LRU 缓存的缩略图获取"""
    cache_key = str(image_path.resolve())
    if cache_key in _thumb_cache:
        return _thumb_cache[cache_key]
    data = _resize_image(image_path)
    # 缓存管理：超过上限时清理一半
    if len(_thumb_cache) >= _THUMB_CACHE_MAX:
        # 删除前 250 个（简单清理）
        for k in list(_thumb_cache.keys())[:250]:
            del _thumb_cache[k]
    _thumb_cache[cache_key] = data
    return data


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
        try:
            data = _get_cached_thumbnail(Path(slide.thumbnail_path))
            return Response(content=data, media_type="image/png")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"缩略图处理失败: {e}")

    # 按 thumbnails/deck_{name}/slide_{index:03d}.png 格式查找
    deck_name = slide.deck.title if slide.deck else str(slide.deck_id)[:8]
    thumb_path = _thumb_root / f"deck_{deck_name}" / f"slide_{slide.slide_index:03d}.png"
    if thumb_path.exists():
        try:
            data = _get_cached_thumbnail(thumb_path)
            return Response(content=data, media_type="image/png")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"缩略图处理失败: {e}")

    raise HTTPException(status_code=404, detail="缩略图未找到")
