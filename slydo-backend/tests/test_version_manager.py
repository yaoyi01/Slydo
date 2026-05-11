"""
A5 测试 — 版本管理
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.etl.version_manager import cleanup_old_versions


class TestCleanupVersions:
    """版本清理测试"""

    @pytest.mark.asyncio
    async def test_cleanup_removes_old_versions(self):
        with patch("app.services.etl.version_manager.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__.return_value = mock_session
            mock_result = MagicMock()
            mock_result.rowcount = 3
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()

            result = await cleanup_old_versions(max_versions=2)
            assert result["deleted"] == 3

    @pytest.mark.asyncio
    async def test_cleanup_without_excess(self):
        with patch("app.services.etl.version_manager.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__.return_value = mock_session
            mock_result = MagicMock()
            mock_result.rowcount = 0
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()

            result = await cleanup_old_versions(max_versions=5)
            assert result["deleted"] == 0


class TestRestoreAPI:
    """API 端点测试"""

    @pytest.mark.asyncio
    async def test_restore_endpoint_ok(self):
        from app.routers.version import api_restore_deck
        with patch("app.routers.version.restore_deck") as mock_restore:
            mock_restore.return_value = {"deck_id": "d", "restored_version": 1, "slide_count": 5}
            r = await api_restore_deck("d", target_version=1)
            assert r["status"] == "ok"

    @pytest.mark.asyncio
    async def test_restore_endpoint_not_found(self):
        from app.routers.version import api_restore_deck
        from fastapi import HTTPException
        with patch("app.routers.version.restore_deck") as mock_restore:
            mock_restore.side_effect = ValueError("Deck 不存在")
            with pytest.raises(HTTPException) as exc:
                await api_restore_deck("d", target_version=1)
            assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_cleanup_endpoint(self):
        from app.routers.version import api_cleanup_versions
        with patch("app.routers.version.cleanup_old_versions") as mock_clean:
            mock_clean.return_value = {"deleted": 2, "kept_per_deck": 2}
            r = await api_cleanup_versions(max_versions=2)
            assert r["status"] == "ok"
            assert r["data"]["deleted"] == 2
