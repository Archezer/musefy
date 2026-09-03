from random import Random

from app.domain.models import Recommendation, Track
from app.domain.recommendations import RecommendationMode
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

    def rebuild(self) -> TrackSimilarityIndex:
        tracks = list(self.store.list_tracks())
        self._index = TrackSimilarityIndex(
            tracks,
            neighbors_per_track=self.neighbors_per_track
        )
        return self._index

    def update_track(self, track: Track) -> None:
        if self._index is None:
            if track.track_embedding is not None:
                self.rebuild()
            return

        self._index.upsert(track)

    def remove_track(self, track_id: str) -> None:
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
    ) -> list[Recommendation]:
        if limit <= 0:
            raise ValueError("Limit must be positive.")

        seed_track = self.store.get_track(track_id)
        if seed_track is None or seed_track.track_embedding is None:
            return []

        tracks_by_id = {
            track.id: track
            for track in self.store.list_tracks()
        }
        if self._index is None:
            self.rebuild()

        # Keep the candidate pool close to the seed in embedding space, then
        # apply a tiny jitter so repeated radio starts do not feel identical.
        # The pool is deliberately kept only a few tracks wider than the
        # requested result size to avoid drifting into merely related tracks.
        neighbors = self._index.neighbors_for(track_id)
        candidate_pool_size = min(
            len(neighbors),
            limit + 6,
        )
        candidate_pool = list(neighbors[:candidate_pool_size])
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
