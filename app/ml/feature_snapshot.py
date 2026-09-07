"""Canonical point-in-time features for recommendation impressions."""

from __future__ import annotations

from datetime import UTC, datetime
from math import sqrt

from app.domain.genres import track_genre_evidence
from app.domain.models import (
    InteractionType,
    Recommendation,
    SpotifyListeningStats,
    Track,
)
from app.domain.mood import MoodVector
from app.ml.spotify_features import build_spotify_listening_features
from app.storage.protocols import MusicStore

RECOMMENDATION_FEATURE_NAMES = (
    "baseline_score",
    "embedding_similarity",
    "mood_similarity",
    "playlist_context_available",
    "playlist_embedding_similarity",
    "playlist_genre_similarity",
    "playlist_mood_similarity",
    "playlist_position",
    "playlist_track_membership",
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
    playlist_id: str | None = None,
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
        _build_playlist_features(
            store,
            playlist_id=playlist_id,
            track=recommendation.track,
        )
    )
    features.update(
        build_spotify_listening_features(stats, now=timestamp)
    )
    return tuple(
        sorted(
            (name, float(features.get(name, 0.0)))
            for name in RECOMMENDATION_FEATURE_NAMES
        )
    )


def _build_playlist_features(
    store: MusicStore,
    *,
    playlist_id: str | None,
    track: Track,
) -> dict[str, float]:
    """Build frozen numeric context features for an active playlist."""

    if not playlist_id or store.get_playlist(playlist_id) is None:
        return {}

    entries = sorted(
        store.list_playlist_entries(playlist_id),
        key=lambda entry: entry.position,
    )
    playlist_tracks = [
        playlist_track
        for entry in entries
        if (playlist_track := store.get_track(entry.track_id)) is not None
    ]
    if not playlist_tracks:
        return {"playlist_context_available": 1.0}

    entry_positions = {
        entry.track_id: entry.position
        for entry in entries
    }
    track_position = entry_positions.get(track.id)
    features = {
        "playlist_context_available": 1.0,
        "playlist_track_membership": float(track_position is not None),
    }
    if track_position is not None:
        features["playlist_position"] = 1.0 - (
            track_position
            / max(len(entries) - 1, 1)
        )

    candidate_genres = dict(track_genre_evidence(track))
    playlist_genre_weights: dict[str, float] = {}
    for playlist_track in playlist_tracks:
        for label, relevance in track_genre_evidence(playlist_track):
            key = label.casefold()
            playlist_genre_weights[key] = (
                playlist_genre_weights.get(key, 0.0) + relevance
            )
    if candidate_genres and playlist_genre_weights:
        maximum_weight = max(playlist_genre_weights.values())
        candidate_weight = sum(candidate_genres.values())
        if maximum_weight > 0.0 and candidate_weight > 0.0:
            features["playlist_genre_similarity"] = sum(
                relevance
                * min(
                    1.0,
                    playlist_genre_weights.get(label.casefold(), 0.0)
                    / maximum_weight,
                )
                for label, relevance in candidate_genres.items()
            ) / candidate_weight

    mood_tracks = [
        playlist_track
        for playlist_track in playlist_tracks
        if playlist_track.mood is not None
    ]
    candidate_mood = track.mood
    if candidate_mood is not None and mood_tracks:
        average_mood = MoodVector(
            valence=sum(
                playlist_track.mood.valence
                for playlist_track in mood_tracks
                if playlist_track.mood is not None
            )
            / len(mood_tracks),
            arousal=sum(
                playlist_track.mood.arousal
                for playlist_track in mood_tracks
                if playlist_track.mood is not None
            )
            / len(mood_tracks),
        )
        features["playlist_mood_similarity"] = max(
            0.0,
            min(
                1.0,
                1.0 - candidate_mood.distance_to(average_mood) / sqrt(8.0),
            ),
        )

    candidate_embedding = track.track_embedding
    playlist_embeddings = [
        playlist_track.track_embedding
        for playlist_track in playlist_tracks
        if playlist_track.track_embedding is not None
        and candidate_embedding is not None
        and len(playlist_track.track_embedding) == len(candidate_embedding)
    ]
    if candidate_embedding is not None and playlist_embeddings:
        centroid = tuple(
            sum(embedding[index] for embedding in playlist_embeddings)
            / len(playlist_embeddings)
            for index in range(len(candidate_embedding))
        )
        cosine = _cosine_similarity(candidate_embedding, centroid)
        features["playlist_embedding_similarity"] = max(
            0.0,
            min(1.0, (cosine + 1.0) / 2.0),
        )

    return features


def _cosine_similarity(
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> float:
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (
        left_norm * right_norm
    )


def _interaction_name(interaction: object) -> str:
    interaction_type = getattr(interaction, "interaction_type", "")
    value = getattr(interaction_type, "value", interaction_type)
    return str(value).lower()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
