from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import Track


@dataclass(frozen=True)
class SimilarTrack:
    track_id: str
    score: float


def cosine_similarity(
    left: Sequence[float],
    right: Sequence[float]       
) -> float:
    if len(left) != len(right):
        raise ValueError("Both sequences must have the same length")

    if not left:
        return 0.0

    dot_product = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    return dot_product / (left_norm * right_norm)


class TrackSimilarityIndex:
    def __init__(
        self,
        tracks: Sequence[Track],
        neighbors_per_track: int = 20
    ) -> None:
        if neighbors_per_track <= 0:
            raise ValueError(
                "Neighbors per track must be positive."
            )
        self.neighbors_per_track = neighbors_per_track
        self._neighbors = self._build_neighbors(tracks)

    def neighbors_for(
        self,
        track_id: str
    ) -> tuple[SimilarTrack, ...]:
        return self._neighbors.get(track_id, ())

    def _build_neighbors(
        self,
        tracks: Sequence[Track]
    ) -> dict[str, tuple[SimilarTrack, ...]]:
        embedded_tracks = [
            track
            for track in tracks
            if track.track_embedding is not None
        ]
        neighbors: dict[str, tuple[SimilarTrack, ...]] = {}
        for source_track in embedded_tracks:
            candidates = [
                SimilarTrack(
                    track_id=candidate_track.id,
                    score=cosine_similarity(
                        source_track.track_embedding or (),
                        candidate_track.track_embedding or ()
                    )
                )
                for candidate_track in embedded_tracks
                if candidate_track.id != source_track.id
            ]

            candidates.sort(
                key=lambda candidate: candidate.score,
                reverse=True
            )
            neighbors[source_track.id] = tuple(
                candidates[:self.neighbors_per_track]
            )

        return neighbors