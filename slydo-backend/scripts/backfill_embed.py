#!/usr/bin/env python3
"""
补向量脚本 — 对缺少 Qdrant 向量的 deck 执行嵌入。

用法：
    python3 scripts/backfill_embed.py                      # 补所有缺少向量的
    python3 scripts/backfill_embed.py --deck 6ae9e3ad      # 只补特定 deck (前缀)
    python3 scripts/backfill_embed.py --dry-run             # 只统计不执行
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import async_session_factory
from app.services.etl.phase4_embed import embed_to_qdrant
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_embed")


async def get_decks_needing_embed(deck_prefix: str | None = None) -> list[dict]:
    """获取需要补向量的 decks，并读取它们的 slide 数据。"""
    from app.qdrant import COLLECTION_NAME, get_qdrant

    async with async_session_factory() as session:
        if deck_prefix:
            r = await session.execute(
                text("SELECT id::text, title FROM decks WHERE id::text LIKE :prefix ORDER BY created_at"),
                {"prefix": f"{deck_prefix}%"},
            )
        else:
            r = await session.execute(
                text("SELECT id::text, title FROM decks ORDER BY created_at")
            )
        all_decks = [{"deck_id": row.id, "title": row.title} for row in r.fetchall()]

    # 从 Qdrant 查出已有向量的 deck_id
    try:
        qdrant = get_qdrant()
        scroll_result = qdrant.scroll(
            collection_name=COLLECTION_NAME,
            limit=10000,
            with_payload=["deck_id"],
            with_vectors=False,
        )
        qdrant_deck_ids = set()
        for point in scroll_result[0]:
            did = point.payload.get("deck_id", "")
            if did:
                qdrant_deck_ids.add(did)
    except Exception as e:
        logger.warning(f"查询 Qdrant 失败: {e}")
        qdrant_deck_ids = set()

    # 过滤出不在 Qdrant 中的 deck
    candidates = []
    if deck_prefix:
        candidates = all_decks
    else:
        candidates = [d for d in all_decks if d["deck_id"] not in qdrant_deck_ids]

    # 读取每个 deck 的 slide 数据
    result = []
    async with async_session_factory() as session:
        for d in candidates:
            r = await session.execute(
                text("""
                    SELECT id::text, slide_index, title, body_text, notes_text,
                           semantic_role, semantic_summary, visual_desc, semantic_tags,
                           thumbnail_path, quality_score
                    FROM slides
                    WHERE deck_id = CAST(:did AS uuid)
                    ORDER BY slide_index
                """),
                {"did": d["deck_id"]},
            )
            slides = []
            for row in r.fetchall():
                slides.append({
                    "slide_id": row.id,
                    "slide_index": row.slide_index,
                    "title": row.title or "",
                    "body_text": row.body_text or "",
                    "notes_text": row.notes_text or "",
                    "semantic_role": row.semantic_role or "argument",
                    "semantic_summary": row.semantic_summary or "",
                    "visual_desc": row.visual_desc or "",
                    "semantic_tags": row.semantic_tags or [],
                    "thumbnail_path": row.thumbnail_path or "",
                    "quality_score": row.quality_score or 0.0,
                })
            result.append({**d, "slides": slides, "slide_count": len(slides)})

    return result


async def main():
    parser = argparse.ArgumentParser(description="向量嵌入补跑")
    parser.add_argument("--deck", help="只补特定 deck (UUID 前缀)")
    parser.add_argument("--dry-run", action="store_true", help="只统计不执行")
    args = parser.parse_args()

    logger.info("🔍 正在扫描需要补向量的 decks...")
    decks = await get_decks_needing_embed(deck_prefix=args.deck)

    if not decks:
        logger.info("✅ 没有需要补向量的 deck")
        return

    # 筛选指定 deck
    if args.deck:
        target = [d for d in decks if d["deck_id"].startswith(args.deck)]
        if not target:
            # 可能已有向量了
            logger.info(f"  Deck {args.deck} 可能已有向量，尝试直接处理")
            target = [d for d in decks if len(decks) == 1] or decks[:1]
        decks = target

    total_slides = sum(d["slide_count"] for d in decks)
    logger.info(f"📊 共 {len(decks)} 个 deck / {total_slides} 页需补向量")

    for d in decks:
        logger.info(f"  {d['title']}: {d['slide_count']} 页")

    if args.dry_run:
        logger.info("🏁 DRY RUN 模式，不执行")
        return

    start_time = time.time()
    total_points = 0

    for i, deck in enumerate(decks, 1):
        deck_id = deck["deck_id"]
        title = deck["title"]
        logger.info(f"[{i}/{len(decks)}] {title} ({deck['slide_count']} 页)")

        try:
            points = await embed_to_qdrant(
                deck_id=deck_id,
                slides=deck["slides"],
            )
            total_points += points
            logger.info(f"  ✅ {points} 个 vectors")
        except Exception as e:
            logger.error(f"  ❌ {e}")

        elapsed = time.time() - start_time
        rate = i / elapsed if elapsed > 0 else 0
        logger.info(f"  ⏱️ 进度: {i}/{len(decks)}, 耗时: {elapsed:.0f}s")

    elapsed = time.time() - start_time
    logger.info(f"🏁 完成: {len(decks)} decks, {total_points} vectors, 耗时 {elapsed:.0f}s")


if __name__ == "__main__":
    asyncio.run(main())
