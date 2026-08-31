from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


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
    source_url: str | None = None
    local_path: str | None = None


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


@dataclass(frozen=True)
class Recommendation:
    track: Track
    score: float
    reason: str
