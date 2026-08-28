from collections import defaultdict

from app.domain.models import Track
from app.storage.memory import InMemoryMusicStore


class MostPopularRecommender:
    def __init__(self, store: InMemoryMusicStore) -> None:
        self.store = store

    def recommend(
            self,
            user_id: str,
            limit: int = 10,
    ) -> list[Track]:
        if limit <= 0:
            raise ValueError("Limit must be greater than 0")

        interactions = self.store.list_interactions()

        track_scores: dict[str, float] = defaultdict(float)

        for interaction in interactions:
            track_scores[interaction.track_id] += (
                interaction.interaction_type.weight
            )

        listened_track_ids = {
            interaction.track_id
            for interaction in interactions
            if interaction.user_id == user_id
        }

        candidate_tracks = [
            track
            for track in self.store.list_tracks()
            if track.id not in listened_track_ids
        ]

        candidate_tracks.sort(
            key=lambda track: (
                -track_scores[track.id],
                track.artist,
                track.title,
            )
        )

        return candidate_tracks[:limit]