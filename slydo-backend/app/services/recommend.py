"""
推荐引擎 — 多路召回 + LLM 重排

流程：
    Step 1: 解析查询语义
    Step 2: 多路召回（Qdrant 语义 + PG FTS 关键词）
    Step 3: 双路去重
    Step 4: LLM 逻辑重排（DeepSeek API + Wiki 上下文）
    Step 5: 返回 Top-5 + 推荐理由
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.config import settings
from app.database import async_session_factory
from app.qdrant import COLLECTION_NAME, get_qdrant
from app.services.etl.phase4_embed import build_embedding_text, embed_text
from app.utils.llm import RE_RANK_PROMPT, deepseek_chat, parse_reranked_json

logger = logging.getLogger(__name__)

# 语义召回量
SEMANTIC_LIMIT = 30
# 关键词召回量
FTS_LIMIT = 20
# 最终返回数
TOP_N = 20


def get_wiki_root() -> Path:
    return Path(settings.slydo_wiki_path).expanduser()


# ═══════════════════════════════════════════════════════════
# 1. 语义召回（Qdrant）
# ═══════════════════════════════════════════════════════════


async def semantic_search(query: str, limit: int = SEMANTIC_LIMIT) -> list[dict[str, Any]]:
    """
    语义召回：将查询文本嵌入为向量，在 Qdrant 中搜索相似 slides。

    返回：list[dict]，每个 dict 含：
        - slide_id: Qdrant point ID
        - deck_id: str
        - slide_index: int
        - title: str
        - semantic_role: str
        - semantic_tags: list[str]
        - score: float（余弦相似度）
    """
    if not query.strip():
        return []

    # 嵌入查询
    vector = await embed_text(query)
    if not vector or all(v == 0.0 for v in vector):
        logger.warning("[推荐] 查询文本嵌入为空")
        return []

    # 搜索 Qdrant（兼容 v1.17+ 的 query_points API）
    try:
        client = get_qdrant()
        if hasattr(client, 'query_points'):
            # Qdrant 1.17+
            results = client.query_points(
                collection_name=COLLECTION_NAME,
                query=vector,
                limit=limit,
                with_payload=True,
            ).points
        else:
            # Qdrant < 1.17
            results = client.search(
                collection_name=COLLECTION_NAME,
                query_vector=vector,
                limit=limit,
                with_payload=True,
            )
    except Exception as e:
        logger.error(f"[推荐] Qdrant 搜索失败: {e}")
        return []

    candidates = []
    for res in results:
        payload = res.payload or {}
        deck_id = payload.get("deck_id", "")
        slide_index = payload.get("slide_index", 0)

        candidates.append({
            "slide_id": str(res.id),
            "deck_id": deck_id,
            "slide_index": slide_index,
            "title": payload.get("title", ""),
            "semantic_role": payload.get("semantic_role", ""),
            "semantic_tags": payload.get("semantic_tags", []),
            "score": round(res.score, 4),
            "source": "semantic",
        })

    # 反查 UUID：用 deck_id + slide_index 从 PG 中取 slide_id
    if candidates:
        try:
            async with async_session_factory() as session:
                from sqlalchemy import text
                cases = " OR ".join(
                    f"(deck_id = '{c['deck_id']}'::uuid AND slide_index = {c['slide_index']})"
                    for c in candidates
                )
                result = await session.execute(
                    text(f"SELECT id::text, deck_id::text, slide_index FROM slides WHERE {cases}")
                )
                uuid_map: dict[str, str] = {}
                for row in result:
                    key = f"{row.deck_id}_{row.slide_index}"
                    uuid_map[key] = str(row.id)

                for c in candidates:
                    key = f"{c['deck_id']}_{c['slide_index']}"
                    if key in uuid_map:
                        c["slide_id"] = uuid_map[key]
        except Exception as e:
            logger.warning(f"[推荐] UUID 反查失败: {e}")

    return candidates


# ═══════════════════════════════════════════════════════════
# 2. 关键词召回（PG FTS）
# ═══════════════════════════════════════════════════════════


async def keyword_search(keywords: str, limit: int = FTS_LIMIT) -> list[dict[str, Any]]:
    """
    关键词召回：PostgreSQL 全文搜索（标题 + 摘要 + 视觉描述）。

    返回：list[dict]（结构与 semantic_search 一致）
    """
    if not keywords.strip():
        return []

    async with async_session_factory() as session:
        try:
            # 用 ILIKE 模糊匹配代替 FTS（FTS 的 simple 配置不支持中文）
            # 对关键词按空格拆分，每个词都要匹配
            terms = [t.strip() for t in keywords.split() if t.strip()]
            if not terms:
                return []
            conditions = " AND ".join(
                f"(COALESCE(s.title,'') ILIKE '%' || :term{i} || '%' "
                f"OR COALESCE(s.semantic_summary,'') ILIKE '%' || :term{i} || '%' "
                f"OR COALESCE(s.visual_desc,'') ILIKE '%' || :term{i} || '%')"
                for i in range(len(terms))
            )
            params = {f"term{i}": t for i, t in enumerate(terms)}
            params["lim"] = limit

            result = await session.execute(
                text(f"""
                    SELECT
                        s.id,
                        s.deck_id::text,
                        s.slide_index,
                        COALESCE(s.title, '') AS title,
                        COALESCE(s.semantic_role, '') AS semantic_role,
                        COALESCE(s.semantic_summary, '') AS semantic_summary,
                        s.semantic_tags,
                        1.0 AS rank
                    FROM slides s
                    WHERE {conditions}
                    ORDER BY s.slide_index
                    LIMIT :lim
                """),
                params,
            )
            rows = result.fetchall()
        except Exception as e:
            logger.error(f"[推荐] PG FTS 搜索失败: {e}")
            return []

    candidates = []
    for row in rows:
        candidates.append({
            "slide_id": str(row.id),
            "deck_id": str(row.deck_id),
            "slide_index": row.slide_index,
            "title": row.title,
            "semantic_role": row.semantic_role,
            "semantic_tags": row.semantic_tags or [],
            "score": 0.5,
            "source": "keyword",
        })

    return candidates


# ═══════════════════════════════════════════════════════════
# 3. 双路合并去重
# ═══════════════════════════════════════════════════════════


def merge_dedup(
    semantic: list[dict[str, Any]],
    keyword: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    合并两路召回结果并去重。

    去重规则：按 slide_id 去重，语义召回优先（保留语义的 score）。
    """
    seen = set()
    merged: list[dict[str, Any]] = []

    for c in semantic:
        key = f"{c['deck_id']}_{c['slide_index']}"
        if key not in seen:
            seen.add(key)
            merged.append(c)

    for c in keyword:
        key = f"{c['deck_id']}_{c['slide_index']}"
        if key not in seen:
            seen.add(key)
            merged.append(c)

    logger.info(f"[推荐] 合并: 语义{len(semantic)} + 关键词{len(keyword)} → 去重后{len(merged)}")
    return merged


