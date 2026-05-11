"""
A3 集成测试 — 端到端验证视觉模型调用

注意：这些测试需要 Ollama qwen3-vl:8b 模型可用。
图片测试依赖之前渲染生成的缩略图。
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

# 测试用缩略图
TEST_THUMB = Path("/tmp/slydo_test_f7cv0nl0/slide_001.png")
HAS_THUMB = TEST_THUMB.exists()


@pytest.mark.integration
class TestVisionIntegration:
    """视觉模型集成测试（需要 Ollama）"""

    @pytest.mark.skipif(not HAS_THUMB, reason="测试缩略图不存在")
    @pytest.mark.asyncio
    async def test_call_vision_api_with_image(self):
        """真实调用 Ollama 视觉模型分析有图片的页面"""
        from app.utils.vision import call_vision_api
        result = await call_vision_api(
            image_path=TEST_THUMB,
            title="联软信息防扩散解决方案",
            body_text="联软科技 姚祎",
        )
        assert "role" in result
        assert "summary" in result
        assert "visual_desc" in result
        assert "tags" in result
        assert isinstance(result["tags"], list)
        # role 必须是有效角色
        assert result["role"] in (
            "cover", "toc", "transition", "argument",
            "evidence", "conclusion", "appendix",
        )
        # 摘要不应为空
        assert len(result["summary"]) > 10


class TestPhase2Integration:
    """Phase 2 批量分析集成测试（使用 mock）"""

    @pytest.mark.asyncio
    async def test_llm_extract_meaning_batch_with_mock(self):
        """Mock 视觉模型调用验证批处理逻辑"""
        from app.services.etl.phase2_vision import llm_extract_meaning_batch

        slides = [
            {"slide_index": 1, "title": "封面", "body_text": "test1", "notes_text": ""},
            {"slide_index": 2, "title": "目录", "body_text": "test2", "notes_text": ""},
            {"slide_index": 3, "title": "内容", "body_text": "test3", "notes_text": "备注3"},
        ]

        async def mock_call(*args, **kwargs):
            slide_idx = kwargs.get("slide_data", {}).get("slide_index", 1)
            return {
                "role": "cover" if slide_idx == 1 else "argument",
                "summary": f"第{slide_idx}页摘要",
                "visual_desc": f"第{slide_idx}页视觉",
                "tags": ["tag1", "tag2"],
            }

        with patch("app.services.etl.phase2_vision.call_vision_api", mock_call):
            results = await llm_extract_meaning_batch(slides, thumbnail_dir=None)

        assert len(results) == 3
        for r in results:
            assert "semantic_role" in r
            assert "semantic_summary" in r
            assert "semantic_tags" in r
        assert results[0]["semantic_role"] == "cover"

    @pytest.mark.asyncio
    async def test_llm_extract_meaning_batch_exception_handling(self):
        """异常处理：某一页失败不影响其他页"""
        from app.services.etl.phase2_vision import llm_extract_meaning_batch

        slides = [
            {"slide_index": 1, "title": "A", "body_text": "a", "notes_text": ""},
            {"slide_index": 2, "title": "B", "body_text": "b", "notes_text": ""},
        ]

        call_count = [0]
        async def mock_call(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("模拟失败")
            return {"role": "argument", "summary": "ok", "visual_desc": "", "tags": []}

        with patch("app.services.etl.phase2_vision.call_vision_api", mock_call):
            results = await llm_extract_meaning_batch(slides, thumbnail_dir=None)

        assert len(results) == 2
        # 第一页失败但应返回降级结果
        assert "[分析失败]" in results[0]["semantic_summary"]
        assert results[1]["semantic_summary"] == "ok"

    @pytest.mark.asyncio
    async def test_etl_ingest_phase1_phase2_pipeline(self):
        """Mock 全流程：Phase 1 → Phase 2 联合测试"""
        from app.services.etl.phase2_vision import llm_extract_meaning_batch
        from app.services.etl.phase1_extract import extract_slides

        pptx = "/mnt/c/Users/kiven/Documents/LLM_wiki/知识库/raw/sources/信息防扩散解决方案.pptx"
        if not Path(pptx).exists():
            pytest.skip("测试 PPT 文件不存在")

        slides = extract_slides(pptx)
        assert len(slides) == 36

        async def mock_call(*args, **kwargs):
            return {
                "role": "argument",
                "summary": "测试摘要内容",
                "visual_desc": "测试视觉描述",
                "tags": ["安全", "测试"],
            }

        with patch("app.services.etl.phase2_vision.call_vision_api", mock_call):
            results = await llm_extract_meaning_batch(
                slides[:5], thumbnail_dir=None, max_concurrency=5
            )

        assert len(results) == 5
        for r in results:
            assert r["semantic_summary"] == "测试摘要内容"
            assert r["semantic_tags"] == ["安全", "测试"]
