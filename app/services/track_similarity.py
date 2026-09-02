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
        neighbors_per_track: int = 20
    ) -> None:
        self.store = store
        self.neighbors_per_track = neighbors_per_track
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
        seed_track = self.store.get_track(track_id)
        if seed_track is None or seed_track.track_embedding is None:
            return []

        tracks_by_id = {
            track.id: track
            for track in self.store.list_tracks()
        }
        recommendations = []

        for neighbor in self.neighbors_for(track_id, limit):
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
