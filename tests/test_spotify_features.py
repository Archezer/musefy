from datetime import UTC, datetime, timedelta

from app.domain.models import SpotifyListeningStats
from app.ml.spotify_features import (
    build_spotify_listening_feature_map,
    build_spotify_listening_features,
)


def test_spotify_history_becomes_real_ranker_features() -> None:
    now = datetime(2026, 9, 7, 12, tzinfo=UTC)
    stats = SpotifyListeningStats(
        spotify_id="spotify-1",
        play_count=10,
        total_ms_played=900_000,
        first_played_at=now - timedelta(days=10),
        last_played_at=now - timedelta(days=2),
        completion_count=7,
        skip_count=2,
        imported_at=now,
    )

    features = build_spotify_listening_features(stats, now=now)

    assert features["spotify_play_count"] == 10.0
    assert features["spotify_total_ms_played"] == 900_000.0
    assert features["spotify_completion_count"] == 7.0
    assert features["spotify_skip_count"] == 2.0
    assert features["spotify_completion_rate"] == 0.7
    assert features["spotify_skip_rate"] == 0.2
    assert features["spotify_days_since_last_played"] == 2.0
    assert features["spotify_has_history"] == 1.0


def test_missing_history_is_not_a_negative_signal() -> None:
    stats = SpotifyListeningStats(spotify_id="spotify-unknown")

    features = build_spotify_listening_features(
        stats,
        now=datetime(2026, 9, 7, tzinfo=UTC),
    )

    assert features["spotify_has_history"] == 0.0
    assert features["spotify_completion_rate"] == 0.0
    assert features["spotify_skip_rate"] == 0.0
    assert features["spotify_play_count"] == 0.0


def test_feature_map_is_keyed_by_spotify_id() -> None:
    stats = SpotifyListeningStats(spotify_id="spotify-1", play_count=3)

    feature_map = build_spotify_listening_feature_map([stats])

    assert list(feature_map) == ["spotify-1"]
    assert feature_map["spotify-1"]["spotify_play_count"] == 3.0
