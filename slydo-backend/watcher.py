#!/usr/bin/env python3
"""
Slydo 目录监控 — PptWatcher

自动监控指定目录中的 PPT 文件变化，触发入库/更新/清理。

两种模式：
  1. 守护进程模式 (watchdog)：实时监听文件事件
     python3 watcher.py /path/to/monitor

  2. 单次扫描模式 (poll)：手动触发全量扫描（适合 cron 定时轮询）
     python3 watcher.py /path/to/monitor --poll

用法：
    python3 watcher.py /path/to/monitor
    python3 watcher.py /path/to/monitor --poll
    python3 watcher.py /path/to/monitor --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
import time
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import async_session_factory
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watcher] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("watcher")


# ═══════════════════════════════════════════════════════════
# 文件校验
# ═══════════════════════════════════════════════════════════


PPT_EXTENSIONS = {".pptx", ".ppt"}


def is_pptx(path: Path) -> bool:
    return path.suffix.lower() in PPT_EXTENSIONS and path.exists()


def compute_checksum(path: str | Path) -> str:
    """计算文件 SHA256 checksum（流式读取，适合大文件）。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ═══════════════════════════════════════════════════════════
# 数据库查询
# ═══════════════════════════════════════════════════════════


async def find_deck_by_path(file_path: str) -> str | None:
    """根据文件路径查找数据库中已有的 deck_id。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT id::text FROM decks WHERE file_path = :path ORDER BY updated_at DESC LIMIT 1"),
            {"path": file_path},
        )
        row = result.fetchone()
        return str(row[0]) if row else None


async def find_deck_by_checksum(checksum: str) -> str | None:
    """根据 checksum 查找数据库中的 deck_id（用于去重）。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT id::text FROM decks WHERE checksum = :cs LIMIT 1"),
            {"cs": checksum},
        )
        row = result.fetchone()
        return str(row[0]) if row else None


