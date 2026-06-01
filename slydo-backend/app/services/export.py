"""
单页导出 — 从原始 PPT 中提取单页幻灯片并返回 PPTX 文件流

核心方案：ZIP-level 操作
    1. 解析 ppt/presentation.xml 中的 sldIdLst，只保留目标页
    2. 解析目标 slide 的 XML 和 rels，找出其引用的 media 文件
    3. 只保留目标 slide 实际引用的 media，丢弃其他页的图片
    4. 重建 PPTX 文件
"""
from __future__ import annotations

import io
import logging
import uuid
from pathlib import Path
from zipfile import ZipFile

from lxml import etree

from app.database import async_session_factory
from app.models.slide import Slide
from app.models.deck import Deck

logger = logging.getLogger(__name__)

NS_PRESENTATION = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS_RELATIONSHIPS = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_RELS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_DRAWINGML = "http://schemas.openxmlformats.org/drawingml/2006/main"

SLD_TAG = f"{{{NS_PRESENTATION}}}sldId"
SLD_LST_TAG = f"{{{NS_PRESENTATION}}}sldIdLst"
RID_ATTR = f"{{{NS_RELS}}}id"
RELS_NS_VAL = "http://schemas.openxmlformats.org/package/2006/relationships"

# ═══════════════════════════════════════════════════════════
# 文件路径查找
# ═══════════════════════════════════════════════════════════


def _find_source_file(deck: Deck) -> Path:
    """
    查找原始 PPT 文件路径。
    优先使用 deck.file_path，如果文件不存在则尝试在 archive 目录中按文件名查找。
    """
    src_path = Path(deck.file_path) if deck.file_path else None

    if src_path and src_path.exists():
        return src_path

    watch_dir = Path.home() / ".slydo" / "watch"
    archive_dir = Path.home() / ".slydo" / "archive"

    def _find_in_dir(dir_path: Path, src_path: Path | None) -> Path | None:
        if not dir_path or not dir_path.exists():
            return None
        if src_path:
            exact = dir_path / src_path.name
            if exact.exists():
                return exact
            stem = src_path.stem
            title_part = stem.split("_", 1)[-1] if "_" in stem else stem
            for f in sorted(dir_path.iterdir(), reverse=True):
                if f.suffix not in (".ppt", ".pptx"):
                    continue
                if f.stem == stem:
                    return f
                if title_part and title_part in f.stem:
                    logger.info(f"[导出] 在 {dir_path.name} 模糊匹配: {f.name}")
                    return f
        return None

    found = _find_in_dir(archive_dir, src_path)
    if found:
        return found
    found = _find_in_dir(watch_dir, src_path)
    if found:
        return found

    if src_path:
        raise ValueError(f"原始文件不存在: {src_path}（已检查 archive 及 watch 目录）")
    raise ValueError(f"Deck {deck.id} 无原始文件路径，无法导出")


# ═══════════════════════════════════════════════════════════
# Media 引用分析
# ═══════════════════════════════════════════════════════════


def _get_target_media_refs(zin: ZipFile, target_rid: str) -> set[str]:
    """
    从目标 slide 的 XML 及 rels 文件中，找出其实际引用的 media 文件路径。

    步骤：
    1. 从 ppt/_rels/presentation.xml.rels 中找到 target_rid 对应的 slide 文件路径
    2. 读取该 slide 的 .xml.rels 文件，找到所有 media 引用
    3. 返回这些 media 文件的 ZIP 内路径（如 ppt/media/image1.png）
    """
    # 1. 找 target_rid 对应的 slide 文件
    rels_xml = zin.read("ppt/_rels/presentation.xml.rels")
    rels_root = etree.fromstring(rels_xml)
    slide_target = ""
    for rel_elem in rels_root.findall(f"{{{RELS_NS_VAL}}}Relationship"):
        if rel_elem.get("Id") == target_rid:
            slide_target = rel_elem.get("Target", "")
            break

    if not slide_target:
        logger.warning(f"[导出] 找不到 rid={target_rid} 对应的 slide 文件")
        return set()

    # slide_target 是相对路径如 "slides/slide2.xml"
    slide_rels_path = f"ppt/{slide_target.rsplit('.', 1)[0]}.xml.rels"

    try:
        slide_rels = zin.read(slide_rels_path)
    except KeyError:
        logger.warning(f"[导出] slide rels 文件不存在: {slide_rels_path}")
        return set()

    # 2. 解析 slide 的 rels，找出所有 media 引用
    media_refs: set[str] = set()
    slide_rels_root = etree.fromstring(slide_rels)
    for rel_elem in slide_rels_root.findall(f"{{{RELS_NS_VAL}}}Relationship"):
        target = rel_elem.get("Target", "")
        # media 文件通常以 "../media/" 开头
        if target.startswith("../media/"):
            # 转换为 ZIP 内路径
            media_path = f"ppt/{target[3:]}"  # 去掉 "../"
            media_refs.add(media_path)
        # 也处理直连 media 的情况
        elif target.startswith("media/"):
            media_refs.add(f"ppt/{target}")

    return media_refs


