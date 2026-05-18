"""
API 路由 — 推荐与搜索
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.auth import get_current_user
from app.services.recommend import recommend_slides

router = APIRouter(prefix="/api", tags=["推荐与搜索"], dependencies=[Depends(get_current_user)])


@router.get("/recommend")
@router.get("/v1/recommend/slides")
async def api_recommend(
    q: str = Query("", description="搜索关键词（兼容 VSTO 客户端）"),
    title: str = Query("", description="当前页面标题"),
    keywords: str = Query("", description="搜索关键词"),
    top_n: int = Query(20, ge=1, le=20, alias="top_k", description="返回结果数"),
):
    """推荐幻灯片页面。"""
    context_title = str(title) if title else ""
    context_keywords = str(keywords) if keywords else ""
    if q and not context_keywords:
        context_keywords = str(q)
    if not context_title and not context_keywords:
        context_keywords = ""

    results = await recommend_slides(
        context_title=context_title,
        context_keywords=context_keywords,
        top_n=top_n,
    )

    # 异步记录搜索行为
    record_usage(context_keywords, results)

    return {
        "status": "ok",
        "query": {"title": title, "keywords": keywords},
        "count": len(results),
        "results": results,
    }


def record_usage(query: str, results: list[dict]) -> None:
    """后台记录搜索日志（不阻塞推荐响应）"""
    import asyncio
    import logging

    logger = logging.getLogger(__name__)

    async def _do():
        from app.database import async_session_factory
        from sqlalchemy import text
        try:
            async with async_session_factory() as session:
                # 记录搜索行为（不关联具体 slide）
                await session.execute(
                    text("""
                        INSERT INTO usage_log (slide_id, action, metadata)
                        VALUES (NULL, 'search',
                                jsonb_build_object('query', :query))
                    """),
                    {"query": query or ""},
                )
                # 对推荐结果中的每个页面记录 view 行为
                for r in results[:5]:  # 只记录点击结果的前5个（浏览视图）
                    sid = r.get("slide_id", "")
                    if sid and sid != "00000000-0000-0000-0000-000000000000":
                        await session.execute(
                            text("INSERT INTO usage_log (slide_id, action) VALUES (CAST(:sid AS uuid), 'view')"),
                            {"sid": sid},
                        )
                        # 更新 usage_count
                        await session.execute(
                            text("UPDATE slides SET usage_count = COALESCE(usage_count, 0) + 1 WHERE id = CAST(:sid AS uuid)"),
                            {"sid": sid},
                        )
                await session.commit()
        except Exception:
            pass

    try:
        asyncio.create_task(_do())
    except Exception:
        pass


@router.get("/recommend/outline")
async def api_outline_recommend(
    titles: str = Query("", description="已完成页面标题列表（逗号分隔，按顺序）"),
    current: str = Query("", description="当前页面标题"),
    top_k: int = Query(3, ge=1, le=6, description="返回走向数"),
):
    """场景 B：大纲推理推荐 — 根据已完成页面序列推理接下来的逻辑走向。"""
    from app.services.recommend import outline_reasoning

    title_list = [t.strip() for t in titles.split(",") if t.strip()]
    results = await outline_reasoning(
        completed_titles=title_list,
        current_title=current,
        top_k=top_k,
    )
    return {
        "status": "ok",
        "completed_titles": title_list,
        "current_title": current,
        "directions": results,
    }
