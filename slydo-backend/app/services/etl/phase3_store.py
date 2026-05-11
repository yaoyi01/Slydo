"""
ETL Phase 3: 结构化存储 — PostgreSQL + LLM Wiki 写入

核心能力：
    1. write_to_postgres() — 批量写入 decks + slides
    2. write_to_llm_wiki() — Markdown 写入 ~/.slydo/wiki/
    3. Phase 5 QS 初始化
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.database import async_session_factory
from app.models.deck import Deck
from app.models.slide import Slide

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 1. PostgreSQL 写入
# ═══════════════════════════════════════════════════════════


async def write_to_postgres(
    file_path: str,
    checksum: str,
    slides: list[dict[str, Any]],
    source_path: str = "",
) -> dict[str, Any]:
    """
    将 PPT 解析结果写入 PostgreSQL（decks + slides 表）。

    参数：
        file_path: 源文件路径（用于提取文件名作为标题）
        checksum: 文件 MD5 checksum
        slides: 包含 Phase 1 + Phase 2 结果的 slide dict 列表
        source_path: 源文件保存路径（可选）

    返回：
        {
            "deck_id": UUID 字符串,
            "title": str,
            "slide_count": int,
        }
    """
    from pathlib import Path as P
    title = P(file_path).stem

    deck_id = uuid.uuid4()

    async with async_session_factory() as session:
        # 写入 decks 表
        deck = Deck(
            id=deck_id,
            title=title,
            file_path=source_path or file_path,
            slide_count=len(slides),
            checksum=checksum,
            version=1,
            is_official=False,
        )
        session.add(deck)

        # 批量写入 slides 表
        for s in slides:
            slide = Slide(
                id=uuid.uuid4(),
                deck_id=deck_id,
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

        await session.commit()
        logger.info(
            f"[PG] 写入完成: deck={deck_id}, title={title}, "
            f"slides={len(slides)}"
        )

    return {
        "deck_id": str(deck_id),
        "title": title,
        "slide_count": len(slides),
    }


# ═══════════════════════════════════════════════════════════
# 2. LLM Wiki 写入
# ═══════════════════════════════════════════════════════════


def write_to_llm_wiki(
    deck_id: str,
    title: str,
    slides: list[dict[str, Any]],
    wiki_root: str | Path | None = None,
) -> list[str]:
    """
    将 PPT 内容写入 LLM Wiki（Markdown 文件）。

    目录结构：
        ~/.slydo/wiki/
        ├── decks/
        │   └── deck_<deck_id>.md           (文档总览)
        └── slides/
            └── deck_<deck_id>/
                └── slide_<index>.md         (单页详情)

    参数：
        deck_id: UUID 字符串
        title: 文档标题
        slides: slide dict 列表（含 Phase1+Phase2 结果）
        wiki_root: Wiki 根目录（默认 ~/.slydo/wiki/）

    返回：
        list[str] — 生成的文件路径列表
    """
    if wiki_root is None:
        wiki_root = Path(settings.slydo_wiki_path).expanduser()
    wiki_root = Path(wiki_root)

    # 创建目录
    decks_dir = wiki_root / "decks"
    slides_dir = wiki_root / "slides" / f"deck_{deck_id}"
    decks_dir.mkdir(parents=True, exist_ok=True)
    slides_dir.mkdir(parents=True, exist_ok=True)

    generated_files: list[str] = []

    # ── 文档总览页 ──────────────────────────────────────
    deck_file = decks_dir / f"deck_{deck_id}.md"
    deck_lines = [
        f"# {title}",
        "",
        f"- **Deck ID:** `{deck_id}`",
        f"- **页数:** {len(slides)}",
        f"- **生成时间:** {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "---",
        "",
        "## 页面列表",
        "",
    ]
    for s in slides:
        idx = s["slide_index"]
        slide_title = s.get("title", "(无标题)") or "(无标题)"
        role = s.get("semantic_role", "unknown")
        summary = s.get("semantic_summary", "") or ""
        tags = s.get("semantic_tags", []) or []
        deck_lines.append(f"### 第 {idx} 页: {slide_title}")
        deck_lines.append(f"- **角色:** {role}")
        if summary:
            deck_lines.append(f"- **摘要:** {summary}")
        if tags:
            deck_lines.append(f"- **标签:** {', '.join(tags)}")
        deck_lines.append(
            f"- **Wiki 链接:** [slide_{idx:03d}.md](slides/deck_{deck_id}/slide_{idx:03d}.md)"
        )
        deck_lines.append("")

    deck_content = "\n".join(deck_lines)
    deck_file.write_text(deck_content, encoding="utf-8")
    generated_files.append(str(deck_file))

    # ── 单页详情 ────────────────────────────────────────
    for s in slides:
        idx = s["slide_index"]
        slide_title = s.get("title", "") or "(无标题)"
        body_text = s.get("body_text", "") or ""
        notes_text = s.get("notes_text", "") or ""
        role = s.get("semantic_role", "unknown") or "unknown"
        summary = s.get("semantic_summary", "") or ""
        visual_desc = s.get("visual_desc", "") or ""
        tags = s.get("semantic_tags", []) or []

        # 构建标签行
        tags_str = ", ".join(tags) if tags else "(无标签)"

        # 视觉描述
        visual_section = f"**视觉描述:** {visual_desc}" if visual_desc else ""

        slide_content = f"""---
deck_id: {deck_id}
slide_index: {idx}
role: {role}
tags: [{tags_str}]
---

# 第 {idx} 页: {slide_title}

## 基本信息

| 字段 | 内容 |
|:---|:---|
| **所属文档** | [{title}](../decks/deck_{deck_id}.md) |
| **页面索引** | {idx} / {len(slides)} |
| **页面角色** | {role} |
| **语义标签** | {tags_str} |

## 含义摘要

{summary}

## 视觉描述

{visual_section or "(无视觉描述)"}

## 提取的原始文本

### 标题
{slide_title or "(无标题)"}

### 正文
{body_text or "(无正文)"}

### 备注
{notes_text or "(无备注)"}
"""
        slide_file = slides_dir / f"slide_{idx:03d}.md"
        slide_file.write_text(slide_content.strip(), encoding="utf-8")
        generated_files.append(str(slide_file))

    logger.info(
        f"[Wiki] 写入完成: {len(generated_files)} 个文件 → {wiki_root}"
    )
    return generated_files


# ═══════════════════════════════════════════════════════════
# 3. Phase 5 QS 初始化
# ═══════════════════════════════════════════════════════════


async def init_quality_scores(deck_id: str, slide_count: int) -> None:
    """
    初始化质量评分：将新建 deck 的所有 slide 的 quality_score 设为 0.0。

    QS 公式见开发说明书第6章：
        QS = 0.40*is_official + 0.30*usage_freq + 0.20*source_level + 0.10*llm_score
    初始 all 0.0，后续通过复用和人工评分更新。
    """
    async with async_session_factory() as session:
        # deck_id 已经是字符串，直接作为文本参数传
        result = await session.execute(
            text("""
                UPDATE slides
                SET quality_score = 0.0
                WHERE deck_id = CAST(:deck_id AS uuid)
            """),
            {"deck_id": deck_id},
        )
        await session.commit()
        logger.info(f"[QS] 初始化完成: deck={deck_id}, slides={slide_count}，quality_score=0.0")
