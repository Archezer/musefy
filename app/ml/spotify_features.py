"""Leakage-safe numeric features derived from Spotify listening statistics."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from app.domain.models import SpotifyListeningStats


def build_spotify_listening_features(
    stats: SpotifyListeningStats,
    *,
    now: datetime | None = None,
) -> dict[str, float]:
    """Convert one aggregate Spotify history row into ranker features.

    Raw counters are kept alongside bounded rates and log-scaled values so a
    future ranker can choose the appropriate representation without treating
    missing history as a negative label.
    """

    play_count = max(stats.play_count, 0)
    total_ms_played = max(stats.total_ms_played, 0)
    completion_count = max(stats.completion_count, 0)
    skip_count = max(stats.skip_count, 0)
    denominator = max(play_count, 1)
    reference_time = _as_utc(now or datetime.now(UTC))
    recency_days = 0.0
    if stats.last_played_at is not None:
        recency_days = max(
            (
                reference_time
                - _as_utc(stats.last_played_at)
            ).total_seconds()
            / 86_400.0,
            0.0,
        )

    return {
        "spotify_play_count": float(play_count),
        "spotify_total_ms_played": float(total_ms_played),
        "spotify_completion_count": float(completion_count),
        "spotify_skip_count": float(skip_count),
        "spotify_log_play_count": math.log1p(play_count),
        "spotify_log_total_ms_played": math.log1p(total_ms_played),
        "spotify_completion_rate": min(
            completion_count / denominator,
            1.0,
        ),
        "spotify_skip_rate": min(skip_count / denominator, 1.0),
        "spotify_days_since_last_played": recency_days,
        "spotify_has_history": 1.0 if play_count else 0.0,
    }


def build_spotify_listening_feature_map(
    stats_rows: list[SpotifyListeningStats],
    *,
    now: datetime | None = None,
) -> dict[str, dict[str, float]]:
    """Build ranker features keyed by Spotify track ID."""

    return {
        stats.spotify_id: build_spotify_listening_features(
            stats,
            now=now,
        )
        for stats in stats_rows
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
