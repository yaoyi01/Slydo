"""
版本管理模块 — 文档更新+版本历史+回滚+清理

核心能力：
    1. update_deck() — 旧版归档 + 新版覆盖（含缩略图+Wiki+Qdrant）
    2. restore_deck() — 从历史版本回滚
    3. cleanup_old_versions() — 清理超过2版本的旧记录
    4. VersionManager — 统一的版本管理入口
"""
from __future__ import annotations

import json
import logging
import shutil
import uuid
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any

from qdrant_client import models as qdrant_models
from sqlalchemy import text

from app.config import settings
from app.database import async_session_factory
from app.models.deck import Deck
from app.models.deck_version import DeckVersion
from app.models.slide import Slide
from app.qdrant import COLLECTION_NAME, get_qdrant
from app.services.etl.phase1_extract import compute_checksum, extract_slides, render_slides_to_images
from app.services.etl.phase3_store import write_to_llm_wiki

logger = logging.getLogger(__name__)


def get_wiki_root() -> Path:
    return Path(settings.slydo_wiki_path).expanduser()


def get_raw_dir() -> Path:
    """源文件备份目录：~/.slydo/wiki/raw/"""
    return get_wiki_root() / "raw"


# ═══════════════════════════════════════════════════════════
# 1. update_deck — 文档更新
# ═══════════════════════════════════════════════════════════


