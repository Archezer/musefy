from collections import deque
from collections.abc import Iterable
from dataclasses import replace

from app.domain.models import PlaybackQueue, QueueMode, RepeatMode


class PlaybackQueueService:
    def __init__(self, *, history_limit: int = 10) -> None:
        if history_limit < 1:
            raise ValueError("Queue history limit must be positive")

        self._queue: PlaybackQueue | None = None
        self._history = deque[str](maxlen=history_limit)
        self._repeat_mode = RepeatMode.OFF
        self._cycle_track_ids: tuple[str, ...] = ()
        self._cycle_queue_mode = QueueMode.NORMAL
        self._cycle_source_playlist_id: str | None = None

    @property
    def queue(self) -> PlaybackQueue | None:
        return self._queue

    @property
    def repeat_mode(self) -> RepeatMode:
        return self._repeat_mode

    def set_repeat_mode(self, mode: RepeatMode) -> RepeatMode:
        self._repeat_mode = mode
        return self._repeat_mode

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
        self._cycle_track_ids = normalized_track_ids
        self._cycle_queue_mode = mode
        self._cycle_source_playlist_id = source_playlist_id

        return self._queue

    def enqueue(self, track_id: str) -> PlaybackQueue:
        normalized_track_id = track_id.strip()

        if not normalized_track_id:
            raise ValueError("Track ID must not be empty")

        if self._queue is None:
            self._queue = PlaybackQueue(
                queued_track_ids=(normalized_track_id,),
            )
            self._cycle_track_ids = (normalized_track_id,)
            self._cycle_queue_mode = QueueMode.NORMAL
            self._cycle_source_playlist_id = None
            return self._queue

        self._queue = replace(
            self._queue,
            queued_track_ids=(
                *self._queue.queued_track_ids,
                normalized_track_id,
            ),
        )
        self._cycle_track_ids = (
            *self._cycle_track_ids,
            normalized_track_id,
        )

        return self._queue

    def jump_to(self, track_id: str) -> PlaybackQueue | None:
        """Make an upcoming track current and discard items before it.

        The queue panel displays the flattened playback order (manual items
        first, followed by the regular remaining sequence).  Selecting a row
        should move the playback cursor within that order, not rebuild a new
        library queue around the selected track.
        """

        normalized_track_id = track_id.strip()
        if not normalized_track_id or self._queue is None:
            return None

        if self._queue.current_track_id == normalized_track_id:
            return self._queue

        upcoming = self.upcoming_track_ids()
        try:
            selected_index = upcoming.index(normalized_track_id)
        except ValueError:
            return None

        if self._queue.current_track_id is not None:
            self._history.append(self._queue.current_track_id)

        self._queue = replace(
            self._queue,
            current_track_id=normalized_track_id,
            remaining_track_ids=upcoming[selected_index + 1 :],
            queued_track_ids=(),
        )
        return self._queue

    def append_remaining(
        self,
        track_ids: Iterable[str],
    ) -> PlaybackQueue | None:
        """Append automatic tracks after the current manual queue.

        ``queued_track_ids`` is deliberately left untouched so manually
        queued tracks continue to win in :meth:`advance`.
        """

        normalized_track_ids = self._normalize_track_ids(track_ids)
        if not normalized_track_ids:
            return self._queue

        if self._queue is None:
            unique_track_ids = tuple(dict.fromkeys(normalized_track_ids))
            self._queue = PlaybackQueue(
                remaining_track_ids=unique_track_ids,
            )
            self._cycle_track_ids = unique_track_ids
            self._cycle_queue_mode = QueueMode.NORMAL
            self._cycle_source_playlist_id = None
            return self._queue

        occupied_ids = {
            self._queue.current_track_id,
            *self._queue.remaining_track_ids,
            *self._queue.queued_track_ids,
        }
        additions = tuple(
            track_id
            for track_id in dict.fromkeys(normalized_track_ids)
            if track_id not in occupied_ids
        )
        if not additions:
            return self._queue

        self._queue = replace(
            self._queue,
            remaining_track_ids=(
                *self._queue.remaining_track_ids,
                *additions,
            ),
        )
        self._cycle_track_ids = (
            *self._cycle_track_ids,
            *additions,
        )
        return self._queue

    def restart_cycle(self) -> PlaybackQueue | None:
        """Restart the queue sequence retained for repeat-playlist mode."""

        if not self._cycle_track_ids:
            return None

        self._history.clear()
        self._queue = PlaybackQueue(
            current_track_id=self._cycle_track_ids[0],
            remaining_track_ids=self._cycle_track_ids[1:],
            mode=self._cycle_queue_mode,
            source_playlist_id=self._cycle_source_playlist_id,
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
        self._cycle_track_ids = ()
        self._cycle_queue_mode = QueueMode.NORMAL
        self._cycle_source_playlist_id = None

    def clear_upcoming(self) -> None:
        if self._queue is None:
            return

        if self._queue.current_track_id is None:
            self._queue = None
            self._cycle_track_ids = ()
            return

        self._queue = replace(
            self._queue,
            remaining_track_ids=(),
            queued_track_ids=(),
        )
        self._cycle_track_ids = (self._queue.current_track_id,)

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