async def delete_deck_cascade(deck_id: str) -> bool:
    """
    级联删除 deck 全部关联数据。

    清理范围：
        - slides (CASCADE → slide_tags)
        - deck_versions
        - decks
        - Qdrant points
        - LLM Wiki 文件
        - 缩略图
        - 源文件备份
    """
    from app.config import settings
    from app.qdrant import COLLECTION_NAME, get_qdrant
    from qdrant_client import models as qdrant_models

    async with async_session_factory() as session:
        # 删除 slides（CASCADE 会删 slide_tags）
        await session.execute(
            text("DELETE FROM slides WHERE deck_id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )
        # 删除版本历史
        await session.execute(
            text("DELETE FROM deck_versions WHERE deck_id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )
        # 删除 deck
        await session.execute(
            text("DELETE FROM decks WHERE id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )
        await session.commit()

    # 清理 Qdrant
    try:
        client = get_qdrant()
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qdrant_models.FilterSelector(
                filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="deck_id",
                            match=qdrant_models.MatchValue(value=deck_id),
                        )
                    ]
                )
            ),
        )
    except Exception as e:
        logger.warning(f"  [清理] Qdrant 清理失败: {e}")

    # 清理文件
    wiki_root = Path(settings.slydo_wiki_path).expanduser()
    import shutil
    for subdir in ["slides", "thumbnails"]:
        shutil.rmtree(wiki_root / subdir / f"deck_{deck_id}", ignore_errors=True)
    # 清理源文件备份
    for p in (wiki_root / "raw").glob(f"deck_{deck_id}_*.pptx"):
        p.unlink(missing_ok=True)

    logger.info(f"  [清理] 级联删除完成: deck={deck_id}")
    return True


# ═══════════════════════════════════════════════════════════
# 事件处理器
# ═══════════════════════════════════════════════════════════


async def handle_created(file_path: Path) -> None:
    """新 PPT 文件 → 增量入库。"""
    logger.info(f"  [on_created] 新文件: {file_path.name}")

    checksum = compute_checksum(file_path)
    existing = await find_deck_by_checksum(checksum)
    if existing:
        logger.info(f"  [on_created] 已存在相同内容 (deck={existing[:8]}...)，跳过")
        return

    # 调用 ETL 入库
    from etl_ingest import ingest_pptx
    pages = await ingest_pptx(str(file_path))
    if pages > 0:
        logger.info(f"  [on_created] ✅ 入库完成: {file_path.name} ({pages} 页)")
    else:
        logger.warning(f"  [on_created] ⚠️ 入库失败或跳过: {file_path.name}")


async def handle_modified(file_path: Path) -> None:
    """修改的 PPT 文件 → checksum 比对 → 更新。"""
    logger.info(f"  [on_modified] 文件变更: {file_path.name}")

    new_checksum = compute_checksum(file_path)
    deck_id = await find_deck_by_path(str(file_path))

    if not deck_id:
        logger.info(f"  [on_modified] 数据库中无记录，按新文件处理")
        await handle_created(file_path)
        return

    # 查询旧 checksum
    async with async_session_factory() as session:
        result = await session.execute(
            text("SELECT checksum FROM decks WHERE id = CAST(:deck_id AS uuid)"),
            {"deck_id": deck_id},
        )
        row = result.fetchone()
        old_checksum = row[0] if row else ""

    if old_checksum == new_checksum:
        logger.info(f"  [on_modified] checksum 相同，内容未变，跳过")
        return

    logger.info(f"  [on_modified] checksum 变化，触发更新 (deck={deck_id[:8]}...)")
    from app.services.etl.version_manager import update_deck
    result = await update_deck(deck_id=deck_id, new_pptx_path=str(file_path))
    logger.info(
        f"  [on_modified] ✅ 更新完成: {file_path.name} "
        f"(v{result['old_version']} → v{result['new_version']}, {result['slide_count']} 页)"
    )


async def handle_deleted(file_path: Path) -> None:
    """文件删除 → 级联清理全部关联数据。"""
    logger.info(f"  [on_deleted] 文件删除: {file_path.name}")

    deck_id = await find_deck_by_path(str(file_path))
    if not deck_id:
        logger.info(f"  [on_deleted] 数据库中无记录，无需清理")
        return

    success = await delete_deck_cascade(deck_id)
    if success:
        logger.info(f"  [on_deleted] ✅ 清理完成: {file_path.name}")


# ═══════════════════════════════════════════════════════════
# 单次扫描（poll 模式）
# ═══════════════════════════════════════════════════════════


async def poll_directory(monitor_dir: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """
    全量扫描目录：对每个 PPT 文件检查是否需要入库或更新。

    返回扫描统计：
        {"created": int, "updated": int, "skipped": int, "errors": int}
    """
    stats: dict[str, int] = {"created": 0, "updated": 0, "skipped": 0, "errors": 0}
    pptx_files = sorted(
        list(monitor_dir.rglob("*.pptx")) + list(monitor_dir.rglob("*.ppt"))
    )
    if not pptx_files:
        logger.info("  目录中无 PPT 文件")
        return stats

    logger.info(f"  扫描到 {len(pptx_files)} 个 PPT 文件")

    for f in pptx_files:
        try:
            if dry_run:
                logger.info(f"  [试运行] {f.name}")
                stats["skipped"] += 1
                continue

            checksum = compute_checksum(f)
            existing = await find_deck_by_checksum(checksum)
            if existing:
                stats["skipped"] += 1
                continue

            deck_id = await find_deck_by_path(str(f))
            if deck_id:
                logger.info(f"  [更新] {f.name} (已有 deck={deck_id[:8]}...)")
                from app.services.etl.version_manager import update_deck
                result = await update_deck(deck_id=deck_id, new_pptx_path=str(f))
                stats["updated"] += 1
                logger.info(f"    v{result['old_version']} → v{result['new_version']}")
            else:
                from etl_ingest import ingest_pptx
                pages = await ingest_pptx(str(f))
                if pages > 0:
                    stats["created"] += 1
                    logger.info(f"  [入库] {f.name} ({pages} 页)")
                else:
                    stats["errors"] += 1

        except Exception as e:
            logger.error(f"  [错误] {f.name}: {e}")
            stats["errors"] += 1

    return stats


# ═══════════════════════════════════════════════════════════
# 实时监控（daemon 模式）
# ═══════════════════════════════════════════════════════════


def start_watchdog(monitor_dir: Path, event_delay: float = 1.0) -> None:
    """启动 watchdog 实时监控（同步线程，内部跑 asyncio 事件循环）。"""
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class PptHandler(FileSystemEventHandler):
        def __init__(self):
            self._pending: dict[str, float] = {}
            self._last_event_time: float = 0

        def _debounce(self, src_path: str) -> bool:
            """防抖：1s 内同路径事件只触发一次。"""
            now = time.time()
            if src_path in self._pending and now - self._pending[src_path] < event_delay:
                return True
            self._pending[src_path] = now
            return False

        def on_created(self, event):
            if event.is_directory or not is_pptx(Path(event.src_path)):
                return
            if self._debounce(event.src_path):
                return
            logger.info(f"[事件] 创建: {Path(event.src_path).name}")
            asyncio.run(handle_created(Path(event.src_path)))

        def on_modified(self, event):
            if event.is_directory or not is_pptx(Path(event.src_path)):
                return
            if self._debounce(event.src_path):
                return
            logger.info(f"[事件] 修改: {Path(event.src_path).name}")
            asyncio.run(handle_modified(Path(event.src_path)))

        def on_deleted(self, event):
            if event.is_directory:
                return
            # 文件删除时 event.src_path 是最终路径，no suffix check needed
            logger.info(f"[事件] 删除: {Path(event.src_path).name}")
            asyncio.run(handle_deleted(Path(event.src_path)))

        def on_moved(self, event):
            if event.is_directory:
                return
            # 改名 = 旧路径删除 + 新路径创建
            if is_pptx(Path(event.dest_path)):
                logger.info(f"[事件] 移动/改名: {Path(event.src_path).name} → {Path(event.dest_path).name}")
                asyncio.run(handle_deleted(Path(event.src_path)))
                asyncio.run(handle_created(Path(event.dest_path)))

    event_handler = PptHandler()
    observer = Observer()
    observer.schedule(event_handler, str(monitor_dir), recursive=True)
    observer.start()
    logger.info(f"🚀 目录监控已启动: {monitor_dir}")

    try:
        while observer.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    logger.info("目录监控已停止")


# ═══════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(description="Slydo 目录监控 — PptWatcher")
    parser.add_argument("directory", help="要监控的 PPT 目录路径")
    parser.add_argument("--poll", action="store_true", help="单次扫描模式（非实时监控）")
    parser.add_argument("--dry-run", action="store_true", help="试运行（仅扫描不入库）")
    args = parser.parse_args()

    monitor_dir = Path(args.directory).resolve()
    if not monitor_dir.exists() or not monitor_dir.is_dir():
        logger.error(f"目录不存在: {monitor_dir}")
        sys.exit(1)

    if args.poll:
        logger.info(f"🔍 单次扫描: {monitor_dir}")
        stats = asyncio.run(poll_directory(monitor_dir, dry_run=args.dry_run))
        logger.info(
            f"  统计: 入库 {stats['created']}, 更新 {stats['updated']}, "
            f"跳过 {stats['skipped']}, 错误 {stats['errors']}"
        )
    else:
        if args.dry_run:
            logger.warning("--dry-run 仅支持 --poll 模式，忽略")
        logger.info(f"👀 实时监控启动: {monitor_dir}")
        start_watchdog(monitor_dir)


if __name__ == "__main__":
    main()
