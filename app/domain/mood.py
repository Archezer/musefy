from __future__ import annotations

from dataclasses import dataclass
from math import sqrt


@dataclass(frozen=True)
class MoodVector:
    valence: float
    arousal: float

    def __post_init__(self) -> None:
        if not -1.0 <= self.valence <= 1.0:
            raise ValueError("Valence must be between -1 and 1.")

        if not -1.0 <= self.arousal <= 1.0:
            raise ValueError("Arousal must be between -1 and 1.")

    def distance_to(self, other: MoodVector) -> float:
        return sqrt(
            (self.valence - other.valence) ** 2
            + (self.arousal - other.arousal) ** 2
        )


MOOD_PRESETS = {
    "melancholic": MoodVector(
        valence=-0.85,
        arousal=-0.7,
    ),
    "calm": MoodVector(
        valence=-0.1,
        arousal=-0.8,
    ),
    "happy": MoodVector(
        valence=0.85,
        arousal=0.6,
    ),
    "energetic": MoodVector(
        valence=0.4,
        arousal=0.9,
    ),
    "dark": MoodVector(
        valence=-0.55,
        arousal=0.75,
    ),
    "romantic": MoodVector(
        valence=0.6,
        arousal=-0.1,
    ),
    "focus": MoodVector(
        valence=0.0,
        arousal=-0.35,
    ),
    "party": MoodVector(
        valence=0.7,
        arousal=0.8,
    ),
}
