import pytest

from app.domain.models import QueueMode, RepeatMode
from app.services.playback_queue import PlaybackQueueService


def test_manual_queue_has_priority_over_playlist() -> None:
    service = PlaybackQueueService()
    service.start(
        ("playlist-1", "playlist-2", "playlist-3"),
        mode=QueueMode.NORMAL,
        source_playlist_id="playlist-id",
    )
    service.enqueue("queued-1")
    service.enqueue("queued-2")

    assert service.upcoming_track_ids() == (
        "queued-1",
        "queued-2",
        "playlist-2",
        "playlist-3",
    )

    assert service.advance().current_track_id == "queued-1"
    assert service.advance().current_track_id == "queued-2"
    assert service.advance().current_track_id == "playlist-2"


def test_appended_recommendations_stay_behind_manual_queue() -> None:
    service = PlaybackQueueService()
    service.start(
        ("current", "recommendation-1"),
        mode=QueueMode.RECOMMENDATIONS,
    )
    service.enqueue("manual-1")

    service.append_remaining(
        ("recommendation-2", "current", "recommendation-2")
    )

    assert service.upcoming_track_ids() == (
        "manual-1",
        "recommendation-1",
        "recommendation-2",
    )
    assert service.advance().current_track_id == "manual-1"
    assert service.advance().current_track_id == "recommendation-1"
    assert service.advance().current_track_id == "recommendation-2"


def test_repeat_cycle_restores_the_started_sequence() -> None:
    service = PlaybackQueueService()
    service.start(
        ("track-1", "track-2", "track-3"),
        mode=QueueMode.SHUFFLE,
        source_playlist_id="playlist-id",
    )
    service.set_repeat_mode(RepeatMode.QUEUE)
    service.advance()
    service.advance()

    queue = service.restart_cycle()

    assert queue is not None
    assert queue.current_track_id == "track-1"
    assert queue.remaining_track_ids == ("track-2", "track-3")
    assert queue.mode == QueueMode.SHUFFLE
    assert queue.source_playlist_id == "playlist-id"


def test_enqueue_without_active_playback_waits_for_next() -> None:
    service = PlaybackQueueService()

    queue = service.enqueue("track-1")

    assert queue.current_track_id is None
    assert service.upcoming_track_ids() == ("track-1",)
    assert service.advance().current_track_id == "track-1"


def test_queue_ends_after_all_tracks_are_played() -> None:
    service = PlaybackQueueService()
    service.start(("track-1",))

    assert service.advance() is None
    assert service.queue is None


def test_previous_restores_the_last_played_track() -> None:
    service = PlaybackQueueService()
    service.start(("track-1", "track-2", "track-3"))

    service.advance()
    queue = service.previous()

    assert queue is not None
    assert queue.current_track_id == "track-1"
    assert service.upcoming_track_ids() == (
        "track-2",
        "track-3",
    )


def test_previous_after_queue_end_restores_the_last_track() -> None:
    service = PlaybackQueueService()
    service.start(("track-1",))
    service.advance()

    queue = service.previous()

    assert queue is not None
    assert queue.current_track_id == "track-1"


def test_previous_without_history_returns_none() -> None:
    assert PlaybackQueueService().previous() is None


def test_start_rejects_an_empty_queue() -> None:
    with pytest.raises(
        ValueError,
        match="Playback queue must contain at least one track",
    ):
        PlaybackQueueService().start(())


def test_previous_keeps_the_ten_most_recent_tracks() -> None:
    service = PlaybackQueueService()
    service.start(tuple(f"track-{index}" for index in range(1, 14)))

    for _ in range(12):
        assert service.advance() is not None

    previous_ids = []
    for _ in range(10):
        queue = service.previous()
        assert queue is not None
        assert queue.current_track_id is not None
        previous_ids.append(queue.current_track_id)

    assert previous_ids == [
        "track-12",
        "track-11",
        "track-10",
        "track-9",
        "track-8",
        "track-7",
        "track-6",
        "track-5",
        "track-4",
        "track-3",
    ]
    assert service.previous() is None


def test_history_limit_must_be_positive() -> None:
    with pytest.raises(
        ValueError,
        match="Queue history limit must be positive",
    ):
        PlaybackQueueService(history_limit=0)


def test_clear_upcoming_keeps_the_current_track() -> None:
    service = PlaybackQueueService()
    service.start(("current", "playlist-next"))
    service.enqueue("manual-next")

    service.clear_upcoming()

    assert service.queue is not None
    assert service.queue.current_track_id == "current"
    assert service.upcoming_track_ids() == ()
