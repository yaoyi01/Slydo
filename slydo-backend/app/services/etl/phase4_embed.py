"""
ETL Phase 4: 向量嵌入 — BGE-M3 → Qdrant

核心能力：
    1. embed_text() — 调用 Ollama BGE-M3 生成向量
    2. embed_to_qdrant() — 批量嵌入 + Qdrant upsert
    3. 基于语义摘要 + 视觉描述 + 标题 + 标签生成嵌入向量
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from qdrant_client import models as qdrant_models

from app.config import settings
from app.qdrant import COLLECTION_NAME, get_qdrant

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 1. BGE-M3 文本嵌入
# ═══════════════════════════════════════════════════════════


async def embed_text(text: str) -> list[float]:
    """
    使用 Ollama BGE-M3 模型将文本转换为 1024 维向量。

    参数：
        text: 待嵌入文本

    返回：
        list[float] — 1024 维向量

    注意：
        如果 text 为空，返回全零向量（不会调用 API）
    """
    text = text.strip() if text else ""
    if not text:
        logger.warning("[embed] 收到空文本，返回全零向量")
        return [0.0] * 1024

    url = f"{settings.ollama_base_url}/api/embed"
    payload = {
        "model": "bge-m3",
        "input": [text],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    embeddings = data.get("embeddings", [])
    if not embeddings:
        raise ValueError("BGE-M3 返回空嵌入")

    return embeddings[0]


def build_embedding_text(slide: dict[str, Any]) -> str:
    """
    构建用于嵌入的文本。

    策略（与设计说明书一致）：
        - 标题 + 含义摘要 + 视觉描述 + 语义标签
        - 而非原始文本，确保语义一致性
        - 纯图片页也能靠视觉描述做语义匹配
    """
    parts = []
    title = (slide.get("title") or "").strip()
    summary = (slide.get("semantic_summary") or "").strip()
    visual = (slide.get("visual_desc") or "").strip()
    tags = slide.get("semantic_tags") or []

    if title:
        parts.append(f"标题: {title}")
    if summary:
        parts.append(f"含义: {summary}")
    if visual:
        parts.append(f"视觉: {visual}")
    if tags:
        parts.append(f"标签: {', '.join(tags[:8])}")

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════
# 2. 批量嵌入 + Qdrant upsert
# ═══════════════════════════════════════════════════════════


async def embed_to_qdrant(
    deck_id: str,
    slides: list[dict[str, Any]],
    batch_size: int = 10,
) -> int:
    """
    将 slide 的语义摘要批量嵌入并写入 Qdrant。

    流程：
        1. 为每个 slide 构建嵌入文本（标题+摘要+视觉+标签）
        2. 调用 BGE-M3 生成向量
        3. upsert 到 Qdrant "slides" collection

    参数：
        deck_id: Deck UUID
        slides: slide dict 列表（含 Phase2 结果）
        batch_size: 每批嵌入数量（默认 10）

    返回：
        int — 成功写入 Qdrant 的点数
    """
    client = get_qdrant()
    points: list[qdrant_models.PointStruct] = []

    for s in slides:
        slide_id = s.get("slide_id") or str(s.get("slide_index", 0))
        embed_text_content = build_embedding_text(s)

        # 生成向量
        vector = await embed_text(embed_text_content)

        # 构建 payload（用于搜索过滤 + 结果展示）
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

    # 剩余批次
    if points:
        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True,
        )
        logger.info(f"[Qdrant] 写入 {len(points)} 个 vectors（尾批）")

    logger.info(
        f"[Qdrant] 完成: deck={deck_id}, slides={len(slides)}"
    )
    return len(slides)
