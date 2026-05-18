"""Slydo FastAPI 入口"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import check_db
from app.qdrant import check_qdrant


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print(f"[Slydo] 启动: {settings.app_name} (debug={settings.debug})")
    yield
    # 关闭时
    print("[Slydo] 关闭")


app = FastAPI(
    title=settings.app_name,
    version="0.0.1",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 中间件 ────────────────────────────────────────────────


@app.middleware("http")
async def add_process_time(request: Request, call_next):
    """请求耗时记录"""
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    response.headers["X-Process-Time"] = f"{elapsed:.3f}s"
    return response


# ─── 健康检查 ──────────────────────────────────────────────


@app.get("/health")
async def health():
    # 检查各组件连接状态
    db_status = await check_db()
    qdrant_status = await check_qdrant()
    all_ok = db_status.get("connected") and qdrant_status.get("connected")
    return {
        "status": "ok" if all_ok else "degraded",
        "app": settings.app_name,
        "version": "0.0.1",
        "timestamp": time.time(),
        "components": {
            "postgresql": db_status,
            "qdrant": qdrant_status,
        },
    }


# ─── 路由注册 ──────────────────────────────────────────────

from app.routers import version, recommend, export, deck, slide, thumbnail, monitor, usage, usage_dashboard
app.include_router(version.router)
app.include_router(recommend.router)
app.include_router(export.router)
app.include_router(export.vsto_router)  # VSTO 兼容路由
app.include_router(deck.router)
app.include_router(slide.router)
app.include_router(thumbnail.router)
app.include_router(monitor.router)  # 监控仪表盘
app.include_router(usage.router)  # 使用统计 API
app.include_router(usage_dashboard.router)  # 使用统计面板

# ─── 静态文件服务（缩略图路径） ───────────────────────────

from pathlib import Path
from fastapi.staticfiles import StaticFiles
from app.config import settings

wiki_path = Path(settings.slydo_wiki_path).expanduser() / "thumbnails"
if wiki_path.exists():
    app.mount("/api/thumbnails", StaticFiles(directory=str(wiki_path)), name="thumbnails")
