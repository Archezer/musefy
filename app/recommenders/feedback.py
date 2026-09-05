"""Shared interaction semantics for recommendation models.

Playback telemetry is deliberately split from preference feedback.  The
helpers in this module keep the popularity and mood recommenders in sync while
remaining compatible with the older ``PLAY``/``LISTEN`` records already in the
local database.
"""

from datetime import UTC, datetime, timedelta

from app.domain.models import Interaction, InteractionType

DEFAULT_INTEREST_HALF_LIFE_DAYS = 45.0
DEFAULT_SKIP_COOLDOWN_DAYS = 14
DEFAULT_SHORT_SKIP_COOLDOWN_DAYS = 7
DEFAULT_SNOOZE_DAYS = 14
MAX_PLAYBACK_WEIGHT_PER_TRACK = 6.0

# Starts and seeks are useful telemetry, but must not move a track up the
# ranking.  Legacy PLAY is included in playback history for replay cooldowns,
# while its weight is now zero for newly computed scores.
PLAYBACK_INTERACTION_TYPES = frozenset(
    {
        InteractionType.PLAY,
        InteractionType.PLAY_START,
        InteractionType.PLAYED_30S,
        InteractionType.COMPLETED_80,
        InteractionType.LISTEN,
        InteractionType.REPEAT,
    }
)

PLAYBACK_SESSION_TYPES = frozenset(
    {
        InteractionType.PLAY,
        InteractionType.PLAY_START,
        InteractionType.REPEAT,
    }
)

STATEFUL_INTERACTION_TYPES = frozenset(
    {
        InteractionType.LIKE,
        InteractionType.SAVE,
        InteractionType.DISLIKE,
        InteractionType.DO_NOT_RECOMMEND,
        InteractionType.ALLOW_RECOMMEND,
    }
)

POSITIVE_PREFERENCE_TYPES = frozenset(
    {
        InteractionType.LIKE,
        # Retained for compatibility with history written before Save was
        # removed from the player UI.
        InteractionType.SAVE,
    }
)

NEGATIVE_PREFERENCE_TYPES = frozenset(
    {
        InteractionType.DISLIKE,
    }
)

PREFERENCE_STATE_TYPES = POSITIVE_PREFERENCE_TYPES | NEGATIVE_PREFERENCE_TYPES

COMPLETION_INTERACTION_TYPES = frozenset(
    {
        # LISTEN is the durable event written by older app versions.
        InteractionType.LISTEN,
        InteractionType.COMPLETED_80,
    }
)

DECAYED_INTERACTION_TYPES = frozenset(
    {
        InteractionType.PLAYED_30S,
        InteractionType.COMPLETED_80,
        InteractionType.LISTEN,
        InteractionType.REPEAT,
        InteractionType.SKIP,
        InteractionType.SKIP_UNDER_30S,
        InteractionType.SNOOZE,
    }
)

PERMANENT_INTERACTION_TYPES = frozenset(
    {
        InteractionType.LIKE,
        InteractionType.SAVE,
        InteractionType.DISLIKE,
        InteractionType.DO_NOT_RECOMMEND,
        InteractionType.ALLOW_RECOMMEND,
    }
)

TEMPORARY_SUPPRESSION_TYPES = frozenset(
    {
        InteractionType.SKIP,
        InteractionType.SKIP_UNDER_30S,
        InteractionType.SNOOZE,
    }
)


def as_utc(value: datetime) -> datetime:
    """Normalize timestamps from SQLite and in-memory stores to UTC."""

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def interaction_decay(
    interaction: Interaction,
    *,
    now: datetime,
    half_life_days: float = DEFAULT_INTEREST_HALF_LIFE_DAYS,
) -> float:
    """Return an exponential half-life factor for transient signals."""

    if interaction.interaction_type not in DECAYED_INTERACTION_TYPES:
        return 1.0

    if half_life_days <= 0:
        raise ValueError("Interest half-life must be positive")

    age_days = max(
        0.0,
        (as_utc(now) - as_utc(interaction.created_at)).total_seconds()
        / 86_400.0,
    )
    return 2.0 ** (-age_days / half_life_days)


def effective_weight(
    interaction: Interaction,
    *,
    now: datetime,
    half_life_days: float = DEFAULT_INTEREST_HALF_LIFE_DAYS,
) -> float:
    """Calculate the ranking contribution of one interaction."""

    return interaction.interaction_type.weight * interaction_decay(
        interaction,
        now=now,
        half_life_days=half_life_days,
    )


def latest_user_preference_states(
    user_id: str,
    interactions: list[Interaction],
) -> dict[str, Interaction]:
    """Return one latest explicit preference state per track.

    Playback milestones are events and are intentionally ignored here.  The
    result is also used to collapse legacy duplicate like/save/dislike rows
    before they can distort a recommendation profile.
    """

    return {
        track_id: interaction
        for (state_user_id, track_id), interaction
        in latest_preference_states(interactions).items()
        if state_user_id == user_id
    }


def latest_preference_state_indices(
    interactions: list[Interaction],
) -> dict[tuple[str, str], int]:
    """Return list positions of the latest explicit state per user/track."""

    latest: dict[tuple[str, str], int] = {}
    for index, interaction in enumerate(interactions):
        if interaction.interaction_type not in PREFERENCE_STATE_TYPES:
            continue

        state_key = (interaction.user_id, interaction.track_id)
        previous_index = latest.get(state_key)
        if previous_index is None or as_utc(
            interaction.created_at
        ) >= as_utc(interactions[previous_index].created_at):
            latest[state_key] = index
    return latest


