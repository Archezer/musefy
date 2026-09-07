from collections.abc import Callable, Collection, Sequence
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
from app.recommenders.recency import recency_bonus
from app.storage.protocols import MusicStore

RADIO_BASE_POOL_EXTRA = 6
RADIO_MAX_CANDIDATE_POOL = 20
RADIO_MIN_CONFIDENT_SIMILARITY = 0.55
RADIO_MAX_CONFIDENCE_DROP = 0.12


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
        self._embedding_catalog: dict[
            int,
            tuple[tuple[Track, ...], np.ndarray],
        ] | None = None
        self._seed_neighbor_cache: dict[
            str,
            tuple[SimilarTrack, ...],
        ] = {}

    def rebuild(self) -> TrackSimilarityIndex:
        tracks = [
            track
            for dimension_tracks, _matrix in self._get_embedding_catalog().values()
            for track in dimension_tracks
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
        self._embedding_catalog = None
        self._seed_neighbor_cache.clear()

    def update_track(self, track: Track) -> None:
        self._removed_track_ids.discard(track.id)
        self._embedding_catalog = None
        self._seed_neighbor_cache.clear()
        if self._index is None:
            return

        self._index.upsert(track)

    def remove_track(self, track_id: str) -> None:
        self._removed_track_ids.add(track_id)
        self._embedding_catalog = None
        self._seed_neighbor_cache.clear()
        if self._index is not None:
            self._index.remove(track_id)

    def neighbors_for(
        self,
        track_id: str,
        limit: int = 10
    ) -> tuple[SimilarTrack, ...]:
        if limit <= 0:
            raise ValueError("Limit must be positive.")

        seed_track = self.store.get_track(track_id)
        if seed_track is None or seed_track.track_embedding is None:
            return ()

        catalog = self._get_embedding_catalog()
        dimension_catalog = catalog.get(len(seed_track.track_embedding))
        if dimension_catalog is None:
            return ()

        tracks, embedding_matrix = dimension_catalog
        neighbors = self._seed_neighbor_cache.get(track_id)
        if neighbors is None:
            neighbors = tuple(
                self._neighbors_for_seed(
                    seed_track.track_embedding,
                    tracks,
                    embedding_matrix=embedding_matrix,
                    excluded_ids={track_id},
                )
            )
            self._seed_neighbor_cache[track_id] = neighbors

        return neighbors[:limit]

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

        catalog = self._get_embedding_catalog()
        dimension_catalog = catalog.get(len(seed_track.track_embedding))
        if dimension_catalog is None:
            return []

        tracks, embedding_matrix = dimension_catalog
        tracks_by_id = {track.id: track for track in tracks}
        excluded_ids = set(excluded_track_ids or ())
        excluded_ids.update(self._removed_track_ids)
        excluded_ids.add(track_id)

        if user_id is not None and user_id.strip():
            permanent, temporary = suppressed_track_ids(
                user_id,
                list(self.store.list_interactions(user_id=user_id)),
                now=datetime.now(UTC),
                context=f"track_radio:{track_id.casefold()}",
            )
            excluded_ids.update(permanent | temporary)

        # Keep the candidate pool close to the seed in embedding space, then
        # apply a tiny jitter so repeated radio starts do not feel identical.
        # A confident seed can use up to 20 candidates; weak neighborhoods
        # stay compact instead of padding the radio with unrelated tracks.
        # Radio only needs one seed-to-library search.  Building the complete
        # all-pairs index here made the first radio start quadratic in the
        # library size and blocked the first visible batch for too long.
        neighbors = self._seed_neighbor_cache.get(track_id)
        if neighbors is None:
            neighbors = tuple(
                self._neighbors_for_seed(
                    seed_track.track_embedding,
                    tracks,
                    embedding_matrix=embedding_matrix,
                    excluded_ids=set(),
                    should_cancel=should_cancel,
                )
            )
            self._seed_neighbor_cache[track_id] = neighbors

        neighbors = [
            neighbor
            for neighbor in neighbors
            if neighbor.track_id not in excluded_ids
        ]
        candidate_pool = self._select_candidate_pool(neighbors, limit)
        current_time = datetime.now(UTC)
        candidate_pool.sort(
            key=lambda neighbor: (
                neighbor.score
                + (
                    recency_bonus(
                        tracks_by_id[neighbor.track_id],
                        now=current_time,
                    )
                    if neighbor.track_id in tracks_by_id
                    else 0.0
                )
                + self.random.uniform(-0.02, 0.02)
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
    def _select_candidate_pool(
        neighbors: Sequence[SimilarTrack],
        limit: int,
    ) -> list[SimilarTrack]:
        """Expand the shuffle pool only while similarity remains trustworthy."""

        base_size = min(
            len(neighbors),
            limit + RADIO_BASE_POOL_EXTRA,
        )
        if base_size == len(neighbors):
            return list(neighbors)

        best_score = neighbors[0].score
        if best_score < RADIO_MIN_CONFIDENT_SIMILARITY:
            return list(neighbors[:base_size])

        confidence_floor = max(
            RADIO_MIN_CONFIDENT_SIMILARITY,
            best_score - RADIO_MAX_CONFIDENCE_DROP,
        )
        confident_count = sum(
            neighbor.score >= confidence_floor
            for neighbor in neighbors[:RADIO_MAX_CANDIDATE_POOL]
        )
        pool_size = max(
            base_size,
            min(RADIO_MAX_CANDIDATE_POOL, confident_count),
        )
        return list(neighbors[:pool_size])

    @staticmethod
    def _neighbors_for_seed(
        seed_embedding: tuple[float, ...],
        tracks: Sequence[Track],
        *,
        embedding_matrix: np.ndarray | None = None,
        excluded_ids: set[str],
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[SimilarTrack]:
        compatible_tracks: list[Track] = []
        compatible_indexes: list[int] = []
        for index, track in enumerate(tracks):
            if (
                index % 64 == 0
                and should_cancel is not None
                and should_cancel()
            ):
                raise RuntimeError("Recommendation calculation cancelled")

            if (
                track.id in excluded_ids
                or track.track_embedding is None
                or len(track.track_embedding) != len(seed_embedding)
            ):
                continue
            compatible_tracks.append(track)
            compatible_indexes.append(index)

        if not compatible_tracks:
            return []

        seed_vector = np.asarray(seed_embedding, dtype=np.float32)
        candidate_matrix = (
            embedding_matrix[compatible_indexes]
            if embedding_matrix is not None
            else np.asarray(
                [track.track_embedding for track in compatible_tracks],
                dtype=np.float32,
            )
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

    def _get_embedding_catalog(
        self,
    ) -> dict[int, tuple[tuple[Track, ...], np.ndarray]]:
        if self._embedding_catalog is not None:
            return self._embedding_catalog

        tracks_by_dimension: dict[int, list[Track]] = {}
        for track in self.store.list_tracks():
            if (
                track.id in self._removed_track_ids
                or track.track_embedding is None
            ):
                continue
            tracks_by_dimension.setdefault(
                len(track.track_embedding),
                [],
            ).append(track)

        self._embedding_catalog = {
            dimension: (
                tuple(dimension_tracks),
                np.asarray(
                    [track.track_embedding for track in dimension_tracks],
                    dtype=np.float32,
                ),
            )
            for dimension, dimension_tracks in tracks_by_dimension.items()
        }
        return self._embedding_catalog
