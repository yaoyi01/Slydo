#!/usr/bin/env python3
"""
Slydo Wiki 维护脚本 — 自动更新全库 index.md + 清理孤立页面

功能：
1. 为每个 deck 生成/更新 index.md（包含页面清单、角色分布、标签云等）
2. 生成全库索引 / 查询历史推荐记录缓存
3. 清理 orphaned Wiki 页面（PG 中已删除的 deck）

用法：
    python3 scripts/wiki_maintenance.py                     # 全量更新
    python3 scripts/wiki_maintenance.py --deck <uuid>        # 只更新某个 deck
    python3 scripts/wiki_maintenance.py --cleanup            # 只清理孤立页面
    python3 scripts/wiki_maintenance.py --dry-run            # 试运行
"""
import argparse
import asyncio
import logging
import sys
import os
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.database import async_session_factory
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [wiki_maint] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("wiki_maint")

wiki_slides_dir = Path(settings.slydo_wiki_path).expanduser() / "slides"
wiki_root = Path(settings.slydo_wiki_path).expanduser()


async def generate_deck_index(deck_id: str) -> bool:
    """为单个 deck 生成 index.md。"""
    async with async_session_factory() as session:
        r = await session.execute(
            text("""
                SELECT id::text, title, slide_count, file_path, created_at, updated_at
                FROM decks WHERE id = CAST(:did AS uuid)
            """),
            {"did": deck_id},
        )
        deck = r.fetchone()
        if not deck:
            logger.warning(f"  Deck 不存在: {deck_id[:8]}...")
            return False

        # 查询所有 slides
        r = await session.execute(
            text("""
                SELECT id::text as slide_id, slide_index, title,
                       COALESCE(semantic_role, 'argument') as role,
                       semantic_tags, quality_score
                FROM slides WHERE deck_id = CAST(:did AS uuid)
                ORDER BY slide_index
            """),
            {"did": deck_id},
        )
        slides = r.fetchall()

        # 统计角色分布
        role_counts = Counter(s.role for s in slides)
        # 统计标签云
        all_tags = []
        for s in slides:
            tags = s.semantic_tags or []
            if isinstance(tags, str):
                import json
                try:
                    tags = json.loads(tags)
                except:
                    tags = []
            all_tags.extend(tags if isinstance(tags, list) else [])
        tag_counts = Counter(all_tags).most_common(30)

        # 查询使用次数
        r = await session.execute(
            text("""
                SELECT ul.slide_id::text, COUNT(*) as cnt FROM usage_log ul
                WHERE ul.slide_id IN (
                    SELECT s.id FROM slides s WHERE s.deck_id = CAST(:did AS uuid)
                )
                GROUP BY ul.slide_id
            """),
            {"did": deck_id},
        )
        usage_map = {str(r2[0]): r2[1] for r2 in r.fetchall()}

    source_name = os.path.basename(deck.file_path) if deck.file_path else "未知"
    created = deck.created_at.strftime("%Y-%m-%d %H:%M") if deck.created_at else "未知"
    updated = deck.updated_at.strftime("%Y-%m-%d %H:%M") if deck.updated_at else "未知"

    # 构造 Markdown
    md = f"""# {deck.title}

> **文档信息**
> - 源文件: `{source_name}`
> - 总页数: {deck.slide_count}
> - 入库时间: {created}
> - 最后更新: {updated}

## 页面角色分布

| 角色 | 数量 | 占比 |
|:---|:---:|:---:|
"""
    total = len(slides)
    for role_name, count in sorted(role_counts.items(), key=lambda x: -x[1]):
        pct = round(count / total * 100) if total else 0
        role_label = {"cover": "封面", "toc": "目录", "transition": "转场",
                      "argument": "论点", "evidence": "论据", "conclusion": "结论",
                      "appendix": "附录"}.get(role_name, role_name)
        md += f"| {role_label} | {count} | {pct}% |\n"

    md += f"\n## 标签云（Top 30）\n\n"
    if tag_counts:
        for tag, cnt in tag_counts:
            md += f"- **{tag}** ({cnt}次)\n"
    else:
        md += "- (暂无标签)\n"

    md += f"\n## 页面清单\n\n"
    md += f"| 序号 | 标题 | 角色 | 使用次数 |\n"
    md += f"|:---:|:---|:---:|:---:|\n"
    for s in slides:
        slide_id_str = str(s.slide_id) if s.slide_id else ""
        usage_cnt = usage_map.get(slide_id_str, 0)

        role_label = {"cover": "封面", "toc": "目录", "transition": "转场",
                      "argument": "论点", "evidence": "论据", "conclusion": "结论",
                      "appendix": "附录"}.get(s.role, s.role)
        title_esc = (s.title or "(无标题)").replace("|", "\\|")
        md += f"| {s.slide_index} | {title_esc} | {role_label} | {usage_cnt} |\n"

    # 写入文件
    deck_dir = wiki_slides_dir / f"deck_{deck_id}"
    deck_dir.mkdir(parents=True, exist_ok=True)
    (deck_dir / "index.md").write_text(md, encoding="utf-8")
    logger.info(f"  index.md 已更新: {deck.title[:40]} ({deck.slide_count}页, {total}次使用)")
    return True