# ═══════════════════════════════════════════════════════════
# 4a. 最近入库（无查询时兜底）
# ═══════════════════════════════════════════════════════════


async def recent_slides(limit: int = TOP_N) -> list[dict[str, Any]]:
    """无搜索词时返回最近入库的 slide（按入库时间倒序）"""
    try:
        async with async_session_factory() as session:
            rows = (await session.execute(
                text("""
                    SELECT s.id::text, s.deck_id::text, s.slide_index,
                           s.title, s.semantic_role, COALESCE(s.semantic_tags, ARRAY[]::text[]) AS semantic_tags
                    FROM slides s
                    JOIN decks d ON d.id = s.deck_id
                    WHERE s.thumbnail_path IS NOT NULL AND s.thumbnail_path != ''
                    ORDER BY d.created_at DESC, s.slide_index
                    LIMIT :lim
                """),
                {"lim": limit},
            )).fetchall()

        return [{
            "slide_id": str(r.id),
            "deck_id": str(r.deck_id),
            "slide_index": r.slide_index,
            "title": r.title or "",
            "semantic_role": r.semantic_role or "",
            "semantic_tags": r.semantic_tags or [],
            "score": 0.5,
            "source": "recent",
        } for r in rows]
    except Exception as e:
        logger.error(f"[推荐] 获取最近入库失败: {e}")
        return []


# ═══════════════════════════════════════════════════════════
# 4. LLM 逻辑重排
# ═══════════════════════════════════════════════════════════


