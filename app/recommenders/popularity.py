from collections import defaultdict
from math import exp
from random import Random

from app.domain.models import (
    Interaction,
    InteractionType,
    Recommendation,
    Track,
)
from app.recommenders.protocols import Recommender
from app.storage.protocols import MusicStore

DEFAULT_REPLAY_COOLDOWN = 30
DEFAULT_EXPLORATION_POOL_SIZE = 30
EXPLORATION_TEMPERATURE = 2.0

PLAYBACK_INTERACTION_TYPES = frozenset(
    {
        InteractionType.PLAY,
        InteractionType.REPEAT,
    }
)


class MostPopularRecommender(Recommender):
    def __init__(
        self,
        store: MusicStore,
        replay_cooldown: int = DEFAULT_REPLAY_COOLDOWN,
        exploration_pool_size: int = (
            DEFAULT_EXPLORATION_POOL_SIZE
        ),
        random_generator: Random | None = None
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
        self.exploration_pool_size = (
            exploration_pool_size
        )
        self.random = random_generator or Random()

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
                in PLAYBACK_INTERACTION_TYPES
            )
        ]

        playback_history.sort(
            key=lambda interaction: interaction.created_at
        )

        recent_playback = playback_history[
            -self.replay_cooldown:
        ]

        return {
            interaction.track_id
            for interaction in recent_playback
        }


    def _select_with_exploration(
        self,
        candidates: list[Track],
        track_scores: dict[str, float],
        limit: int,
    ) -> list[Track]:
        pool_size = max(
            limit,
            self.exploration_pool_size,
        )

        pool = candidates[:pool_size]
        selected_tracks: list[Track] = []

        while pool and len(selected_tracks) < limit:
            minimum_score = min(
                track_scores[track.id]
                for track in pool
            )

            weights = [
                exp(
                    (
                        track_scores[track.id]
                        - minimum_score
                    )
                    / EXPLORATION_TEMPERATURE
                )
                for track in pool
            ]

            selected_track = self.random.choices(
                population=pool,
                weights=weights,
                k=1,
            )[0]

            selected_tracks.append(selected_track)
            pool.remove(selected_track)

        return selected_tracks



    def recommend(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list[Recommendation]:
        if limit <= 0:
            raise ValueError("Recommendation limit must be positive")

        interactions = list(self.store.list_interactions())

        track_scores: dict[str, float] = defaultdict(float)
        seen_states: set[
            tuple[str, str, InteractionType]
        ] = set()

        for interaction in interactions:
            if interaction.interaction_type in {
                InteractionType.LIKE,
                InteractionType.SAVE,
            }:
                state_key = (
                    interaction.user_id,
                    interaction.track_id,
                    interaction.interaction_type,
                )

                if state_key in seen_states:
                    continue

                seen_states.add(state_key)

            track_scores[interaction.track_id] += (
                interaction.interaction_type.weight
            )

        latest_user_interactions = {}

        cooldown_track_ids = (
            self._get_cooldown_track_ids(
                user_id=user_id,
                interactions=interactions,
            )
        )

        for interaction in interactions:
            if interaction.user_id != user_id:
                continue

            previous_interaction = latest_user_interactions.get(
                interaction.track_id
            )

            if (
                previous_interaction is None
                or interaction.created_at
                > previous_interaction.created_at
            ):
                latest_user_interactions[
                    interaction.track_id
                ] = interaction

        skipped_track_ids = {
            track_id
            for track_id, interaction
            in latest_user_interactions.items()
            if interaction.interaction_type
            == InteractionType.SKIP
        }

        excluded_track_ids = (
            skipped_track_ids | cooldown_track_ids
        )

        candidate_tracks = [
            track
            for track in self.store.list_tracks()
            if track.id not in excluded_track_ids
        ]

        candidate_tracks.sort(
            key=lambda track: (
                -track_scores[track.id],
                track.artist,
                track.title,
            )
        )

        selected_tracks = (
            self._select_with_exploration(
                candidates=candidate_tracks,
                track_scores=track_scores,
                limit=limit,
            )
        )

        recommendations = []

        for track in selected_tracks:
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
