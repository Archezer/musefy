"""Leakage-safe training rows for recommendation rankers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import exp
from random import Random

from app.domain.models import (
    Interaction,
    InteractionType,
    RecommendationImpression,
)
from app.ml.feature_snapshot import RECOMMENDATION_FEATURE_NAMES
from app.storage.protocols import MusicStore

DEFAULT_MIN_RANKER_EXAMPLES = 100

POSITIVE_INTERACTION_TYPES = frozenset(
    {
        InteractionType.LIKE.value,
        InteractionType.PLAYED_30S.value,
        InteractionType.COMPLETED_80.value,
        InteractionType.LISTEN.value,
        InteractionType.REPEAT.value,
    }
)
NEGATIVE_INTERACTION_TYPES = frozenset(
    {
        InteractionType.DISLIKE.value,
        InteractionType.DO_NOT_RECOMMEND.value,
        InteractionType.SKIP.value,
        InteractionType.SKIP_UNDER_30S.value,
    }
)


@dataclass(frozen=True)
class RankerExample:
    """One labelled impression with its frozen point-in-time features."""

    user_id: str
    track_id: str
    shown_at: datetime
    feature_snapshot: tuple[tuple[str, float], ...]
    label: int


@dataclass(frozen=True)
class RankerDataset:
    """Small framework-independent dataset consumed by ML backends."""

    feature_names: tuple[str, ...]
    examples: tuple[RankerExample, ...]

    @property
    def labels(self) -> tuple[int, ...]:
        return tuple(example.label for example in self.examples)

    def as_matrix(self) -> tuple[tuple[float, ...], ...]:
        rows: list[tuple[float, ...]] = []
        for example in self.examples:
            values = dict(example.feature_snapshot)
            rows.append(
                tuple(values.get(name, 0.0) for name in self.feature_names)
            )
        return tuple(rows)


@dataclass(frozen=True)
class RankerDataReadiness:
    """Data-collection status used before starting a real training run."""

    total_impressions: int
    snapshot_impressions: int
    labelled_examples: int
    positive_examples: int
    negative_examples: int
    user_count: int
    feature_names: tuple[str, ...]
    minimum_examples: int

    @property
    def ready(self) -> bool:
        return (
            self.labelled_examples >= self.minimum_examples
            and self.positive_examples > 0
            and self.negative_examples > 0
        )

    @property
    def status(self) -> str:
        return "ready" if self.ready else "collecting_data"


def inspect_ranker_data(
    store: MusicStore,
    *,
    user_id: str | None = None,
    attribution_days: int = 1,
    minimum_examples: int = DEFAULT_MIN_RANKER_EXAMPLES,
) -> RankerDataReadiness:
    """Summarize whether stored impressions are useful for training."""

    if minimum_examples <= 0:
        raise ValueError("Minimum examples must be positive")
    impressions = list(
        store.list_recommendation_impressions(user_id=user_id)
    )
    dataset = build_ranker_dataset(
        store,
        user_id=user_id,
        attribution_days=attribution_days,
    )
    labels = dataset.labels
    return RankerDataReadiness(
        total_impressions=len(impressions),
        snapshot_impressions=sum(
            bool(impression.feature_snapshot)
            for impression in impressions
        ),
        labelled_examples=len(dataset.examples),
        positive_examples=sum(label == 1 for label in labels),
        negative_examples=sum(label == 0 for label in labels),
        user_count=len({example.user_id for example in dataset.examples}),
        feature_names=dataset.feature_names,
        minimum_examples=minimum_examples,
    )


def build_ranker_dataset(
    store: MusicStore,
    *,
    user_id: str | None = None,
    attribution_days: int = 1,
) -> RankerDataset:
    """Build labels only from explicit reactions after an impression.

    Impressions without a feature snapshot or without an attributable,
    labelled interaction are deliberately omitted.  In particular, an
    impression with no response is not treated as a negative example.
    """

    if attribution_days <= 0:
        raise ValueError("Attribution days must be positive")

    impressions = list(
        store.list_recommendation_impressions(user_id=user_id)
    )
    impressions.sort(key=_impression_sort_key)
    interactions = list(store.list_interactions(user_id=user_id))

    attributed: dict[int, list[Interaction]] = {}
    window = timedelta(days=attribution_days)
    for interaction in interactions:
        event_time = _as_utc(interaction.created_at)
        matching = [
            (index, impression)
            for index, impression in enumerate(impressions)
            if _matches_impression(
                impression,
                interaction,
                event_time=event_time,
                window=window,
            )
        ]
        if matching:
            index, _ = max(
                matching,
                key=lambda item: _as_utc(item[1].shown_at),
            )
            attributed.setdefault(index, []).append(interaction)

    examples: list[RankerExample] = []
    for index, impression in enumerate(impressions):
        if not impression.feature_snapshot:
            continue
        label = _resolve_label(attributed.get(index, ()))
        if label is None:
            continue
        examples.append(
            RankerExample(
                user_id=impression.user_id,
                track_id=impression.track_id,
                shown_at=_as_utc(impression.shown_at),
                feature_snapshot=_normalize_snapshot(
                    impression.feature_snapshot
                ),
                label=label,
            )
        )

    observed_feature_names = {
        name
        for example in examples
        for name, _ in example.feature_snapshot
    }
    feature_names = tuple(
        sorted(
            set(RECOMMENDATION_FEATURE_NAMES)
            | observed_feature_names
        )
    )
    return RankerDataset(
        feature_names=feature_names,
        examples=tuple(examples),
    )


def make_synthetic_ranker_dataset(
    *,
    user_count: int = 8,
    examples_per_user: int = 80,
    seed: int = 7,
) -> RankerDataset:
    """Create a reproducible multi-user dataset for pipeline smoke tests."""

    if user_count <= 1:
        raise ValueError("User count must be greater than one")
    if examples_per_user <= 1:
        raise ValueError("Examples per user must be greater than one")

    feature_names = RECOMMENDATION_FEATURE_NAMES
    random = Random(seed)
    start = datetime(2020, 1, 1, tzinfo=UTC)
    examples: list[RankerExample] = []
    for user_index in range(user_count):
        user_affinity = random.uniform(-1.2, 1.2)
        user_positive_count = random.uniform(0.0, 8.0)
        user_negative_count = random.uniform(0.0, 3.0)
        for item_index in range(examples_per_user):
            baseline_score = random.uniform(0.0, 1.0)
            mood_similarity = random.uniform(0.0, 1.0)
            embedding_similarity = random.uniform(0.0, 1.0)
            completion_rate = random.random()
            skip_rate = random.random() * 0.6
            log_play_count = random.uniform(0.0, 3.5)
            log_total_ms_played = random.uniform(0.0, 12.0)
            play_count = log_play_count
            total_ms_played = log_total_ms_played
            completion_count = completion_rate * max(play_count, 1.0)
            skip_count = skip_rate * max(play_count, 1.0)
            days_since_last_played = random.uniform(0.0, 90.0)
            has_history = float(play_count > 0.1)
            track_has_mood = float(mood_similarity > 0.2)
            position = float((item_index % 10) + 1)
            playlist_context_available = float(random.random() > 0.25)
            playlist_embedding_similarity = (
                random.random() * playlist_context_available
            )
            playlist_genre_similarity = (
                random.random() * playlist_context_available
            )
            playlist_mood_similarity = (
                random.random() * playlist_context_available
            )
            playlist_track_membership = float(
                playlist_context_available > 0.0
                and random.random() > 0.45
            )
            playlist_position = (
                random.random() * playlist_track_membership
            )
            logit = (
                0.6 * baseline_score
                + 0.5 * mood_similarity
                + 0.4 * embedding_similarity
                + 0.25 * playlist_mood_similarity
                + 0.2 * playlist_embedding_similarity
                + 0.15 * playlist_genre_similarity
                + 0.1 * playlist_track_membership
                + 0.7 * user_affinity
                + 0.45 * completion_rate
                + 0.2 * log_play_count
                - 0.9 * skip_rate
                + 0.08 * user_positive_count
                - 0.15 * user_negative_count
                - 0.04 * position
            )
            probability = 1.0 / (1.0 + exp(-logit))
            label = int(random.random() < probability)
            examples.append(
                RankerExample(
                    user_id=f"synthetic-user-{user_index}",
                    track_id=f"synthetic-track-{user_index}-{item_index}",
                    shown_at=start + timedelta(
                        days=item_index,
                        seconds=user_index,
                    ),
                    feature_snapshot=tuple(
                        sorted(
                            {
                                "baseline_score": baseline_score,
                                "embedding_similarity": (
                                    embedding_similarity
                                ),
                                "mood_similarity": mood_similarity,
                                "playlist_context_available": (
                                    playlist_context_available
                                ),
                                "playlist_embedding_similarity": (
                                    playlist_embedding_similarity
                                ),
                                "playlist_genre_similarity": (
                                    playlist_genre_similarity
                                ),
                                "playlist_mood_similarity": (
                                    playlist_mood_similarity
                                ),
                                "playlist_position": playlist_position,
                                "playlist_track_membership": (
                                    playlist_track_membership
                                ),
                                "position": position,
                                "popularity_score": baseline_score,
                                "spotify_completion_count": (
                                    completion_count
                                ),
                                "spotify_completion_rate": completion_rate,
                                "spotify_days_since_last_played": (
                                    days_since_last_played
                                ),
                                "spotify_has_history": has_history,
                                "spotify_log_play_count": log_play_count,
                                "spotify_log_total_ms_played": (
                                    log_total_ms_played
                                ),
                                "spotify_play_count": play_count,
                                "spotify_skip_count": skip_count,
                                "spotify_skip_rate": skip_rate,
                                "spotify_total_ms_played": total_ms_played,
                                "track_has_mood": track_has_mood,
                                "user_interaction_count_before_show": (
                                    user_positive_count + user_negative_count
                                ),
                                "user_negative_interaction_count_before_show": (
                                    user_negative_count
                                ),
                                "user_positive_interaction_count_before_show": (
                                    user_positive_count
                                ),
                                "user_track_interaction_count_before_show": 0.0,
                            }.items()
                        )
                    ),
                    label=label,
                )
            )
    return RankerDataset(
        feature_names=feature_names,
        examples=tuple(examples),
    )


def split_ranker_dataset_by_time(
    dataset: RankerDataset,
    *,
    train_fraction: float = 0.8,
) -> tuple[RankerDataset, RankerDataset]:
    """Split chronologically so validation never influences training time."""

    if not 0.0 < train_fraction < 1.0:
        raise ValueError("Train fraction must be between zero and one")
    ordered = tuple(
        sorted(
            dataset.examples,
            key=lambda example: (
                _as_utc(example.shown_at),
                example.user_id,
                example.track_id,
            ),
        )
    )
    split_index = max(
        1,
        min(len(ordered) - 1, round(len(ordered) * train_fraction)),
    )
    return (
        RankerDataset(dataset.feature_names, ordered[:split_index]),
        RankerDataset(dataset.feature_names, ordered[split_index:]),
    )


def _matches_impression(
    impression: RecommendationImpression,
    interaction: Interaction,
    *,
    event_time: datetime,
    window: timedelta,
) -> bool:
    shown_at = _as_utc(impression.shown_at)
    if impression.user_id != interaction.user_id:
        return False
    if impression.track_id != interaction.track_id:
        return False
    if (
        interaction.recommendation_session_id is not None
        and impression.session_id != interaction.recommendation_session_id
    ):
        return False
    return shown_at <= event_time <= shown_at + window


def _resolve_label(interactions: tuple[Interaction, ...] | list[Interaction]) -> int | None:
    labelled = [
        interaction
        for interaction in interactions
        if _interaction_name(interaction) in (
            POSITIVE_INTERACTION_TYPES | NEGATIVE_INTERACTION_TYPES
        )
    ]
    if not labelled:
        return None
    latest = max(labelled, key=lambda item: _as_utc(item.created_at))
    return int(_interaction_name(latest) in POSITIVE_INTERACTION_TYPES)


def _normalize_snapshot(
    snapshot: tuple[tuple[str, float], ...],
) -> tuple[tuple[str, float], ...]:
    return tuple(
        sorted((str(name), float(value)) for name, value in snapshot)
    )


def _interaction_name(interaction: Interaction) -> str:
    value = getattr(interaction.interaction_type, "value", interaction.interaction_type)
    return str(value).lower()


def _impression_sort_key(
    impression: RecommendationImpression,
) -> tuple[str, datetime, int]:
    return (
        impression.user_id,
        _as_utc(impression.shown_at),
        impression.position,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
