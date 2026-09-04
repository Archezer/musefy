from datetime import UTC, datetime, timedelta

from app.domain.models import Interaction, InteractionType, Track, User
from app.services.statistics import ListeningStatisticsService
from app.storage.memory import InMemoryMusicStore


def test_statistics_builds_completed_listens_and_daily_breakdown() -> None:
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Alex"))
    first = Track(
        id="first",
        title="First track",
        artist="Artist A",
        genres=("electronic",),
        duration_ms=180_000,
        created_at=now - timedelta(days=2),
    )
    second = Track(
        id="second",
        title="Second track",
        artist="Artist B",
        genres=("jazz",),
        duration_ms=240_000,
        created_at=now - timedelta(days=1),
    )
    store.add_track(first)
    store.add_track(second)
    store.add_interaction(
        Interaction("user-1", first.id, InteractionType.LISTEN, now - timedelta(days=1))
    )
    store.add_interaction(
        Interaction("user-1", first.id, InteractionType.LISTEN, now - timedelta(days=1, hours=1))
    )
    store.add_interaction(
        Interaction("user-1", second.id, InteractionType.SKIP, now - timedelta(days=1))
    )

    result = ListeningStatisticsService(store).build("user-1", now=now)

    assert result.completed_listens == 2
    assert result.listening_ms == 360_000
    assert result.active_days == 1
    assert result.top_tracks[0].label == "First track"
    assert result.top_tracks[0].count == 2
    assert result.favorite_artists[0].label == "Artist A"
    assert result.favorite_genres[0].label == "Electronic"
    assert result.skipped_tracks[0].label == "Second track"
    assert len(result.daily) == 30
    selected_day = next(item for item in result.daily if item.day == (now - timedelta(days=1)).date())
    assert selected_day.completed_listens == 2
    assert selected_day.skipped == 1
    assert selected_day.top_tracks[0].label == "First track"
    assert selected_day.top_genres[0].label == "Electronic"
    assert len(result.monthly) == 12
    assert result.monthly[-1].top_genre == "Electronic"
    assert result.monthly[-1].track_count == 1


def test_statistics_counts_new_completion_and_short_skip_events() -> None:
    now = datetime(2026, 9, 4, 12, tzinfo=UTC)
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Alex"))
    track = Track(
        id="track",
        title="Completed track",
        artist="Artist",
        genres=("electronic",),
        duration_ms=120_000,
    )
    store.add_track(track)
    store.add_interaction(
        Interaction(
            "user-1",
            track.id,
            InteractionType.PLAY_START,
            now,
        )
    )
    store.add_interaction(
        Interaction(
            "user-1",
            track.id,
            InteractionType.PLAYED_30S,
            now,
        )
    )
    store.add_interaction(
        Interaction(
            "user-1",
            track.id,
            InteractionType.COMPLETED_80,
            now,
        )
    )
    store.add_interaction(
        Interaction(
            "user-1",
            track.id,
            InteractionType.SKIP_UNDER_30S,
            now,
        )
    )

    result = ListeningStatisticsService(store).build("user-1", now=now)

    assert result.completed_listens == 1
    assert result.skipped_count == 1
    assert result.daily[-1].completed_listens == 1
    assert result.daily[-1].skipped == 1