def latest_preference_states(
    interactions: list[Interaction],
) -> dict[tuple[str, str], Interaction]:
    """Return the latest explicit like/save/dislike for each user and track."""

    return {
        state_key: interactions[index]
        for state_key, index in latest_preference_state_indices(
            interactions
        ).items()
    }


def aggregate_playback_weights(
    user_id: str,
    interactions: list[Interaction],
    *,
    now: datetime,
    half_life_days: float = DEFAULT_INTEREST_HALF_LIFE_DAYS,
    max_per_track: float = MAX_PLAYBACK_WEIGHT_PER_TRACK,
) -> dict[str, float]:
    """Aggregate positive playback events with diminishing total influence."""

    if max_per_track <= 0.0:
        raise ValueError("Maximum playback weight must be positive")

    totals: dict[str, float] = {}
    for interaction in interactions:
        if (
            interaction.user_id != user_id
            or interaction.interaction_type not in PLAYBACK_INTERACTION_TYPES
        ):
            continue

        weight = max(
            0.0,
            effective_weight(
                interaction,
                now=now,
                half_life_days=half_life_days,
            ),
        )
        if weight <= 0.0:
            continue
        totals[interaction.track_id] = totals.get(interaction.track_id, 0.0) + weight

    return {
        track_id: min(weight, max_per_track)
        for track_id, weight in totals.items()
    }


def aggregate_user_track_weights(
    user_id: str,
    interactions: list[Interaction],
    *,
    now: datetime,
    half_life_days: float = DEFAULT_INTEREST_HALF_LIFE_DAYS,
    max_playback_weight: float = MAX_PLAYBACK_WEIGHT_PER_TRACK,
) -> dict[str, float]:
    """Combine one user's events without multiplying explicit states."""

    totals = aggregate_playback_weights(
        user_id,
        interactions,
        now=now,
        half_life_days=half_life_days,
        max_per_track=max_playback_weight,
    )
    latest_state_indices = latest_preference_state_indices(interactions)

    for index, interaction in enumerate(interactions):
        if interaction.user_id != user_id:
            continue
        if interaction.interaction_type in PLAYBACK_INTERACTION_TYPES:
            continue
        if (
            interaction.interaction_type in PREFERENCE_STATE_TYPES
            and latest_state_indices.get(
                (interaction.user_id, interaction.track_id)
            ) != index
        ):
            continue
        if interaction.interaction_type in {
            InteractionType.DO_NOT_RECOMMEND,
            InteractionType.ALLOW_RECOMMEND,
        }:
            continue

        totals[interaction.track_id] = (
            totals.get(interaction.track_id, 0.0)
            + effective_weight(
                interaction,
                now=now,
                half_life_days=half_life_days,
            )
        )

    return totals


def latest_user_interactions(
    user_id: str,
    interactions: list[Interaction],
) -> dict[str, Interaction]:
    """Return the latest state/action for each track for one user."""

    latest: dict[str, Interaction] = {}
    for interaction in interactions:
        if interaction.user_id != user_id:
            continue
        previous = latest.get(interaction.track_id)
        if previous is None or as_utc(interaction.created_at) > as_utc(
            previous.created_at
        ):
            latest[interaction.track_id] = interaction
    return latest


def _cooldown_for(interaction_type: InteractionType) -> int:
    if interaction_type == InteractionType.SKIP_UNDER_30S:
        return DEFAULT_SHORT_SKIP_COOLDOWN_DAYS
    if interaction_type == InteractionType.SNOOZE:
        return DEFAULT_SNOOZE_DAYS
    return DEFAULT_SKIP_COOLDOWN_DAYS


def suppressed_track_ids(
    user_id: str,
    interactions: list[Interaction],
    *,
    now: datetime,
) -> tuple[set[str], set[str]]:
    """Return ``(permanent, temporary)`` recommendation exclusions.

    A newer action replaces an older one.  ``DO_NOT_RECOMMEND`` is permanent;
    skips and snoozes expire automatically, after which the track may return
    through exploration (with its decayed negative signal still accounted for).
    """

    latest = latest_user_interactions(user_id, interactions)
    permanent_decisions: dict[str, Interaction] = {}
    for interaction in interactions:
        if (
            interaction.user_id != user_id
            or interaction.interaction_type
            not in {
                InteractionType.DO_NOT_RECOMMEND,
                InteractionType.ALLOW_RECOMMEND,
            }
        ):
            continue
        previous = permanent_decisions.get(interaction.track_id)
        if previous is None or as_utc(interaction.created_at) > as_utc(
            previous.created_at
        ):
            permanent_decisions[interaction.track_id] = interaction

    permanent: set[str] = set()
    temporary: set[str] = set()
    current = as_utc(now)
    for track_id, interaction in permanent_decisions.items():
        if interaction.interaction_type == InteractionType.DO_NOT_RECOMMEND:
            permanent.add(track_id)

    for track_id, interaction in latest.items():
        interaction_type = interaction.interaction_type
        if interaction_type in {
            InteractionType.DO_NOT_RECOMMEND,
            InteractionType.ALLOW_RECOMMEND,
        }:
            continue
        if interaction_type not in TEMPORARY_SUPPRESSION_TYPES:
            continue
        expires_at = as_utc(interaction.created_at) + timedelta(
            days=_cooldown_for(interaction_type)
        )
        if current < expires_at:
            temporary.add(track_id)
    return permanent, temporary
