from collections import defaultdict

from app.domain.models import Recommendation
from app.recommenders.protocols import Recommender
from app.storage.protocols import MusicStore


class MostPopularRecommender(Recommender):
    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def recommend(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[Recommendation]:
        if limit <= 0:
            raise ValueError("Recommendation limit must be positive")

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

        recommendations = []

        for track in candidate_tracks[:limit]:
            score = track_scores[track.id]

            if score > 0:
                reason = "Popular among users"
            else:
                reason = "Not enough interaction data"

            recommendations.append(
                Recommendation(
                    track=track,
                    score=score,
                    reason=reason,
                )
            )

        return recommendations