"""Slides 幻灯片页面 ORM"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Slide(Base):
    __tablename__ = "slides"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    deck_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("decks.id", ondelete="CASCADE"), nullable=False
    )
    slide_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # 原始文本
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 语义含义（ETL 中由 LLM 提取）
    semantic_role: Mapped[str | None] = mapped_column(
        String, nullable=True,
        comment="角色：cover/toc/transition/argument/evidence/conclusion/appendix"
    )
    semantic_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    semantic_tags: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )

    # 视觉特征
    layout_type: Mapped[str | None] = mapped_column(String, nullable=True)
    visual_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 质量评分
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Qdrant 关联
    qdrant_point_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # 关系
    deck = relationship("Deck", back_populates="slides")
