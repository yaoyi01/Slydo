"""
API 集成测试 — uvicorn 进程 + httpx 客户端

用 httpx.AsyncClient 连接本地 uvicorn 进程，避免 TestClient + asyncpg 的 loop 冲突。

前置条件：
    运行 start_server.sh 或手动启动 uvicorn 在端口 8011。

运行方式：
    终端1: python3 -m uvicorn app.main:app --port 8011
    终端2: python3 -m pytest tests/test_api_integration.py -v
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import httpx

# uvicorn 端口
TEST_PORT = int(os.environ.get("TEST_PORT", "18011"))
BASE_URL = f"http://localhost:{TEST_PORT}"

# 是否自动启动/停止 uvicorn（默认不启动）
AUTO_START = os.environ.get("AUTO_START_SERVER", "0") == "1"


@pytest.fixture(scope="session")
def server():
    """启动 uvicorn 测试服务器（仅一次）"""
    if not AUTO_START:
        # 手动启动模式：快速检查连接
        try:
            import urllib.request
            urllib.request.urlopen(f"{BASE_URL}/health", timeout=2)
            yield None
            return
        except Exception:
            yield None
            return

    # 自动启动模式
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "127.0.0.1",
        "--port", str(TEST_PORT),
        "--log-level", "error",
    ]
    proc = subprocess.Popen(
        cmd,
        cwd=Path(__file__).parent.parent,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # 等待启动
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(f"{BASE_URL}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.5)
    yield None
    proc.terminate()
    proc.wait()


@pytest.fixture
async def client():
    """httpx 异步客户端"""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as ac:
        yield ac


# ─── 健康检查 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")


# ─── Deck API ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_decks(client):
    resp = await client.get("/api/decks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "count" in data
    assert "items" in data


@pytest.mark.asyncio
async def test_list_decks_with_limit(client):
    resp = await client.get("/api/decks", params={"limit": 5})
    assert resp.status_code == 200
    assert len(resp.json()["items"]) <= 5


@pytest.mark.asyncio
async def test_get_deck_invalid_uuid(client):
    resp = await client.get("/api/decks/not-a-uuid")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_get_deck_not_found(client):
    resp = await client.get("/api/decks/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_deck_with_slides(client):
    """先查列表拿到第一个 deck_id，再查详情含 slides"""
    list_resp = await client.get("/api/decks", params={"limit": 1})
    items = list_resp.json().get("items", [])
    if not items:
        pytest.skip("无 Deck 数据")

    deck_id = items[0]["id"]
    resp = await client.get(f"/api/decks/{deck_id}", params={"include_slides": True})
    assert resp.status_code == 200
    data = resp.json()
    assert "slides" in data["data"]
    assert data["data"]["id"] == deck_id
    assert "title" in data["data"]


# ─── Slide API ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_slide_invalid_uuid(client):
    """非UUID格式的 slide_id → 按 qdrant_point_id 查询 → 404"""
    resp = await client.get("/api/slides/not-a-uuid")
    assert resp.status_code == 404  # qdrant_point_id 查询也找不到


@pytest.mark.asyncio
async def test_get_slide_not_found(client):
    resp = await client.get("/api/slides/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_slide_existing(client):
    """先查推荐拿到一个 slide_id"""
    resp = await client.get("/api/recommend", params={"keywords": "水印"})
    if resp.status_code != 200:
        pytest.skip("推荐 API 异常")

    results = resp.json().get("results", [])
    if not results:
        pytest.skip("推荐结果为空，无 Slide 数据")

    slide_id = results[0]["slide_id"]
    resp = await client.get(f"/api/slides/{slide_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["id"] == slide_id
    assert "deck_title" in data["data"]


# ─── Export API ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_not_found(client):
    resp = await client.get("/api/slides/00000000-0000-0000-0000-000000000000/export")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_existing(client):
    """先推荐拿到 slide_id，再导出"""
    resp = await client.get("/api/recommend", params={"keywords": "水印"})
    if resp.status_code != 200:
        pytest.skip("推荐 API 异常")

    results = resp.json().get("results", [])
    if not results:
        pytest.skip("推荐结果为空")

    slide_id = results[0]["slide_id"]
    resp = await client.get(f"/api/slides/{slide_id}/export")
    assert resp.status_code == 200
    assert len(resp.content) > 1000


# ─── Recommend API ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_recommend_no_params(client):
    resp = await client.get("/api/recommend")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_recommend_with_keywords(client):
    resp = await client.get("/api/recommend", params={"keywords": "水印"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_recommend_with_title(client):
    resp = await client.get("/api/recommend", params={"title": "水印技术"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 0
    if data["count"] > 0:
        assert "slide_id" in data["results"][0]
        assert "reason" in data["results"][0]


# ─── Version API ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_versions(client):
    resp = await client.post("/api/decks/cleanup-versions", params={"max_versions": 2})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_restore_not_found(client):
    resp = await client.post("/api/decks/00000000-0000-0000-0000-000000000000/restore")
    assert resp.status_code == 404


# ─── Search API（通过 recommend + q 参数实现）──────────────────


@pytest.mark.asyncio
async def test_search_no_query(client):
    """无查询条件的搜索走 recommend api，返回空结果"""
    resp = await client.get("/api/recommend")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_search_with_keywords(client):
    resp = await client.get("/api/recommend", params={"q": "水印"})
    assert resp.status_code == 200
    data = resp.json()
    assert "results" in data


# ─── Outline Recommend API ────────────────────────────────────────


@pytest.mark.asyncio
async def test_outline_recommend(client):
    resp = await client.get("/api/recommend/outline")
    assert resp.status_code == 200
    data = resp.json()
    assert "directions" in data
    assert len(data["directions"]) > 0


@pytest.mark.asyncio
async def test_outline_recommend_with_titles(client):
    resp = await client.get(
        "/api/recommend/outline",
        params={"titles": "行业背景,业务痛点,需求分析,解决方案概述", "top_k": 2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["directions"]) <= 2
    for d in data["directions"]:
        assert "direction" in d
        assert "slides" in d


# ─── Monitor / Health API ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_monitor_stats(client):
    resp = await client.get("/api/monitor/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "deck_count" in data["data"]
    assert "slide_count" in data["data"]


@pytest.mark.asyncio
async def test_monitor_health(client):
    resp = await client.get("/api/monitor/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "components" in data


# ─── Dashboard ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_html(client):
    resp = await client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
