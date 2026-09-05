from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from app.domain.mood import MoodVector
from app.domain.recommendations import RecommendationMode


class InteractionType(str, Enum):
    # ``PLAY`` and ``LISTEN`` are retained for imported/legacy history.
    # New playback sessions use milestone events so a one-second preview
    # cannot look like a positive listen.
    PLAY = "play"
    LISTEN = "listen"
    PLAY_START = "play_start"
    PLAYED_30S = "played_30s"
    COMPLETED_80 = "completed_80"
    SEEK = "seek"
    LIKE = "like"
    SAVE = "save"
    SKIP = "skip"
    SKIP_UNDER_30S = "skip_under_30s"
    SNOOZE = "snooze"
    DISLIKE = "dislike"
    DO_NOT_RECOMMEND = "do_not_recommend"
    ALLOW_RECOMMEND = "allow_recommend"
    REPEAT = "repeat"

    @property
    def weight(self) -> float:
        weights = {
            # A start is telemetry, not a preference signal.
            InteractionType.PLAY: 0.0,
            InteractionType.LISTEN: 1.0,
            InteractionType.PLAY_START: 0.0,
            InteractionType.PLAYED_30S: 1.0,
            InteractionType.COMPLETED_80: 2.0,
            InteractionType.SEEK: 0.0,
            InteractionType.LIKE: 4.0,
            InteractionType.SAVE: 5.0,
            # These are written only for explicit feedback from the playback
            # menu.  Normal next/previous navigation is intentionally neutral.
            InteractionType.SKIP: -2.0,
            InteractionType.SKIP_UNDER_30S: -1.0,
            InteractionType.SNOOZE: -0.5,
            InteractionType.DISLIKE: -4.0,
            InteractionType.DO_NOT_RECOMMEND: -8.0,
            InteractionType.ALLOW_RECOMMEND: 0.0,
            InteractionType.REPEAT: 2.0,
        }

        return weights[self]


@dataclass(frozen=True)
class DetectedGenre:
    genre: str
    parent_genre: str
    subgenre: str
    score: float
    rank: int
    rank_weight: float
    weighted_score: float


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    artist: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    genres: tuple[str, ...] = ()
    detected_genres: tuple[DetectedGenre, ...] = ()
    track_embedding: tuple[float, ...] | None = None
    duration_ms: int | None = None
    source: str = "local_upload"
    source_id: str | None = None
    source_url: str | None = None
    local_path: str | None = None
    cover_path: str | None = None
    mood: MoodVector | None = None
    mood_tags: tuple[tuple[str, float], ...] = ()
    mood_profiles: tuple[tuple[str, float], ...] = ()
    mood_analysis_version: str | None = None


@dataclass(frozen=True)
class User:
    id: str
    display_name: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True)
class Interaction:
    user_id: str
    track_id: str
    interaction_type: InteractionType
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )
    mood_context: str | None = None
    recommendation_session_id: str | None = None


@dataclass(frozen=True)
class Recommendation:
    track: Track
    score: float
    reason: str
    mode: RecommendationMode = RecommendationMode.POPULARITY
    mood_similarity: float | None = None
    embedding_similarity: float | None = None
    popularity_score: float | None = None

    @property
    def match_score(self) -> float:
        return self.score


@dataclass(frozen=True)
class RecommendationImpression:
    """A recommendation that was actually presented or queued."""

    user_id: str
    track_id: str
    mode: RecommendationMode
    position: int
    score: float
    reason: str = ""
    shown_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    session_id: str | None = None


@dataclass(frozen=True)
class Playlist:
    id: str
    name: str
    cover_path: str | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )


@dataclass(frozen=True)
class PlaylistEntry:
    playlist_id: str
    track_id: str
    position: int


class QueueMode(str, Enum):
    NORMAL = "normal"
    SHUFFLE = "shuffle"
    SMART_SHUFFLE = "smart_shuffle"
    SESSION = "session"
    RECOMMENDATIONS = "recommendations"


class RepeatMode(str, Enum):
    OFF = "off"
    QUEUE = "queue"
    TRACK = "track"


@dataclass(frozen=True)
class PlaybackQueue:
    current_track_id: str | None = None
    remaining_track_ids: tuple[str, ...] = ()
    queued_track_ids: tuple[str, ...] = ()
    mode: QueueMode = QueueMode.NORMAL
    source_playlist_id: str | None = None

    def __post_init__(self) -> None:
        track_ids = (
            (self.current_track_id,)
            if self.current_track_id is not None
            else ()
        ) + self.remaining_track_ids + self.queued_track_ids

        if not track_ids:
            raise ValueError(
                "Playback queue must contain at least one track"
            )

        if any(not track_id.strip() for track_id in track_ids):
            raise ValueError("Queue track IDs must not be empty")
