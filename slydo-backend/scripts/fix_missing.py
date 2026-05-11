#!/usr/bin/env python3
"""
修复入库中缺失的数据：缩略图、Wiki、视觉分析。

处理策略：
1. 虎符锁（8页全部无缩略图）→ 重新跑 LibreOffice 生成缩略图 → 重新跑视觉
2. 其他12个文档（缺1-8页缩略图）→ 重新跑对应 PPT 的缩略图渲染
3. 联软可信上网（Wiki缺失）→ 用文本和视觉数据重新生成 Wiki MD 文件
"""
import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import async_session_factory
from app.services.etl.phase1_extract import render_slides_to_images
from app.services.etl.phase2_vision import llm_extract_meaning_single
from app.utils.token_counter import TokenCounter
from app.utils.vision import call_vision_api
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("fix_missing")

thumb_base_dir = Path(settings.slydo_wiki_path).expanduser() / "thumbnails"
wiki_base_dir = Path(settings.slydo_wiki_path).expanduser() / "slides"


def run_thumbnail(pptx_path: str, deck_id: str, slide_count: int) -> list[str]:
    """运行 LibreOffice 渲染缩略图"""
    output_dir = thumb_base_dir / f"deck_{deck_id}"
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return render_slides_to_images(pptx_path, output_dir)


async def update_thumbnail_path(deck_id: str, slide_index: int, thumb_path: str):
    """更新缩略图路径"""
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE slides SET thumbnail_path = :path WHERE deck_id = CAST(:did AS uuid) AND slide_index = :idx"),
            {"did": deck_id, "idx": slide_index, "path": thumb_path},
        )
        await session.commit()


async def run_vision(deck_id: str, slide_index: int, title: str, body_text: str, notes_text: str, thumb_path: str):
    """对单页运行视觉分析并更新"""
    slide_data = {
        "slide_index": slide_index,
        "title": title,
        "body_text": body_text,
        "notes_text": notes_text,
    }
    thumb_dir = Path(thumb_path).parent if thumb_path else None
    
    result = await call_vision_api(
        image_path=thumb_path,
        title=title,
        body_text=body_text,
        notes_text=notes_text,
    )
    
    async with async_session_factory() as session:
        await session.execute(
            text("""UPDATE slides SET 
                semantic_role = :role, semantic_summary = :summary,
                visual_desc = :visual_desc, semantic_tags = :tags
                WHERE deck_id = CAST(:did AS uuid) AND slide_index = :idx
            """),
            {
                "did": deck_id, "idx": slide_index,
                "role": result["role"],
                "summary": result["summary"],
                "visual_desc": result["visual_desc"],
                "tags": result["tags"],
            },
        )
        await session.commit()
    return result


async def regenerate_wiki(deck_id: str):
    """为缺失 Wiki 的 deck 重新生成 Markdown 文件"""
    wiki_dir = wiki_base_dir / f"deck_{deck_id}"
    wiki_dir.mkdir(parents=True, exist_ok=True)
    
    async with async_session_factory() as session:
        r = await session.execute(
            text("""SELECT slide_index, title, body_text, notes_text, semantic_role, semantic_summary, visual_desc, semantic_tags
                     FROM slides WHERE deck_id = CAST(:did AS uuid) ORDER BY slide_index"""),
            {"did": deck_id},
        )
        slides = r.fetchall()
        
        r = await session.execute(
            text("SELECT title, slide_count, file_path FROM decks WHERE id = CAST(:did AS uuid)"),
            {"did": deck_id},
        )
        deck = r.fetchone()
    
    deck_title = deck[0]
    # 写 deck 级 summary
    deck_md = f"""# {deck_title}

> 总页数: {len(slides)}

## 页面内容

"""
    for s in slides:
        idx, title, body, notes, role, summary, visual_desc, tags = s
        tags_str = ", ".join(tags) if tags else ""
        deck_md += f"""### 第 {idx} 页 — {title or '(无标题)'}

- **角色**: {role or 'argument'}
- **摘要**: {summary or ''}
- **视觉**: {visual_desc or ''}
- **标签**: {tags_str}

"""
    
    with open(wiki_dir / "index.md", "w", encoding="utf-8") as f:
        f.write(deck_md)
    
    # 写每个 slide
    for s in slides:
        idx, title, body, notes, role, summary, visual_desc, tags = s
        tags_str = "\n".join(f"- {t}" for t in (tags or []))
        slide_md = f"""---
deck: {deck_title}
slide: {idx}
role: {role}
tags: {tags}
---

# {title or '(无标题)'}

## 摘要

{summary or ''}

## 视觉描述

{visual_desc or ''}

## 正文

{body or '(无正文)'}

## 备注

{notes or '(无备注)'}

## 标签

{tags_str}
"""
        with open(wiki_dir / f"slide_{idx:03d}.md", "w", encoding="utf-8") as f:
            f.write(slide_md)
    
    logger.info(f"Wiki 已生成: {wiki_dir} ({len(slides)} 页)")
    return len(slides)


