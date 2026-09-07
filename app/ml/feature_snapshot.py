"""Canonical point-in-time features for recommendation impressions."""

from __future__ import annotations

from datetime import UTC, datetime

from app.domain.models import (
    InteractionType,
    Recommendation,
    SpotifyListeningStats,
)
from app.ml.spotify_features import build_spotify_listening_features
from app.storage.protocols import MusicStore

RECOMMENDATION_FEATURE_NAMES = (
    "baseline_score",
    "embedding_similarity",
    "mood_similarity",
    "popularity_score",
    "position",
    "spotify_completion_count",
    "spotify_completion_rate",
    "spotify_days_since_last_played",
    "spotify_has_history",
    "spotify_log_play_count",
    "spotify_log_total_ms_played",
    "spotify_play_count",
    "spotify_skip_count",
    "spotify_skip_rate",
    "spotify_total_ms_played",
    "track_has_mood",
    "user_interaction_count_before_show",
    "user_negative_interaction_count_before_show",
    "user_positive_interaction_count_before_show",
    "user_track_interaction_count_before_show",
)

POSITIVE_INTERACTION_NAMES = frozenset(
    {
        InteractionType.LIKE.value,
        InteractionType.PLAYED_30S.value,
        InteractionType.COMPLETED_80.value,
        InteractionType.LISTEN.value,
        InteractionType.REPEAT.value,
    }
)
NEGATIVE_INTERACTION_NAMES = frozenset(
    {
        InteractionType.DISLIKE.value,
        InteractionType.DO_NOT_RECOMMEND.value,
        InteractionType.SKIP.value,
        InteractionType.SKIP_UNDER_30S.value,
    }
)


def build_recommendation_feature_snapshot(
    store: MusicStore,
    *,
    user_id: str,
    recommendation: Recommendation,
    position: int,
    shown_at: datetime,
) -> tuple[tuple[str, float], ...]:
    """Build features using only data known when a recommendation is shown."""

    timestamp = _as_utc(shown_at)
    prior_interactions = [
        interaction
        for interaction in store.list_interactions(user_id=user_id)
        if _as_utc(interaction.created_at) <= timestamp
    ]
    track_interactions = [
        interaction
        for interaction in prior_interactions
        if interaction.track_id == recommendation.track.id
    ]
    positive_count = sum(
        _interaction_name(interaction) in POSITIVE_INTERACTION_NAMES
        for interaction in prior_interactions
    )
    negative_count = sum(
        _interaction_name(interaction) in NEGATIVE_INTERACTION_NAMES
        for interaction in prior_interactions
    )

    spotify_id = recommendation.track.source_id
    stats_by_id = {
        stats.spotify_id: stats
        for stats in store.list_spotify_listening_stats()
    }
    stats = stats_by_id.get(spotify_id) if spotify_id else None
    if stats is None:
        stats = SpotifyListeningStats(spotify_id=spotify_id or "unknown")

    features = {
        "baseline_score": float(recommendation.score),
        "embedding_similarity": float(
            recommendation.embedding_similarity or 0.0
        ),
        "mood_similarity": float(recommendation.mood_similarity or 0.0),
        "position": float(position),
        "popularity_score": float(recommendation.popularity_score or 0.0),
        "track_has_mood": float(recommendation.track.mood is not None),
        "user_interaction_count_before_show": float(
            len(prior_interactions)
        ),
        "user_negative_interaction_count_before_show": float(
            negative_count
        ),
        "user_positive_interaction_count_before_show": float(
            positive_count
        ),
        "user_track_interaction_count_before_show": float(
            len(track_interactions)
        ),
    }
    features.update(
        build_spotify_listening_features(stats, now=timestamp)
    )
    return tuple(
        sorted(
            (name, float(features.get(name, 0.0)))
            for name in RECOMMENDATION_FEATURE_NAMES
        )
    )


def _interaction_name(interaction: object) -> str:
    interaction_type = getattr(interaction, "interaction_type", "")
    value = getattr(interaction_type, "value", interaction_type)
    return str(value).lower()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