def read_wiki_context(deck_id: str, slide_index: int) -> str:
    """从 LLM Wiki 读取页面上下文 Markdown。"""
    wiki_root = get_wiki_root()
    path = wiki_root / "slides" / f"deck_{deck_id}" / f"slide_{slide_index:03d}.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


async def llm_rerank(
    candidates: list[dict[str, Any]],
    context_title: str,
    top_n: int = TOP_N,
) -> list[dict[str, Any]]:
    """
    LLM 逻辑重排 — 结合 Wiki 上下文，DeepSeek API 重排。

    参数：
        candidates: 去重后的候选列表
        context_title: 当前 PPT 页面的标题/上下文
        top_n: 最终返回数量

    返回：
        排序后的候选列表（含推荐理由）
    """
    if not candidates:
        return []

    # 只对 Top-20 做重排
    to_rerank = candidates[:20]

    # 读取 Wiki 上下文
    candidate_details = []
    for c in to_rerank:
        wiki = read_wiki_context(c["deck_id"], c["slide_index"])
        if wiki:
            # 提取关键信息摘要
            lines = wiki.split("\n")
            summary = ""
            tags = ""
            for i, line in enumerate(lines):
                if line.startswith("## 含义摘要") and i + 1 < len(lines):
                    summary = lines[i + 1].strip()
                if "语义标签" in line:
                    parts = line.split("|")
                    if len(parts) >= 3:
                        tags = parts[2].strip()

            detail = (
                f"候选 {c['slide_index']}: "
                f"slide_id={c['slide_id']}, "
                f"标题={c.get('title', '')}, "
                f"角色={c.get('semantic_role', '')}, "
                f"摘要={summary[:100]}, "
                f"标签={tags}"
            )
        else:
            detail = (
                f"候选 {c['slide_index']}: "
                f"slide_id={c['slide_id']}, "
                f"标题={c.get('title', '')}"
            )
        candidate_details.append(detail)

    # 构造 Prompt
    prompt = RE_RANK_PROMPT.format(
        context_title=context_title or "(无标题)",
        candidate_count=len(to_rerank),
        candidate_details="\n".join(candidate_details),
    )

    # 调用 DeepSeek API
    try:
        response = await deepseek_chat(
            prompt=prompt,
            system_prompt="你是一个专业的 PPT 页面推荐引擎，严格按 JSON 格式输出。",
        )
        reranked = parse_reranked_json(response)
    except Exception as e:
        logger.error(f"[推荐] LLM 重排失败: {e}")
        # 降级：QS 混合排序 (α·cosine + β·QS)
        ALPHA_QS = 0.7
        BETA_QS = 0.3
        for c in to_rerank:
            semantic_score = c.get("score", 0)
            qs_score = c.get("quality_score", 0)
            c["qs_score"] = round(ALPHA_QS * semantic_score + BETA_QS * qs_score, 4)
            c["reason"] = "（降级：按 QS 混合排序）"
        to_rerank.sort(key=lambda x: x.get("qs_score", 0), reverse=True)
        return to_rerank[:top_n]

    # 构建结果
    result_map = {c["slide_id"]: c for c in to_rerank}
    result: list[dict[str, Any]] = []
    for item in reranked:
        slide_id = item.get("slide_id", "")
        if slide_id in result_map:
            result_map[slide_id]["reason"] = item.get("reason", "")
            result_map[slide_id]["llm_score"] = item.get("score", 0)
            result.append(result_map[slide_id])

    # 补充分数最高的未选中项（如果不够 Top-N）
    for c in to_rerank:
        if len(result) >= top_n:
            break
        if c["slide_id"] not in {r["slide_id"] for r in result}:
            c["reason"] = ""
            result.append(c)

    return result[:top_n]


# ═══════════════════════════════════════════════════════════
# 5. 主入口 — 推荐
# ═══════════════════════════════════════════════════════════


