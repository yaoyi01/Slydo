"""API 路由 — 文件上传与入库触发"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status

from app.routers.auth import get_current_user
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ingest", tags=["文件上传"], dependencies=[Depends(get_current_user)])

# 监控目录（watcher 监听的目标）
WATCH_DIR = Path.home() / ".slydo" / "watch"


@router.post("/upload")
async def upload_pptx(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """上传 PPT/PPTX 文件并触发入库"""
    # 验证文件类型
    if not file.filename or not file.filename.lower().endswith((".ppt", ".pptx")):
        raise HTTPException(status_code=400, detail="仅支持 PPT/PPTX 文件")

    # 确保监控目录存在
    WATCH_DIR.mkdir(parents=True, exist_ok=True)

    # 写入文件到监控目录
    dest_path = WATCH_DIR / file.filename

    # 如果同名文件已存在，添加时间戳避免覆盖
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        import time
        dest_path = WATCH_DIR / f"{stem}_{int(time.time())}{suffix}"

    try:
        content = await file.read()
        max_size = 100 * 1024 * 1024  # 100MB
        if len(content) > max_size:
            raise HTTPException(status_code=413, detail="文件过大，最大支持 100MB")

        with open(dest_path, "wb") as f:
            f.write(content)

        # 触发入库（后台异步执行）
        asyncio.create_task(_run_ingest(dest_path))

        return {
            "status": "ok",
            "detail": f"文件 {file.filename} 已上传，入库任务已触发",
            "data": {
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
                "status": "待入库",
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


async def _run_ingest(file_path: Path):
    """后台执行入库（直接调用 watcher 的 handle_created）"""
    try:
        from watcher import handle_created
        logger.info(f"开始入库: {file_path.name}")
        await handle_created(file_path)
        logger.info(f"入库完成: {file_path.name}")
    except Exception as e:
        logger.error(f"入库异常: {e}", exc_info=True)
