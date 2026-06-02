"""API 路由 — 文件上传与入库触发"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy import text

from app.routers.auth import get_current_user
from app.models.user import User
from app.config import settings
from app.database import async_session_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["文件上传"], dependencies=[Depends(get_current_user)])

# ── 并发控制 ─────────────────────────────────────────
INGEST_SEMAPHORE_MAX = getattr(settings, 'ingest_concurrency', 2)
_ingest_semaphore = asyncio.Semaphore(INGEST_SEMAPHORE_MAX)

# 监控目录
WATCH_DIR = Path.home() / ".slydo" / "watch"


# ═══════════════════════════════════════════════════════
# 数据库操作（upload_tasks 表）
# ═══════════════════════════════════════════════════════

_UPLOAD_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS upload_tasks (
    id SERIAL PRIMARY KEY,
    task_id TEXT UNIQUE NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'uploading',  -- uploading / uploaded / ingesting / success / failed
    progress_pct INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT '',
    error TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP
)
"""

async def _ensure_upload_tasks_table():
    """确保 upload_tasks 表存在"""
    async with async_session_factory() as session:
        await session.execute(text(_UPLOAD_TASKS_TABLE))
        await session.commit()


async def _create_task(task_id: str, filename: str):
    """创建入库任务记录"""
    await _ensure_upload_tasks_table()
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO upload_tasks (task_id, filename, original_name, status, progress_pct, detail) "
                 "VALUES (:tid, :fn, :oname, 'uploading', 0, '上传中...')"),
            {"tid": task_id, "fn": filename, "oname": filename},
        )
        await session.commit()


async def _update_task(task_id: str, **kwargs):
    """更新任务字段"""
    if not kwargs:
        return
    sets = ", ".join(f"{k} = :{k}" for k in kwargs)
    async with async_session_factory() as session:
        await session.execute(
            text(f"UPDATE upload_tasks SET {sets} WHERE task_id = :tid"),
            {"tid": task_id, **kwargs},
        )
        await session.commit()


async def _update_task_detail(task_id: str, detail: str):
    """只更新 detail 字段（轻量更新，入库进度回调用）"""
    try:
        async with async_session_factory() as session:
            await session.execute(
                text("UPDATE upload_tasks SET detail = :d WHERE task_id = :tid AND status = 'ingesting'"),
                {"tid": task_id, "d": detail},
            )
            await session.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════
# 上传
# ═══════════════════════════════════════════════════════

