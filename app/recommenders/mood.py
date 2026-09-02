from math import exp
from random import Random

from app.domain.models import (
    Interaction,
    InteractionType,
    Recommendation,
    Track,
)
from app.domain.mood import MoodVector
from app.domain.recommendations import RecommendationMode
from app.storage.protocols import MusicStore

DEFAULT_REPLAY_COOLDOWN = 30
MOOD_DISTANCE_NORMALIZER = 2**0.5
DEFAULT_EXPLORATION_POOL_SIZE = 8
MOOD_EXPLORATION_TEMPERATURE = 0.05
MOOD_RANDOM_SCORE_GAP = 0.12
MOOD_FEEDBACK_FACTOR = 0.05


class MoodRecommender:
    def __init__(
        self,
        store: MusicStore,
        replay_cooldown: int = DEFAULT_REPLAY_COOLDOWN,
        exploration_pool_size: int = (
            DEFAULT_EXPLORATION_POOL_SIZE
        ),
        random_generator: Random | None = None,
    ) -> None:
        if replay_cooldown < 0:
            raise ValueError(
                "Replay cooldown must not be negative"
            )

        if exploration_pool_size <= 0:
            raise ValueError(
                "Exploration pool size must be positive"
            )

        self.store = store
        self.replay_cooldown = replay_cooldown
        self.exploration_pool_size = exploration_pool_size
        self.random = random_generator or Random()

    def recommend(
        self,
        user_id: str,
        target_mood: MoodVector,
        limit: int = 10,
        mood_name: str | None = None,
    ) -> list[Recommendation]:
        if limit <= 0:
            raise ValueError("Recommendation limit must be positive")

        interactions = self._get_context_interactions(
            user_id=user_id,
            mood_name=mood_name,
        )
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

        feedback_scores = self._get_feedback_scores(
            user_id=user_id,
            interactions=interactions,
        )

        scored_tracks = [
            (
                track,
                self._similarity(track.mood, target_mood),
                feedback_scores.get(track.id, 0.0),
            )
            for track in candidates
        ]
        scored_tracks.sort(
            key=lambda item: (
                -(item[1] + item[2]),
                item[0].artist.casefold(),
                item[0].title.casefold(),
            )
        )

        effective_scores = [
            (
                track,
                min(1.0, similarity + feedback_bonus),
            )
            for track, similarity, feedback_bonus in scored_tracks
        ]

        selected_tracks = self._select_with_exploration(
            effective_scores,
            limit,
        )

        return [
            Recommendation(
                track=track,
                score=similarity,
                reason="Matches the selected mood",
                mode=RecommendationMode.MOOD,
                mood_similarity=self._similarity(
                    track.mood,
                    target_mood,
                ),
            )
            for track, similarity in selected_tracks
        ]

    def _get_context_interactions(
        self,
        user_id: str,
        mood_name: str | None,
    ) -> list[Interaction]:
        normalized_mood_name = (
            mood_name.strip().casefold()
            if mood_name and mood_name.strip()
            else None
        )

        return [
            interaction
            for interaction in self.store.list_interactions()
            if (
                interaction.user_id == user_id
                and interaction.mood_context == normalized_mood_name
            )
        ]

    @staticmethod
    def _get_feedback_scores(
        user_id: str,
        interactions: list[Interaction],
    ) -> dict[str, float]:
        feedback_scores: dict[str, float] = {}

        for interaction in interactions:
            if interaction.user_id != user_id:
                continue

            if interaction.interaction_type not in {
                InteractionType.LIKE,
                InteractionType.SAVE,
            }:
                continue

            feedback_scores[interaction.track_id] = min(
                MOOD_FEEDBACK_FACTOR,
                feedback_scores.get(interaction.track_id, 0.0)
                + MOOD_FEEDBACK_FACTOR,
            )

        return feedback_scores

    def _select_with_exploration(
        self,
        scored_tracks: list[tuple[Track, float]],
        limit: int,
    ) -> list[tuple[Track, float]]:
        if len(scored_tracks) <= limit:
            return scored_tracks[:limit]

        pool_size = min(
            len(scored_tracks),
            max(limit * 2, self.exploration_pool_size),
        )
        pool = scored_tracks[:pool_size]
        top_score = pool[0][1]
        eligible = [
            item
            for item in pool
            if top_score - item[1] <= MOOD_RANDOM_SCORE_GAP
        ]

        if len(eligible) <= limit:
            return scored_tracks[:limit]

        selected: list[tuple[Track, float]] = []
        remaining = list(eligible)

        while remaining and len(selected) < limit:
            minimum_score = min(
                item[1]
                for item in remaining
            )
            weights = [
                exp(
                    (item[1] - minimum_score)
                    / MOOD_EXPLORATION_TEMPERATURE
                )
                for item in remaining
            ]
            selected_item = self.random.choices(
                population=remaining,
                weights=weights,
                k=1,
            )[0]
            selected.append(selected_item)
            remaining.remove(selected_item)

        selected_ids = {
            item[0].id
            for item in selected
        }
        for item in scored_tracks:
            if len(selected) >= limit:
                break
            if item[0].id not in selected_ids:
                selected.append(item)
                selected_ids.add(item[0].id)

        return selected

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
