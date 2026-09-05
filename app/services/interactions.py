from dataclasses import dataclass

from app.domain.models import Interaction, InteractionType
from app.recommenders.feedback import (
    PREFERENCE_STATE_TYPES,
    STATEFUL_INTERACTION_TYPES,
    latest_preference_state_indices,
    latest_user_preference_states,
)
from app.storage.protocols import MusicStore


@dataclass(frozen=True)
class InteractionResult:
    interaction: Interaction
    created: bool


@dataclass(frozen=True)
class PreferenceCompactionPlan:
    redundant_records: int
    affected_tracks: int


class InteractionService:
    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def record(
        self,
        user_id: str,
        track_id: str,
        interaction_type: InteractionType,
        mood_context: str | None = None,
        recommendation_session_id: str | None = None,
    ) -> InteractionResult:
        normalized_user_id = user_id.strip()
        normalized_track_id = track_id.strip()
        normalized_mood_context = (
            mood_context.strip().casefold()
            if mood_context and mood_context.strip()
            else None
        )
        normalized_recommendation_session_id = (
            recommendation_session_id.strip()
            if recommendation_session_id
            and recommendation_session_id.strip()
            else None
        )

        if not normalized_user_id:
            raise ValueError("User ID must not be empty")

        if not normalized_track_id:
            raise ValueError("Track ID must not be empty")
        if (
            normalized_recommendation_session_id is not None
            and len(normalized_recommendation_session_id) > 100
        ):
            raise ValueError("Recommendation session ID is too long")

        if self.store.get_user(normalized_user_id) is None:
            raise ValueError(
                f"User does not exist: {normalized_user_id}"
            )

        if self.store.get_track(normalized_track_id) is None:
            raise ValueError(
                f"Track does not exist: {normalized_track_id}"
            )

        if interaction_type in STATEFUL_INTERACTION_TYPES:
            existing_state = self._find_existing_state(
                user_id=normalized_user_id,
                track_id=normalized_track_id,
                interaction_type=interaction_type,
                mood_context=normalized_mood_context,
            )

            if existing_state is not None:
                return InteractionResult(
                    interaction=existing_state,
                    created=False,
                )

        interaction = Interaction(
            user_id=normalized_user_id,
            track_id=normalized_track_id,
            interaction_type=interaction_type,
            mood_context=normalized_mood_context,
            recommendation_session_id=(
                normalized_recommendation_session_id
            ),
        )

        self.store.add_interaction(interaction)

        return InteractionResult(
            interaction=interaction,
            created=True,
        )

    def is_liked(self, user_id: str, track_id: str) -> bool:
        normalized_user_id = user_id.strip()
        normalized_track_id = track_id.strip()

        if not normalized_user_id:
            raise ValueError("User ID must not be empty")

        if not normalized_track_id:
            raise ValueError("Track ID must not be empty")

        return self._find_existing_like(
            user_id=normalized_user_id,
            track_id=normalized_track_id,
        ) is not None

    def remove_like(self, user_id: str, track_id: str) -> bool:
        normalized_user_id = user_id.strip()
        normalized_track_id = track_id.strip()

        if not normalized_user_id:
            raise ValueError("User ID must not be empty")

        if not normalized_track_id:
            raise ValueError("Track ID must not be empty")

        if self.store.get_user(normalized_user_id) is None:
            raise ValueError(
                f"User does not exist: {normalized_user_id}"
            )

        if self.store.get_track(normalized_track_id) is None:
            raise ValueError(
                f"Track does not exist: {normalized_track_id}"
            )

        removed_count = self.store.delete_interactions(
            normalized_user_id,
            normalized_track_id,
            InteractionType.LIKE.value,
        )
        return removed_count > 0

    def preference_compaction_plan(self) -> PreferenceCompactionPlan:
        interactions = list(self.store.list_interactions())
        latest_indices = latest_preference_state_indices(interactions)
        duplicate_keys: set[tuple[str, str]] = set()
        redundant_records = 0
        for index, interaction in enumerate(interactions):
            if interaction.interaction_type not in PREFERENCE_STATE_TYPES:
                continue
            state_key = (interaction.user_id, interaction.track_id)
            if latest_indices.get(state_key) != index:
                redundant_records += 1
                duplicate_keys.add(state_key)

        return PreferenceCompactionPlan(
            redundant_records=redundant_records,
            affected_tracks=len(duplicate_keys),
        )

    def compact_preference_history(self) -> int:
        return self.store.compact_preference_interactions()

    def _find_existing_state(
        self,
        user_id: str,
        track_id: str,
        interaction_type: InteractionType,
        mood_context: str | None,
    ) -> Interaction | None:
        for interaction in self.store.list_interactions():
            if (
                interaction.user_id == user_id
                and interaction.track_id == track_id
                and interaction.interaction_type
                == interaction_type
                and interaction.mood_context
                == mood_context
            ):
                return interaction

        return None

    def _find_existing_like(
        self,
        user_id: str,
        track_id: str,
    ) -> Interaction | None:
        latest_state = latest_user_preference_states(
            user_id,
            list(self.store.list_interactions()),
        ).get(track_id)
        if (
            latest_state is not None
            and latest_state.interaction_type == InteractionType.LIKE
        ):
            return latest_state
        return None
