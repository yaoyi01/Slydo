"""
A4 单元测试 — phase3_store / phase4_embed
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from app.services.etl.phase3_store import write_to_llm_wiki


class TestWriteToLlmWiki:
    """LLM Wiki 写入测试"""

    def setup_method(self):
        self.mock_slides = [
            {
                "slide_index": 1,
                "title": "封面",
                "body_text": "封面正文",
                "notes_text": "",
                "text_length": 10,
                "semantic_role": "cover",
                "semantic_summary": "这是一个封面页",
                "visual_desc": "深蓝背景商务风",
                "semantic_tags": ["安全", "方案"],
            },
            {
                "slide_index": 2,
                "title": "目录",
                "body_text": "1. 介绍 2. 方案",
                "notes_text": "备注内容",
                "text_length": 20,
                "semantic_role": "toc",
                "semantic_summary": "目录概览",
                "visual_desc": "列表结构",
                "semantic_tags": ["目录", "导航"],
            },
        ]

    def test_writes_deck_file(self):
        """生成文档总览 Markdown"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = write_to_llm_wiki(
                deck_id="test-uuid-123",
                title="测试文档",
                slides=self.mock_slides,
                wiki_root=tmpdir,
            )

            deck_file = Path(tmpdir) / "decks" / "deck_test-uuid-123.md"
            assert deck_file.exists()
            content = deck_file.read_text(encoding="utf-8")
            assert "# 测试文档" in content
            assert "test-uuid-123" in content
            assert "封面" in content
            assert "目录" in content

    def test_writes_slide_files(self):
        """生成单页详情 Markdown"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = write_to_llm_wiki(
                deck_id="test-uuid-456",
                title="测试",
                slides=self.mock_slides,
                wiki_root=tmpdir,
            )

            slide_1 = Path(tmpdir) / "slides" / "deck_test-uuid-456" / "slide_001.md"
            slide_2 = Path(tmpdir) / "slides" / "deck_test-uuid-456" / "slide_002.md"
            assert slide_1.exists()
            assert slide_2.exists()

            c1 = slide_1.read_text(encoding="utf-8")
            assert "封面" in c1
            assert "cover" in c1
            assert "深蓝背景" in c1
            assert "安全" in c1

    def test_generates_correct_file_count(self):
        """文件数量 = 1 个 deck 总览 + N 个 slide 详情"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = write_to_llm_wiki(
                deck_id="test-count",
                title="计数测试",
                slides=self.mock_slides,
                wiki_root=tmpdir,
            )
            assert len(files) == 1 + len(self.mock_slides)

    def test_empty_slides_still_writes_deck_file(self):
        """空 slide 列表仍生成 deck 总览"""
        with tempfile.TemporaryDirectory() as tmpdir:
            files = write_to_llm_wiki(
                deck_id="empty", title="空文档", slides=[], wiki_root=tmpdir,
            )
            assert len(files) == 1
            deck_file = Path(tmpdir) / "decks" / "deck_empty.md"
            assert deck_file.exists()

    def test_missing_fields_handled(self):
        """缺失字段的 slide 不报错"""
        incomplete_slides = [
            {"slide_index": 1},
            {"slide_index": 2, "title": "有标题"},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            files = write_to_llm_wiki(
                deck_id="missing-fields", title="缺字段",
                slides=incomplete_slides, wiki_root=tmpdir,
            )
            assert len(files) == 3


class TestWriteToPostgres:
    """PostgreSQL 写入测试（mock 数据库）"""

    @pytest.mark.asyncio
    async def test_writes_deck_and_slides(self):
        """写入 decks + slides 表"""
        slides_data = [
            {"slide_index": 1, "title": "A", "body_text": "a", "notes_text": "",
             "text_length": 1, "semantic_role": "cover", "semantic_summary": "aa",
             "visual_desc": "", "semantic_tags": ["t1"], "thumbnail_path": ""},
        ]

        with patch("app.services.etl.phase3_store.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()
            mock_sf.return_value.__aenter__.return_value = mock_session

            from app.services.etl.phase3_store import write_to_postgres
            result = await write_to_postgres(
                source_path="/tmp/test.pptx",
                file_path="/tmp/test.pptx",
                checksum="abc123",
                slides=slides_data,
            )

            assert "deck_id" in result
            assert result["title"] == "test"
            assert result["slide_count"] == 1
            assert mock_session.add.call_count == 2
            mock_session.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multi_page_write(self):
        """多页写入"""
        slides = [
            {"slide_index": i, "title": f"Page{i}", "body_text": "", "notes_text": "",
             "text_length": 0, "semantic_role": "argument", "semantic_summary": "",
             "visual_desc": "", "semantic_tags": [], "thumbnail_path": ""}
            for i in range(1, 6)
        ]
        with patch("app.services.etl.phase3_store.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()
            mock_sf.return_value.__aenter__.return_value = mock_session

            from app.services.etl.phase3_store import write_to_postgres
            result = await write_to_postgres("/tmp/t.pptx", "cs", slides)
            assert result["slide_count"] == 5
            assert mock_session.add.call_count == 6

    @pytest.mark.asyncio
    async def test_quality_score_initialization(self):
        """QS 初始化"""
        with patch("app.services.etl.phase3_store.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__.return_value = mock_session

            from app.services.etl.phase3_store import init_quality_scores
            await init_quality_scores(deck_id="test-uuid", slide_count=10)

            mock_session.execute.assert_awaited_once()
            mock_session.commit.assert_awaited_once()


class TestEmbedToQdrant:
    """Qdrant 嵌入测试（mock Ollama + Qdrant）"""

    def test_build_embedding_text(self):
        """构建嵌入文本"""
        from app.services.etl.phase4_embed import build_embedding_text

        slide = {
            "title": "标题",
            "semantic_summary": "摘要",
            "visual_desc": "视觉描述",
            "semantic_tags": ["标签1", "标签2"],
        }
        text = build_embedding_text(slide)
        assert "标题: 标题" in text
        assert "摘要" in text
        assert "视觉描述" in text
        assert "标签1" in text

    def test_build_embedding_text_minimal(self):
        """最小 slide 也能构建文本"""
        from app.services.etl.phase4_embed import build_embedding_text
        text = build_embedding_text({"title": "仅标题"})
        assert "仅标题" in text

    @pytest.mark.asyncio
    async def test_embeds_and_upserts(self):
        """生成向量并 upsert 到 Qdrant"""
        mock_slides = [
            {"slide_index": 1, "title": "A", "body_text": "a", "semantic_role": "cover",
             "semantic_summary": "摘要A", "visual_desc": "描述A",
             "semantic_tags": ["tag1"], "quality_score": 0.0, "thumbnail_path": ""},
        ]

        with patch("app.services.etl.phase4_embed.embed_text",
                   return_value=[0.1] * 1024):
            with patch("app.services.etl.phase4_embed.get_qdrant") as mock_get_q:
                mock_client = MagicMock()
                mock_get_q.return_value = mock_client

                from app.services.etl.phase4_embed import embed_to_qdrant
                count = await embed_to_qdrant(deck_id="test-uuid", slides=mock_slides)
                assert count == 1
                mock_client.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_upsert(self):
        """batch_size=1 时分批 upsert"""
        slides = [
            {"slide_index": i, "title": f"P{i}", "body_text": "", "semantic_role": "argument",
             "semantic_summary": "", "visual_desc": "", "semantic_tags": [],
             "quality_score": 0.0, "thumbnail_path": ""}
            for i in range(1, 4)
        ]
        with patch("app.services.etl.phase4_embed.embed_text",
                   return_value=[0.0] * 1024):
            with patch("app.services.etl.phase4_embed.get_qdrant") as mock_get_q:
                mock_client = MagicMock()
                mock_get_q.return_value = mock_client

                from app.services.etl.phase4_embed import embed_to_qdrant
                count = await embed_to_qdrant(deck_id="d", slides=slides, batch_size=1)
                assert count == 3
                assert mock_client.upsert.call_count == 3
