from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class TrackRecord(Base):
    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True
    )
    title: Mapped[str] = mapped_column(String(500))
    artist: Mapped[str] = mapped_column(String(500))
    genres_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    local_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    interactions: Mapped[list["InteractionRecord"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
    )


class InteractionRecord(Base):
    __tablename__ = "interactions"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )
    user_id: Mapped[str] = mapped_column(String(64))
    track_id: Mapped[str] = mapped_column(
        ForeignKey(
            "tracks.id",
            ondelete="CASCADE",
        )
    )
    interaction_type: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    track: Mapped[TrackRecord] = relationship(
        back_populates="interactions"
    )