async def generate_global_index():
    """生成全库索引 / 统计总览。"""
    async with async_session_factory() as session:
        r = await session.execute(text("""
            SELECT COUNT(*) as decks, SUM(slide_count) as slides FROM decks
        """))
        total = r.fetchone()
        deck_count = total.decks or 0
        slide_count = total.slides or 0

        r = await session.execute(text("SELECT COUNT(*) FROM usage_log WHERE action='import'"))
        import_count = r.scalar() or 0

        r = await session.execute(text("""
            SELECT title, slide_count,
                   (SELECT COUNT(*) FROM usage_log ul JOIN slides s ON s.id = ul.slide_id WHERE s.deck_id = d.id)
            FROM decks d ORDER BY slide_count DESC
        """))
        decks = r.fetchall()

        # 全库标签云
        r = await session.execute(text("""
            SELECT unnest(semantic_tags) as tag, COUNT(*) as cnt
            FROM slides WHERE semantic_tags IS NOT NULL AND array_length(semantic_tags, 1) > 0
            GROUP BY tag ORDER BY cnt DESC LIMIT 50
        """))
        tags = r.fetchall()

    md = f"""# Slydo 全库索引

> 生成时间: {__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")}

## 统计总览

| 指标 | 数值 |
|:---|---:|
| 📁 文档总数 | {deck_count} |
| 📄 页面总数 | {slide_count} |
| 🔄 累计导入次数 | {import_count} |

## 文档列表

| 文档名称 | 页数 | 累计使用 |
|:---|:---:|:---:|
"""
    for d in decks:
        title = (d.title or "未知").replace("|", "\\|")
        md += f"| {title} | {d.slide_count} | {d[2] or 0} |\n"

    md += f"\n## 全库标签云（Top 50）\n\n"
    for tag, cnt in tags:
        md += f"- **{tag}** ({cnt})\n"

    # 写入
    (wiki_root / "index.md").write_text(md, encoding="utf-8")
    logger.info(f"✅ 全库索引已更新: {deck_count} 文档, {slide_count} 页, {import_count} 次导入")


async def cleanup_orphaned():
    """清理孤立 Wiki 文件（数据库中已删除的 deck）。"""
    async with async_session_factory() as session:
        r = await session.execute(text("SELECT id::text FROM decks"))
        valid_ids = {str(row[0]) for row in r.fetchall()}
    import shutil

    cleaned = 0
    if wiki_slides_dir.exists():
        for d in wiki_slides_dir.iterdir():
            if d.is_dir() and d.name.startswith("deck_"):
                deck_id = d.name.replace("deck_", "", 1)
                if deck_id not in valid_ids:
                    shutil.rmtree(d, ignore_errors=True)
                    logger.info(f"  清理孤立: {d.name}")
                    cleaned += 1
        # 清理 thumbnails
        thumb_dir = wiki_root / "thumbnails"
        if thumb_dir.exists():
            for d in thumb_dir.iterdir():
                if d.is_dir() and d.name.startswith("deck_"):
                    deck_id = d.name.replace("deck_", "", 1)
                    if deck_id not in valid_ids:
                        shutil.rmtree(d, ignore_errors=True)
                        logger.info(f"  清理孤立缩略图: {d.name}")
                        cleaned += 1
    if cleaned:
        logger.info(f"✅ 共清理 {cleaned} 个孤立目录")
    else:
        logger.info("✅ 无孤立目录需要清理")
    return cleaned


async def main():
    parser = argparse.ArgumentParser(description="Slydo Wiki 维护")
    parser.add_argument("--deck", help="只更新特定 deck (UUID)")
    parser.add_argument("--cleanup", action="store_true", help="只清理孤立页面")
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    args = parser.parse_args()

    if args.cleanup:
        logger.info("🔍 清理孤立 Wiki 文件...")
        await cleanup_orphaned()
        return

    # 更新 index.md
    if args.deck:
        logger.info(f"📝 更新 index.md: deck={args.deck[:8]}...")
        await generate_deck_index(args.deck)
    else:
        # 全量更新
        async with async_session_factory() as session:
            r = await session.execute(text("SELECT id::text FROM decks ORDER BY title"))
            decks = r.fetchall()

        logger.info(f"📝 生成 index.md ({len(decks)} 个 deck)...")
        success = 0
        for row in decks:
            deck_id = str(row[0])
            if await generate_deck_index(deck_id):
                success += 1
        logger.info(f"  ✅ {success}/{len(decks)} 个 index.md 已更新")

    # 全库索引
    logger.info("📊 生成全库索引...")
    await generate_global_index()

    # 清理孤立
    await cleanup_orphaned()

    logger.info("🏁 Wiki 维护完成")


if __name__ == "__main__":
    asyncio.run(main())
