import pytest

from app.domain.models import QueueMode
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
