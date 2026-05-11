"""
A3 单元测试 — retry / token_counter / vision (JSON 解析)
"""
from __future__ import annotations

import json
import pytest

from app.utils.retry import retry
from app.utils.token_counter import TokenCounter, estimate_text_tokens, estimate_image_tokens
from app.utils.vision import parse_vision_response, validate_and_fill


# ═══════════════════════════════════════════════════════════
# retry 测试
# ═══════════════════════════════════════════════════════════


class TestRetry:
    """指数退避重试装饰器"""

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        """第二次尝试成功"""
        attempt_count = 0

        @retry(max_attempts=3, delay=0.01)
        async def flaky():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise ValueError("temp failure")
            return "ok"

        result = await flaky()
        assert result == "ok"
        assert attempt_count == 2

    @pytest.mark.asyncio
    async def test_retry_raises_after_all_attempts(self):
        """全部重试失败后抛出原始异常"""
        @retry(max_attempts=3, delay=0.01)
        async def always_fails():
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            await always_fails()

    @pytest.mark.asyncio
    async def test_retry_does_not_retry_on_success(self):
        """第一次成功不重试"""
        call_count = 0

        @retry(max_attempts=3, delay=0.01)
        async def works():
            nonlocal call_count
            call_count += 1
            return "ok"

        await works()
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_captures_specific_exceptions_only(self):
        """只捕获指定异常类型"""
        @retry(max_attempts=2, delay=0.01, exceptions=(ValueError,))
        async def raises_type_error():
            raise TypeError("not caught")

        with pytest.raises(TypeError):
            await raises_type_error()


# ═══════════════════════════════════════════════════════════
# token_counter 测试
# ═══════════════════════════════════════════════════════════


class TestTokenCounter:
    """Token 计数和费用估算"""

    def test_estimate_text_tokens(self):
        """中文和英文的 token 估算"""
        cn = estimate_text_tokens("联软信息安全解决方案")
        en = estimate_text_tokens("hello world this is test")
        empty = estimate_text_tokens("")
        assert cn > 0
        assert en > 0
        assert empty == 0
        # 相同长度的中文 token 数应大于英文
        cn_len = estimate_text_tokens("中" * 100)
        en_len = estimate_text_tokens("a" * 100)
        assert cn_len > en_len

    def test_estimate_image_tokens(self):
        """图片 token 估算"""
        assert estimate_image_tokens("low") == 85
        assert estimate_image_tokens("high") == 800

    def test_counter_accumulation(self):
        """计数器累加"""
        c = TokenCounter(model_name="deepseek-v4-flash")
        c.add_tokens(input_t=1500, output_t=200)
        c.add_tokens(input_t=2000, output_t=300)
        assert c.input_tokens == 3500
        assert c.output_tokens == 500
        assert c.calls == 2

    def test_counter_report(self):
        """费用报告格式正确"""
        c = TokenCounter(model_name="deepseek-v4-flash")
        c.add_tokens(input_t=1_000_000, output_t=0)
        report = c.report()
        assert report["total_tokens"] == 1_000_000
        assert report["cost_yuan"] == 0.3  # ¥0.3/1M tokens
        assert report["calls"] == 1

    def test_zero_cost_local_model(self):
        """本地模型费用为 0"""
        c = TokenCounter(model_name="qwen3-vl:8b")
        c.add_tokens(input_t=100000, output_t=50000)
        report = c.report()
        assert report["cost_yuan"] == 0.0

    def test_add_call_with_actual_tokens(self):
        """add_call 支持实际 token 数"""
        c = TokenCounter()
        c.add_call(actual_input_tokens=1500, actual_output_tokens=300)
        assert c.input_tokens == 1500
        assert c.output_tokens == 300

    def test_print_report(self):
        """打印报告无异常"""
        c = TokenCounter(model_name="deepseek-v4-flash")
        c.add_tokens(input_t=50000, output_t=10000)
        report_str = c.print_report()
        assert "Token" in report_str
        assert "DeepSeek" in report_str
        assert "60,000" in report_str  # total = 50K + 10K


# ═══════════════════════════════════════════════════════════
# JSON 解析容错测试
# ═══════════════════════════════════════════════════════════


class TestParseVisionResponse:
    """视觉模型 JSON 解析容错"""

    def test_parse_direct_json(self):
        """标准 JSON 直接解析"""
        text = '{"role": "cover", "summary": "封面页", "visual_desc": "深蓝背景", "tags": ["安全", "方案"]}'
        result = parse_vision_response(text)
        assert result["role"] == "cover"
        assert result["summary"] == "封面页"

    def test_parse_json_code_block(self):
        """```json ... ``` 包裹的 JSON"""
        text = '```json\n{"role": "argument", "summary": "核心论点", "visual_desc": "左文右图", "tags": ["金融", "技术"]}\n```'
        result = parse_vision_response(text)
        assert result["role"] == "argument"

    def test_parse_mixed_text_with_json(self):
        """JSON 前面有多余文本"""
        text = '根据分析，结果如下：{"role": "toc", "summary": "目录页", "visual_desc": "列表结构", "tags": ["目录"]}'
        result = parse_vision_response(text)
        assert result["role"] == "toc"

    def test_parse_empty_response_raises(self):
        """空响应抛出 ValueError"""
        with pytest.raises(ValueError):
            parse_vision_response("")
        with pytest.raises(ValueError):
            parse_vision_response("  \n  ")

    def test_parse_junk_response_raises(self):
        """无法解析的内容抛出 ValueError"""
        with pytest.raises(ValueError):
            parse_vision_response("完全不是 JSON 的内容啊啊啊啊啊")


class TestValidateAndFill:
    """解析结果验证与补全"""

    def test_valid_role_preserved(self):
        """有效角色保留"""
        result = validate_and_fill({"role": "cover", "summary": "a", "visual_desc": "b", "tags": ["c"]})
        assert result["role"] == "cover"

    def test_invalid_role_defaults_to_argument(self):
        """无效角色默认 argument"""
        result = validate_and_fill({"role": "unknown", "summary": "", "visual_desc": "", "tags": []})
        assert result["role"] == "argument"

    def test_chinese_role_mapped(self):
        """中文角色名映射到英文"""
        result = validate_and_fill({"role": "封面", "summary": "", "visual_desc": "", "tags": []})
        assert result["role"] == "cover"

    def test_tags_as_string_converted(self):
        """字符串类型 tags 转为列表"""
        result = validate_and_fill({
            "role": "argument", "summary": "", "visual_desc": "",
            "tags": "安全, 金融, 技术",
        })
        assert isinstance(result["tags"], list)
        assert len(result["tags"]) == 3

    def test_tags_capped_at_8(self):
        """tags 最多 8 个"""
        many_tags = [f"tag{i}" for i in range(20)]
        result = validate_and_fill({
            "role": "argument", "summary": "", "visual_desc": "",
            "tags": many_tags,
        })
        assert len(result["tags"]) <= 8

    def test_empty_fields_filled(self):
        """缺失字段填充为空字符串"""
        result = validate_and_fill({"role": "cover"})
        assert result["summary"] == ""
        assert result["visual_desc"] == ""
        assert result["tags"] == []
