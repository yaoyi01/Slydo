#!/usr/bin/env python3
"""
D3 — QS 评分离线计算脚本

功能：
1. 汇总 usage_log 的 import 次数，更新 slides.usage_count
2. 按公式计算 quality_score：QS = α·(usage_norm) + β·official
   其中 α=0.6, β=0.4, usage_norm = min(usage_count / 10, 1.0), official = 1.0 if is_official else 0.0
3. 可 cron 定时运行（建议每日凌晨）

用法：
    python3 scripts/qs_calculate.py                     # 全量计算
    python3 scripts/qs_calculate.py --dry-run           # 试运行（不写入）
    python3 scripts/qs_calculate.py --deck <uuid>       # 只计算某个 deck
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import async_session_factory
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [QS] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("qs")

# QS 公式权重
ALPHA = 0.6   # usage 权重
BETA = 0.4    # official 权重
USAGE_CAP = 10  # usage_count 归一化上限


async def calculate_qs(dry_run: bool = False, deck_id: str | None = None) -> dict:
    """计算并更新 quality_score。"""
    stats = {"updated": 0, "skipped": 0, "errors": 0}

    async with async_session_factory() as session:
        # 1. 更新 usage_count（从 usage_log 汇总）
        where_clause = ""
        params: dict = {}
        if deck_id:
            where_clause = "AND s.deck_id = CAST(:did AS uuid)"
            params["did"] = deck_id

        await session.execute(
            text(f"""
                UPDATE slides s
                SET usage_count = COALESCE((
                    SELECT COUNT(*) FROM usage_log ul
                    WHERE ul.slide_id = s.id AND ul.action = 'import'
                ), 0)
                WHERE s.usage_count != COALESCE((
                    SELECT COUNT(*) FROM usage_log ul
                    WHERE ul.slide_id = s.id AND ul.action = 'import'
                ), 0)
                {where_clause}
            """),
            params if params else {},
        )

        # 2. 计算 quality_score
        # QS = α · min(usage_count / USAGE_CAP, 1.0) + β · (1.0 if official else 0.0)
        await session.execute(
            text(f"""
                UPDATE slides s
                SET quality_score = {ALPHA} * LEAST(s.usage_count::float / {USAGE_CAP}, 1.0)
                                   + {BETA} * CASE WHEN s.is_official THEN 1.0 ELSE 0.0 END
                {where_clause.replace('AND s.deck_id = CAST(:did AS uuid)', '') if where_clause else ''}
            """),
            params if params else {},
        )

        if not dry_run:
            await session.commit()

        # 3. 统计
        if deck_id:
            r = await session.execute(
                text("SELECT COUNT(*) FROM slides WHERE deck_id = CAST(:did AS uuid)"),
                {"did": deck_id},
            )
        else:
            r = await session.execute(text("SELECT COUNT(*) FROM slides"))
        total = r.scalar() or 0

        # 采样查看
        r = await session.execute(
            text("""
                SELECT s.slide_index, s.title, s.usage_count, s.is_official, s.quality_score
                FROM slides s
                ORDER BY s.quality_score DESC
                LIMIT 10
            """)
        )
        top = r.fetchall()

    return {"total": total, "top": top}


async def main():
    parser = argparse.ArgumentParser(description="QS 评分计算")
    parser.add_argument("--dry-run", action="store_true", help="试运行")
    parser.add_argument("--deck", help="只计算特定 deck (UUID)")
    args = parser.parse_args()

    if args.dry_run:
        logger.info("🔍 试运行模式（不写入数据库）")

    logger.info("📊 开始 QS 评分计算...")
    result = await calculate_qs(dry_run=args.dry_run, deck_id=args.deck)

    logger.info(f"  总页面: {result['total']}")
    logger.info(f"  Top 10 质量评分:")
    for row in result["top"]:
        idx, title, usage, official, qs = row
        title_short = (title or "(无标题)")[:30]
        official_flag = "⭐" if official else " "
        logger.info(f"    [{official_flag}] #{idx} \"{title_short}\" | usage={usage} | QS={qs:.3f}")

    total_dry = "（试运行，未写入）" if args.dry_run else ""
    logger.info(f"🏁 QS 评分计算完成{total_dry}")


if __name__ == "__main__":
    asyncio.run(main())
