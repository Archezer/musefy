from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    display_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    interactions: Mapped[list["InteractionRecord"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class TrackRecord(Base):
    __tablename__ = "tracks"

    __table_args__ = (
        Index(
            "uq_tracks_source_source_id",
            "source",
            "source_id",
            unique=True,
        ),
    )

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
    detected_genres_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
    )
    track_embedding_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
    )
    mood_valence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    mood_arousal: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    source: Mapped[str] = mapped_column(String(100))
    source_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    source_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    local_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    cover_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    interactions: Mapped[list["InteractionRecord"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
    )

    playlist_entries: Mapped[list["PlaylistEntryRecord"]] = relationship(
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
    user_id: Mapped[str] = mapped_column(
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        )
    )
    track_id: Mapped[str] = mapped_column(
        ForeignKey(
            "tracks.id",
            ondelete="CASCADE",
        )
    )
    interaction_type: Mapped[str] = mapped_column(String(20))
    mood_context: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    track: Mapped[TrackRecord] = relationship(
        back_populates="interactions"
    )
    user: Mapped[UserRecord] = relationship(
        back_populates="interactions"
    )


class PlaylistRecord(Base):
    __tablename__ = "playlists"

    id: Mapped[str] = mapped_column(
        String(64),
        primary_key=True,
    )
    name: Mapped[str] = mapped_column(String(200))
    cover_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True)
    )

    entries: Mapped[list["PlaylistEntryRecord"]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
    )


class PlaylistEntryRecord(Base):
    __tablename__ = "playlist_entries"

    playlist_id: Mapped[str] = mapped_column(
        ForeignKey(
            "playlists.id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    position: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
    )
    track_id: Mapped[str] = mapped_column(
        ForeignKey(
            "tracks.id",
            ondelete="CASCADE",
        )
    )

    playlist: Mapped[PlaylistRecord] = relationship(
        back_populates="entries"
    )
    track: Mapped[TrackRecord] = relationship(
        back_populates="playlist_entries"
    )
