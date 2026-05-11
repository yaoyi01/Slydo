"""
API 路由 — 推荐与搜索
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.recommend import recommend_slides

router = APIRouter(prefix="/api", tags=["推荐与搜索"])


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
    return {
        "status": "ok",
        "query": {"title": title, "keywords": keywords},
        "count": len(results),
        "results": results,
    }


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