async def recommend_slides(
    context_title: str = "",
    context_keywords: str = "",
    top_n: int = TOP_N,
) -> list[dict[str, Any]]:
    """
    推荐幻灯片页面 — 完整流程。

    参数：
        context_title: 当前页面标题（场景 A：标题驱动）
        context_keywords: 搜索关键词（场景 C：手动搜索）
        top_n: 返回结果数

    返回：
        list[dict] — 推荐结果列表
    """
    query = context_title or context_keywords
    if not query.strip():
        logger.warning("[推荐] 查询为空，返回最近入库的内容")
        # 没有搜索词时返回最近入库的 slide（推荐最新内容）
        return await recent_slides(top_n)

    # Step 1: 语义召回
    semantic = await semantic_search(query)
    logger.info(f"[推荐] 语义召回: {len(semantic)} 个")

    # Step 2: 关键词召回
    keyword = await keyword_search(query)
    logger.info(f"[推荐] 关键词召回: {len(keyword)} 个")

    # Step 3: 双路去重合并
    merged = merge_dedup(semantic, keyword)
    if not merged:
        logger.info("[推荐] 无结果")
        return []

    # Step 4: LLM 重排
    results = await llm_rerank(merged, context_title=context_title, top_n=top_n)

    logger.info(f"[推荐] 最终结果: {len(results)} 个")
    for r in results:
        logger.info(f"  [{r.get('semantic_role','?')}] {r.get('title','')} "
                    f"(score={r.get('score',0)}, reason={r.get('reason','')[:30]})")

    return results


# ═══════════════════════════════════════════════════════════
# 6. 场景 B — 大纲推荐
# ═══════════════════════════════════════════════════════════


DEFAULT_OUTLINE = [
    {"direction": "解决方案概述", "keywords": ["解决方案", "方案概述", "产品介绍"],
     "reason": "基于已完成页面推测，需要总体方案介绍"},
    {"direction": "核心功能详解", "keywords": ["核心功能", "功能特性", "技术架构"],
     "reason": "在介绍方案背景后通常进入功能详解"},
    {"direction": "客户案例", "keywords": ["客户案例", "项目实践", "应用场景"],
     "reason": "方案介绍类 PPT 通常在中间插入典型案例"},
]


async def outline_reasoning(
    completed_titles: list[str],
    current_title: str = "",
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """
    场景 B — 大纲推理推荐。

    参数：
        completed_titles: 已完成页面的标题序列（按顺序）
        current_title: 当前页面的标题（可能为空）
        top_k: 返回的走向数（默认 3）

    返回：
        list[dict] — 每个走向包含 direction / keywords / reason / slides（推荐页面列表）
    """
    from app.utils.llm import OUTLINE_REASONING_PROMPT, parse_outline_json, deepseek_chat

    if not completed_titles:
        logger.info("[大纲] 无已完成页面，返回默认走向")
        directions = DEFAULT_OUTLINE[:top_k]
    else:
        # 构造 Prompt
        titles_str = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(completed_titles))
        prompt = OUTLINE_REASONING_PROMPT.format(
            completed_titles=titles_str,
            current_title=current_title or "(空白页)",
        )

        # 调用 LLM
        try:
            response = await deepseek_chat(
                prompt=prompt,
                system_prompt="你是一个 PPT 大纲推理专家，严格按 JSON 格式输出。",
            )
            directions = parse_outline_json(response)
            if not directions:
                logger.warning("[大纲] LLM 返回空方向，使用默认走向")
                directions = DEFAULT_OUTLINE[:top_k]
        except Exception as e:
            logger.error(f"[大纲] LLM 推理失败: {e}")
            directions = DEFAULT_OUTLINE[:top_k]

    # 对每个走向，用关键词搜索推荐页面
    result = []
    for i, d in enumerate(directions[:top_k]):
        keywords = d.get("keywords", [])
        keyword_str = " ".join(keywords) if isinstance(keywords, list) else str(keywords)

        # 用关键词做语义搜索
        semantic = await semantic_search(keyword_str, limit=6)
        keyword_hits = await keyword_search(keyword_str, limit=4)
        merged = merge_dedup(semantic, keyword_hits)

        # 截取 top-5
        slides = merged[:5]

        result.append({
            "direction": d.get("direction", f"走向{i+1}"),
            "keywords": keywords,
            "reason": d.get("reason", ""),
            "slide_count": len(slides),
            "slides": slides,
        })

    logger.info(f"[大纲] 返回 {len(result)} 个走向")
    return result
