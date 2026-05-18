"""
API 路由 — 版本管理
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.routers.auth import get_current_user
from app.services.etl.version_manager import restore_deck, cleanup_old_versions, update_deck

router = APIRouter(prefix="/api/decks", tags=["版本管理"], dependencies=[Depends(get_current_user)])


@router.post("/{deck_id}/restore")
async def api_restore_deck(deck_id: str, target_version: int | None = None):
    """
    从历史版本恢复文档。

    - deck_id: Deck UUID
    - target_version: 目标版本号（不传则恢复上一版）
    """
    try:
        result = await restore_deck(deck_id, target_version=target_version)
        return {"status": "ok", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{deck_id}/update")
async def api_update_deck(deck_id: str, new_pptx_path: str):
    """
    更新文档（旧版归档 → 新版覆盖）。

    - deck_id: Deck UUID
    - new_pptx_path: 新 PPT 文件路径
    """
    try:
        uuid.UUID(deck_id)  # 验证 UUID 格式
        result = await update_deck(deck_id, new_pptx_path)
        return {"status": "ok", "data": result}
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cleanup-versions")
async def api_cleanup_versions(max_versions: int = 2):
    """
    清理超过 max_versions 个版本的旧记录。
    默认保留最近 2 个版本。
    """
    result = await cleanup_old_versions(max_versions=max_versions)
    return {"status": "ok", "data": result}
