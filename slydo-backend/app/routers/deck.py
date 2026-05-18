"""
API 路由 — Deck 文档管理
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import joinedload

from app.config import settings
from app.database import async_session_factory
from app.models.deck import Deck
from app.models.slide import Slide
from app.qdrant import COLLECTION_NAME, get_qdrant
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/decks", tags=["文档管理"], dependencies=[Depends(get_current_user)])


def _slide_to_dict(slide: Slide) -> dict:
    return {
        "id": str(slide.id),
        "slide_index": slide.slide_index,
        "title": slide.title or "",
        "semantic_role": slide.semantic_role or "",
        "semantic_summary": slide.semantic_summary or "",
        "semantic_tags": slide.semantic_tags or [],
        "thumbnail_path": slide.thumbnail_path or "",
        "quality_score": slide.quality_score,
    }


def _deck_to_dict(deck: Deck, include_slides: bool = False) -> dict:
    data = {
        "id": str(deck.id),
        "title": deck.title,
        "department": deck.department or "",
        "category": deck.category or "",
        "slide_count": deck.slide_count,
        "version": deck.version,
        "is_official": deck.is_official,
        "file_path": deck.file_path or "",
        "checksum": deck.checksum or "",
        "created_at": deck.created_at.isoformat() if deck.created_at else "",
        "updated_at": deck.updated_at.isoformat() if deck.updated_at else "",
    }
    if include_slides and deck.slides:
        data["slides"] = [_slide_to_dict(s) for s in sorted(deck.slides, key=lambda x: x.slide_index)]
    return data


# ─── 查询 ───────────────────────────────────────────────────


@router.get("/{deck_id}")
async def api_get_deck(deck_id: str, include_slides: bool = False):
    """
    获取文档详情。

    - deck_id: Deck UUID
    - include_slides: 是否包含页面列表（可选参数）
    """
    try:
        uid = uuid.UUID(deck_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的 UUID: {deck_id}")

    async with async_session_factory() as session:
        stmt = select(Deck).where(Deck.id == uid)
        if include_slides:
            stmt = stmt.options(joinedload(Deck.slides))
        result = await session.execute(stmt)
        deck = result.unique().scalar_one_or_none()

    if deck is None:
        raise HTTPException(status_code=404, detail=f"Deck {deck_id} 不存在")

    return {"status": "ok", "data": _deck_to_dict(deck, include_slides=include_slides)}


# ─── 删除 ───────────────────────────────────────────────────


@router.delete("/{deck_id}")
async def api_delete_deck(deck_id: str):
    """
    删除文档及其关联数据（级联）。

    级联清理内容：
        - slides（DB 行）
        - deck_versions（DB 行）
        - Qdrant 中该 deck 对应的所有 points
        - LLM Wiki 中的对应文件夹
    """
    try:
        uid = uuid.UUID(deck_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的 UUID: {deck_id}")

    # 1. 查询 Deck 信息（用于后续清理）
    async with async_session_factory() as session:
        stmt = select(Deck).options(joinedload(Deck.slides)).where(Deck.id == uid)
        result = await session.execute(stmt)
        deck = result.unique().scalar_one_or_none()

    if deck is None:
        raise HTTPException(status_code=404, detail=f"Deck {deck_id} 不存在")

    # 2. 清理 Qdrant — 删除该 deck 的所有 points
    try:
        qdrant = get_qdrant()
        slide_ids = [str(s.id) for s in deck.slides]
        if slide_ids:
            if hasattr(qdrant, 'delete'):
                qdrant.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=slide_ids,
                )
            else:
                # Qdrant 1.17+
                from qdrant_client.http import models
                qdrant.delete(
                    collection_name=COLLECTION_NAME,
                    points_selector=models.Filter(
                        must=[models.FieldCondition(
                            key="deck_id",
                            match=models.MatchValue(value=str(deck.id)),
                        )]
                    ),
                )
            logger.info(f"[删除] Qdrant 已清理 deck {deck_id} 的 {len(slide_ids)} 个 points")
    except Exception as e:
        logger.warning(f"[删除] Qdrant 清理失败: {e}")

    # 3. 清理 LLM Wiki 文件夹
    try:
        wiki_root = Path(settings.slydo_wiki_path).expanduser()
        deck_wiki_dir = wiki_root / "slides" / f"deck_{deck_id}"
        if deck_wiki_dir.exists():
            import shutil
            shutil.rmtree(deck_wiki_dir)
            logger.info(f"[删除] Wiki 文件夹已删除: {deck_wiki_dir}")
    except Exception as e:
        logger.warning(f"[删除] Wiki 文件夹清理失败: {e}")

    # 4. 删除 DB 行（slides/deck_versions 通过 CASCADE 自动清理）
    async with async_session_factory() as session:
        stmt = delete(Deck).where(Deck.id == uid)
        await session.execute(stmt)
        await session.commit()

    return {"status": "ok", "detail": f"Deck {deck_id} 已删除"}


# ─── 列表 ───────────────────────────────────────────────────


@router.get("")
async def api_list_decks(
    category: str | None = None,
    department: str | None = None,
    limit: int = 20,
    offset: int = 0,
):
    """
    获取文档列表（支持分类/部门筛选）。
    """
    async with async_session_factory() as session:
        stmt = select(Deck).order_by(Deck.updated_at.desc())

        if category:
            stmt = stmt.where(Deck.category == category)
        if department:
            stmt = stmt.where(Deck.department == department)

        stmt = stmt.limit(limit).offset(offset)
        result = await session.execute(stmt)
        decks = result.scalars().all()

    return {
        "status": "ok",
        "count": len(decks),
        "items": [_deck_to_dict(d) for d in decks],
    }


# ─── 管理员标记 ⭐ ────────────────────────────────────────────


@router.post("/{deck_id}/toggle-official")
async def api_toggle_official(
    deck_id: str,
    slide_id: str | None = None,
    is_official: bool = True,
):
    """
    管理员标记某页面为金牌（is_official=true），
    或取消金牌（is_official=false）。

    - 如果提供了 slide_id，只标记该页面
    - 如果未提供，标记整个 deck 的所有页面
    """
    try:
        uid = uuid.UUID(deck_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"无效的 UUID: {deck_id}")

    async with async_session_factory() as session:
        if slide_id:
            try:
                slide_uid = uuid.UUID(slide_id)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"无效的 slide UUID: {slide_id}")

            stmt = select(Slide).where(Slide.id == slide_uid, Slide.deck_id == uid)
            result = await session.execute(stmt)
            slide = result.scalar_one_or_none()
            if slide is None:
                raise HTTPException(status_code=404, detail=f"Slide {slide_id} 不存在于 deck {deck_id}")

            slide.is_official = is_official
            updated_count = 1
        else:
            # 标记整个 deck
            stmt = select(Slide).where(Slide.deck_id == uid)
            result = await session.execute(stmt)
            slides = result.scalars().all()
            if not slides:
                raise HTTPException(status_code=404, detail=f"Deck {deck_id} 没有页面")
            for s in slides:
                s.is_official = is_official
            updated_count = len(slides)

        await session.commit()

    action = "标记为 ⭐ 金牌" if is_official else "取消 ⭐ 金牌"
    return {
        "status": "ok",
        "detail": f"{action}: {updated_count} 页",
        "data": {"deck_id": deck_id, "slide_id": slide_id, "is_official": is_official, "count": updated_count},
    }


import logging
logger = logging.getLogger(__name__)
