"""Canonical point-in-time features for recommendation impressions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import sqrt

from app.domain.genres import track_genre_evidence
from app.domain.models import (
    Interaction,
    InteractionType,
    Recommendation,
    SpotifyListeningStats,
    SpotifyTrackMetadata,
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


@dataclass(frozen=True)
class RecommendationFeatureContext:
    """Data shared by all candidates shown in one recommendation batch."""

    shown_at: datetime
    prior_interactions: tuple[Interaction, ...]
    spotify_stats_by_id: Mapping[str, SpotifyListeningStats]
    spotify_metadata_by_title: Mapping[
        str, tuple[SpotifyTrackMetadata, ...]
    ] = field(default_factory=dict)
    playlist_id: str | None = None
    playlist_tracks: tuple[Track, ...] = ()
    playlist_entry_positions: Mapping[str, int] = field(default_factory=dict)
    playlist_size: int = 0


def build_recommendation_feature_context(
    store: MusicStore,
    *,
    user_id: str,
    shown_at: datetime,
    playlist_id: str | None = None,
    spotify_ids: Iterable[str] | None = None,
    tracks: Iterable[Track] | None = None,
) -> RecommendationFeatureContext:
    """Load point-in-time data once for a batch of recommendations."""

    timestamp = _as_utc(shown_at)
    prior_interactions = tuple(
        interaction
        for interaction in store.list_interactions(user_id=user_id)
        if _as_utc(interaction.created_at) <= timestamp
    )
    requested_spotify_ids = {
        spotify_id
        for spotify_id in (spotify_ids or ())
        if spotify_id
    }
    candidate_tracks = tuple(tracks or ())
    metadata_by_title: dict[str, list[SpotifyTrackMetadata]] = {}
    if candidate_tracks:
        candidate_titles = {
            _normalize_match_text(track.title)
            for track in candidate_tracks
            if _normalize_match_text(track.title)
        }
        for metadata in store.list_spotify_track_metadata():
            title_key = _normalize_match_text(metadata.title)
            if title_key in candidate_titles:
                metadata_by_title.setdefault(title_key, []).append(metadata)
                requested_spotify_ids.add(metadata.spotify_id)

    if spotify_ids is None and not candidate_tracks:
        stats_by_id = {
            stats.spotify_id: stats
            for stats in store.list_spotify_listening_stats()
        }
    else:
        stats_by_id = {}
        for spotify_id in sorted(requested_spotify_ids):
            stats = store.get_spotify_listening_stats(spotify_id)
            if stats is not None:
                stats_by_id[stats.spotify_id] = stats

    playlist_tracks: tuple[Track, ...] = ()
    playlist_entry_positions: dict[str, int] = {}
    playlist_size = 0
    if playlist_id and store.get_playlist(playlist_id) is not None:
        entries = sorted(
            store.list_playlist_entries(playlist_id),
            key=lambda entry: entry.position,
        )
        playlist_size = len(entries)
        playlist_entry_positions = {
            entry.track_id: entry.position
            for entry in entries
        }
        track_by_id = {
            track.id: track
            for track in store.list_tracks()
        }
        playlist_tracks = tuple(
            track_by_id[entry.track_id]
            for entry in entries
            if entry.track_id in track_by_id
        )

    return RecommendationFeatureContext(
        shown_at=timestamp,
        prior_interactions=prior_interactions,
        spotify_stats_by_id=stats_by_id,
        spotify_metadata_by_title={
            title: tuple(metadata_rows)
            for title, metadata_rows in metadata_by_title.items()
        },
        playlist_id=playlist_id,
        playlist_tracks=playlist_tracks,
        playlist_entry_positions=playlist_entry_positions,
        playlist_size=playlist_size,
    )


def build_recommendation_feature_snapshot(
    store: MusicStore,
    *,
    user_id: str,
    recommendation: Recommendation,
    position: int,
    shown_at: datetime,
    playlist_id: str | None = None,
    context: RecommendationFeatureContext | None = None,
) -> tuple[tuple[str, float], ...]:
    """Build features using only data known when a recommendation is shown."""

    timestamp = _as_utc(shown_at)
    if (
        context is None
        or context.shown_at != timestamp
        or context.playlist_id != playlist_id
    ):
        context = build_recommendation_feature_context(
            store,
            user_id=user_id,
            shown_at=timestamp,
            playlist_id=playlist_id,
            spotify_ids=(
                (recommendation.track.source_id,)
                if recommendation.track.source_id
                else ()
            ),
            tracks=(recommendation.track,),
        )

    prior_interactions = context.prior_interactions
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
    stats = context.spotify_stats_by_id.get(spotify_id) if spotify_id else None
    if stats is None:
        stats = _resolve_spotify_stats_for_track(
            recommendation.track,
            context,
        )
    if stats is None:
        stats = SpotifyListeningStats(spotify_id=spotify_id or "unknown")

    features = {
        "baseline_score": float(
            recommendation.baseline_score
            if recommendation.baseline_score is not None
            else recommendation.score
        ),
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
            context=context,
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
    context: RecommendationFeatureContext | None = None,
) -> dict[str, float]:
    """Build frozen numeric context features for an active playlist."""

    if not playlist_id:
        return {}

    if context is not None and context.playlist_id == playlist_id:
        playlist_tracks = list(context.playlist_tracks)
        entry_positions = dict(context.playlist_entry_positions)
        entries_count = context.playlist_size
    else:
        if store.get_playlist(playlist_id) is None:
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
        entry_positions = {
            entry.track_id: entry.position
            for entry in entries
        }
        entries_count = len(entries)

    if not playlist_tracks:
        return {"playlist_context_available": 1.0} if entries_count else {}

    track_position = entry_positions.get(track.id)
    features = {
        "playlist_context_available": 1.0,
        "playlist_track_membership": float(track_position is not None),
    }
    if track_position is not None:
        features["playlist_position"] = 1.0 - (
            track_position
            / max(entries_count - 1, 1)
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


def _resolve_spotify_stats_for_track(
    track: Track,
    context: RecommendationFeatureContext,
) -> SpotifyListeningStats | None:
    """Resolve Spotify history without persisting a cross-source link."""

    title_key = _normalize_match_text(track.title)
    for metadata in context.spotify_metadata_by_title.get(title_key, ()):
        if not _artists_match(track.artist, metadata.artist):
            continue
        if not _durations_match(track.duration_ms, metadata.duration_ms):
            continue
        stats = context.spotify_stats_by_id.get(metadata.spotify_id)
        if stats is not None:
            return stats
    return None


def _artists_match(left: str, right: str) -> bool:
    left_key = _normalize_match_text(left)
    right_key = _normalize_match_text(right)
    return bool(
        left_key
        and right_key
        and (
            left_key == right_key
            or left_key in right_key
            or right_key in left_key
        )
    )


def _durations_match(
    left_ms: int | None,
    right_ms: int | None,
) -> bool:
    if left_ms is None or right_ms is None:
        return True
    return abs(left_ms - right_ms) <= 5_000


def _normalize_match_text(value: str) -> str:
    return " ".join(
        "".join(character if character.isalnum() else " " for character in value)
        .casefold()
        .split()
    )


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
