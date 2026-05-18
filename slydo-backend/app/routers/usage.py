"""
API 路由 — 使用统计

提供：
1. POST /api/usage/log — 记录搜索/浏览/导入行为
2. GET /api/usage/stats — 使用统计查询（按页面/文档/时间）
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.routers.auth import get_current_user
from app.database import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/usage", tags=["使用统计"], dependencies=[Depends(get_current_user)])


# ═══════════════════════════════════════════════════════════
# 1. 记录使用行为
# ═══════════════════════════════════════════════════════════


@router.post("/log")
@router.get("/log")
async def api_log_usage(
    action: str = Query(..., description="行为类型: search / view / import"),
    slide_id: str = Query("", description="页面 ID（view/import 时必填）"),
    deck_id: str = Query("", description="文档 ID"),
    query: str = Query("", description="搜索关键词（search 时填写）"),
    user_id: str = Query("", description="操作用户（可选）"),
):
    """
    记录一次使用行为。

    - search：搜索记录（仅记录 query，不关联具体页面）
    - view：浏览/推荐结果点击（需 slide_id）
    - import：导入/导出页面（需 slide_id）
    """
    import uuid as uuid_mod

    try:
        async with async_session_factory() as session:
            if action == "search":
                # 搜索行为不关联具体 slide，slide_id 为 NULL
                await session.execute(
                    text("""
                        INSERT INTO usage_log (slide_id, action, user_id, created_at, metadata)
                        VALUES (NULL, 'search', :user_id, NOW(),
                                jsonb_build_object(
                                    'query', CAST(:query AS text)
                                ))
                    """),
                    {"query": query or "", "user_id": user_id or None},
                )
            elif slide_id:
                # 验证 slide_id
                try:
                    uuid_mod.UUID(slide_id)
                except ValueError:
                    # 非 UUID 格式，反查
                    result = await session.execute(
                        text("SELECT id::text FROM slides WHERE qdrant_point_id = :pid"),
                        {"pid": slide_id},
                    )
                    row = result.fetchone()
                    if row:
                        slide_id = row[0]
                    else:
                        raise HTTPException(status_code=400, detail=f"无效的 slide_id: {slide_id}")

                # 用 CAST 替换 ::uuid 语法（asyncpg 不支持参数级 :: 转换）
                await session.execute(
                    text("""
                        INSERT INTO usage_log (slide_id, action, user_id, created_at, metadata)
                        VALUES (CAST(:sid AS uuid), :action, :user_id, NOW(),
                                jsonb_build_object('deck_id', CAST(NULLIF(:deck_id, '') AS text)))
                    """),
                    {
                        "sid": slide_id,
                        "action": action,
                        "user_id": user_id or None,
                        "deck_id": deck_id or "",
                    },
                )

                # 更新 usage_count
                await session.execute(
                    text("UPDATE slides SET usage_count = COALESCE(usage_count, 0) + 1 WHERE id = CAST(:sid AS uuid)"),
                    {"sid": slide_id},
                )
            else:
                raise HTTPException(status_code=400, detail="search 以外的操作需要 slide_id")

            await session.commit()

        return {"status": "ok", "detail": f"记录 {action} 成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[用法统计] 记录失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════
# 2. 使用统计查询
# ═══════════════════════════════════════════════════════════


@router.get("/stats")
async def api_usage_stats(
    days: int = Query(30, ge=1, le=365, description="统计最近 N 天"),
    limit: int = Query(20, ge=1, le=100, description="返回条目数"),
    action: str | None = Query(None, description="筛选行为类型（可选）"),
):
    """获取使用统计概览。"""
    since = datetime.utcnow() - timedelta(days=days)

    async with async_session_factory() as session:
        result = {}

        # 总览
        r = await session.execute(
            text("""
                SELECT
                    COUNT(*) AS total_logs,
                    COUNT(DISTINCT slide_id) AS unique_slides,
                    COUNT(DISTINCT user_id) AS unique_users
                FROM usage_log
                WHERE created_at >= :since
            """),
            {"since": since},
        )
        row = r.fetchone()
        result["overview"] = {
            "total_logs": row.total_logs or 0,
            "unique_slides": row.unique_slides or 0,
            "unique_users": row.unique_users or 0,
            "period_days": days,
        }

        # 按行为类型分布
        r = await session.execute(
            text("""
                SELECT action, COUNT(*) AS cnt
                FROM usage_log
                WHERE created_at >= :since
                GROUP BY action
                ORDER BY cnt DESC
            """),
            {"since": since},
        )
        result["by_action"] = [{"action": row[0], "count": row[1]} for row in r.fetchall()]

        # 按日趋势
        r = await session.execute(
            text("""
                SELECT DATE(created_at) AS d, action, COUNT(*) AS cnt
                FROM usage_log
                WHERE created_at >= :since
                GROUP BY DATE(created_at), action
                ORDER BY d DESC
            """),
            {"since": since},
        )
        trend = {}
        for row in r.fetchall():
            d_str = row.d.isoformat() if row.d else ""
            if d_str not in trend:
                trend[d_str] = {"date": d_str, "total": 0}
            trend[d_str]["total"] += row.cnt
            trend[d_str][row.action] = row.cnt
        result["daily_trend"] = sorted(trend.values(), key=lambda x: x["date"], reverse=True)[:31]

        # 热门页面（按使用次数排序）
        action_filter = ""
        params: dict[str, Any] = {"since": since, "limit": limit}
        if action:
            action_filter = " AND ul.action = :action"
            params["action"] = action

        r = await session.execute(
            text(f"""
                SELECT
                    ul.slide_id::text,
                    COALESCE(s.title, '') AS title,
                    s.slide_index,
                    COALESCE(d.title, '') AS deck_title,
                    COALESCE(d.department, '') AS deck_dept,
                    COUNT(*) AS usage_count
                FROM usage_log ul
                LEFT JOIN slides s ON s.id = ul.slide_id
                LEFT JOIN decks d ON d.id = s.deck_id
                WHERE ul.created_at >= :since{action_filter}
                  AND ul.slide_id IS NOT NULL
                  AND ul.slide_id != '00000000-0000-0000-0000-000000000000'::uuid
                GROUP BY ul.slide_id, s.title, s.slide_index, d.title, d.department
                ORDER BY usage_count DESC
                LIMIT :limit
            """),
            params,
        )
        result["top_slides"] = []
        for row in r.fetchall():
            result["top_slides"].append({
                "slide_id": row[0],
                "title": row.title or "",
                "slide_index": row.slide_index or 0,
                "deck_title": row.deck_title or "",
                "deck_dept": row.deck_dept or "",
                "usage_count": row.usage_count,
            })

        # 热门文档（按所有页面使用次数汇总）
        r = await session.execute(
            text("""
                SELECT
                    d.id::text,
                    COALESCE(d.title, '') AS title,
                    COALESCE(d.department, '') AS dept,
                    COUNT(*) AS total_usage,
                    COUNT(DISTINCT ul.slide_id) AS used_slides,
                    d.slide_count
                FROM usage_log ul
                JOIN slides s ON s.id = ul.slide_id
                JOIN decks d ON d.id = s.deck_id
                WHERE ul.created_at >= :since
                  AND ul.slide_id IS NOT NULL
                  AND ul.slide_id != '00000000-0000-0000-0000-000000000000'::uuid
                GROUP BY d.id, d.title, d.department, d.slide_count
                ORDER BY total_usage DESC
                LIMIT :limit
            """),
            {"since": since, "limit": limit},
        )
        result["top_decks"] = []
        for row in r.fetchall():
            cover_pct = round(row.used_slides / row.slide_count * 100, 1) if row.slide_count and row.slide_count > 0 else 0
            result["top_decks"].append({
                "deck_id": row[0],
                "title": row.title or "",
                "dept": row.dept or "",
                "total_usage": row.total_usage or 0,
                "used_slides": row.used_slides or 0,
                "slide_count": row.slide_count or 0,
                "coverage_pct": cover_pct,
            })

        # 搜索关键词 TOP
        r = await session.execute(
            text("""
                SELECT
                    ul.metadata->>'query' AS query,
                    COUNT(*) AS cnt
                FROM usage_log ul
                WHERE ul.created_at >= :since
                  AND ul.action = 'search'
                  AND ul.metadata->>'query' != ''
                  AND ul.metadata->>'query' IS NOT NULL
                GROUP BY ul.metadata->>'query'
                ORDER BY cnt DESC
                LIMIT :limit
            """),
            {"since": since, "limit": limit},
        )
        result["top_queries"] = [{"query": row[0], "count": row[1]} for row in r.fetchall() if row[0]]

        return {"status": "ok", "data": result}
