"""Tags 分类标签 ORM"""
from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)


class SlideTag(Base):
    """幻灯片-标签关联表"""
    __tablename__ = "slide_tags"

    slide_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("slides.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
