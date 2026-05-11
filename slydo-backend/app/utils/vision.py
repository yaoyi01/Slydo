"""
视觉模型封装 — 支持 Ollama 和 DashScope (阿里云) 双后端

核心功能：
    1. call_vision_api() — 发送图片+文本给视觉模型（自动选择后端）
    2. parse_vision_response() — JSON 解析容错（re.search 兜底）
    3. encode_image() — 图片转 base64

后端选择逻辑：
    - 如果 settings.dashscope_api_key 非空 → 使用 DashScope qwen3-vl-plus
    - 否则 → 使用 Ollama 本地视觉模型
"""
from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx

from app.config import settings
from app.utils.retry import retry

logger = logging.getLogger(__name__)

# 视觉模型 Prompt（与设计说明书一致）
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


# ═══════════════════════════════════════════════════════════
# 1. 图片编码
# ═══════════════════════════════════════════════════════════


def encode_image(image_path: str | Path) -> str:
    """将图片文件编码为 base64 字符串"""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ═══════════════════════════════════════════════════════════
# 2. JSON 解析容错
# ═══════════════════════════════════════════════════════════


def parse_vision_response(text: str) -> dict[str, Any]:
    """
    从视觉模型输出中解析 JSON。

    容错策略：
        1. 直接尝试 json.loads
        2. 提取 ```json ... ``` 代码块
        3. 使用 re.search 直接在大文本中找 { } 结构
        4. 全部失败 → 抛出 ValueError
    """
    if not text or not text.strip():
        raise ValueError("视觉模型返回空响应")

    text = text.strip()

    # 策略 1: 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 策略 2: 提取 ```json ... ``` 代码块
    block_match = re.search(
        r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL
    )
    if block_match:
        try:
            return json.loads(block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 策略 3: 在大文本中找第一对 { } 结构
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    # 策略 4: 移除多余换行和缩进后重试
    cleaned = re.sub(r'\n\s+', ' ', text)
    cleaned = re.sub(r',\s*}', '}', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 全部失败
    logger.warning(f"视觉模型返回不可解析的响应 (前200字符): {text[:200]}")
    raise ValueError(f"无法从视觉模型输出中解析 JSON: {text[:100]}")


# ═══════════════════════════════════════════════════════════
# 3. 结果验证与补全
# ═══════════════════════════════════════════════════════════


def validate_and_fill(result: dict[str, Any]) -> dict[str, Any]:
    """
    验证解析结果并填充默认值。

    确保返回的 dict 始终包含 role / summary / visual_desc / tags 四个字段。
    """
    valid_roles = {"cover", "toc", "transition", "argument", "evidence", "conclusion", "appendix"}

    role = result.get("role", "").strip().lower()
    if role not in valid_roles:
        if any(k in role for k in ("cover", "封面", "封")):
            role = "cover"
        elif any(k in role for k in ("toc", "目录", "目")):
            role = "toc"
        elif any(k in role for k in ("transition", "转场", "过渡")):
            role = "transition"
        elif any(k in role for k in ("conclusion", "结论", "总结")):
            role = "conclusion"
        elif any(k in role for k in ("appendix", "附录", "附")):
            role = "appendix"
        elif any(k in role for k in ("evidence", "论据", "数据")):
            role = "evidence"
        else:
            role = "argument"

    # 确保 tags 是列表
    tags = result.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.replace("，", ",").split(",") if t.strip()]

    return {
        "role": role,
        "summary": (result.get("summary", "") or "").strip(),
        "visual_desc": (result.get("visual_desc", "") or "").strip(),
        "tags": tags[:8],
    }


# ═══════════════════════════════════════════════════════════
# 4. DashScope (阿里云) 视觉 API 调用
# ═══════════════════════════════════════════════════════════


async def _call_dashscope_vision(
    image_path: str | Path | None,
    title: str = "",
    body_text: str = "",
    notes_text: str = "",
) -> dict[str, Any]:
    """
    调用 DashScope qwen3-vl-plus 视觉模型。
    API 文档：https://help.aliyun.com/zh/model-studio/use-cases/qwen-vl-plus
    """
    prompt = VISION_PROMPT.format(
        title=title or "(无标题)",
        body_text=body_text or "(无正文)",
        notes_text=notes_text or "(无备注)",
    )

    # 构建消息内容
    content_parts = []

    if image_path:
        img_path = Path(image_path)
        if img_path.exists():
            img_b64 = encode_image(img_path)
            content_parts.append({
                "image": f"data:image/png;base64,{img_b64}",
            })
        else:
            logger.warning(f"图片不存在: {image_path}")

    content_parts.append({"text": prompt})

    payload = {
        "model": settings.dashscope_vision_model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": content_parts,
                }
            ],
        },
        "parameters": {
            "temperature": 0.3,
            "max_tokens": 2000,
        },
    }

    api_url = f"{settings.dashscope_base_url.rstrip('/')}/services/aigc/multimodal-generation/generation"
    headers = {
        "Authorization": f"Bearer {settings.dashscope_api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        logger.debug(f"  调用 DashScope 视觉模型: {settings.dashscope_vision_model}")
        response = await client.post(api_url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    # DashScope 返回结构：output.choices[0].message.content[0].text
    choices = data.get("output", {}).get("choices", [])
    if not choices:
        msg = data.get("message", data.get("code", "unknown"))
        logger.warning(f"DashScope 返回无有效内容: {data}")
        raise ValueError(f"DashScope 视觉分析无输出: {msg}")

    content_list = choices[0].get("message", {}).get("content", [])
    text_content = ""
    for item in content_list:
        if "text" in item:
            text_content += item["text"]
        elif isinstance(item, str):
            text_content += item

    if not text_content:
        raise ValueError("DashScope 返回空内容")

    return parse_vision_response(text_content)


# ═══════════════════════════════════════════════════════════
# 5. Ollama 视觉 API 调用
# ═══════════════════════════════════════════════════════════


async def _call_ollama_vision(
    image_path: str | Path | None,
    title: str = "",
    body_text: str = "",
    notes_text: str = "",
) -> dict[str, Any]:
    """
    调用 Ollama 本地视觉模型。
    """
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
        else:
            logger.warning(f"图片不存在: {image_path}")

    payload = {
        "model": settings.ollama_vision_model,
        "messages": [
            {
                "role": "user",
                "content": message_text,
            }
        ],
        "stream": False,
        "options": {
            "temperature": 0.3,
        },
    }

    url = f"{settings.ollama_base_url}/api/chat"

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        logger.debug(f"  调用 Ollama 视觉模型: {settings.ollama_vision_model} (图片: {'有' if image_path else '无'})")
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    message = data.get("message", {})
    content = message.get("content", "")

    return parse_vision_response(content)


# ═══════════════════════════════════════════════════════════
# 6. 统一 API 入口
# ═══════════════════════════════════════════════════════════


# 同时重试 DashScope（httpx 网络异常、ValueError JSON 解析、KeyError 字段缺失）
@retry(max_attempts=5, delay=3.0, backoff=2.0, exceptions=(httpx.HTTPError, httpx.TimeoutException, ValueError, KeyError))
async def call_vision_api(
    image_path: str | Path | None,
    title: str = "",
    body_text: str = "",
    notes_text: str = "",
) -> dict[str, Any]:
    """
    调用视觉模型分析幻灯片页面。

    自动选择后端：
        - settings.dashscope_api_key 非空 → DashScope
        - 否则 → Ollama

    参数：
        image_path: 页面截图路径（None 表示无截图）
        title/body_text/notes_text: 提取到的文本

    返回：
        {"role": "...", "summary": "...", "visual_desc": "...", "tags": [...]}

    异常：
        httpx.HTTPError: API 调用失败（会被 @retry 重试）
        ValueError: JSON 解析失败（会被 @retry 重试）
    """
    # 判断后端
    use_dashscope = bool(settings.dashscope_api_key)

    if use_dashscope:
        logger.info(f"  [DashScope] {settings.dashscope_vision_model} 分析...")
        result = await _call_dashscope_vision(
            image_path=image_path,
            title=title,
            body_text=body_text,
            notes_text=notes_text,
        )
    else:
        logger.info(f"  [Ollama] {settings.ollama_vision_model} 分析...")
        result = await _call_ollama_vision(
            image_path=image_path,
            title=title,
            body_text=body_text,
            notes_text=notes_text,
        )

    # 验证并补全
    return validate_and_fill(result)
