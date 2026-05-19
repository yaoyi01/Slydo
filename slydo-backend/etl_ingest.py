#!/usr/bin/env python3
"""
Slydo ETL 入库入口 — 处理单份 PPT 文件

用法：
    python3 etl_ingest.py path/to/your.pptx
    python3 etl_ingest.py path/to/your.pptx --dry-run   # 仅提取+渲染，不入库
    python3 etl_ingest.py path/to/your.pptx --skip-vision # 跳过视觉模型分析

流程：
    Phase 1: 文档解析（文本提取）+ 页面渲染（PNG 缩略图）
    Phase 2: 多模态 LLM 含义提取（视觉模型）
    Phase 3: 结构化存储（PostgreSQL + LLM Wiki）
    Phase 4: 向量嵌入（BGE-M3 → Qdrant）
    Phase 5: 质量评分初始化
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import tempfile
import time
import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import settings
from app.services.etl.phase1_extract import (
    compute_checksum,
    extract_slides,
    render_slides_to_images,
)
from app.utils.token_counter import TokenCounter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("etl_ingest")


async def check_db_checksum(checksum: str) -> bool:
    """检查数据库中是否已存在相同 checksum 的文档。"""
    try:
        from app.database import async_session_factory
        from sqlalchemy import text
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT COUNT(*) FROM decks WHERE checksum = :cs"),
                {"cs": checksum},
            )
            count = result.scalar()
            if count and count > 0:
                logger.info(f"  [去重] 数据库已存在相同 checksum ({checksum[:12]}...)，跳过")
                return True
    except Exception as e:
        logger.warning(f"  [去重] 数据库检查失败: {e}")
    return False


async def ingest_pptx(pptx_path: str, *, dry_run: bool = False, skip_vision: bool = False, skip_embed: bool = False) -> int:
    """
    处理单份 PPT 文件的完整 ETL 流程。

    返回：处理的页面数量（0 表示跳过或失败）
    """
    pptx_path = Path(pptx_path).resolve()
    if not pptx_path.exists():
        logger.error(f"文件不存在: {pptx_path}")
        return 0
    if pptx_path.suffix.lower() not in (".pptx", ".ppt"):
        logger.warning(f"不支持的文件格式: {pptx_path.suffix}")
        return 0

    start_time = time.time()
    file_stem = pptx_path.stem
    mode_label = "【试运行】" if dry_run else ""
    logger.info(f"{mode_label} 开始处理: {file_stem}")

    # ── Phase 1: checksum ──────────────────────────────
    checksum = compute_checksum(pptx_path)
    logger.info(f"  Phase1 [去重] checksum={checksum[:16]}...")

    if not dry_run:
        exists = await check_db_checksum(checksum)
        if exists:
            return 0

    # ── Phase 1: 文本提取 ────────────────────────────
    slides = extract_slides(pptx_path)
    if not slides:
        logger.warning("  Phase1 [提取] 未能提取到任何页面")
        return 0

    logger.info(f"  Phase1 [提取] {len(slides)} 页")
    pure_img = sum(1 for s in slides if s["text_length"] == 0)
    if pure_img:
        logger.info(f"  Phase1 [提取] 其中 {pure_img} 页为纯图片页")

    # ── Phase 1: 页面渲染 ────────────────────────────
    # 使用临时目录渲染缩略图，Phase3 拿到 deck_id 后 rename 到正确目录
    thumb_temp_dir = Path(tempfile.mkdtemp(prefix="slydo_thumb_"))

    try:
        png_paths = render_slides_to_images(pptx_path, thumb_temp_dir, dpi=150)
        logger.info(f"  Phase1 [渲染] {len(png_paths)} 张缩略图")
        # 更新 slide dict 中的缩略图路径（临时路径）
        for s in slides:
            idx = s["slide_index"]
            thumb_path = thumb_temp_dir / f"slide_{idx:03d}.png"
            s["thumbnail_path"] = str(thumb_path) if thumb_path.exists() else ""
    except RuntimeError as e:
        logger.warning(f"  Phase1 [渲染] 失败: {e}")

    # ── Phase 2: 多模态含义提取 ───────────────────────
    if not skip_vision:
        from app.services.etl.phase2_vision import llm_extract_meaning_batch
        counter = TokenCounter(model_name=settings.ollama_vision_model)
        slides = await llm_extract_meaning_batch(
            slides, thumbnail_dir=thumb_temp_dir, max_concurrency=1, counter=counter,
        )
        logger.info(counter.print_report())
    else:
        logger.info("  Phase2 [视觉] 已跳过 (--skip-vision)")
        for s in slides:
            s["semantic_role"] = "argument"
            s["semantic_summary"] = ""
            s["visual_desc"] = ""
            s["semantic_tags"] = []

    # dry-run 到此结束
    if dry_run:
        for s in slides:
            idx = s["slide_index"]
            title_preview = (s.get("title") or "(无标题)")[:40]
            role = s.get("semantic_role", "?")
            logger.info(f"  Page {idx:02d}: [{role}] {title_preview}")

        elapsed = time.time() - start_time
        logger.info(f"  ✅ DRY RUN 完成: {pptx_path.name} ({len(slides)} 页, 耗时 {elapsed:.0f}s)")
        return len(slides)

    # ── Phase 3: 结构化存储 ─────────────────────────
    from app.services.etl.phase3_store import write_to_postgres, write_to_llm_wiki
    deck_info = await write_to_postgres(
        file_path=str(pptx_path),
        checksum=checksum,
        slides=slides,
        source_path=str(pptx_path),
    )
    deck_id = deck_info["deck_id"]

    wiki_files = write_to_llm_wiki(
        deck_id=deck_id,
        title=file_stem,
        slides=slides,
    )
    logger.info(f"  Phase3 [Wiki] {len(wiki_files)} 个文件")

    # ── Phase 3.5: 缩略图迁移 ────────────────────────
    # 将缩略图从临时目录移动到 deck_{deck_id} 目录，并更新 slide 路径
    thumb_final_dir = Path(settings.slydo_wiki_path).expanduser() / "thumbnails" / f"deck_{deck_id}"
    if thumb_temp_dir.exists():
        thumb_final_dir.mkdir(parents=True, exist_ok=True)
        for s in slides:
            idx = s["slide_index"]
            src = thumb_temp_dir / f"slide_{idx:03d}.png"
            if src.exists():
                dst = thumb_final_dir / f"slide_{idx:03d}.png"
                shutil.move(str(src), str(dst))
                s["thumbnail_path"] = str(dst)
        # 清理临时目录（如果非空则删除）
        try:
            thumb_temp_dir.rmdir()
        except OSError:
            pass
        logger.info(f"  缩略图迁移: {thumb_final_dir}")

        # 更新数据库中的缩略图路径
        for s in slides:
            tp = s.get("thumbnail_path", "")
            idx = s.get("slide_index", 0)
            if tp and str(tp).startswith(str(thumb_temp_dir)):
                s["thumbnail_path"] = str(thumb_final_dir / f"slide_{idx:03d}.png")

    # 批量 UPDATE 缩略图路径到数据库
    async with async_session_factory() as session:
        for s in slides:
            tp = s.get("thumbnail_path", "")
            idx = s.get("slide_index", 0)
            if tp:
                await session.execute(
                    text("UPDATE slides SET thumbnail_path = :path WHERE deck_id = CAST(:deck_id AS uuid) AND slide_index = :idx"),
                    {"path": tp, "deck_id": deck_id, "idx": idx},
                )
        await session.commit()
        logger.info(f"  缩略图路径已更新到数据库 ({len(slides)} 条)")

    # ── Phase 4: 向量嵌入（仅未跳过时执行） ──────────
    if not skip_embed:
        from app.services.etl.phase4_embed import embed_to_qdrant
        qdrant_points = await embed_to_qdrant(
            deck_id=deck_id,
            slides=slides,
        )
        logger.info(f"  Phase4 [Qdrant] {qdrant_points} 个 vectors")
    else:
        qdrant_points = 0
        logger.info("  Phase4 [嵌入] 已跳过 (--skip-embed)")

    # ── Phase 5: QS 初始化 ──────────────────────────
    from app.services.etl.phase3_store import init_quality_scores
    await init_quality_scores(deck_id=deck_id, slide_count=len(slides))

    # ── 汇总输出 ────────────────────────────────────
    elapsed = time.time() - start_time
    logger.info(f"  ╔══ ETL 入库完成 ═══════════════════════════════════")
    logger.info(f"  ║  文件: {pptx_path.name}")
    logger.info(f"  ║  Deck ID: {deck_id}")
    logger.info(f"  ║  PG 记录: {len(slides)} slides")
    logger.info(f"  ║  Wiki: {len(wiki_files)} 个 Markdown 文件")
    logger.info(f"  ║  Qdrant: {qdrant_points} 个 vectors")
    logger.info(f"  ║  耗时: {elapsed:.1f}s")
    logger.info(f"  ╚═══════════════════════════════════════════════════")
    return len(slides)


async def main():
    parser = argparse.ArgumentParser(description="Slydo PPT 入库工具")
    parser.add_argument("path", help="PPT 文件路径或目录路径")
    parser.add_argument("--dry-run", action="store_true", help="仅提取+渲染，不入库")
    parser.add_argument("--skip-vision", action="store_true", help="跳过视觉模型分析")
    parser.add_argument("--skip-embed", action="store_true", help="跳过向量嵌入（后端运行时使用）")
    args = parser.parse_args()

    input_path = Path(args.path)
    total_pages = 0
    total_files = 0

    if input_path.is_dir():
        pptx_files = sorted(
            list(input_path.rglob("*.pptx")) + list(input_path.rglob("*.ppt"))
        )
        if not pptx_files:
            logger.warning(f"目录中未找到 PPT 文件: {input_path}")
            return
        logger.info(f"找到 {len(pptx_files)} 个 PPT 文件，开始批量处理...")
        for f in pptx_files:
            pages = await ingest_pptx(
                str(f), dry_run=args.dry_run, skip_vision=args.skip_vision, skip_embed=args.skip_embed,
            )
            if pages > 0:
                total_files += 1
                total_pages += pages
        logger.info(f"批量处理完成: {total_files} 个文件, {total_pages} 页")
    else:
        pages = await ingest_pptx(
            input_path, dry_run=args.dry_run, skip_vision=args.skip_vision, skip_embed=args.skip_embed,
        )
        total_pages = pages

    if total_pages > 0 and not args.dry_run:
        logger.info(f"✨ 入库完成！共 {total_pages} 页，可在 Qdrant 中搜索")


if __name__ == "__main__":
    asyncio.run(main())
