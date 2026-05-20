"""API 路由 — 文件上传与入库触发"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.routers.auth import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["文件上传"], dependencies=[Depends(get_current_user)])

# ── 并发控制 ─────────────────────────────────────────
# 上传信号量：限制同时处理的文件上传数（含去重查询+写盘）
# 避免多文件并行上传时压满磁盘 IO
UPLOAD_SEMAPHORE_MAX = 2  # 同时最多处理 2 个文件的上传
_upload_semaphore = asyncio.Semaphore(UPLOAD_SEMAPHORE_MAX)

# 入库队列 + worker：替代直接 create_task，让入库任务排队串行执行
# 队列中的任务会逐个执行，避免多个 LibreOffice 实例同时读盘
_ingest_queue: asyncio.Queue[tuple[Path, str]] = asyncio.Queue()
_ingest_queue_worker_running = False

# 监控目录（watcher 监听的目标）
WATCH_DIR = Path.home() / ".slydo" / "watch"

# ── 入库任务状态追踪（内存） ─────────────────────────
# 结构: { task_id: { filename, status, progress_pct, detail, error } }
# status: uploading -> uploaded -> ingesting -> success / failed
# 上传完成后 60 秒自动清理已完成/失败的任务
ingest_tasks: dict[str, dict] = {}
_cleanup_task: asyncio.Task | None = None

TASK_CLEANUP_DELAY = 60  # 完成后 60 秒自动删除


async def _ingest_queue_worker():
    """入库队列工作线程：逐个取出队列中的文件执行入库"""
    global _ingest_queue_worker_running
    _ingest_queue_worker_running = True
    logger.info("[ingest_queue] 入库队列 worker 已启动")
    try:
        while True:
            file_path, task_id = await _ingest_queue.get()
            try:
                await _run_ingest(file_path, task_id)
            except Exception as e:
                logger.error(f"[ingest_queue] 入库异常: {e}", exc_info=True)
                task = ingest_tasks.get(task_id)
                if task:
                    task["status"] = "failed"
                    task["detail"] = f"❌ 入库失败"
                    task["error"] = str(e)
                    task["_finished_at"] = time.time()
            finally:
                _ingest_queue.task_done()
    except asyncio.CancelledError:
        logger.info("[ingest_queue] worker 已停止")
    finally:
        _ingest_queue_worker_running = False


def _cleanup_finished_tasks():
    """清理已完成的任务（延迟 60 秒）"""
    global _cleanup_task

    async def _do_cleanup():
        await asyncio.sleep(TASK_CLEANUP_DELAY)
        now = time.time()
        to_remove = []
        for tid, t in ingest_tasks.items():
            if t["status"] in ("success", "failed") and now - t.get("_finished_at", now) >= 1:
                to_remove.append(tid)
        for tid in to_remove:
            ingest_tasks.pop(tid, None)
        logger.info(f"[ingest_tasks] 清理了 {len(to_remove)} 个已完成任务")

    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_do_cleanup())


def _make_task_id() -> str:
    return f"task_{int(time.time() * 1000)}_{len(ingest_tasks)}"


@router.post("/upload")
async def upload_pptx(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传 PPT/PPTX 文件并触发入库"""
    # 验证文件类型
    if not file.filename or not file.filename.lower().endswith((".ppt", ".pptx")):
        raise HTTPException(status_code=400, detail="仅支持 PPT/PPTX 文件")

    # 获取信号量：限制并发上传数，避免多文件同时写盘压满 IO
    # 超过限制时阻塞等待，前端会看到上传进度卡住
    acquired = await asyncio.wait_for(_upload_semaphore.acquire(), timeout=300)
    try:
        return await _do_upload(file)
    finally:
        _upload_semaphore.release()


