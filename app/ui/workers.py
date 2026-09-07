"""Qt worker objects used by the desktop window.

Workers keep slow I/O, model inference, and incremental rendering away from
the GUI thread.  They intentionally expose only Qt signals and small input
objects; the window remains responsible for deciding how results are shown.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, QThread, Signal
from PySide6.QtWidgets import QWidget

from app.domain.models import Track
from app.ml.cancellation import AnalysisCancelled
from app.services.library_maintenance import LibraryHealthService
from app.services.loudness import LoudnessAnalysisError, analyze_loudness
from app.services.mp3party_import import Mp3PartyCandidate
from app.services.soundcloud_import import SoundCloudCandidate
from app.services.youtube_import import OperationCancelled
from app.sources.spotify import SpotifyTrack
from app.sources.youtube import YouTubeCandidate
from app.ui.music_map import MapBuildResult, MusicMapWidget

if TYPE_CHECKING:
    from app.ml.genre_analysis import GenreAnalysisService


@dataclass(frozen=True)
class AlternativePlaylistSearchResult:
    """Candidates returned while searching failed playlist tracks elsewhere."""

    provider: str
    candidates: tuple[
        YouTubeCandidate | SoundCloudCandidate | Mp3PartyCandidate,
        ...,
    ]
    failed: tuple[tuple[SpotifyTrack, str], ...]
    failed_positions: tuple[int, ...]


class YouTubeTaskThread(QThread):
    """Run one cancellable import operation and report its outcome."""

    result_ready = Signal(object)
    error_occurred = Signal(str)
    cancelled = Signal()
    progress_updated = Signal(int, int)
    # completed, total, found, failed, current track title
    search_progress_updated = Signal(int, int, int, int, str)
    track_imported = Signal(object, object)

    def __init__(
        self,
        task: Callable[[], object],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.task = task
        self._cancel_event = Event()

    def cancel(self) -> None:
        """Request cooperative cancellation of the current operation."""

        self._cancel_event.set()
        self.requestInterruption()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set() or self.isInterruptionRequested()

    def run(self) -> None:
        if self.is_cancelled():
            self.cancelled.emit()
            return
        try:
            result = self.task()
        except OperationCancelled:
            self.cancelled.emit()
            return
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            message = str(error) or error.__class__.__name__
            self.error_occurred.emit(message)
        else:
            if self.is_cancelled():
                self.cancelled.emit()
            else:
                self.result_ready.emit(result)


class LibraryHealthTaskThread(QThread):
    """Keep slow decoding and fingerprinting outside the UI thread."""

    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(
        self,
        service: LibraryHealthService,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.service = service

    def run(self) -> None:
        try:
            result = self.service.scan()
        except (OSError, RuntimeError, ValueError) as error:
            self.error_occurred.emit(str(error) or error.__class__.__name__)
        else:
            self.result_ready.emit(result)


class WatchFolderTaskThread(QThread):
    """Run a watch-folder pass without blocking playback controls."""

    result_ready = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, task: Callable[[], object], parent: QWidget) -> None:
        super().__init__(parent)
        self.task = task

    def run(self) -> None:
        try:
            result = self.task()
        except (OSError, RuntimeError, ValueError) as error:
            self.error_occurred.emit(str(error) or error.__class__.__name__)
        else:
            self.result_ready.emit(result)


class GenreAnalysisSignals(QObject):
    result_ready = Signal(str, object)
    error_occurred = Signal(str, str)
    finished = Signal()


class LazyGenreAnalysisService:
    """Create the heavy ML service only inside the analysis worker."""

    def __init__(self, factory: Callable[[], GenreAnalysisService]) -> None:
        self._factory = factory
        self._service: GenreAnalysisService | None = None
        self._lock = Lock()

    def get(self) -> GenreAnalysisService:
        service = self._service
        if service is not None:
            return service

        with self._lock:
            service = self._service
            if service is None:
                service = self._factory()
                self._service = service
        return service

    def unload_idle_models(self) -> bool:
        service = self._service
        if service is None:
            return False
        return service.unload_idle_models()

    def unload(self) -> bool:
        """Release the shared model service immediately when it is safe."""

        with self._lock:
            service = self._service
            if service is None:
                return False
            service.unload()
        return True

    def set_gpu_optimized(self, enabled: bool) -> None:
        """Apply the GPU batching option when the service is already loaded."""

        service = self._service
        if service is not None:
            service.set_gpu_optimized(enabled)


class GenreAnalysisTask(QRunnable):
    """Analyze one track using the shared genre-analysis service."""

    def __init__(
        self,
        service: GenreAnalysisService | LazyGenreAnalysisService,
        track_id: str,
        audio_path: Path,
    ) -> None:
        super().__init__()

        self.service = service
        self.track_id = track_id
        self.audio_path = audio_path
        self.cancel_requested = Event()
        self.signals = GenreAnalysisSignals()

    def cancel(self) -> None:
        self.cancel_requested.set()

    def is_cancelled(self) -> bool:
        return self.cancel_requested.is_set()

    def run(self) -> None:
        try:
            if self.is_cancelled():
                return
            service = (
                self.service.get()
                if isinstance(self.service, LazyGenreAnalysisService)
                else self.service
            )
            if self.is_cancelled():
                return
            analysis_result = service.analyze_track_result(
                self.audio_path,
                is_cancelled=self.is_cancelled,
            )
        except AnalysisCancelled:
            return
        except (
            FileNotFoundError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            self.signals.error_occurred.emit(
                self.track_id,
                str(error),
            )
        # Keep the UI state recoverable even for an unexpected model/library
        # exception: an unhandled QRunnable error would leave the track pending.
        except Exception as error:  # noqa: BLE001
            self.signals.error_occurred.emit(
                self.track_id,
                str(error) or error.__class__.__name__,
            )
        else:
            if not self.is_cancelled():
                self.signals.result_ready.emit(
                    self.track_id,
                    analysis_result,
                )
        finally:
            self.signals.finished.emit()


class LoudnessAnalysisSignals(QObject):
    """Signals emitted by one background loudness measurement."""

    result_ready = Signal(str, object)
    error_occurred = Signal(str, str)
    finished = Signal(str)


class LoudnessAnalysisTask(QRunnable):
    """Measure one local track without blocking the playback controls."""

    def __init__(self, track_id: str, audio_path: Path) -> None:
        super().__init__()
        self.track_id = track_id
        self.audio_path = audio_path
        self.cancel_requested = Event()
        self.signals = LoudnessAnalysisSignals()

    def cancel(self) -> None:
        self.cancel_requested.set()

    def is_cancelled(self) -> bool:
        return self.cancel_requested.is_set()

    def run(self) -> None:
        try:
            if self.is_cancelled():
                return
            result = analyze_loudness(self.audio_path)
        except (
            FileNotFoundError,
            LoudnessAnalysisError,
            OSError,
            ValueError,
        ) as error:
            self.signals.error_occurred.emit(
                self.track_id,
                str(error) or error.__class__.__name__,
            )
        except Exception as error:  # noqa: BLE001
            self.signals.error_occurred.emit(
                self.track_id,
                str(error) or error.__class__.__name__,
            )
        else:
            if not self.is_cancelled():
                self.signals.result_ready.emit(self.track_id, result)
        finally:
            self.signals.finished.emit(self.track_id)


class MusicMapSignals(QObject):
    """Signals emitted by the background music-map builder."""

    result_ready = Signal(int, object)
    error_occurred = Signal(int, str)
    finished = Signal(int)


class MusicMapTask(QRunnable):
    """Build the expensive similarity map without blocking the UI thread."""

    def __init__(self, tracks: list[Track], generation: int) -> None:
        super().__init__()
        self.tracks = tuple(tracks)
        self.generation = generation
        self.signals = MusicMapSignals()

    def run(self) -> None:
        try:
            result: MapBuildResult = MusicMapWidget.build_map_data(
                list(self.tracks)
            )
        except (
            MemoryError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as error:
            self.signals.error_occurred.emit(
                self.generation,
                str(error) or error.__class__.__name__,
            )
        else:
            self.signals.result_ready.emit(self.generation, result)
        finally:
            self.signals.finished.emit(self.generation)


class RecommendationSignals(QObject):
    """Signals emitted while recommendations are calculated off the UI thread."""

    batch_ready = Signal(int, object)
    finished = Signal(int)
    error_occurred = Signal(int, str)


class RecommendationTask(QRunnable):
    """Calculate recommendations in small batches so playback stays responsive."""

    def __init__(
        self,
        fetcher: Callable[[], object],
        generation: int,
        *,
        batch_size: int = 5,
        cancellable_fetcher: Callable[[Callable[[], bool]], object]
        | None = None,
    ) -> None:
        super().__init__()
        self.fetcher = fetcher
        self.cancellable_fetcher = cancellable_fetcher
        self.generation = generation
        self.batch_size = max(1, batch_size)
        self.cancel_requested = Event()
        self.signals = RecommendationSignals()

    def cancel(self) -> None:
        self.cancel_requested.set()

    def is_cancelled(self) -> bool:
        """Return whether the producer should stop expensive work."""

        return self.cancel_requested.is_set()

    def run(self) -> None:
        if self.cancel_requested.is_set():
            return

        try:
            if self.cancellable_fetcher is not None:
                recommendations = list(
                    self.cancellable_fetcher(self.is_cancelled)
                )
            else:
                recommendations = list(self.fetcher())
        except Exception as error:
            # A cancellable recommender exits through RuntimeError once it
            # observes the flag.  Cancellation is an expected outcome, not a
            # user-visible failure.
            if self.cancel_requested.is_set():
                return
            self.signals.error_occurred.emit(
                self.generation,
                str(error) or error.__class__.__name__,
            )
            return

        for start in range(0, len(recommendations), self.batch_size):
            if self.cancel_requested.is_set():
                return

            self.signals.batch_ready.emit(
                self.generation,
                tuple(recommendations[start : start + self.batch_size]),
            )
            # Give the main thread a chance to paint each partial result.  The
            # first batch is therefore visible while the rest is still being
            # added to the sidebar/queue.
            QThread.msleep(20)

        self.signals.finished.emit(self.generation)
