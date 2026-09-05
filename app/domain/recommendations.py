from dataclasses import dataclass
from enum import Enum

from app.domain.mood import MoodVector


class RecommendationMode(str, Enum):
    POPULARITY = "popularity"
    MOOD = "mood"
    GENRE = "genre"
    MY_WAVE = "my_wave"
    TRACK_RADIO = "track_radio"


@dataclass(frozen=True)
class RecommendationContext:
    mode: RecommendationMode = RecommendationMode.POPULARITY
    seed_track_id: str | None = None
    target_mood: MoodVector | None = None
    mood_name: str | None = None
    genre_name: str | None = None

    def __post_init__(self) -> None:
        if (
            self.mode == RecommendationMode.POPULARITY
            and (
                self.seed_track_id is not None
                or self.target_mood is not None
                or self.mood_name is not None
                or self.genre_name is not None
            )
        ):
            raise ValueError(
                "Popularity context must not contain extra filters."
            )

        if self.mode == RecommendationMode.MOOD:
            if self.target_mood is None:
                raise ValueError(
                    "Mood recommendation context needs a target mood."
                )
            if self.seed_track_id is not None:
                raise ValueError(
                    "Mood context must not contain a seed track."
                )
            if self.genre_name is not None:
                raise ValueError(
                    "Mood context must not contain a genre filter."
                )
            if self.mood_name is not None and not self.mood_name.strip():
                raise ValueError(
                    "Mood context name must not be empty."
                )

        if self.mode == RecommendationMode.GENRE:
            if self.genre_name is None or not self.genre_name.strip():
                raise ValueError(
                    "Genre recommendation context needs a genre name."
                )
            if (
                self.seed_track_id is not None
                or self.target_mood is not None
                or self.mood_name is not None
            ):
                raise ValueError(
                    "Genre context must not contain extra filters."
                )

        if self.mode == RecommendationMode.MY_WAVE and (
            self.seed_track_id is not None
            or self.target_mood is not None
            or self.mood_name is not None
            or self.genre_name is not None
        ):
            raise ValueError(
                "My Wave context must not contain extra filters."
            )

        if (
            self.mode == RecommendationMode.TRACK_RADIO
            and (
                not self.seed_track_id
                or self.target_mood is not None
                or self.mood_name is not None
                or self.genre_name is not None
            )
        ):
            raise ValueError(
                "Track radio context needs only a seed track."
            )

    @classmethod
    def mood(
        cls,
        target_mood: MoodVector,
        mood_name: str | None = None,
    ) -> "RecommendationContext":
        return cls(
            mode=RecommendationMode.MOOD,
            target_mood=target_mood,
            mood_name=mood_name,
        )

    @classmethod
    def track_radio(cls, seed_track_id: str) -> "RecommendationContext":
        return cls(
            mode=RecommendationMode.TRACK_RADIO,
            seed_track_id=seed_track_id,
        )

    @classmethod
    def genre(cls, genre_name: str) -> "RecommendationContext":
        return cls(
            mode=RecommendationMode.GENRE,
            genre_name=genre_name,
        )

    @classmethod
    def my_wave(cls) -> "RecommendationContext":
        """Build a personalized mood/profile recommendation context."""

        return cls(mode=RecommendationMode.MY_WAVE)
