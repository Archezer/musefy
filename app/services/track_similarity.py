from collections.abc import Callable, Collection
from datetime import UTC, datetime
from random import Random

import numpy as np

from app.domain.models import Recommendation, Track
from app.domain.recommendations import RecommendationMode
from app.recommenders.feedback import suppressed_track_ids
from app.recommenders.similarity import (
    SimilarTrack,
    TrackSimilarityIndex,
)
from app.storage.protocols import MusicStore


class TrackSimilarityService:
    def __init__(
        self,
        store: MusicStore,
        neighbors_per_track: int = 20,
        random_generator: Random | None = None,
    ) -> None:
        self.store = store
        self.neighbors_per_track = neighbors_per_track
        self.random = random_generator or Random()
        self._index: TrackSimilarityIndex | None = None
        self._removed_track_ids: set[str] = set()

    def rebuild(self) -> TrackSimilarityIndex:
        tracks = [
            track
            for track in self.store.list_tracks()
            if track.id not in self._removed_track_ids
        ]
        self._index = TrackSimilarityIndex(
            tracks,
            neighbors_per_track=self.neighbors_per_track
        )
        return self._index

    def invalidate(self) -> None:
        """Drop the optional all-pairs index without doing expensive work."""

        self._index = None
        self._removed_track_ids.clear()

    def update_track(self, track: Track) -> None:
        self._removed_track_ids.discard(track.id)
        if self._index is None:
            return

        self._index.upsert(track)

    def remove_track(self, track_id: str) -> None:
        self._removed_track_ids.add(track_id)
        if self._index is not None:
            self._index.remove(track_id)

    def neighbors_for(
        self,
        track_id: str,
        limit: int = 10
    ) -> tuple[SimilarTrack, ...]:
        if limit <= 0:
            raise ValueError("Limit must be positive.")
        
        if self._index is None:
            self.rebuild()
            
        return self._index.neighbors_for(track_id)[:limit]

    def recommendations_for(
        self,
        track_id: str,
        limit: int = 10,
        *,
        user_id: str | None = None,
        excluded_track_ids: Collection[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[Recommendation]:
        if limit <= 0:
            raise ValueError("Limit must be positive.")

        seed_track = self.store.get_track(track_id)
        if seed_track is None or seed_track.track_embedding is None:
            return []

        tracks = [
            track
            for track in self.store.list_tracks()
            if track.id not in self._removed_track_ids
        ]
        tracks_by_id = {track.id: track for track in tracks}
        excluded_ids = set(excluded_track_ids or ())
        excluded_ids.update(self._removed_track_ids)
        excluded_ids.add(track_id)

        if user_id is not None and user_id.strip():
            permanent, temporary = suppressed_track_ids(
                user_id,
                list(self.store.list_interactions()),
                now=datetime.now(UTC),
            )
            excluded_ids.update(permanent | temporary)

        # Keep the candidate pool close to the seed in embedding space, then
        # apply a tiny jitter so repeated radio starts do not feel identical.
        # The pool is deliberately kept only a few tracks wider than the
        # requested result size to avoid drifting into merely related tracks.
        # Radio only needs one seed-to-library search.  Building the complete
        # all-pairs index here made the first radio start quadratic in the
        # library size and blocked the first visible batch for too long.
        neighbors = self._neighbors_for_seed(
            seed_track.track_embedding,
            tracks,
            excluded_ids=excluded_ids,
            should_cancel=should_cancel,
        )
        candidate_pool = neighbors[: limit + 6]
        candidate_pool.sort(
            key=lambda neighbor: (
                neighbor.score + self.random.uniform(-0.02, 0.02)
            ),
            reverse=True,
        )

        recommendations = []

        for neighbor in candidate_pool[:limit]:
            track = tracks_by_id.get(neighbor.track_id)
            if track is None:
                continue

            recommendations.append(
                Recommendation(
                    track=track,
                    score=neighbor.score,
                    reason="Similar to the selected track",
                    mode=RecommendationMode.TRACK_RADIO,
                    embedding_similarity=neighbor.score,
                )
            )

        return recommendations

    @staticmethod
    def _neighbors_for_seed(
        seed_embedding: tuple[float, ...],
        tracks: list[Track],
        *,
        excluded_ids: set[str],
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[SimilarTrack]:
        compatible_tracks: list[Track] = []
        for index, track in enumerate(tracks):
            if index % 64 == 0 and should_cancel is not None:
                if should_cancel():
                    raise RuntimeError("Recommendation calculation cancelled")

            if (
                track.id in excluded_ids
                or track.track_embedding is None
                or len(track.track_embedding) != len(seed_embedding)
            ):
                continue
            compatible_tracks.append(track)

        if not compatible_tracks:
            return []

        seed_vector = np.asarray(seed_embedding, dtype=np.float32)
        candidate_matrix = np.asarray(
            [track.track_embedding for track in compatible_tracks],
            dtype=np.float32,
        )
        seed_norm = float(np.linalg.norm(seed_vector))
        candidate_norms = np.linalg.norm(candidate_matrix, axis=1)
        valid_indexes = candidate_norms > 1e-6
        if seed_norm == 0.0 or not np.any(valid_indexes):
            return []

        scores = (
            candidate_matrix[valid_indexes] @ seed_vector
        ) / (
            candidate_norms[valid_indexes] * seed_norm
        )
        valid_tracks = [
            track
            for track, is_valid in zip(compatible_tracks, valid_indexes)
            if is_valid
        ]
        neighbors = [
            SimilarTrack(
                track_id=track.id,
                score=float(score),
            )
            for track, score in zip(valid_tracks, scores)
        ]

        if should_cancel is not None and should_cancel():
            raise RuntimeError("Recommendation calculation cancelled")

        neighbors.sort(
            key=lambda neighbor: neighbor.score,
            reverse=True,
        )
        return neighbors
