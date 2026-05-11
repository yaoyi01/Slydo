#!/usr/bin/env python3
"""
Slydo 视觉分析补跑脚本

从 PG 读取已入库但缺少真实视觉分析的 slide，
逐个调用 Ollama qwen3-vl:8b 视觉模型分析缩略图，
将结果写回 PG。

用法：
    python3 backfill_vision.py                          # 全量补跑
    python3 backfill_vision.py --deck <deck_id>         # 只补指定文档
    python3 backfill_vision.py --dry-run                # 试运行
    python3 backfill_vision.py --resume                 # 从上次中断处恢复

支持断点续传：每处理完一个 slide 记录 checkpoint，
下次 --resume 从上次中断处继续。
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import text

from app.config import settings
from app.database import async_session_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_vision")

CHECKPOINT_FILE = Path.home() / ".slydo" / "backfill_vision_checkpoint.json"
CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════
# 视觉 API 调用（直接从 phase2_vision + vision 复制逻辑）
# ═══════════════════════════════════════════════════════════


def encode_image(image_path: str | Path) -> str:
    import base64
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def parse_vision_response(text: str) -> dict[str, Any]:
    import re
    if not text or not text.strip():
        raise ValueError("视觉模型返回空响应")
    text = text.strip()
    # 策略 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 策略 2: ```json ... ```
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(1).strip())
        except json.JSONDecodeError: pass
    # 策略 3: { ... }
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try: return json.loads(m.group(0))
        except json.JSONDecodeError: pass
    raise ValueError(f"无法解析JSON: {text[:100]}")


def validate_and_fill(result: dict[str, Any]) -> dict[str, Any]:
    valid_roles = {"cover", "toc", "transition", "argument", "evidence", "conclusion", "appendix"}
    role = result.get("role", "").strip().lower()
    if role not in valid_roles:
        if any(k in role for k in ("cover", "封面", "封")): role = "cover"
        elif any(k in role for k in ("toc", "目录", "目")): role = "toc"
        elif any(k in role for k in ("transition", "转场", "过渡")): role = "transition"
        elif any(k in role for k in ("conclusion", "结论", "总结")): role = "conclusion"
        elif any(k in role for k in ("appendix", "附录", "附")): role = "appendix"
        elif any(k in role for k in ("evidence", "论据", "数据")): role = "evidence"
        else: role = "argument"
    tags = result.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]
    return {
        "role": role,
        "summary": (result.get("summary", "") or "").strip(),
        "visual_desc": (result.get("visual_desc", "") or "").strip(),
        "tags": tags[:8],
    }


VISION_PROMPT = """你正在分析一个 PPT 页面的截图及其提取的文本，请给出 JSON 格式的结果：

{{
    "role": "页面角色",
    "summary": "含义摘要",
    "visual_desc": "视觉描述",
    "tags": ["标签1", "标签2"]
}}

字段说明：
1. role: 页面角色，必须是以下之一：
   - cover(封面) / toc(目录) / transition(转场页) / argument(核心论点)
   - evidence(论据/数据支撑) / conclusion(结论页) / appendix(附录)

2. summary: 含义摘要，用 1-3 句话概括这一页在说什么（不是原文摘录，而是理解后的语义含义）

3. visual_desc: 视觉描述，简述页面视觉结构（如：左文右图结构，饼图展示市场份额占比，深蓝商务风配色）

4. tags: 语义标签，3-8 个标签，覆盖：行业、场景、分析维度、关键词

【页面信息】
截图通过视觉输入提供。
文本提取结果（可能为空）：
标题：{title}
正文：{body_text}
备注：{notes_text}

