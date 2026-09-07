from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    recommendation_impressions: Mapped[
        list["RecommendationImpressionRecord"]
    ] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class SpotifyTrackMetadataRecord(Base):
    __tablename__ = "spotify_track_metadata"

    spotify_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    title: Mapped[str] = mapped_column(String(500))
    artist: Mapped[str] = mapped_column(String(500))
    album: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    added_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    isrc: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    cover_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )


class SpotifyListeningStatsRecord(Base):
    __tablename__ = "spotify_listening_stats"

    spotify_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    play_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    total_ms_played: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    first_played_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_played_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completion_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    skip_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )


class SpotifyFavoriteRecord(Base):
    __tablename__ = "spotify_favorites"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "spotify_id",
            name="uq_spotify_favorites_user_spotify",
        ),
        Index(
            "ix_spotify_favorites_user_active",
            "user_id",
            "active",
        ),
    )

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
    spotify_id: Mapped[str] = mapped_column(String(100))
    added_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )
    album: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    isrc: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
    )
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
    mood_tags_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
    )
    mood_profiles_json: Mapped[str] = mapped_column(
        Text,
        default="[]",
        nullable=False,
    )
    mood_analysis_version: Mapped[str | None] = mapped_column(
        String(50),
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
    recommendation_impressions: Mapped[
        list["RecommendationImpressionRecord"]
    ] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
    )

    playlist_entries: Mapped[list["PlaylistEntryRecord"]] = relationship(
        back_populates="track",
        cascade="all, delete-orphan",
    )


class InteractionRecord(Base):
    __tablename__ = "interactions"

    __table_args__ = (
        Index(
            "ix_interactions_user_created_at",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_interactions_user_track_created_at",
            "user_id",
            "track_id",
            "created_at",
        ),
    )

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
    recommendation_session_id: Mapped[str | None] = mapped_column(
        String(100),
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


class RecommendationImpressionRecord(Base):
    __tablename__ = "recommendation_impressions"

    __table_args__ = (
        Index(
            "ix_recommendation_impressions_user_shown",
            "user_id",
            "shown_at",
        ),
        Index(
            "ix_recommendation_impressions_session_position",
            "session_id",
            "position",
        ),
    )

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
    mode: Mapped[str] = mapped_column(String(30))
    position: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    session_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    feature_snapshot_json: Mapped[str] = mapped_column(
        Text,
        default="{}",
        nullable=False,
    )

    track: Mapped[TrackRecord] = relationship(
        back_populates="recommendation_impressions"
    )
    user: Mapped[UserRecord] = relationship(
        back_populates="recommendation_impressions"
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
