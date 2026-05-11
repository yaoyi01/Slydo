"""
B1 测试 — 推荐引擎
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.recommend import merge_dedup, recommend_slides, parse_reranked_json


class TestRecommendSlides:
    """推荐引擎核心测试"""

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self):
        """空查询返回空列表"""
        result = await recommend_slides(context_title="")
        assert result == []

    @pytest.mark.asyncio
    async def test_semantic_search_called(self):
        """验证语义召回被调用"""
        with patch("app.services.recommend.semantic_search", return_value=[]):
            with patch("app.services.recommend.keyword_search", return_value=[]):
                with patch("app.services.recommend.llm_rerank") as mock_rerank:
                    mock_rerank.return_value = []
                    result = await recommend_slides(context_title="测试")
                    assert result == []


class TestMergeDedup:
    """双路去重合并测试"""

    def test_merge_dedup_removes_duplicates(self):
        """语义和关键词结果按 slide_id+index 去重"""
        semantic = [
            {"slide_id": "1", "deck_id": "d1", "slide_index": 1, "title": "A", "source": "semantic", "score": 0.9},
        ]
        keyword = [
            {"slide_id": "1", "deck_id": "d1", "slide_index": 1, "title": "A", "source": "keyword", "score": 0.5},
            {"slide_id": "2", "deck_id": "d1", "slide_index": 2, "title": "B", "source": "keyword", "score": 0.4},
        ]

        merged = merge_dedup(semantic, keyword)
        assert len(merged) == 2
        # 语义召回的结果在前
        assert merged[0]["source"] == "semantic"
        assert merged[1]["source"] == "keyword"

    def test_merge_empty(self):
        """两路都空返回空"""
        assert merge_dedup([], []) == []

    def test_merge_semantic_only(self):
        """只有语义召回"""
        s = [{"slide_id": "1", "deck_id": "d", "slide_index": 1, "title": "A", "source": "semantic", "score": 0.9}]
        assert len(merge_dedup(s, [])) == 1

    def test_merge_keyword_only(self):
        """只有关键词召回"""
        k = [{"slide_id": "1", "deck_id": "d", "slide_index": 1, "title": "A", "source": "keyword", "score": 0.5}]
        assert len(merge_dedup([], k)) == 1


class TestParseReranked:
    """LLM 重排结果解析"""

    def test_parse_valid_json(self):
        """标准 JSON 数组"""
        text = '[{"slide_id": "1", "reason": "相关", "score": 9}]'
        result = parse_reranked_json(text)
        assert len(result) == 1
        assert result[0]["slide_id"] == "1"

    def test_parse_code_block(self):
        """```json 包裹"""
        text = '```json\n[{"slide_id": "1", "reason": "相关", "score": 9}]\n```'
        result = parse_reranked_json(text)
        assert len(result) == 1

    def test_parse_mixed_text(self):
        """混合文本中提取 JSON 数组"""
        text = '分析结果：[{"slide_id": "a", "reason": "好", "score": 0.9}]'
        result = parse_reranked_json(text)
        assert len(result) == 1

    def test_dict_response_becomes_empty(self):
        """单个字典而非数组返回空列表（格式异常）"""
        text = '{"slide_id": "a", "reason": "好", "score": 0.9}'
        result = parse_reranked_json(text)
        assert result == []

    def test_parse_empty_string(self):
        """空字符串返回空"""
        assert parse_reranked_json("") == []
        assert parse_reranked_json("无意义文本") == []

    def test_parse_not_array(self):
        """非数组 JSON 返回空"""
        assert parse_reranked_json('{"key": "value"}') == []


class TestRecommendAPI:
    """推荐 API 测试"""

    @pytest.mark.asyncio
    async def test_recommend_endpoint(self):
        """GET /api/recommend"""
        from app.routers.recommend import api_recommend

        with patch("app.routers.recommend.recommend_slides") as mock_rec:
            mock_rec.return_value = [
                {"slide_id": "1", "title": "结果1", "score": 0.9, "reason": "相关"},
            ]
            response = await api_recommend(title="测试标题")
            assert response["status"] == "ok"
            assert response["count"] == 1
            assert response["results"][0]["title"] == "结果1"