请只输出 JSON，不要包含其他任何内容。"""


async def call_ollama_vision(
    image_path: str | Path | None,
    title: str = "",
    body_text: str = "",
    notes_text: str = "",
) -> dict[str, Any]:
    """调用 Ollama 视觉模型（带重试）"""
    import httpx
    
    prompt = VISION_PROMPT.format(
        title=title or "(无标题)",
        body_text=body_text or "(无正文)",
        notes_text=notes_text or "(无备注)",
    )
    
    message_text = prompt
    if image_path:
        img_path = Path(image_path)
        if img_path.exists():
            img_b64 = encode_image(img_path)
            message_text = f"![image](data:image/png;base64,{img_b64})\n{prompt}"
    
    payload = {
        "model": settings.ollama_vision_model,
        "messages": [{"role": "user", "content": message_text}],
        "stream": False,
        "options": {"temperature": 0.3},
    }
    
    url = f"{settings.ollama_base_url}/api/chat"
    
    # 手动重试（比装饰器更可控）
    last_exc = None
    for attempt in range(1, 6):  # 最多5次
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
                logger.info(f"  [视觉] 调用模型: {settings.ollama_vision_model} (第{attempt}次)")
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
            
            content = data.get("message", {}).get("content", "")
            result = parse_vision_response(content)
            result = validate_and_fill(result)
            return result
        
        except (httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError) as e:
            last_exc = e
            if attempt < 5:
                wait = 5.0 * (2.0 ** (attempt - 1))
                logger.warning(f"  [视觉] 第{attempt}次失败: {type(e).__name__}: {str(e)[:80]}，{wait:.0f}s后重试...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"  [视觉] 重试{attempt}次后仍失败: {e}")
    
    raise last_exc  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════
# 检查点管理
# ═══════════════════════════════════════════════════════════


def save_checkpoint(deck_id: str, slide_index: int):
    """保存处理进度"""
    cp = {
        "last_deck_id": deck_id,
        "last_slide_index": slide_index,
        "updated_at": datetime.datetime.now().isoformat(),
    }
    CHECKPOINT_FILE.write_text(json.dumps(cp, ensure_ascii=False, indent=2))


def load_checkpoint() -> dict:
    """加载检查点"""
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {}


# ═══════════════════════════════════════════════════════════
# 核心逻辑
# ═══════════════════════════════════════════════════════════


async def get_pending_slides(deck_filter: str | None = None) -> list[dict]:
    """获取需要做视觉分析的 slide"""
    async with async_session_factory() as s:
        # 判断是否已做视觉的标准：visual_desc 不为空 且 semantic_role 是有效角色之一
        # （假数据特征：visual_desc='' 且 role='argument' 且 tags=空）
        where = """
            (s.visual_desc IS NULL OR s.visual_desc = '')
        """
        if deck_filter:
            where += f" AND d.id::text LIKE '{deck_filter}%'"
        
        rows = await s.execute(text(f"""
            SELECT s.id::text as slide_id, s.deck_id::text as deck_id, 
                   s.slide_index, s.title, s.body_text, s.notes_text,
                   s.thumbnail_path, d.title as deck_title
            FROM slides s
            JOIN decks d ON d.id = s.deck_id
            WHERE {where}
            ORDER BY d.created_at, s.slide_index
        """))
        results = []
        for r in rows.fetchall():
            # 检查缩略图是否存在
            thumb = r.thumbnail_path or ""
            deck_thumb_dir = Path(settings.slydo_wiki_path).expanduser() / "thumbnails" / f"deck_{r.deck_id}"
            # 如果没有 thumbnail_path 字段，尝试从标准路径构建
            if not thumb or not Path(thumb).exists():
                thumb_guess = deck_thumb_dir / f"slide_{r.slide_index:03d}.png"
                if thumb_guess.exists():
                    thumb = str(thumb_guess)
            
            results.append({
                "slide_id": r.slide_id,
                "deck_id": r.deck_id,
                "slide_index": r.slide_index,
                "title": r.title or "",
                "body_text": r.body_text or "",
                "notes_text": r.notes_text or "",
                "thumbnail_path": thumb,
                "deck_title": r.deck_title or "",
            })
        return results


async def update_slide_vision(slide_id: str, result: dict):
    """将视觉分析结果写回 PG"""
    tags_json = json.dumps(result["tags"], ensure_ascii=False)
    async with async_session_factory() as s:
        await s.execute(text("""
            UPDATE slides
            SET semantic_role = :role,
                semantic_summary = :summary,
                visual_desc = :visual_desc,
                semantic_tags = :tags
            WHERE id = CAST(:slide_id AS uuid)
        """), {
            "slide_id": slide_id,
            "role": result["role"],
            "summary": result["summary"],
            "visual_desc": result["visual_desc"],
            "tags": tags_json,
        })
        await s.commit()


async def main():
    parser = argparse.ArgumentParser(description="Slydo 视觉分析补跑脚本")
    parser.add_argument("--deck", help="只补跑指定 deck (UUID 前缀或完整)")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不写 PG")
    parser.add_argument("--resume", action="store_true", help="从中断处恢复")
    
    args = parser.parse_args()
    
    # 获取待处理 slides
    slides = await get_pending_slides(args.deck)
    logger.info(f"待处理 slide 总数: {len(slides)}")
    
    if args.dry_run:
        logger.info("=== 试运行模式 ===")
        # 按 deck 分组展示
        deck_groups: dict[str, list] = {}
        for s in slides:
            deck_groups.setdefault(s["deck_title"], []).append(s)
        for title, sds in deck_groups.items():
            print(f"  {title}: {len(sds)} 页待处理")
        print(f"总计: {len(slides)} 页")
        return
    
    # 断点续传
    skip_until = None
    if args.resume:
        cp = load_checkpoint()
        if cp.get("last_deck_id"):
            skip_until = (cp["last_deck_id"], cp.get("last_slide_index", 0))
            logger.info(f"从检查点恢复: last_deck={cp['last_deck_id'][:8]} slide={cp['last_slide_index']}")
    
    # 逐个处理
    total = len(slides)
    success = 0
    failed = 0
    skipped = 0
    t_start = time.time()
    
    for idx, s in enumerate(slides, 1):
        # 断点续传跳过已处理的
        if skip_until and (s["deck_id"] == skip_until[0] and s["slide_index"] <= skip_until[1]):
            skipped += 1
            continue
        if skip_until and (s["deck_id"] == skip_until[0] and s["slide_index"] > skip_until[1]):
            skip_until = None  # 过了断点，之后正常处理
        
        has_thumb = "✅" if s["thumbnail_path"] and Path(s["thumbnail_path"]).exists() else "❌"
        logger.info(f"[{idx}/{total}] deck={s['deck_title'][:20]} slide={s['slide_index']} 缩略图:{has_thumb}")
        
        try:
            result = await call_ollama_vision(
                image_path=s["thumbnail_path"] if s["thumbnail_path"] and Path(s["thumbnail_path"]).exists() else None,
                title=s["title"],
                body_text=s["body_text"],
                notes_text=s["notes_text"],
            )
            await update_slide_vision(s["slide_id"], result)
            success += 1
            # 保存检查点
            save_checkpoint(s["deck_id"], s["slide_index"])
            
            elapsed_min = (time.time() - t_start) / 60
            speed = idx / elapsed_min if elapsed_min > 0 else 0
            est_remaining = (total - idx) / speed if speed > 0 else 0
            logger.info(f"  ✅ role={result['role']} tags={result['tags'][:3]}... ({speed:.0f}页/分, 预计剩余{est_remaining:.0f}min)")
        
        except Exception as e:
            failed += 1
            logger.error(f"  ❌ 失败: {type(e).__name__}: {e}")
            # 失败也记录检查点以免卡死
            save_checkpoint(s["deck_id"], s["slide_index"])
    
    elapsed = time.time() - t_start
    logger.info(f"\n{'='*50}")
    logger.info(f"完成! 成功={success} 失败={failed} 跳过={skipped} 耗时={elapsed/60:.1f}min")


if __name__ == "__main__":
    asyncio.run(main())
