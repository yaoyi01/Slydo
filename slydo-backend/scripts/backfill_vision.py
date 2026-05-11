#!/usr/bin/env python3
"""
视觉分析补跑脚本 — 对所有已入库但缺少视觉分析的 slide 进行 Phase2 视觉分析。

用法：
    python3 scripts/backfill_vision.py                    # 补跑所有 slides
    python3 scripts/backfill_vision.py --deck f358         # 只补跑特定 deck (前缀匹配)
    python3 scripts/backfill_vision.py --resume            # 从断点继续 (只处理 visual_desc='' 的)
    python3 scripts/backfill_vision.py --dry-run           # 只统计不执行
    python3 scripts/backfill_vision.py --max-concurrency 2 # 并发数 (默认1, 视觉模型建议1)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# 确保项目路径正确
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import async_session_factory
from app.services.etl.phase2_vision import llm_extract_meaning_single
from app.utils.token_counter import TokenCounter
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_vision")


async def get_pending_slides(deck_prefix: str | None = None, resume: bool = False) -> list[dict]:
    """从 PG 中读取需要补视觉分析的 slides。"""
    async with async_session_factory() as session:
        # 先查所有 deck
        if deck_prefix:
            r = await session.execute(
                text("SELECT id::text, title FROM decks WHERE id::text LIKE :prefix ORDER BY created_at"),
                {"prefix": f"{deck_prefix}%"},
            )
        else:
            r = await session.execute(text("SELECT id::text, title FROM decks ORDER BY created_at"))

        decks = r.fetchall()
        slides = []

        for row in decks:
            deck_id = row.id
            deck_title = row.title

            # 取每个 deck 的最新版本 slides
            if resume:
                r2 = await session.execute(
                    text("""
                        SELECT slide_index, title, body_text, notes_text, thumbnail_path
                        FROM slides
                        WHERE deck_id = CAST(:did AS uuid)
                          AND (visual_desc IS NULL OR visual_desc = '')
                          AND thumbnail_path IS NOT NULL
                          AND thumbnail_path != ''
                        ORDER BY slide_index
                    """),
                    {"did": deck_id},
                )
            else:
                r2 = await session.execute(
                    text("""
                        SELECT slide_index, title, body_text, notes_text, thumbnail_path
                        FROM slides
                        WHERE deck_id = CAST(:did AS uuid)
                          AND thumbnail_path IS NOT NULL
                          AND thumbnail_path != ''
                        ORDER BY slide_index
                    """),
                    {"did": deck_id},
                )

            rows = r2.fetchall()
            if rows:
                logger.info(f"  Deck [{deck_title}] ({deck_id[:8]}...): {len(rows)} 页待分析")
                for srow in rows:
                    slides.append({
                        "deck_id": deck_id,
                        "deck_title": deck_title,
                        "slide_index": srow.slide_index,
                        "title": srow.title or "",
                        "body_text": srow.body_text or "",
                        "notes_text": srow.notes_text or "",
                        "thumbnail_path": srow.thumbnail_path or "",
                    })

        return slides


async def update_slide_vision(deck_id: str, slide_index: int, result: dict) -> None:
    """更新 PG 中单个 slide 的视觉分析结果。"""
    async with async_session_factory() as session:
        await session.execute(
            text("""
                UPDATE slides
                SET semantic_role = :role,
                    semantic_summary = :summary,
                    visual_desc = :visual_desc,
                    semantic_tags = :tags
                WHERE deck_id = CAST(:did AS uuid)
                  AND slide_index = :idx
            """),
            {
                "did": deck_id,
                "idx": slide_index,
                "role": result["semantic_role"],
                "summary": result["semantic_summary"],
                "visual_desc": result["visual_desc"],
                "tags": result["semantic_tags"],
            },
        )
        await session.commit()


async def main():
    parser = argparse.ArgumentParser(description="视觉分析补跑")
    parser.add_argument("--deck", help="只补跑特定 deck (UUID 前缀)")
    parser.add_argument("--resume", action="store_true", help="从断点继续 (只处理 visual_desc='')")
    parser.add_argument("--dry-run", action="store_true", help="只统计不执行")
    parser.add_argument("--max-concurrency", type=int, default=1, help="并发数 (默认1)")
    args = parser.parse_args()

    logger.info("🔍 正在扫描待分析的 slides...")
    slides = await get_pending_slides(deck_prefix=args.deck, resume=args.resume or True)

    if not slides:
        logger.info("✅ 没有需要分析的 slide")
        return

    total = len(slides)
    logger.info(f"📊 共 {total} 页需要视觉分析")

    if args.dry_run:
        logger.info("🏁 DRY RUN 模式，不执行分析")
        return

    # 确认视觉模型可用（DashScope 或 Ollama）
    use_dashscope = bool(settings.dashscope_api_key)
    if use_dashscope:
        logger.info(f"  使用 DashScope 视觉模型: {settings.dashscope_vision_model}")
    else:
        import httpx
        try:
            base = settings.ollama_base_url
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{base}/api/tags")
                if r.status_code == 200:
                    models = [m["name"] for m in r.json().get("models", []) if "name" in m]
                    logger.info(f"  Ollama 模型: {models}")
                    vision_model = [m for m in models if "vl" in m]
                    if vision_model:
                        logger.info(f"  视觉模型: {vision_model}")
                    else:
                        logger.warning("⚠️ 未找到视觉模型 (含 vl 的模型)")
                else:
                    logger.warning(f"⚠️ Ollama 返回 {r.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Ollama 连接失败: {e}")

    counter = TokenCounter(model_name=settings.dashscope_vision_model if use_dashscope else settings.ollama_vision_model)
    start_time = time.time()
    success = 0
    failed = 0

    for i, slide in enumerate(slides, 1):
        idx = slide["slide_index"]
        title = slide["title"]
        deck_title = slide["deck_title"]
        thumb_path = slide["thumbnail_path"]

        logger.info(f"[{i}/{total}] {deck_title[:20]}... :{idx} ({title[:30]})")

        # 构建 slide_data
        slide_data = {
            "slide_index": idx,
            "title": title,
            "body_text": slide["body_text"],
            "notes_text": slide["notes_text"],
        }

        # 缩略图目录
        thumb_dir = Path(thumb_path).parent if thumb_path else None

        try:
            result = await llm_extract_meaning_single(
                slide_data,
                thumbnail_dir=thumb_dir,
                counter=counter,
            )
            await update_slide_vision(
                deck_id=slide["deck_id"],
                slide_index=idx,
                result=result,
            )
            summary_preview = result.get("semantic_summary", "")[:40]
            logger.info(f"  ✅ 完成: {summary_preview}")
            success += 1
        except Exception as e:
            logger.error(f"  ❌ 失败: {e}")
            failed += 1

        # 每 50 页日志输出进度
        if i % 50 == 0:
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (total - i) / rate if rate > 0 else 0
            logger.info(
                f"  ⏱️ 进度: {i}/{total} ({i/total*100:.0f}%), "
                f"耗时: {elapsed:.0f}s, 速度: {rate:.1f}页/s, "
                f"预计剩余: {eta:.0f}s ({eta/60:.0f}min)"
            )

    elapsed = time.time() - start_time
    logger.info(counter.print_report())
    logger.info(
        f"🏁 视觉分析完成: "
        f"成功={success}, 失败={failed}, "
        f"总计={total}, 耗时={elapsed:.0f}s ({elapsed/60:.1f}min)"
    )


if __name__ == "__main__":
    asyncio.run(main())
