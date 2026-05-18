"""
API 路由 — 单页导出
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.export import export_single_slide

router = APIRouter(prefix="/api/slides", tags=["单页导出"])

# /api/v1/recommend/export 别名 — 兼容 VSTO 客户端
vsto_router = APIRouter(prefix="/api/v1/recommend", tags=["单页导出（VSTO 兼容）"])


@router.get("/{slide_id}/export")
@vsto_router.get("/export")
async def api_export_slide(slide_id: str = ""):
    """
    导出单页幻灯片为 PPTX 文件。

    返回：PPTX 文件流（Content-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation）
    """
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