async def _do_upload(file: UploadFile) -> dict:
    """实际执行上传的核心逻辑（受信号量保护）"""
    # 确保监控目录存在
    WATCH_DIR.mkdir(parents=True, exist_ok=True)

    # 写入文件到监控目录
    dest_path = WATCH_DIR / file.filename

    # 如果同名文件已存在，添加时间戳避免覆盖
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        dest_path = WATCH_DIR / f"{stem}_{int(time.time())}{suffix}"

    try:
        content = await file.read()
        max_size = 100 * 1024 * 1024  # 100MB
        if len(content) > max_size:
            raise HTTPException(status_code=413, detail="文件过大，最大支持 100MB")

        # 计算 SHA256 去重
        file_hash = hashlib.sha256(content).hexdigest()
        from app.database import async_session_factory
        from sqlalchemy import text
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

        # 创建任务记录
        task_id = _make_task_id()
        ingest_tasks[task_id] = {
            "task_id": task_id,
            "filename": file.filename,
            "status": "uploading",
            "progress_pct": 0,
            "detail": "上传中...",
            "error": None,
            "_finished_at": None,
        }

        with open(dest_path, "wb") as f:
            f.write(content)

        # 更新任务状态
        ingest_tasks[task_id].update({
            "status": "uploaded",
            "progress_pct": 100,
            "detail": f"文件已上传，触发入库...",
        })

        # 重命名文件为安全的英文名（避免 LibreOffice 中文路径问题）
        safe_name = f"{int(time.time())}_{dest_path.stem[:20]}.pptx"
        safe_path = dest_path.parent / safe_name
        if safe_path != dest_path:
            dest_path.rename(safe_path)
            dest_path = safe_path
            logger.info(f"文件已重命名为: {safe_path.name}")

        # 确保队列 worker 正在运行
        global _ingest_queue_worker_running
        if not _ingest_queue_worker_running:
            asyncio.create_task(_ingest_queue_worker())

        # 将入库任务提交到队列（串行执行）
        await _ingest_queue.put((dest_path, task_id))

        return {
            "status": "ok",
            "detail": f"文件 {file.filename} 已上传，入库任务已入队（队列位置 #{_ingest_queue.qsize()}）",
            "data": {
                "task_id": task_id,
                "filename": dest_path.name,
                "path": str(dest_path),
                "size": len(content),
            },
        }
    except HTTPException:
        raise
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="服务器繁忙，请稍后重试")
    except Exception as e:
        logger.error(f"上传失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.get("/tasks")
async def list_tasks(current_user: User = Depends(get_current_user)):
    """列出所有入库任务的实时状态"""
    tasks = []
    for t in ingest_tasks.values():
        tasks.append({
            "task_id": t["task_id"],
            "filename": t["filename"],
            "status": t["status"],
            "progress_pct": t.get("progress_pct", 0),
            "detail": t.get("detail", ""),
            "error": t.get("error"),
        })
    # 按创建时间倒序
    tasks.reverse()
    return {"status": "ok", "tasks": tasks}


@router.get("/files")
async def list_watch_files(current_user: User = Depends(get_current_user)):
    """列出监控目录中的文件（仅返回待入库的文件）"""
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


async def _run_ingest(file_path: Path, task_id: str):
    """后台执行入库，更新任务状态"""
    task = ingest_tasks.get(task_id)
    if not task:
        return

    def _update_detail(detail: str):
        """更新任务详情（供入库流程回调）"""
        t = ingest_tasks.get(task_id)
        if t and t["status"] == "ingesting":
            t["detail"] = detail

    try:
        # 更新状态为入库中
        task["status"] = "ingesting"
        task["progress_pct"] = 100
        task["detail"] = "⏳ 等待其他入库任务完成...（串行处理）"

        from watcher import handle_created
        
        # 在 watcher 模块和 etl_ingest 模块中注入回调，让入库可以回写进度
        import watcher as watcher_module
        import etl_ingest as etl_module
        watcher_module._progress_callback = _update_detail
        etl_module._progress_callback = _update_detail
        
        # 同时也注入到 etl_ingest.ingest_pptx 函数的全局命名空间
        import app.services.etl.phase1_extract as p1
        import app.services.etl.phase2_vision as p2
        import app.services.etl.phase3_store as p3
        import app.services.etl.phase4_embed as p4
        for mod in [p1, p2, p3, p4]:
            mod._progress_callback = _update_detail

        logger.info(f"[ingest_tasks] 开始入库: {file_path.name} (task={task_id})")
        await handle_created(file_path)
        logger.info(f"[ingest_tasks] 入库完成: {file_path.name}")

        # 入库成功 → 从监控目录删除源文件
        if file_path.exists():
            file_path.unlink()
            logger.info(f"[ingest_tasks] 源文件已删除: {file_path.name}")

        # 更新任务状态为成功
        task["status"] = "success"
        task["progress_pct"] = 100
        task["detail"] = "✅ 入库完成"
        task["_finished_at"] = time.time()

    except Exception as e:
        logger.error(f"[ingest_tasks] 入库异常: {e}", exc_info=True)
        task["status"] = "failed"
        task["progress_pct"] = 100
        task["detail"] = f"❌ 入库失败"
        task["error"] = str(e)
        task["_finished_at"] = time.time()

    # 触发延迟清理
    _cleanup_finished_tasks()