def _collect_keep_files(zin: ZipFile, target_rid: str, remove_rids: list[str]) -> tuple[set[str], set[str]]:
    """
    确定要保留和删除的文件集合。

    返回：(keep_files, remove_files)
    - keep_files: 必须保留的文件路径
    - remove_files: 必须删除的文件路径
    """

    # 1. 计算要删除的其他 slide 文件
    rels_xml = zin.read("ppt/_rels/presentation.xml.rels")
    rels_root = etree.fromstring(rels_xml)

    remove_files: set[str] = set()
    for rel_elem in rels_root.findall(f"{{{RELS_NS_VAL}}}Relationship"):
        rid = rel_elem.get("Id")
        if rid in remove_rids:
            target = rel_elem.get("Target", "")
            # 删除被移除的 slide XML
            remove_files.add(f"ppt/{target}")
            # 以及对应的 rels
            rels_target = target.rsplit(".", 1)[0] + ".xml.rels"
            remove_files.add(f"ppt/{rels_target}")

    # 2. 找出目标 slide 实际引用的 media
    keep_media = _get_target_media_refs(zin, target_rid)

    # 3. 所有 media 文件路径（除了目标 slide 引用的一律移除）
    all_media: set[str] = set()
    for item in zin.infolist():
        if item.filename.startswith("ppt/media/"):
            all_media.add(item.filename)

    # 不保留的 media → 加入删除列表
    for m in all_media:
        if m not in keep_media:
            remove_files.add(m)

    # 没有 keep_files 概念，用排除法：不删除的 = keep
    return set(), remove_files


# ═══════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════


async def export_single_slide(slide_id: str) -> io.BytesIO:
    """
    从原始 PPT 中提取单页幻灯片并返回 PPTX 文件流。

    参数：
        slide_id: Slide UUID

    返回：
        io.BytesIO — 单页 PPTX 文件流

    异常：
        ValueError — slide_id 不存在或对应 deck 无原始文件
    """
    # 1. 查 DB 获取 Slide + Deck
    async with async_session_factory() as session:
        from sqlalchemy import select
        from sqlalchemy.orm import joinedload

        stmt = (
            select(Slide)
            .options(joinedload(Slide.deck))
        )

        try:
            uid = uuid.UUID(slide_id)
            stmt = stmt.where(Slide.id == uid)
        except ValueError:
            stmt = stmt.where(Slide.qdrant_point_id == slide_id)

        result = await session.execute(stmt)
        slide = result.scalar_one_or_none()

    if slide is None:
        raise ValueError(f"Slide {slide_id} 不存在")

    deck: Deck = slide.deck
    src_path = _find_source_file(deck)
    slide_index = slide.slide_index

    buf = _extract_single_slide_pptx(str(src_path), slide_index)

    logger.info(
        f"[导出] Slide {slide_id} (index={slide_index}) "
        f"已导出, 大小={len(buf.getvalue())} bytes"
    )
    return buf


def _extract_single_slide_pptx(src_path: str, slide_index: int) -> io.BytesIO:
    """
    从 src_path PPT 中提取第 slide_index 页（1-indexed）为独立 PPTX。
    """
    with ZipFile(src_path, "r") as zin:
        pres_xml = zin.read("ppt/presentation.xml")
        root = etree.fromstring(pres_xml)

        sld_id_lst = root.find(SLD_LST_TAG)
        if sld_id_lst is None:
            raise ValueError("presentation.xml 中找不到 sldIdLst")

        slides = list(sld_id_lst.findall(SLD_TAG))
        total = len(slides)

        if slide_index < 1 or slide_index > total:
            raise ValueError(f"slide_index {slide_index} 超出范围 [1, {total}]")

        target_idx = slide_index - 1
        target_rid = slides[target_idx].get(RID_ATTR)

        remove_rids: list[str] = []
        for i, sld in enumerate(slides):
            if i != target_idx:
                remove_rids.append(sld.get(RID_ATTR))
                sld_id_lst.remove(sld)

        modified_pres_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

        # 更新 presentation.xml.rels：删除被移除的 slide 关系
        rels_xml = zin.read("ppt/_rels/presentation.xml.rels")
        rels_root = etree.fromstring(rels_xml)

        for rel_elem in list(rels_root.findall(f"{{{RELS_NS_VAL}}}Relationship")):
            if rel_elem.get("Id") in remove_rids:
                rels_root.remove(rel_elem)

        modified_rels_xml = etree.tostring(rels_root, xml_declaration=True, encoding="UTF-8", standalone=True)

        # 计算要删除的文件
        _, remove_files = _collect_keep_files(zin, target_rid, remove_rids)

        # 构建新的 ZIP
        buf = io.BytesIO()
        with ZipFile(buf, "w") as zout:
            for item in zin.infolist():
                if item.filename in remove_files:
                    continue
                if item.filename == "ppt/presentation.xml":
                    zout.writestr(item, modified_pres_xml)
                elif item.filename == "ppt/_rels/presentation.xml.rels":
                    zout.writestr(item, modified_rels_xml)
                else:
                    zout.writestr(item, zin.read(item.filename))

        buf.seek(0)
        return buf
