from app.recommenders.similarity import (
    SimilarTrack,
    TrackSimilarityIndex,
)
from app.storage.protocols import MusicStore


class TrackSimilarityService:
    def __int__(
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
