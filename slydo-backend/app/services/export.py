"""
单页导出 — 从原始 PPT 中提取单页幻灯片并返回 PPTX 文件流

核心方案：ZIP-level 操作
    python-pptx 的 XML API 不稳定（part.element 不存在），
    所以直接在 ZIP 包级别修改 presentation.xml：
    1. 读取源 PPTX 的 ZIP 结构
    2. 用 lxml 修改 ppt/presentation.xml 中的 sldIdLst
    3. 从 ZIP 中移除非目标页对应的 slide*.xml 和 _rels
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

SLD_TAG = f"{{{NS_PRESENTATION}}}sldId"
SLD_LST_TAG = f"{{{NS_PRESENTATION}}}sldIdLst"
RID_ATTR = f"{{{NS_RELS}}}id"


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

        # 支持 UUID 或 Qdrant point ID
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
    if not deck.file_path:
        raise ValueError(f"Deck {deck.id} 无原始文件路径，无法导出")

    src_path = Path(deck.file_path)
    if not src_path.exists():
        raise ValueError(f"原始文件不存在: {src_path}")

    slide_index = slide.slide_index

    # 2. ZIP-level 单页提取
    buf = _extract_single_slide_pptx(str(src_path), slide_index)

    logger.info(
        f"[导出] Slide {slide_id} (index={slide_index}) "
        f"已导出, 大小={len(buf.getvalue())} bytes"
    )
    return buf


def _extract_single_slide_pptx(src_path: str, slide_index: int) -> io.BytesIO:
    """
    从 src_path PPT 中提取第 slide_index 页（1-indexed）为独立 PPTX。

    通过直接修改 PPTX 的 presentation.xml 实现：
    1. 解析 ppt/presentation.xml 中的 sldIdLst 列表
    2. 只保留目标页对应的 sldId 元素
    3. 从 ZIP 中移除其他 slide*.xml 及其 rels 文件
    4. 写入新的 ZIP
    """
    with ZipFile(src_path, "r") as zin:
        # 读 presentation.xml
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

        # 收集要删除的 rid 列表
        remove_rids: list[str] = []
        for i, sld in enumerate(slides):
            if i != target_idx:
                remove_rids.append(sld.get(RID_ATTR))
                sld_id_lst.remove(sld)

        # 保存修改后的 presentation.xml
        modified_pres_xml = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

        # 读关系文件以确定每个 rid 指向哪个文件
        rels_xml = zin.read("ppt/_rels/presentation.xml.rels")
        rels_root = etree.fromstring(rels_xml)
        RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

        remove_targets: set[str] = set()
        for rel_elem in rels_root.findall(f"{{{RELS_NS}}}Relationship"):
            rid = rel_elem.get("Id")
            if rid in remove_rids:
                target = rel_elem.get("Target", "")
                # target 是相对路径，如 "slides/slide2.xml"
                remove_targets.add(f"ppt/{target}")
                # 对应的 rels 文件
                rels_target = target.rsplit(".", 1)[0] + ".xml.rels"
                remove_targets.add(f"ppt/{rels_target}")
                # 从 rels 中删除
                rels_root.remove(rel_elem)

        modified_rels_xml = etree.tostring(rels_root, xml_declaration=True, encoding="UTF-8", standalone=True)

        # 3. 构建新的 ZIP
        buf = io.BytesIO()
        with ZipFile(buf, "w") as zout:
            for item in zin.infolist():
                # 跳过要删除的文件
                if item.filename in remove_targets:
                    continue
                # 替换修改过的 XML
                if item.filename == "ppt/presentation.xml":
                    zout.writestr(item, modified_pres_xml)
                elif item.filename == "ppt/_rels/presentation.xml.rels":
                    zout.writestr(item, modified_rels_xml)
                else:
                    zout.writestr(item, zin.read(item.filename))

        buf.seek(0)
        return buf
