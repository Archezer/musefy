from dataclasses import dataclass

from app.domain.models import Interaction, InteractionType
from app.storage.protocols import MusicStore


@dataclass(frozen=True)
class InteractionResult:
    interaction: Interaction
    created: bool


STATEFUL_INTERACTION_TYPES = frozenset(
    {
        InteractionType.LIKE,
        InteractionType.SAVE,
    }
)


class InteractionService:
    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def record(
        self,
        user_id: str,
        track_id: str,
        interaction_type: InteractionType,
    ) -> InteractionResult:
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

        if interaction_type in STATEFUL_INTERACTION_TYPES:
            existing_state = self._find_existing_state(
                user_id=normalized_user_id,
                track_id=normalized_track_id,
                interaction_type=interaction_type,
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
        )

        self.store.add_interaction(interaction)

        return InteractionResult(
            interaction=interaction,
            created=True,
        )

    def _find_existing_state(
        self,
        user_id: str,
        track_id: str,
        interaction_type: InteractionType,
    ) -> Interaction | None:
        for interaction in self.store.list_interactions():
            if (
                interaction.user_id == user_id
                and interaction.track_id == track_id
                and interaction.interaction_type
                == interaction_type
            ):
                return interaction

        return None
