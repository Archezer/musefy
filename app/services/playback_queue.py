from collections import deque
from collections.abc import Iterable
from dataclasses import replace

from app.domain.models import PlaybackQueue, QueueMode


class PlaybackQueueService:
    def __init__(self, *, history_limit: int = 5) -> None:
        if history_limit < 1:
            raise ValueError("Queue history limit must be positive")

        self._queue: PlaybackQueue | None = None
        self._history = deque[str](maxlen=history_limit)

    @property
    def queue(self) -> PlaybackQueue | None:
        return self._queue

    def start(
        self,
        track_ids: Iterable[str],
        *,
        mode: QueueMode = QueueMode.NORMAL,
        source_playlist_id: str | None = None,
    ) -> PlaybackQueue:
        normalized_track_ids = self._normalize_track_ids(track_ids)

        if not normalized_track_ids:
            raise ValueError("Playback queue must contain at least one track")

        self._history.clear()
        self._queue = PlaybackQueue(
            current_track_id=normalized_track_ids[0],
            remaining_track_ids=normalized_track_ids[1:],
            mode=mode,
            source_playlist_id=source_playlist_id,
        )

        return self._queue

    def enqueue(self, track_id: str) -> PlaybackQueue:
        normalized_track_id = track_id.strip()

        if not normalized_track_id:
            raise ValueError("Track ID must not be empty")

        if self._queue is None:
            self._queue = PlaybackQueue(
                queued_track_ids=(normalized_track_id,),
            )
            return self._queue

        self._queue = replace(
            self._queue,
            queued_track_ids=(
                *self._queue.queued_track_ids,
                normalized_track_id,
            ),
        )

        return self._queue

    def advance(self) -> PlaybackQueue | None:
        if self._queue is None:
            return None

        if self._queue.current_track_id is not None:
            self._history.append(self._queue.current_track_id)

        if self._queue.queued_track_ids:
            next_track_id = self._queue.queued_track_ids[0]
            self._queue = replace(
                self._queue,
                current_track_id=next_track_id,
                queued_track_ids=self._queue.queued_track_ids[1:],
            )
            return self._queue

        if self._queue.remaining_track_ids:
            next_track_id = self._queue.remaining_track_ids[0]
            self._queue = replace(
                self._queue,
                current_track_id=next_track_id,
                remaining_track_ids=(
                    self._queue.remaining_track_ids[1:]
                ),
            )
            return self._queue

        self._queue = None
        return None

    def previous(self) -> PlaybackQueue | None:
        if not self._history:
            return None

        previous_track_id = self._history.pop()

        if self._queue is None:
            self._queue = PlaybackQueue(
                current_track_id=previous_track_id,
            )
            return self._queue

        current_track_id = self._queue.current_track_id
        remaining_track_ids = self._queue.remaining_track_ids
        if current_track_id is not None:
            remaining_track_ids = (
                current_track_id,
                *remaining_track_ids,
            )

        self._queue = replace(
            self._queue,
            current_track_id=previous_track_id,
            remaining_track_ids=remaining_track_ids,
        )
        return self._queue

    def clear(self) -> None:
        self._queue = None
        self._history.clear()

    def clear_upcoming(self) -> None:
        if self._queue is None:
            return

        if self._queue.current_track_id is None:
            self._queue = None
            return

        self._queue = replace(
            self._queue,
            remaining_track_ids=(),
            queued_track_ids=(),
        )

    def upcoming_track_ids(self) -> tuple[str, ...]:
        if self._queue is None:
            return ()

        return (
            self._queue.queued_track_ids
            + self._queue.remaining_track_ids
        )

    @staticmethod
    def _normalize_track_ids(
        track_ids: Iterable[str],
    ) -> tuple[str, ...]:
        normalized_track_ids = tuple(
            track_id.strip()
            for track_id in track_ids
        )

        if any(not track_id for track_id in normalized_track_ids):
            raise ValueError("Queue track IDs must not be empty")

        return normalized_track_ids
