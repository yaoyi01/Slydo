"""
ETL Phase 2: 多模态 LLM 含义提取

核心能力：
    1. llm_extract_meaning_single() — 单页视觉分析
    2. llm_extract_meaning_batch() — 批量分析（并发 + 限流）
    3. TokenCounter 集成 — 自动追踪消耗

依赖：
    - A2 phase1_extract.py (提取文本 + 渲染缩略图)
    - utils/vision.py (Ollama 视觉模型调用)
    - utils/retry.py (指数退避重试)
    - utils/token_counter.py (Token 费用估算)
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.utils.token_counter import TokenCounter, estimate_image_tokens
from app.utils.vision import call_vision_api

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 1. 单页分析
# ═══════════════════════════════════════════════════════════


async def llm_extract_meaning_single(
    slide_data: dict[str, Any],
    thumbnail_dir: str | Path | None = None,
    counter: TokenCounter | None = None,
) -> dict[str, Any]:
    """
    对一张幻灯片页面进行多模态含义提取。

    参数：
        slide_data: phase1_extract 的输出 dict（含 slide_index / title / body_text / notes_text）
        thumbnail_dir: 缩略图目录（页面截图放在其中，如 slide_001.png）
        counter: 可选的 TokenCounter 实例（在批量处理中用于汇总）

    返回：
        slide_data 的扩展版本，新增字段：
            - semantic_role: str — 页面角色
            - semantic_summary: str — 含义摘要
            - visual_desc: str — 视觉描述
            - semantic_tags: list[str] — 语义标签
    """
    slide_index = slide_data["slide_index"]
    title = slide_data.get("title", "")
    body_text = slide_data.get("body_text", "")
    notes_text = slide_data.get("notes_text", "")

    # 缩略图路径
    image_path = None
    if thumbnail_dir:
        thumb = Path(thumbnail_dir) / f"slide_{slide_index:03d}.png"
        if thumb.exists():
            image_path = thumb

    # 调用视觉模型
    try:
        result = await call_vision_api(
            image_path=image_path,
            title=title,
            body_text=body_text,
            notes_text=notes_text,
        )
    except Exception as e:
        logger.error(f"  第 {slide_index} 页视觉分析失败: {type(e).__name__}: {e}")
        result = {
            "role": "argument",
            "summary": f"[分析失败] {title or '(无标题)'}",
            "visual_desc": "",
            "tags": [],
        }

    # 更新 TokenCounter
    if counter:
        # 视觉模型调用：输入 ≈ 图片(800) + 文本
        input_t = estimate_image_tokens("high") if image_path else 0
        input_t += len(title) + len(body_text) + len(notes_text)
        output_t = (
            len(result.get("summary", ""))
            + len(result.get("visual_desc", ""))
            + sum(len(t) for t in result.get("tags", []))
        )
        counter.add_tokens(input_t=input_t // 2, output_t=output_t // 4)  # 粗略估算

    # 构造返回
    return {
        **slide_data,
        "semantic_role": result["role"],
        "semantic_summary": result["summary"],
        "visual_desc": result["visual_desc"],
        "semantic_tags": result["tags"],
    }


# ═══════════════════════════════════════════════════════════
# 2. 批量分析（并发控制）
# ═══════════════════════════════════════════════════════════


async def llm_extract_meaning_batch(
    slides: list[dict[str, Any]],
    thumbnail_dir: str | Path | None = None,
    max_concurrency: int = 1,
    counter: TokenCounter | None = None,
) -> list[dict[str, Any]]:
    """
    对多张幻灯片进行批量含义提取。

    参数：
        slides: phase1_extract 输出的 slide dict 列表
        thumbnail_dir: 缩略图目录
        max_concurrency: 最大并发数（默认 5，避免 API 限流）
        counter: 可选的 TokenCounter 实例

    返回：
        扩展后的 slide dict 列表（含 semantic_role / semantic_summary / visual_desc / semantic_tags）
    """
    semaphore = asyncio.Semaphore(max_concurrency)

    async def process_one(slide: dict[str, Any]) -> dict[str, Any]:
        async with semaphore:
            return await llm_extract_meaning_single(
                slide, thumbnail_dir=thumbnail_dir, counter=counter,
            )

    tasks = [process_one(s) for s in slides]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 处理异常
    final: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error(f"第 {i+1} 页处理异常: {r}")
            final.append({
                **slides[i],
                "semantic_role": "argument",
                "semantic_summary": f"[分析失败] {slides[i].get('title', '')}",
                "visual_desc": "",
                "semantic_tags": [],
            })
        else:
            final.append(r)

    return final
