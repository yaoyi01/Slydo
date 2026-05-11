"""
DeepSeek API 封装 — LLM 文本生成

用于推荐引擎的 LLM 重排步骤和场景 B 大纲推理。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from app.config import settings
from app.utils.retry import retry

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# 场景 A/C — 推荐重排 Prompt
# ═══════════════════════════════════════════════════════════

RE_RANK_PROMPT = """你是一个 PPT 页面推荐引擎。用户正在制作一份 PPT，当前页面上下文如下：

## 当前上下文
{context_title}

## 候选页面（共 {candidate_count} 个）
{candidate_details}

请分析每个候选页面与当前上下文的「逻辑适配度」，按适合推荐的程度从高到低排序。

要求：
1. 只输出 JSON 数组，不要包含任何其他内容
2. 格式：[{{"slide_id": "...", "reason": "推荐理由", "score": 0-10}}]
3. score 越大表示越适配
4. 推荐理由简洁，一句话说明为什么该页面对当前语境有帮助
5. 返回 Top-5 结果"""

# ═══════════════════════════════════════════════════════════
# 场景 B — 大纲推理 Prompt
# ═══════════════════════════════════════════════════════════

OUTLINE_REASONING_PROMPT = """你是一个专业的 PPT 大纲顾问。用户已完成一份 PPT 的部分页面，需要通过分析已完成的页面标题序列，推理接下来的逻辑走向。

## 已完成的页面标题序列
{completed_titles}

## 当前页面
{current_title}

## 任务
请分析已完成的页面序列，推理接下来 3 个最合理的逻辑走向。每个走向需要包含：

1. direction: 走向标题（一句话概括，如"深入分析XX问题"）
2. keywords: 2-4 个搜索关键词，用于从知识库中检索相关页面（精确、专业）
3. reason: 为什么这个走向合理（结合已完成页面的逻辑链条）

要求：
1. 只输出 JSON 对象，不要包含任何其他内容
2. 格式：{{"directions": [{{"direction": "...", "keywords": ["...", "..."], "reason": "..."}}, ...]}}
3. 输出 3 个方向，按推荐程度从高到低排列
4. direction 控制在 15 字以内"""


# ═══════════════════════════════════════════════════════════
# DeepSeek API 调用
# ═══════════════════════════════════════════════════════════


@retry(max_attempts=3, delay=2.0, backoff=2.0, exceptions=(httpx.HTTPError, httpx.TimeoutException))
async def deepseek_chat(prompt: str, system_prompt: str = "") -> str:
    """
    调用 DeepSeek API 进行文本生成。

    参数：
        prompt: 用户消息
        system_prompt: 系统提示（可选）

    返回：
        str — 模型输出文本
    """
    if not settings.deepseek_api_key:
        raise ValueError("DEEPSEEK_API_KEY 未设置")

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    url = f"{settings.deepseek_base_url}/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 4096,
    }
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    content = data["choices"][0]["message"]["content"]
    return content


# ═══════════════════════════════════════════════════════════
# JSON 解析（通用）
# ═══════════════════════════════════════════════════════════


def parse_json_from_text(text: str) -> Any:
    """
    通用 JSON 提取器 — 从 LLM 输出中提取 JSON 对象或数组。

    容错策略：
        1. 直接解析
        2. 提取 ```json ... ``` 代码块
        3. 在大文本中找 {...} 或 [...] 结构
    """
    text = text.strip()
    if not text:
        return None

    # 策略 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略 2: 提取 json 代码块
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 策略 3: 找 [...] 或 {...} 结构（数组优先，避免只匹配到数组的第一个元素）
    for pat in [r'\[.*\]', r'\{.*\}']:
        match = re.search(pat, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

    logger.warning(f"无法解析 LLM 输出 (前200字符): {text[:200]}")
    return None


def parse_reranked_json(text: str) -> list[dict[str, Any]]:
    """解析重排结果 JSON 数组。"""
    result = parse_json_from_text(text)
    if isinstance(result, list):
        return result
    logger.warning(f"重排结果不是数组: {type(result)}")
    return []


def parse_outline_json(text: str) -> list[dict[str, Any]]:
    """
    解析大纲推理结果。

    返回格式：[{"direction": "...", "keywords": [...], "reason": "..."}]
    """
    result = parse_json_from_text(text)
    if isinstance(result, dict):
        directions = result.get("directions", [])
        if isinstance(directions, list):
            return directions
    if isinstance(result, list):
        # 直接返回了数组（有些 LLM 可能省略外层对象）
        return result
    logger.warning(f"大纲推理结果格式异常: {type(result)}")
    return []
