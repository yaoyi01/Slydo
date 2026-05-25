"""
API 路由 — 单页导出
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.routers.auth import get_current_user
from app.services.export import export_single_slide

router = APIRouter(prefix="/api/slides", tags=["单页导出"], dependencies=[Depends(get_current_user)])

# /api/v1/recommend/export 别名 — 兼容 VSTO 客户端
vsto_router = APIRouter(prefix="/api/v1/recommend", tags=["单页导出（VSTO 兼容）"], dependencies=[Depends(get_current_user)])


@router.get("/{slide_id}/export")
async def api_export_slide_path(slide_id: str):
    """导出单页幻灯片为 PPTX 文件（path 参数）"""
    return await _export_slide(slide_id)


@vsto_router.get("/export")
async def api_export_slide_query(slide_id: str = Query("", description="slide UUID（VSTO 传 query 参数）")):
    """导出单页幻灯片为 PPTX 文件（query 参数，兼容 VSTO 客户端）"""
    return await _export_slide(slide_id)


async def _export_slide(slide_id: str):
    """导出单页幻灯片的核心逻辑"""
    try:
        buf = await export_single_slide(slide_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 记录使用日志并更新 usage_count
    try:
        from app.database import async_session_factory
        from sqlalchemy import text
        async with async_session_factory() as session:
            # 插入使用日志
            await session.execute(
                text("INSERT INTO usage_log (slide_id, action) VALUES (:sid, 'import')"),
                {"sid": slide_id},
            )
            # 更新 slide.usage_count（增量 +1）
            await session.execute(
                text("UPDATE slides SET usage_count = COALESCE(usage_count, 0) + 1 WHERE id = CAST(:sid AS uuid)"),
                {"sid": slide_id},
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"记录 usage_log 失败: {e}")

    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        headers={
            "Content-Disposition": f"attachment; filename=slide_{slide_id[:8]}.pptx",
        },
    )