@router.post("/upload")
async def upload_pptx(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传 PPT/PPTX 文件并触发入库"""
    if not file.filename or not file.filename.lower().endswith((".ppt", ".pptx")):
        raise HTTPException(status_code=400, detail="仅支持 PPT/PPTX 文件")

    return await _do_upload(file)


async def _do_upload(file: UploadFile) -> dict:
    WATCH_DIR.mkdir(parents=True, exist_ok=True)

    dest_path = WATCH_DIR / file.filename

    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        dest_path = WATCH_DIR / f"{stem}_{int(time.time())}{suffix}"

    try:
        content = await file.read()
        max_size = 100 * 1024 * 1024
        if len(content) > max_size:
            raise HTTPException(status_code=413, detail="文件过大，最大支持 100MB")

        # SHA256 去重
        file_hash = hashlib.sha256(content).hexdigest()
        async with async_session_factory() as session:
            row = await session.execute(
                text("SELECT id, title FROM decks WHERE checksum = :cs LIMIT 1"),
                {"cs": file_hash},
            )
            existing = row.fetchone()
        if existing:
            return {
                "status": "skipped",
                "detail": f"文件 {file.filename} 与已入库的「{existing[1]}」内容完全一致（相同 SHA256），已跳过",
                "data": {"duplicate": True, "existing_deck_id": str(existing[0])},
            }

        # 创建任务记录（写入 DB）
        task_id = f"task_{int(time.time() * 1000)}"
        await _create_task(task_id, file.filename)

        with open(dest_path, "wb") as f:
            f.write(content)

        # 更新为已上传
        await _update_task(task_id, status="uploaded", progress_pct=100, detail="文件已上传，触发入库...")

        # 重命名为安全文件名
        safe_name = f"{int(time.time())}_{dest_path.stem[:20]}.pptx"
        safe_path = dest_path.parent / safe_name
        if safe_path != dest_path:
            dest_path.rename(safe_path)
            dest_path = safe_path
            logger.info(f"文件已重命名为: {safe_path.name}")

        # 触发入库
        asyncio.create_task(_run_ingest_with_semaphore(dest_path, task_id))

        return {
            "status": "ok",
            "detail": f"文件 {file.filename} 已上传，入库任务已触发",
            "data": {
                "task_id": task_id,
                "filename": dest_path.name,
                "path": str(dest_path),
                "size": len(content),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


# ═══════════════════════════════════════════════════════
# 任务列表
# ═══════════════════════════════════════════════════════

@router.get("/tasks")
async def list_tasks(current_user: User = Depends(get_current_user)):
    """列出所有入库任务的实时状态（从 DB 读取，支持跨页面）"""
    try:
        async with async_session_factory() as session:
            rows = await session.execute(
                text("SELECT task_id, filename, original_name, status, progress_pct, "
                     "detail, error, created_at, finished_at "
                     "FROM upload_tasks ORDER BY created_at DESC LIMIT 200")
            )
            tasks = []
            for row in rows:
                tasks.append({
                    "task_id": row[0],
                    "filename": row[1],
                    "original_name": row[2],
                    "status": row[3],
                    "progress_pct": row[4],
                    "detail": row[5],
                    "error": row[6],
                    "created_at": row[7].isoformat() if row[7] else None,
                    "finished_at": row[8].isoformat() if row[8] else None,
                })
            return {"status": "ok", "tasks": tasks}
    except Exception as e:
        logger.warning(f"查询 upload_tasks 失败（可能表还未创建）: {e}")
        return {"status": "ok", "tasks": []}


# ═══════════════════════════════════════════════════════
# watch 目录文件管理
# ═══════════════════════════════════════════════════════

@router.get("/files")
async def list_watch_files(current_user: User = Depends(get_current_user)):
    """列出监控目录中的文件"""
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for f in sorted(WATCH_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".ppt", ".pptx"):
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
            })
    return {"status": "ok", "files": files}


@router.delete("/files")
async def delete_watch_file(
    name: str,
    current_user: User = Depends(get_current_user),
):
    """删除监控目录中的文件"""
    file_path = WATCH_DIR / name
    if not file_path.exists() or not file_path.parent.samefile(WATCH_DIR):
        raise HTTPException(status_code=404, detail="文件不存在")
    file_path.unlink()
    return {"status": "ok", "detail": f"已删除: {name}"}


# ═══════════════════════════════════════════════════════
# 入库执行
# ═══════════════════════════════════════════════════════

async def _run_ingest_with_semaphore(file_path: Path, task_id: str):
    async with _ingest_semaphore:
        await _run_ingest(file_path, task_id)


async def _run_ingest(file_path: Path, task_id: str):
    """后台执行入库，通过 DB 更新任务状态"""

    def make_detail_updater(tid: str):
        """返回一个闭包函数，用于更新入库进度"""
        async def _cb(msg: str):
            await _update_task_detail(tid, msg)
        return _cb

    try:
        # 更新为入库中
        active = INGEST_SEMAPHORE_MAX - _ingest_semaphore._value
        wait_msg = (
            f"⏳ 等待其他入库任务完成...（{active-1} 个文件正在处理）"
            if active > 1
            else "⏳ 等待其他入库任务完成..."
        )
        await _update_task(task_id, status="ingesting", progress_pct=100, detail=wait_msg)

        from watcher import handle_created

        # 注入进度回调
        detail_cb = make_detail_updater(task_id)
        import watcher as watcher_module
        import etl_ingest as etl_module
        watcher_module._progress_callback = detail_cb
        etl_module._progress_callback = detail_cb

        import app.services.etl.phase1_extract as p1
        import app.services.etl.phase2_vision as p2
        import app.services.etl.phase3_store as p3
        import app.services.etl.phase4_embed as p4
        for mod in [p1, p2, p3, p4]:
            mod._progress_callback = detail_cb

        logger.info(f"[ingest] 开始入库: {file_path.name} (task={task_id})")
        await handle_created(file_path)
        logger.info(f"[ingest] 入库完成: {file_path.name}")

        # 移动源文件到 archive
        archive_dir = file_path.parent.parent / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = archive_dir / file_path.name
        if file_path.exists():
            if archive_path.exists():
                stem = archive_path.stem
                archive_path = archive_dir / f"{stem}_{int(time.time())}{file_path.suffix}"
            file_path.rename(archive_path)
            logger.info(f"[ingest] 源文件已移至 archive: {archive_path}")
            try:
                async with async_session_factory() as session:
                    await session.execute(
                        text("UPDATE decks SET file_path = :new_path WHERE file_path = :old_path"),
                        {"new_path": str(archive_path), "old_path": str(file_path)},
                    )
                    await session.commit()
                logger.info(f"[ingest] DB file_path 已更新为: {archive_path}")
            except Exception as e:
                logger.warning(f"[ingest] 更新 DB file_path 失败: {e}")

        # 更新为成功
        await _update_task(task_id, status="success", progress_pct=100,
                           detail="✅ 入库完成", finished_at="NOW()")

    except Exception as e:
        logger.error(f"[ingest] 入库异常: {e}", exc_info=True)
        await _update_task(task_id, status="failed", progress_pct=100,
                           detail="❌ 入库失败", error=str(e), finished_at="NOW()")
