from app.domain.models import (
    Interaction,
    InteractionType,
    Recommendation,
)
from app.domain.mood import MoodVector
from app.domain.recommendations import RecommendationMode
from app.storage.protocols import MusicStore

DEFAULT_REPLAY_COOLDOWN = 30
MOOD_DISTANCE_NORMALIZER = 2**0.5


class MoodRecommender:
    def __init__(
        self,
        store: MusicStore,
        replay_cooldown: int = DEFAULT_REPLAY_COOLDOWN,
    ) -> None:
        if replay_cooldown < 0:
            raise ValueError(
                "Replay cooldown must not be negative"
            )

        self.store = store
        self.replay_cooldown = replay_cooldown

    def recommend(
        self,
        user_id: str,
        target_mood: MoodVector,
        limit: int = 10,
    ) -> list[Recommendation]:
        if limit <= 0:
            raise ValueError("Recommendation limit must be positive")

        interactions = list(self.store.list_interactions())
        tracks = list(self.store.list_tracks())
        skipped_track_ids = self._get_skipped_track_ids(
            user_id,
            interactions,
        )
        cooldown_track_ids = self._get_cooldown_track_ids(
            user_id,
            interactions,
        )

        candidates = [
            track
            for track in tracks
            if (
                track.mood is not None
                and track.id not in skipped_track_ids
                and track.id not in cooldown_track_ids
            )
        ]

        if not candidates:
            candidates = [
                track
                for track in tracks
                if (
                    track.mood is not None
                    and track.id not in skipped_track_ids
                )
            ]

        scored_tracks = [
            (
                track,
                self._similarity(track.mood, target_mood),
            )
            for track in candidates
        ]
        scored_tracks.sort(
            key=lambda item: (
                -item[1],
                item[0].artist.casefold(),
                item[0].title.casefold(),
            )
        )

        return [
            Recommendation(
                track=track,
                score=similarity,
                reason="Matches the selected mood",
                mode=RecommendationMode.MOOD,
                mood_similarity=similarity,
            )
            for track, similarity in scored_tracks[:limit]
        ]

    def _get_skipped_track_ids(
        self,
        user_id: str,
        interactions: list[Interaction],
    ) -> set[str]:
        latest_interactions = self._get_latest_user_interactions(
            user_id,
            interactions,
        )
        return {
            track_id
            for track_id, interaction in latest_interactions.items()
            if interaction.interaction_type == InteractionType.SKIP
        }

    def _get_cooldown_track_ids(
        self,
        user_id: str,
        interactions: list[Interaction],
    ) -> set[str]:
        if self.replay_cooldown == 0:
            return set()

        playback_history = [
            interaction
            for interaction in interactions
            if (
                interaction.user_id == user_id
                and interaction.interaction_type
                in {InteractionType.PLAY, InteractionType.REPEAT}
            )
        ]
        playback_history.sort(
            key=lambda interaction: interaction.created_at
        )
        return {
            interaction.track_id
            for interaction in playback_history[-self.replay_cooldown :]
        }

    @staticmethod
    def _get_latest_user_interactions(
        user_id: str,
        interactions: list[Interaction],
    ) -> dict[str, Interaction]:
        latest: dict[str, Interaction] = {}
        for interaction in interactions:
            if interaction.user_id != user_id:
                continue

            previous = latest.get(interaction.track_id)
            if previous is None or interaction.created_at > previous.created_at:
                latest[interaction.track_id] = interaction

        return latest

    @staticmethod
    def _similarity(
        track_mood: MoodVector | None,
        target_mood: MoodVector,
    ) -> float:
        if track_mood is None:
            return 0.0

        return max(
            0.0,
            1.0 - track_mood.distance_to(target_mood)
            / MOOD_DISTANCE_NORMALIZER,
        )
