#!/usr/bin/env python3
"""
清理 slides 表中重复的 slide_index 记录。

背景：多次使用 --skip-vision --skip-embed 重新入库 PPT 时，
未清理旧 slides 记录，导致约 22 个文档的每个 slide_index 有 2~3 条记录。
这导致：
  - 视觉进度统计异常（vision_done/deck.slide_count > 100%）
  - Qdrant 存入重复向量
  - API 调用浪费（同一页视觉分析多次）

策略：每个 deck_id + slide_index 组合，保留 created_at 最新的那条，
删除其他旧记录。如果 visual_desc 已填，优先保留有视觉描述的那条。
"""
import argparse
import logging
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cleanup_dups")


def main():
    parser = argparse.ArgumentParser(description="清理 slides 重复记录")
    parser.add_argument("--dry-run", action="store_true", help="只统计不删除")
    parser.add_argument("--deck", help="只清理特定 deck (UUID 前缀)")
    args = parser.parse_args()

    engine = create_engine(settings.database_url)
    conn = engine.connect()

    # 1. 统计重复情况
    if args.deck:
        where_clause = "WHERE d.id::text LIKE :prefix"
        params = {"prefix": f"{args.deck}%"}
    else:
        where_clause = ""
        params = {}

    # 查所有有重复的 deck
    dup_query = f"""
        SELECT d.id::text, d.title, d.slide_count AS deck_sc,
               COUNT(s.id) AS actual_slides,
               COUNT(DISTINCT s.slide_index) AS unique_pages,
               SUM(CASE WHEN s.visual_desc IS NOT NULL AND s.visual_desc != '' THEN 1 ELSE 0 END) AS vision_done
        FROM decks d
        JOIN slides s ON s.deck_id = d.id
        {where_clause.replace('d.id', 'd.id')}
        GROUP BY d.id, d.title, d.slide_count
        HAVING COUNT(s.id) > COUNT(DISTINCT s.slide_index)
        ORDER BY actual_slides DESC
    """
    # HACK: reuse query without deck filter format issue
    if args.deck:
        dup_query = f"""
            SELECT d.id::text, d.title, d.slide_count AS deck_sc,
                   COUNT(s.id) AS actual_slides,
                   COUNT(DISTINCT s.slide_index) AS unique_pages,
                   SUM(CASE WHEN s.visual_desc IS NOT NULL AND s.visual_desc != '' THEN 1 ELSE 0 END) AS vision_done
            FROM decks d
            JOIN slides s ON s.deck_id = d.id
            WHERE d.id::text LIKE '{args.deck}%'
            GROUP BY d.id, d.title, d.slide_count
            HAVING COUNT(s.id) > COUNT(DISTINCT s.slide_index)
            ORDER BY actual_slides DESC
        """
    
    result = conn.execute(text(dup_query))
    dup_decks = result.fetchall()

    if not dup_decks:
        logger.info("✅ 没有发现重复数据")
        conn.close()
        return

    logger.info(f"📊 发现 {len(dup_decks)} 个文档有重复 slide 记录:")
    total_extra = 0
    total_deleted_vision = 0
    for row in dup_decks:
        extra = row.actual_slides - row.unique_pages
        total_extra += extra
        logger.info(f"  {row.title[:50]} | {row.deck_sc}页 → {row.actual_slides}条 | 重复: +{extra}条 | 视觉: {row.vision_done}")

    logger.info(f"\n  总计多余记录: {total_extra} 条")

    # 2. 清理：每个 (deck_id, slide_index) 保留最新一条
    # 优先保留有 visual_desc 的；同条件下保留 created_at 最新的
    if args.dry_run:
        logger.info("🏁 DRY RUN 模式，不执行删除")
        conn.close()
        return

    # 确认
    logger.warning("⚠️  即将删除重复 slide 记录！")
    logger.warning(f"   预计删除约 {total_extra} 条记录")

    # 用 PostgreSQL 的 CTE 来精确删除
    # 为每个 (deck_id, slide_index) 分组，打上 row_number
    # 优先保留 visual_desc 非空的，再按 created_at DESC 取第一条
    delete_sql = """
    WITH ranked AS (
        SELECT id,
               deck_id,
               slide_index,
               ROW_NUMBER() OVER (
                   PARTITION BY deck_id, slide_index
                   ORDER BY
                       CASE WHEN visual_desc IS NOT NULL AND visual_desc != '' THEN 0 ELSE 1 END,
                       created_at DESC
               ) AS rn
        FROM slides
    )
    DELETE FROM slides
    WHERE id IN (
        SELECT id FROM ranked WHERE rn > 1
    )
    """
    
    # 如果有 --deck 限制
    if args.deck:
        delete_sql = f"""
        WITH ranked AS (
            SELECT s.id,
                   s.deck_id,
                   s.slide_index,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.deck_id, s.slide_index
                       ORDER BY
                           CASE WHEN s.visual_desc IS NOT NULL AND s.visual_desc != '' THEN 0 ELSE 1 END,
                           s.created_at DESC
                   ) AS rn
            FROM slides s
            JOIN decks d ON d.id = s.deck_id
            WHERE d.id::text LIKE '{args.deck}%'
        )
        DELETE FROM slides
        WHERE id IN (
            SELECT id FROM ranked WHERE rn > 1
        )
        """
    
    # 先统计要删除多少
    if args.deck:
        count_sql = f"""
        WITH ranked AS (
            SELECT s.id,
                   ROW_NUMBER() OVER (
                       PARTITION BY s.deck_id, s.slide_index
                       ORDER BY
                           CASE WHEN s.visual_desc IS NOT NULL AND s.visual_desc != '' THEN 0 ELSE 1 END,
                           s.created_at DESC
                   ) AS rn
            FROM slides s
            JOIN decks d ON d.id = s.deck_id
            WHERE d.id::text LIKE '{args.deck}%'
        )
        SELECT COUNT(*) FROM ranked WHERE rn > 1
        """
    else:
        count_sql = """
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY deck_id, slide_index
                       ORDER BY
                           CASE WHEN visual_desc IS NOT NULL AND visual_desc != '' THEN 0 ELSE 1 END,
                           created_at DESC
                   ) AS rn
            FROM slides
        )
        SELECT COUNT(*) FROM ranked WHERE rn > 1
        """

    will_delete = conn.execute(text(count_sql)).scalar()
    logger.info(f"确认删除: {will_delete} 条记录")
    
    if will_delete > 0:
        result = conn.execute(text(delete_sql))
        conn.commit()
        deleted = result.rowcount
        logger.info(f"✅ 成功删除 {deleted} 条重复记录")

    # 3. 更新 deck.slide_count 为实际 unique slides 数
    update_sc_sql = """
    UPDATE decks d
    SET slide_count = (
        SELECT COUNT(DISTINCT slide_index) FROM slides WHERE deck_id = d.id
    )
    WHERE d.id IN (
        SELECT deck_id FROM slides
        GROUP BY deck_id
        HAVING COUNT(DISTINCT slide_index) != MAX(d.slide_count)
    ) AND d.id::text IN (SELECT d2.id::text FROM decks d2 
        JOIN slides s2 ON s2.deck_id = d2.id
        GROUP BY d2.id
        HAVING COUNT(DISTINCT s2.slide_index) != d2.slide_count
    )
    """
    # Simpler update
    update_sc_sql_simple = """
    UPDATE decks d
    SET slide_count = sub.unique_count
    FROM (
        SELECT deck_id, COUNT(DISTINCT slide_index) AS unique_count
        FROM slides
        GROUP BY deck_id
    ) sub
    WHERE d.id = sub.deck_id
      AND d.slide_count != sub.unique_count
    """
    
    update_result = conn.execute(text(update_sc_sql_simple))
    conn.commit()
    logger.info(f"✅ 更新了 {update_result.rowcount} 个 deck 的 slide_count")

    # 4. 最终验证
    if args.deck:
        verify_sql = f"""
            SELECT d.title, d.slide_count AS deck_sc,
                   COUNT(s.id) AS actual, COUNT(DISTINCT slide_index) AS unique_pages,
                   SUM(CASE WHEN s.visual_desc IS NOT NULL AND s.visual_desc != '' THEN 1 ELSE 0 END) AS vision_done,
                   COUNT(DISTINCT CASE WHEN s.visual_desc IS NOT NULL AND s.visual_desc != '' THEN s.slide_index ELSE NULL END) AS unique_vision
            FROM decks d
            JOIN slides s ON s.deck_id = d.id
            WHERE d.id::text LIKE '{args.deck}%'
            GROUP BY d.id, d.title, d.slide_count
        """
    else:
        verify_sql = """
            SELECT d.title, d.slide_count AS deck_sc,
                   COUNT(s.id) AS actual, COUNT(DISTINCT slide_index) AS unique_pages,
                   SUM(CASE WHEN s.visual_desc IS NOT NULL AND s.visual_desc != '' THEN 1 ELSE 0 END) AS vision_done,
                   COUNT(DISTINCT CASE WHEN s.visual_desc IS NOT NULL AND s.visual_desc != '' THEN s.slide_index ELSE NULL END) AS unique_vision
            FROM decks d
            JOIN slides s ON s.deck_id = d.id
            GROUP BY d.id, d.title, d.slide_count
            ORDER BY actual DESC
        """

    result = conn.execute(text(verify_sql))
    rows = result.fetchall()
    
    still_dup = [r for r in rows if r.actual != r.unique_pages]
    wrong_sc = [r for r in rows if r.deck_sc != r.unique_pages]
    
    logger.info(f"\n📊 清理后验证:")
    logger.info(f"  总文档: {len(rows)}")
    if still_dup:
        logger.warning(f"  ⚠️ 仍有 {len(still_dup)} 个文档存在重复: {[(r.title[:30], r.actual, r.unique_pages) for r in still_dup[:5]]}")
    else:
        logger.info(f"  ✅ 无重复数据")
    
    if wrong_sc:
        logger.warning(f"  ⚠️ 仍有 {len(wrong_sc)} 个文档 slide_count 不正确")
    else:
        logger.info(f"  ✅ 所有 slide_count 已修正")

    logger.info(f"\n  视觉概况: {sum(r.vision_done for r in rows)} 条记录 / {sum(r.unique_vision for r in rows)} 个独立页面")
    
    conn.close()


if __name__ == "__main__":
    main()
