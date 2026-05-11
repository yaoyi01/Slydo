"""
ETL Phase 1 集成测试 —— 真实 PPT 文件端到端处理验证
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from app.services.etl.phase1_extract import compute_checksum, extract_slides, render_slides_to_images

TEST_PPTX = Path(
    "/mnt/c/Users/kiven/Documents/LLM_wiki/知识库/raw/sources/信息防扩散解决方案.pptx"
)
HAS_REAL_PPTX = TEST_PPTX.exists()


@pytest.mark.integration
class TestE2EPhase1:
    """Phase 1 端到端集成测试——真实 PPT 入库验证"""

    def test_full_phase1_pipeline(self):
        """完整 Phase 1 流程：提取 → checksum → 渲染"""
        if not HAS_REAL_PPTX:
            pytest.skip("测试 PPT 文件不存在")
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Step 1: checksum
            checksum = compute_checksum(TEST_PPTX)
            assert len(checksum) == 32
            assert checksum.isalnum()

            # Step 2: 文本提取
            slides = extract_slides(TEST_PPTX)
            assert len(slides) > 0
            for s in slides:
                assert isinstance(s["slide_index"], int)
                assert "title" in s

            # Step 3: 渲染
            pngs = render_slides_to_images(TEST_PPTX, Path(tmpdir) / "thumbs", dpi=100)
            assert len(pngs) == len(slides), "渲染页数应与提取页数一致"
            assert Path(pngs[0]).exists()

    def test_file_size_estimation(self):
        """验证入库前的空间估算"""
        if not HAS_REAL_PPTX:
            pytest.skip("测试 PPT 文件不存在")

        file_size_kb = TEST_PPTX.stat().st_size / 1024
        assert 500 < file_size_kb < 20000, f"测试文件大小异常: {file_size_kb:.0f}KB"

        # 估算 100 个相同大小文件的入库空间
        estimated_gb = file_size_kb * 100 / 1024 / 1024  # GB (仅源文件)
        assert estimated_gb < 5, f"100 份同大小文件超过 5GB: {estimated_gb:.2f}GB"

    def test_ppt_without_text_handling(self):
        """无文本页（纯图片页）正确处理"""
        if not HAS_REAL_PPTX:
            pytest.skip("测试 PPT 文件不存在")
        slides = extract_slides(TEST_PPTX)
        pure_image_slides = [s for s in slides if s["text_length"] == 0]
        # 即使有纯图片页，渲染也应该成功
        with tempfile.TemporaryDirectory() as tmpdir:
            pngs = render_slides_to_images(TEST_PPTX, tmpdir, dpi=100)
            assert len(pngs) == len(slides)
