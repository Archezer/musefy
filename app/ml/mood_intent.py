from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.ml.clap import ClapTextEncoder


MOOD_PROMPTS = {
    "rage": "dark aggressive rage music",
    "workout": "energetic music for an intense gym workout",
    "sad": "sad melancholic emotional music",
    "calm": "calm relaxing peaceful music",
    "happy": "happy upbeat joyful music",
    "romantic": "romantic emotional love music",
    "focus": "focused atmospheric music for concentration",
    "party": "fun energetic party music",
    "dreamy": "dreamy ambient atmospheric music",
}


@dataclass(frozen=True)
class MoodPrediction:
    mood: str
    score: float


class MoodIntentResolver:
    def __init__(self, encoder: ClapTextEncoder) -> None:
        self.encoder = encoder
        self._mood_vectors: dict[str, np.ndarray] | None = None

    def _ensure_mood_vectors(self) -> None:
        if self._mood_vectors is not None:
            return

        self._mood_vectors = {
            mood: self.encoder.encode_text(prompt)
            for mood, prompt in MOOD_PROMPTS.items()
        }

    def resolve(
        self,
        text: str,
        top_k: int = 3,
    ) -> list[MoodPrediction]:
        self._ensure_mood_vectors()

        query_vector = self.encoder.encode_text(text)

        predictions = [
            MoodPrediction(
                mood=mood,
                score=float(np.dot(query_vector, vector)),
            )
            for mood, vector in self._mood_vectors.items()
        ]

        return sorted(
            predictions,
            key=lambda item: item.score,
            reverse=True,
        )[:top_k]