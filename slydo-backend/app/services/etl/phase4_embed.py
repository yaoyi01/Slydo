"""
ETL Phase 4: 语义向量嵌入 → Qdrant

将 slide 的语义摘要通过嵌入模型转为向量，写入 Qdrant 向量库。

注意：在云部署环境中（无本地 Ollama），嵌入可能降级使用零向量，
语义搜索功能会受限但入库流程不会被阻塞。
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from qdrant_client import models as qdrant_models

from app.config import settings
from app.models.deck import Deck
from app.qdrant import COLLECTION_NAME, get_qdrant

logger = logging.getLogger(__name__)

# 内置降级：当嵌入服务不可用时用此维度
FALLBACK_VECTOR_SIZE = 1024


async def embed_text(text: str) -> list[float]:
    """
    调用嵌入服务生成向量。

    优先使用 Ollama bge-m3（settings.ollama_base_url），
    如果不可用则返回零向量并记录警告。
    """
    try:
        url = f"{settings.ollama_base_url}/api/embed"
        payload = {"model": "bge-m3", "input": [text]}
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        embeddings = data.get("embeddings", [])
        if embeddings:
            return embeddings[0]
        raise ValueError("嵌入服务返回空数据")
    except Exception as e:
        logger.warning(f"嵌入服务不可用（使用零向量降级）: {e}")
        return [0.0] * FALLBACK_VECTOR_SIZE


def build_embedding_text(slide: dict[str, Any]) -> str:
    """
    构建用于嵌入的文本。

    策略：
        - 标题 + 含义摘要 + 视觉描述 + 语义标签
        - 而非原始文本，确保语义一致性
        - 纯图片页也能靠视觉描述做语义匹配
    """
    parts = []
    title = (slide.get("title") or "").strip()
    if title:
        parts.append(f"标题: {title}")
    summary = (slide.get("semantic_summary") or "").strip()
    if summary:
        parts.append(f"摘要: {summary}")
    visual = (slide.get("visual_desc") or "").strip()
    if visual:
        parts.append(f"视觉: {visual}")
    tags = slide.get("semantic_tags") or []
    if tags:
        parts.append(f"标签: {', '.join(tags[:8])}")

    return "\n".join(parts)


async def embed_to_qdrant(
    deck_id: str,
    slides: list[dict[str, Any]],
    batch_size: int = 10,
) -> int:
    """
    将 slide 的语义摘要批量嵌入并写入 Qdrant。

    流程：
        1. 为每个 slide 构建嵌入文本
        2. 调用嵌入服务生成向量
        3. upsert 到 Qdrant "slides" collection

    返回：成功写入 Qdrant 的点数
    """
    client = get_qdrant()
    points: list[qdrant_models.PointStruct] = []

    for s in slides:
        slide_id = s.get("slide_id") or str(s.get("slide_index", 0))
        embed_text_content = build_embedding_text(s)
        vector = await embed_text(embed_text_content)

        payload = {
            "deck_id": deck_id,
            "slide_index": s.get("slide_index", 0),
            "title": (s.get("title") or "")[:200],
            "semantic_role": s.get("semantic_role") or "unknown",
            "semantic_tags": (s.get("semantic_tags") or [])[:8],
            "thumbnail_path": s.get("thumbnail_path") or "",
            "quality_score": s.get("quality_score", 0.0),
        }

        points.append(
            qdrant_models.PointStruct(
                id=hash(f"{deck_id}_{s.get('slide_index', 0)}") & ((1 << 63) - 1),
                vector=vector,
                payload=payload,
            )
        )

        if len(points) >= batch_size:
            client.upsert(
                collection_name=COLLECTION_NAME,
                points=points,
                wait=True,
            )
            logger.info(f"[Qdrant] 写入 {len(points)} 个 vectors")
            points = []

    if points:
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True,
        )
        logger.info(f"[Qdrant] 写入 {len(points)} 个 vectors（尾批）")

    logger.info(f"[Qdrant] 完成: deck={deck_id}, slides={len(slides)}")
    return len(slides)