async def main():
    parser = argparse.ArgumentParser(description="修复缺失数据")
    parser.add_argument("--dry-run", action="store_true", help="只统计不修复")
    args = parser.parse_args()

    async with async_session_factory() as session:
        # 查所有缺失缩略图的 slides
        r = await session.execute(text("""
            SELECT d.id::text, d.title, d.file_path, d.slide_count,
                   s.slide_index, s.title, s.body_text, s.notes_text,
                   s.thumbnail_path IS NOT NULL AND s.thumbnail_path != '' as has_thumb,
                   s.visual_desc IS NOT NULL AND s.visual_desc != '' as has_vision
            FROM slides s
            JOIN decks d ON d.id = s.deck_id
            WHERE s.thumbnail_path IS NULL OR s.thumbnail_path = ''
            ORDER BY d.title, s.slide_index
        """))
        missing_thumbs = r.fetchall()
        
        # 2. 查缺 Wiki 的 deck
        r = await session.execute(text("SELECT id::text, title, file_path, slide_count FROM decks"))
        decks = r.fetchall()
    
    # Check Wiki existence
    missing_wiki = []
    for d in decks:
        wiki_dir = wiki_base_dir / f"deck_{d[0]}"
        if not wiki_dir.exists() or len(list(wiki_dir.glob("*.md"))) == 0:
            missing_wiki.append(d)
    
    logger.info(f"📊 缺失缩略图的 slides: {len(missing_thumbs)}")
    logger.info(f"📊 缺失 Wiki 的 deck: {len(missing_wiki)}")
    
    # 按 deck 分组
    from collections import defaultdict
    by_deck = defaultdict(list)
    for r in missing_thumbs:
        by_deck[r[0]].append(r)
    
    if by_deck:
        for did, slides_list in by_deck.items():
            title = slides_list[0][1]
            ppt_path = slides_list[0][2]
            ppt_ok = os.path.exists(ppt_path) if ppt_path else False
            logger.info(f"  {title[:40]} ({did[:8]}...): {len(slides_list)} 页缺失缩略图 | 原始PPT存在={ppt_ok}")
    
    if missing_wiki:
        for d in missing_wiki:
            logger.info(f"  Wiki缺失: {d[1][:40]} ({d[0][:8]}...) | 路径: {wiki_base_dir}/deck_{d[0]}")
    
    if args.dry_run:
        logger.info("🏁 DRY RUN 模式，不执行修复")
        return
    
    # ── 修复 1: 重新渲染缩略图 ──
    for did in by_deck:
        slides_list = by_deck[did]
        title = slides_list[0][1]
        ppt_path = slides_list[0][2]
        
        if not ppt_path or not os.path.exists(ppt_path):
            logger.warning(f"  ⚠️ 原始PPT不存在，跳过: {ppt_path}")
            continue
        
        logger.info(f"\n🔧 渲染缩略图: {title[:40]}")
        
        try:
            # 使用 pdf2image 直接渲染。不需要通过 phase1，直接调 render_slides_to_images
            png_paths = run_thumbnail(ppt_path, did, len(slides_list))
            logger.info(f"  生成 {len(png_paths)} 张缩略图")
            
            # 更新 PG 中的缩略图路径
            for png_path in png_paths:
                # 从路径提取 slide_index
                import re
                m = re.search(r'slide_(\d+)\.png$', png_path)
                if m:
                    idx = int(m.group(1))
                    await update_thumbnail_path(did, idx, png_path)
            
            # 重新跑视觉分析
            logger.info(f"  开始视觉分析 ({len(png_paths)} 页)...")
            counter = TokenCounter(model_name=settings.dashscope_vision_model)
            for s in slides_list:
                idx = s[4]
                s_title = s[5] or ""
                s_body = s[6] or ""
                s_notes = s[7] or ""
                thumb = str(thumb_base_dir / f"deck_{did}" / f"slide_{idx:03d}.png")
                
                if not os.path.exists(thumb):
                    logger.warning(f"    跳过 p{idx}: 缩略图依旧不存在: {thumb}")
                    continue
                
                logger.info(f"  [视觉] p{idx} ({s_title[:30] or '(无标题)'})...")
                try:
                    result = await run_vision(did, idx, s_title, s_body, s_notes, thumb)
                    logger.info(f"    ✅ {result.get('semantic_summary', '')[:40]}")
                except Exception as e:
                    logger.error(f"    ❌ 失败: {e}")
            
            logger.info(f"  ✅ 完成: {title[:40]}")
            
        except Exception as e:
            logger.error(f"  ❌ 渲染/视觉失败: {e}")
    
    # ── 修复 2: 补 Wiki ──
    if missing_wiki:
        logger.info(f"\n🔧 生成 Wiki ({len(missing_wiki)} 个 deck)...")
        for d in missing_wiki:
            try:
                n = await regenerate_wiki(d[0])
                logger.info(f"  ✅ {d[1][:40]}: {n} 页 Wiki 生成")
            except Exception as e:
                logger.error(f"  ❌ Wiki 生成失败: {e}")
    
    # ── 最终验证 ──
    async with async_session_factory() as session:
        r = await session.execute(text("""
            SELECT d.title, d.slide_count,
                   (SELECT COUNT(*) FROM slides s WHERE s.deck_id=d.id AND s.thumbnail_path IS NOT NULL AND s.thumbnail_path != '') as thumb_ok,
                   (SELECT COUNT(*) FROM slides s WHERE s.deck_id=d.id AND s.visual_desc IS NOT NULL AND s.visual_desc != '') as vision_ok
            FROM decks d ORDER BY d.title
        """))
        all_done = True
        for r2 in r.fetchall():
            if r2[1] != r2[2] or r2[1] != r2[3]:
                all_done = False
                logger.warning(f"  ❌ {r2[0][:40]}: {r2[1]}页, thumb={r2[2]}, vision={r2[3]}")
        if all_done:
            logger.info("🎉 所有文档 100% 完成!")


if __name__ == "__main__":
    asyncio.run(main())