async def update_deck(
    deck_id: str,
    new_pptx_path: str | Path,
) -> dict[str, Any]:
    """
    更新文档：旧版归档 → 新版覆盖。

    流程：
        1. 读取当前 deck 数据
        2. 当前数据快照写入 deck_versions
        3. 备份旧源文件 raw/deck_<id>_v<n-1>.pptx
        4. 清理旧 slides + Qdrant + Wiki + 缩略图
        5. 全量重新入库（Phase 1-4）
        6. 更新 decks 表版本号

    参数：
        deck_id: 要更新的 Deck UUID
        new_pptx_path: 新的 PPT 文件路径

    返回：
        {
            "deck_id": str,
            "old_version": int,
            "new_version": int,
            "slide_count": int,
        }
    """
    new_pptx_path = Path(new_pptx_path).resolve()
    if not new_pptx_path.exists():
        raise FileNotFoundError(f"新文件不存在: {new_pptx_path}")

    async with async_session_factory() as session:
        # Step 1: 读取当前 deck 数据
        result = await session.execute(
            text("SELECT * FROM decks WHERE id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )
        current = result.fetchone()
        if not current:
            raise ValueError(f"Deck 不存在: {deck_id}")

        old_version = current.version
        old_title = current.title

        # Step 2: 读取当前 slides 快照
        slides_result = await session.execute(
            text("SELECT * FROM slides WHERE deck_id = CAST(:deck_id AS uuid) ORDER BY slide_index"),
            {"deck_id": deck_id},
        )
        current_slides = []
        for row in slides_result.fetchall():
            slide_dict = dict(row._mapping)
            # 将不可 JSON 序列化的类型转为字符串
            for k, v in slide_dict.items():
                if isinstance(v, (uuid.UUID, datetime, date)):
                    slide_dict[k] = str(v)
            current_slides.append(slide_dict)

        # 写入版本历史（当前数据快照）
        version_entry = DeckVersion(
            id=uuid.uuid4(),
            deck_id=uuid.UUID(deck_id),
            version=old_version,
            title=current.title,
            file_path=current.file_path,
            checksum=current.checksum,
            slide_count=current.slide_count,
            snapshot=current_slides,
        )
        session.add(version_entry)
        await session.flush()

    # ── Step 3: 备份旧源文件 ────────────────────────────
    raw_dir = get_raw_dir()
    raw_dir.mkdir(parents=True, exist_ok=True)
    old_raw_path = current.file_path or ""
    if old_raw_path and Path(old_raw_path).exists():
        backup_path = raw_dir / f"deck_{deck_id}_v{old_version}.pptx"
        shutil.copy2(old_raw_path, backup_path)
        logger.info(f"[版本] 源文件备份: {backup_path}")

    # ── Step 4: 清理旧数据 ──────────────────────────────
    async with async_session_factory() as session:
        # 清理旧 slides（CASCADE 自动处理 slide_tags）
        await session.execute(
            text("DELETE FROM slides WHERE deck_id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )

        # 清理旧 Qdrant points
        client = get_qdrant()
        try:
            client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qdrant_models.FilterSelector(
                    filter=qdrant_models.Filter(
                        must=[
                            qdrant_models.FieldCondition(
                                key="deck_id",
                                match=qdrant_models.MatchValue(value=deck_id),
                            )
                        ]
                    )
                ),
            )
            logger.info(f"[版本] Qdrant 旧 points 已清理: deck={deck_id}")
        except Exception as e:
            logger.warning(f"[版本] Qdrant 清理失败: {e}")

        # 清理旧 Wiki + 缩略图
        wiki_root = get_wiki_root()
        slides_wiki = wiki_root / "slides" / f"deck_{deck_id}"
        thumb_dir = wiki_root / "thumbnails" / f"deck_{deck_id}"
        shutil.rmtree(slides_wiki, ignore_errors=True)
        shutil.rmtree(thumb_dir, ignore_errors=True)
        logger.info(f"[版本] Wiki+缩略图已清理: deck={deck_id}")

    # ── Step 5: 全量重新入库 ────────────────────────────
    from app.services.etl.phase4_embed import embed_text

    new_checksum = compute_checksum(new_pptx_path)
    slides = extract_slides(new_pptx_path)

    # 渲染缩略图
    thumb_dir_new = wiki_root / "thumbnails" / f"deck_{deck_id}"
    try:
        png_paths = render_slides_to_images(new_pptx_path, thumb_dir_new, dpi=150)
        for s in slides:
            idx = s["slide_index"]
            tp = thumb_dir_new / f"slide_{idx:03d}.png"
            s["thumbnail_path"] = str(tp) if tp.exists() else ""
    except RuntimeError as e:
        logger.warning(f"[版本] 渲染失败: {e}")

    # 写入新 slides 到 PG
    async with async_session_factory() as session:
        for s in slides:
            slide = Slide(
                id=uuid.uuid4(),
                deck_id=uuid.UUID(deck_id),
                slide_index=s["slide_index"],
                title=s.get("title", ""),
                body_text=s.get("body_text", ""),
                notes_text=s.get("notes_text", ""),
                semantic_role=s.get("semantic_role"),
                semantic_summary=s.get("semantic_summary"),
                semantic_tags=s.get("semantic_tags"),
                visual_desc=s.get("visual_desc"),
                thumbnail_path=s.get("thumbnail_path"),
                usage_count=0,
                quality_score=0.0,
            )
            session.add(slide)

        # 更新 decks 表（版本+1）
        await session.execute(
            text("""
                UPDATE decks
                SET title = :title,
                    file_path = :file_path,
                    checksum = :checksum,
                    slide_count = :slide_count,
                    version = version + 1,
                    updated_at = NOW()
                WHERE id = CAST(:deck_id AS uuid)
            """),
            {
                "deck_id": deck_id,
                "title": new_pptx_path.stem,
                "file_path": str(new_pptx_path),
                "checksum": new_checksum,
                "slide_count": len(slides),
            },
        )
        await session.commit()

        # 读取新版本号
        result = await session.execute(
            text("SELECT version FROM decks WHERE id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )
        new_version = result.scalar()

    # 重新写入 Wiki
    write_to_llm_wiki(deck_id=deck_id, title=new_pptx_path.stem, slides=slides)

    # 重新嵌入 Qdrant
    from app.services.etl.phase4_embed import embed_to_qdrant
    await embed_to_qdrant(deck_id=deck_id, slides=slides)

    logger.info(
        f"[版本] 更新完成: deck={deck_id}, "
        f"v{old_version} → v{new_version}, slides={len(slides)}"
    )
    return {
        "deck_id": deck_id,
        "old_version": old_version,
        "new_version": new_version,
        "slide_count": len(slides),
    }


# ═══════════════════════════════════════════════════════════
# 2. restore_deck — 版本回滚
# ═══════════════════════════════════════════════════════════


async def restore_deck(deck_id: str, target_version: int | None = None) -> dict[str, Any]:
    """
    从历史版本恢复文档。

    参数：
        deck_id: Deck UUID
        target_version: 目标版本号（None=上一版）

    返回：
        {"deck_id": str, "restored_version": int, "slide_count": int}
    """
    async with async_session_factory() as session:
        # 查询当前版本信息
        result = await session.execute(
            text("SELECT version, title FROM decks WHERE id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )
        current = result.fetchone()
        if not current:
            raise ValueError(f"Deck 不存在: {deck_id}")

        current_version = current.version
        current_title = current.title

        # 如果未指定版本，取上一版（version = current - 1 或最大的历史版本）
        if target_version is None:
            target_version = current_version - 1
            if target_version < 1:
                raise ValueError("没有可恢复的历史版本")

        # 查找目标版本的历史记录
        result = await session.execute(
            text("""
                SELECT * FROM deck_versions
                WHERE deck_id = CAST(:deck_id AS uuid) AND version = :target
                ORDER BY created_at DESC
                LIMIT 1
            """),
            {"deck_id": deck_id, "target": target_version},
        )
        version_row = result.fetchone()
        if not version_row:
            raise ValueError(f"版本 v{target_version} 不存在")

        snapshot = version_row.snapshot
        if not snapshot:
            raise ValueError(f"版本 v{target_version} 的快照数据为空")

    # 清理当前数据
    async with async_session_factory() as session:
        await session.execute(
            text("DELETE FROM slides WHERE deck_id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )

    client = get_qdrant()
    try:
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qdrant_models.FilterSelector(
                filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="deck_id",
                            match=qdrant_models.MatchValue(value=deck_id),
                        )
                    ]
                )
            ),
        )
    except Exception as e:
        logger.warning(f"[恢复] Qdrant 清理失败: {e}")

    # 从快照恢复 slides
    slides: list[dict[str, Any]] = []
    async with async_session_factory() as session:
        for snap_slide in snapshot:
            # 转换为 slide dict 格式
            slide_dict = {
                "slide_index": snap_slide.get("slide_index", 1),
                "title": snap_slide.get("title", ""),
                "body_text": snap_slide.get("body_text", ""),
                "notes_text": snap_slide.get("notes_text", ""),
                "semantic_role": snap_slide.get("semantic_role"),
                "semantic_summary": snap_slide.get("semantic_summary"),
                "semantic_tags": snap_slide.get("semantic_tags"),
                "visual_desc": snap_slide.get("visual_desc"),
                "thumbnail_path": snap_slide.get("thumbnail_path"),
                "quality_score": snap_slide.get("quality_score", 0.0),
            }
            slides.append(slide_dict)

            slide = Slide(
                id=uuid.uuid4(),
                deck_id=uuid.UUID(deck_id),
                slide_index=snap_slide.get("slide_index", 1),
                title=snap_slide.get("title", ""),
                body_text=snap_slide.get("body_text", ""),
                notes_text=snap_slide.get("notes_text", ""),
                semantic_role=snap_slide.get("semantic_role"),
                semantic_summary=snap_slide.get("semantic_summary"),
                semantic_tags=snap_slide.get("semantic_tags"),
                visual_desc=snap_slide.get("visual_desc"),
                thumbnail_path=snap_slide.get("thumbnail_path"),
                usage_count=0,
                quality_score=0.0,
            )
            session.add(slide)

        # 更新 decks 表
        old_checksum = version_row.checksum or ""
        await session.execute(
            text("""
                UPDATE decks
                SET version = version + 1,
                    checksum = :checksum,
                    slide_count = :slide_count,
                    updated_at = NOW()
                WHERE id = CAST(:deck_id AS uuid)
            """),
            {
                "deck_id": deck_id,
                "checksum": old_checksum,
                "slide_count": len(slides),
            },
        )
        await session.commit()

        # 读取新版本号
        result = await session.execute(
            text("SELECT version FROM decks WHERE id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )
        new_version = result.scalar()

    # 重新写入 Wiki
    wiki_title = version_row.title or current_title
    write_to_llm_wiki(deck_id=deck_id, title=wiki_title, slides=slides)

    # 重新嵌入 Qdrant
    from app.services.etl.phase4_embed import embed_to_qdrant
    await embed_to_qdrant(deck_id=deck_id, slides=slides)

    logger.info(
        f"[版本] 恢复完成: deck={deck_id}, "
        f"v{current_version} → v{target_version} (当前版本 v{new_version})"
    )
    return {
        "deck_id": deck_id,
        "restored_version": target_version,
        "slide_count": len(slides),
    }


# ═══════════════════════════════════════════════════════════
# 3. 版本清理
# ═══════════════════════════════════════════════════════════


async def cleanup_old_versions(max_versions: int = 2) -> dict[str, Any]:
    """
    清理超过 max_versions 个版本的旧记录。

    逻辑（与设计说明书一致）：
        每个 deck 保留最近 max_versions 个版本的 deck_versions 记录。
        超过的旧记录被删除。

    参数：
        max_versions: 保留的最大版本数（默认 2）

    返回：
        {"deleted": int, "kept_per_deck": int}
    """
    async with async_session_factory() as session:
        # 使用窗口函数找出需要删除的版本
        result = await session.execute(
            text("""
                DELETE FROM deck_versions dv
                WHERE dv.id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (
                            PARTITION BY deck_id ORDER BY version DESC
                        ) AS rn
                        FROM deck_versions
                    ) sub WHERE rn > :max_versions
                )
            """),
            {"max_versions": max_versions},
        )
        deleted = result.rowcount
        await session.commit()

    logger.info(f"[版本] 清理完成: 删除 {deleted} 条旧版本记录")
    return {"deleted": deleted, "kept_per_deck": max_versions}
