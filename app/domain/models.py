from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from app.domain.mood import MoodVector
from app.domain.recommendations import RecommendationMode


class InteractionType(str, Enum):
    PLAY = "play"
    LIKE = "like"
    SAVE = "save"
    SKIP = "skip"
    REPEAT = "repeat"

    @property
    def weight(self) -> float:
        weights = {
            InteractionType.PLAY: 1.0,
            InteractionType.LIKE: 4.0,
            InteractionType.SAVE: 5.0,
            InteractionType.SKIP: -2.0,
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
    genres: tuple[str, ...] = ()
    detected_genres: tuple[DetectedGenre, ...] = ()
    track_embedding: tuple[float, ...] | None = None
    duration_ms: int | None = None
    source: str = "local_upload"
    source_id: str | None = None
    source_url: str | None = None
    local_path: str | None = None
    mood: MoodVector | None = None


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
class Playlist:
    id: str
    name: str
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
