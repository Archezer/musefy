import os
import random
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QRunnable,
    QSettings,
    QSize,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QKeyEvent,
    QKeySequence,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from app.domain.models import (
    DetectedGenre,
    InteractionType,
    Playlist,
    QueueMode,
    Recommendation,
    RepeatMode,
    Track,
)
from app.domain.mood import MOOD_PRESETS
from app.domain.recommendations import RecommendationContext
from app.ingestion.audio import (
    SUPPORTED_AUDIO_EXTENSIONS,
    AudioIngestionService,
)
from app.ingestion.metadata import read_audio_metadata
from app.ml.genre_analysis import (
    GenreAnalysisService,
    TrackAnalysisResult,
)
from app.ml.maest import (
    GenrePrediction,
)
from app.recommenders.similarity import TrackSimilarityIndex
from app.recommenders.smart_shuffle import SmartShuffleBuilder
from app.services.interactions import InteractionService
from app.services.library_maintenance import (
    LibraryBackupService,
    LibraryHealthReport,
    LibraryHealthService,
)
from app.services.mp3party_import import (
    Mp3PartyCandidate,
    Mp3PartyImportService,
    Mp3PartyPlaylistImportResult,
)
from app.services.playback_queue import PlaybackQueueService
from app.services.playlists import PlaylistManagementService
from app.services.recommendation_analytics import RecommendationAnalyticsService
from app.services.recommendations import RecommendationService
from app.services.soundcloud_import import (
    SoundCloudCandidate,
    SoundCloudImportService,
    SoundCloudPlaylist,
    SoundCloudPlaylistImportResult,
)
from app.services.spotify_fav_sync import (
    SpotifyFavSyncResult,
    SpotifyFavSyncService,
)
from app.services.statistics import ListeningStatisticsService
from app.services.tracks import TrackManagementService
from app.services.watch_folder import (
    WatchFolderReport,
    WatchFolderService,
)
from app.services.youtube_import import (
    DEFAULT_SEARCH_WORKERS,
    OperationCancelled,
    SpotifyPlaylistSearchResult,
    SpotifySearchResult,
    YouTubeImportService,
    YouTubePlaylistImportResult,
)
from app.sources.spotify import SpotifyTrack
from app.sources.youtube import YouTubeCandidate
from app.storage.database import create_database, engine
from app.storage.paths import DATA_DIR, PLAYLIST_EXPORTS_DIR
from app.storage.protocols import MusicStore
from app.ui.components import (
    CLEAR_ICON,
    HEART_ICON,
    HEART_LIKED_ICON,
    IMPORT_ICON,
    JSON_ICON,
    LIBRARY_ICON,
    LOCAL_FILE_ICON,
    LOG_ICON,
    MAP_ICON,
    NEXT_ICON,
    PAUSE_ICON,
    PLAY_ICON,
    PLAYLIST_SCROLL_LEFT_ICON,
    PLAYLIST_SCROLL_RIGHT_ICON,
    PREVIOUS_ICON,
    REPEAT_OFF_ICON,
    REPEAT_QUEUE_ICON,
    REPEAT_TRACK_ICON,
    SEARCH_ICON,
    SEQUENTIAL_ICON,
    SHUFFLE_ICON,
    SMART_SHUFFLE_ICON,
    SOUNDCLOUD_ICON,
    SPOTIFY_ICON,
    STATISTICS_ICON,
    VOLUME_ICON,
    YOUTUBE_ICON,
    CreatePlaylistCard,
    FadingVolumeSlider,
    HoverCircleMenuButton,
    HoverTableWidget,
    LibraryHeaderView,
    LiquidGlassPanel,
    MainLibraryCard,
    MarqueeLabel,
    MoodPlaylistCard,
    PlaylistCard,
    QueueDialog,
    RailIconButton,
    RoundedScrollBar,
    SvgIconButton,
    TrackIdentityWidget,
    TrackNumberPlayWidget,
    svg_icon,
    track_cover_pixmap,
)
from app.ui.dialogs import (
    ImportLogDialog,
    LibraryMaintenanceDialog,
    ListeningStatisticsDialog,
    PlaylistImportResultDialog,
    SpotifySettingsDialog,
    TrackMetadataDialog,
    YouTubeSearchDialog,
)
from app.ui.music_map import MusicMapWidget
from app.ui.theme import DARK_THEME

MAX_AUDIO_GAIN = 0.3432
DEFAULT_VOLUME_PERCENT = 50
DEFAULT_MASTER_VOLUME_PERCENT = 100
RECOMMENDATION_QUEUE_SIZE = 30
RECOMMENDATION_REFILL_THRESHOLD = 10
INITIAL_TRACK_BATCH_SIZE = 30
DEFERRED_TRACK_BATCH_SIZE = 30
QUEUE_RENDER_BATCH_SIZE = 12
QUEUE_RENDER_INTERVAL_MS = 12
# A carousel page never shows more than seven playlist-sized cards.  The
# navigation cards (Main library and Mood) count towards this limit, as does
# the Create playlist card on the last page.
PLAYLISTS_PER_PAGE = 7
PREVIOUS_RESTART_THRESHOLD_MS = 5_000
REPEAT_MODES = (
    RepeatMode.OFF,
    RepeatMode.QUEUE,
    RepeatMode.TRACK,
)
LIBRARY_PLAYBACK_MODES = (
    QueueMode.NORMAL,
    QueueMode.SHUFFLE,
    QueueMode.SMART_SHUFFLE,
)
MAP_MODES = ("background", "focus", "hidden")
MY_WAVE_SESSION_NAME = "my_wave"


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
    """Keep slow decoding and fingerprinting outside Qt's UI thread."""

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


class GenreAnalysisTask(QRunnable):
    def __init__(
        self,
        service: GenreAnalysisService,
        track_id: str,
        audio_path: Path,
    ) -> None:
        super().__init__()

        self.service = service
        self.track_id = track_id
        self.audio_path = audio_path
        self.signals = GenreAnalysisSignals()

    def run(self) -> None:
        try:
            analysis_result = self.service.analyze_track_result(
                self.audio_path
            )
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
        else:
            self.signals.result_ready.emit(
                self.track_id,
                analysis_result,
            )


class TrackBatchSignals(QObject):
    batch_ready = Signal(int, int, object)
    finished = Signal(int)


class TrackBatchTask(QRunnable):
    """Prepare deferred table batches without blocking the UI thread."""

    def __init__(
        self,
        tracks: list[Track],
        start_index: int,
        generation: int,
        batch_size: int,
    ) -> None:
        super().__init__()
        self.tracks = tuple(tracks)
        self.start_index = start_index
        self.generation = generation
        self.batch_size = batch_size
        self.cancel_requested = Event()
        self.signals = TrackBatchSignals()

    def cancel(self) -> None:
        self.cancel_requested.set()

    def run(self) -> None:
        for start in range(
            self.start_index,
            len(self.tracks),
            self.batch_size,
        ):
            if self.cancel_requested.is_set():
                return

            batch = self.tracks[start : start + self.batch_size]
            self.signals.batch_ready.emit(
                self.generation,
                start,
                batch,
            )
            # Let the main thread paint between batches so long libraries
            # appear progressively instead of freezing the window.
            QThread.msleep(8)

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
    ) -> None:
        super().__init__()
        self.fetcher = fetcher
        self.generation = generation
        self.batch_size = max(1, batch_size)
        self.cancel_requested = Event()
        self.signals = RecommendationSignals()

    def cancel(self) -> None:
        self.cancel_requested.set()

    def run(self) -> None:
        if self.cancel_requested.is_set():
            return

        try:
            recommendations = list(self.fetcher())
        except (OSError, RuntimeError, TypeError, ValueError) as error:
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


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: MusicStore,
        ingestion_service: AudioIngestionService,
        interaction_service: InteractionService,
        recommendation_service: RecommendationService,
        track_management_service: TrackManagementService,
        youtube_import_service: YouTubeImportService,
        soundcloud_import_service: SoundCloudImportService,
        mp3party_import_service: Mp3PartyImportService,
        playback_queue_service: PlaybackQueueService,
        playlist_management_service: PlaylistManagementService,
        user_id: str,
    ) -> None:
        super().__init__()

        self.store = store
        self.ingestion_service = ingestion_service
        self.interaction_service = interaction_service
        self.recommendation_service = recommendation_service
        self.track_management_service = (
            track_management_service
        )
        self.youtube_import_service = youtube_import_service
        self.spotify_fav_sync_service = SpotifyFavSyncService(
            youtube_import_service.spotify_provider
        )
        self.soundcloud_import_service = soundcloud_import_service
        self.mp3party_import_service = mp3party_import_service
        self.playback_queue_service = playback_queue_service
        self.playlist_management_service = (
            playlist_management_service
        )
        self.user_id = user_id
        self.selected_track_id: str | None = None
        self.selected_playlist_id: str | None = None
        self.selected_mood_name: str | None = None
        self.session_mood_name: str | None = None
        self.current_track_id: str | None = None
        self._current_track_listen_recorded = False
        self._current_track_played_30s_recorded = False
        self._current_track_played_ms = 0
        self._current_track_last_position_ms: int | None = None
        self._current_track_early_exit_recorded = False
        self._library_tracks: list[Track] = []
        self._track_scope_tracks: list[Track] = []
        self._visible_tracks: list[Track] = []
        self._library_search_query = ""
        self._track_table_generation = 0
        self._track_batch_task: TrackBatchTask | None = None
        self._library_sort_column: int | None = None
        self._library_sort_descending = False
        self._playlist_page_index = 0
        self._playlist_page_count = 1
        self._playlist_page_items: list[Playlist] = []
        self._playlist_page_specs: list[tuple[int, int, bool, bool, bool]] = [
            (0, 0, True, True, True)
        ]
        self._youtube_thread: YouTubeTaskThread | None = None
        self._youtube_thread_dialog: QDialog | None = None
        self._youtube_threads: set[YouTubeTaskThread] = set()
        self._library_health_thread: LibraryHealthTaskThread | None = None
        self._recommendation_task: RecommendationTask | None = None
        self._recommendation_generation = 0
        self._radio_recommendation_task: RecommendationTask | None = None
        self._radio_recommendation_generation = 0
        self._radio_recommendation_inflight = False
        self._radio_wait_attempts = 0
        self._radio_wait_seed_track_id: str | None = None
        self._queue_render_generation = 0
        self._queue_render_track_ids: tuple[str, ...] = ()
        self._queue_render_index = 0
        # Modeless dialogs use the native minimize button, but keeping their
        # minimized state in the app makes it possible to restore them without
        # hunting through the Windows taskbar.  Compact restore buttons are
        # inserted next to the top-right playlist menu.
        self._auxiliary_dialog_buttons: dict[QDialog, QToolButton] = {}
        self._auxiliary_minimized_container: QWidget | None = None
        self._auxiliary_minimized_layout: QHBoxLayout | None = None
        self._search_row: QWidget | None = None
        self._search_actions_container: QWidget | None = None
        self._spotify_sync_timer = QTimer(self)
        self._spotify_sync_timer.setInterval(5 * 60 * 1000)
        self._spotify_sync_timer.timeout.connect(
            self._start_background_spotify_sync
        )
        self._spotify_sync_timer.start()
        self._genre_statuses: dict[str, str] = {}
        self._genre_predictions: dict[str, object] = {}
        self._genre_batch_track_ids: set[str] = set()
        self._genre_batch_completed = 0
        self._genre_batch_total = 0
        self._analysis_pending_track_ids: set[str] = set()
        self._playlist_import_active = False
        self._music_map_mode = "background"
        self._liquid_glass_enabled = True
        self._playback_mode = QueueMode.NORMAL
        self._track_radio_enabled = False
        self._repeat_mode = RepeatMode.OFF
        self._player_duration_ms = 0
        self._volume_settings = QSettings("Musefy", "Musefy")
        self._master_volume_percent = self._clamp_master_volume_percent(
            self._volume_settings.value(
                "playback/master_volume_percent",
                DEFAULT_MASTER_VOLUME_PERCENT,
                type=int,
            )
        )
        self._genre_analysis_service = (
            GenreAnalysisService(
                top_k=10,
                min_score=0.1,
            )
        )
        self.library_health_service = LibraryHealthService(store)
        self.library_backup_service = LibraryBackupService(store)
        self.statistics_service = ListeningStatisticsService(store)
        self.recommendation_analytics_service = RecommendationAnalyticsService(
            store
        )
        self.watch_folder_service = WatchFolderService(store)
        self._watch_sync_thread: WatchFolderTaskThread | None = None
        self._watch_sync_dialog: LibraryMaintenanceDialog | None = None
        self._watch_folder_timer = QTimer(self)
        self._watch_folder_timer.setInterval(20_000)
        self._watch_folder_timer.timeout.connect(self._sync_watch_folder)
        self._watch_folder_timer.start()
        self._genre_analysis_pool = QThreadPool(self)
        self._genre_analysis_pool.setMaxThreadCount(
            self._genre_analysis_service.analysis_worker_count
        )
        self._track_batch_pool = QThreadPool(self)
        self._track_batch_pool.setMaxThreadCount(1)
        # Recommendation scoring can scan the whole library or lazily build
        # the similarity index.  Keep it off the GUI thread and let radio and
        # sidebar suggestions progress independently.
        self._recommendation_pool = QThreadPool(self)
        self._recommendation_pool.setMaxThreadCount(1)
        self._radio_recommendation_pool = QThreadPool(self)
        self._radio_recommendation_pool.setMaxThreadCount(1)
        self._model_idle_timer = QTimer(self)
        self._model_idle_timer.setInterval(60_000)
        self._model_idle_timer.timeout.connect(
            self._unload_idle_models
        )
        self._model_idle_timer.start()

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(
            self._output_volume(
                DEFAULT_VOLUME_PERCENT,
                self._master_volume_percent,
            )
        )

        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.errorOccurred.connect(
            self._handle_player_error
        )
        self.media_player.mediaStatusChanged.connect(
            self._handle_media_status_changed
        )
        self.media_player.positionChanged.connect(
            self._handle_player_position_changed
        )
        self.media_player.durationChanged.connect(
            self._handle_player_duration_changed
        )
        self.media_player.playbackStateChanged.connect(
            self._handle_playback_state_changed
        )

        self.setWindowTitle("Musefy")
        self.resize(1240, 800)
        self.setStyleSheet(DARK_THEME)

        self._build_interface()
        self._find_shortcut = QShortcut(
            QKeySequence("Ctrl+F"),
            self,
        )
        self._find_shortcut.setContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self._find_shortcut.setAutoRepeat(False)
        self._find_shortcut.activated.connect(
            self._focus_library_search
        )
        self._space_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Space),
            self,
        )
        self._space_shortcut.setContext(
            Qt.ShortcutContext.ApplicationShortcut
        )
        self._space_shortcut.setAutoRepeat(False)
        self._space_shortcut.activated.connect(self._toggle_playback)
        self._load_playlists()
        self._load_library(refresh_map=False)
        # Let Qt paint the main window before doing the expensive similarity
        # map layout.  The map still appears immediately after first paint,
        # but it no longer delays the window itself from opening.
        QTimer.singleShot(0, self._finish_initial_load)

    def _finish_initial_load(self) -> None:
        self._refresh_music_map(self._library_tracks)
        self._start_background_spotify_sync()

    def _build_interface(self) -> None:
        app_root = QWidget()
        app_root.setObjectName("appRoot")

        self.map_layer = QWidget(app_root)
        self.map_layer.setObjectName("mapLayer")
        self.map_layer.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        map_layout = QVBoxLayout(self.map_layer)
        map_layout.setContentsMargins(0, 0, 0, 0)
        self.music_map = MusicMapWidget(self.map_layer)
        self.music_map.track_activated.connect(
            self._select_track_from_map
        )
        self._map_blur = QGraphicsBlurEffect(self.music_map)
        self._map_blur.setBlurRadius(4.5)
        self.music_map.setGraphicsEffect(self._map_blur)
        map_layout.addWidget(self.music_map)
        self._map_opacity = QGraphicsOpacityEffect(self.map_layer)
        self._map_opacity.setOpacity(0.38)
        self.map_layer.setGraphicsEffect(self._map_opacity)
        self._map_opacity_animation = QPropertyAnimation(
            self._map_opacity,
            b"opacity",
            self,
        )
        self._map_opacity_animation.setDuration(260)
        self.map_layer.lower()

        self.content_overlay = QWidget(app_root)
        self.content_overlay.setObjectName("contentOverlay")
        self.content_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        content_layout = QVBoxLayout(self.content_overlay)
        content_layout.setContentsMargins(8, 8, 8, 78)
        content_layout.setSpacing(8)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        body_layout.setSpacing(0)

        sidebar = QFrame(body)
        sidebar.setObjectName("sidebar")
        rail_size = RailIconButton.BUTTON_SIZE
        sidebar_width = rail_size + 12
        sidebar_height = rail_size * 4 + 20
        # Keep the rail optically centered between the window top and the
        # selected playlist caption.  The transparent frame is intentionally
        # a little lower than the body origin so the two breathing spaces
        # balance out.
        sidebar_top_offset = 0
        sidebar.setFixedSize(sidebar_width, sidebar_height)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(6, 6, 6, 6)
        sidebar_layout.setSpacing(4)
        sidebar_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        import_button = RailIconButton(
            IMPORT_ICON,
            tooltip="Import music",
            variant="download",
            icon_size=RailIconButton.ICON_SIZE,
        )
        import_button.setObjectName("railButton")
        import_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        import_menu = QMenu(import_button)
        local_menu = import_menu.addMenu("Local audio")
        local_menu.setIcon(svg_icon(LOCAL_FILE_ICON))
        local_file_action = local_menu.addAction(
            "File",
            self._import_track,
        )
        local_file_action.setIcon(svg_icon(LOCAL_FILE_ICON))
        local_folder_action = local_menu.addAction(
            "Folder",
            self._import_folder,
        )
        local_folder_action.setIcon(svg_icon(LOCAL_FILE_ICON))
        youtube_action = import_menu.addAction("YouTube", self._import_from_youtube)
        youtube_action.setIcon(svg_icon(YOUTUBE_ICON))
        spotify_action = import_menu.addAction("Spotify", self._import_from_youtube)
        spotify_action.setIcon(svg_icon(SPOTIFY_ICON))
        soundcloud_action = import_menu.addAction(
            "SoundCloud",
            self._import_from_youtube,
        )
        soundcloud_action.setIcon(svg_icon(SOUNDCLOUD_ICON))
        exported_action = import_menu.addAction("Playlist JSON", self._import_exported_playlist)
        exported_action.setIcon(svg_icon(JSON_ICON))
        import_button.setMenu(import_menu)
        sidebar_layout.addWidget(import_button, 0, Qt.AlignmentFlag.AlignHCenter)

        library_button = RailIconButton(
            LIBRARY_ICON,
            tooltip="Library actions",
            variant="library",
            icon_size=RailIconButton.ICON_SIZE,
        )
        library_button.setObjectName("railButton")
        library_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        library_menu = QMenu(library_button)
        # Selection actions are kept as internal QAction objects because the
        # table/context controls still update their enabled state.  They are
        # intentionally not placed in this compact rail menu.
        self.edit_button = QAction("Edit selected", self)
        self.edit_button.triggered.connect(self._edit_selected_track)
        self.edit_button.setEnabled(False)
        self.delete_button = QAction("Delete selected", self)
        self.delete_button.triggered.connect(self._delete_selected_track)
        self.delete_button.setEnabled(False)
        self.queue_selected_button = QAction("Add selected to queue", self)
        self.queue_selected_button.triggered.connect(self._enqueue_selected_track)
        self.queue_selected_button.setEnabled(False)
        self.analyze_genres_button = QAction("Analyze selected", self)
        self.analyze_genres_button.triggered.connect(self._analyze_selected_track)
        self.analyze_genres_button.setEnabled(False)
        self.reanalyze_genres_button = library_menu.addAction(
            "Reanalyze library",
            self._reanalyze_all_genres
        )
        library_menu.addSeparator()
        library_menu.addAction(
            "Library health & backup…",
            self._open_library_maintenance,
        )
        import_log_action = library_menu.addAction(
            "Import log",
            self._show_import_log,
        )
        import_log_action.setIcon(svg_icon(LOG_ICON))
        library_menu.addSeparator()
        library_menu.addAction("Refresh", self._refresh_content)
        library_button.setMenu(library_menu)
        sidebar_layout.addWidget(library_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.map_cycle_button = RailIconButton(
            MAP_ICON,
            tooltip="Toggle the music graph background",
            variant="map",
            icon_size=RailIconButton.ICON_SIZE,
        )
        self.map_cycle_button.setObjectName("mapCycleButton")
        self.map_cycle_button.setProperty("railButton", True)
        self.map_cycle_button.clicked.connect(self._toggle_music_map)
        sidebar_layout.addWidget(self.map_cycle_button, 0, Qt.AlignmentFlag.AlignHCenter)

        self.statistics_button = RailIconButton(
            STATISTICS_ICON,
            tooltip="Listening statistics",
            variant="log",
            icon_size=RailIconButton.ICON_SIZE,
        )
        self.statistics_button.setObjectName("railButton")
        self.statistics_button.clicked.connect(self._show_statistics_dashboard)
        sidebar_layout.addWidget(
            self.statistics_button,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        sidebar_layout.addStretch(1)
        main_column = QWidget()
        main_layout = QVBoxLayout(main_column)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        search_row = QWidget()
        search_row_layout = QHBoxLayout(search_row)
        search_row_layout.setContentsMargins(0, 0, 0, 0)
        search_balance = QWidget()
        search_balance.setFixedWidth(54)
        search_row_layout.addWidget(search_balance)
        search_row_layout.addStretch(1)

        search_frame = QFrame()
        search_frame.setObjectName("librarySearch")
        search_frame.setFixedHeight(38)
        search_frame.setMinimumWidth(280)
        search_frame.setMaximumWidth(430)
        search_frame_layout = QHBoxLayout(search_frame)
        search_frame_layout.setContentsMargins(11, 0, 8, 0)
        search_frame_layout.setSpacing(7)

        search_icon = QLabel()
        search_icon.setPixmap(svg_icon(SEARCH_ICON, size=18).pixmap(18, 18))
        search_icon.setFixedSize(18, 18)
        search_icon.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        search_frame_layout.addWidget(search_icon)

        self.library_search_input = QLineEdit()
        self.library_search_input.setObjectName("librarySearchInput")
        self.library_search_input.setPlaceholderText(
            "Search title or artist"
        )
        self.library_search_input.setClearButtonEnabled(False)
        self.library_search_input.setToolTip(
            "Search title or artist (Ctrl+F)"
        )
        self.library_search_input.textChanged.connect(
            self._handle_library_search_changed
        )
        search_frame_layout.addWidget(self.library_search_input, 1)

        self.library_search_clear = QToolButton()
        self.library_search_clear.setObjectName("librarySearchClear")
        self.library_search_clear.setIcon(
            svg_icon(CLEAR_ICON, size=18)
        )
        self.library_search_clear.setIconSize(QSize(18, 18))
        self.library_search_clear.setToolTip("Clear search")
        self.library_search_clear.setAutoRaise(True)
        self.library_search_clear.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.library_search_clear.setFixedSize(26, 26)
        self.library_search_clear.clicked.connect(
            self.library_search_input.clear
        )
        self.library_search_clear.hide()
        search_frame_layout.addWidget(self.library_search_clear)

        search_row_layout.addWidget(search_frame)
        search_row_layout.addStretch(1)
        # Reserve the original top-right menu slot in the centering layout.
        # The actual controls are overlaid below, so minimized dialog chips
        # can grow without changing the search field's position.
        search_actions_spacer = QWidget()
        search_actions_spacer.setFixedWidth(32)
        search_row_layout.addWidget(search_actions_spacer)

        # Keep actions visually attached to the right edge without including
        # them in the search row's stretch calculation.  Otherwise a
        # minimized auxiliary dialog changes the amount of space on the right
        # and pulls the centered search field to the left.
        self._search_row = search_row
        self._search_actions_container = QWidget(search_row)
        self._search_actions_container.setObjectName(
            "searchActionsContainer"
        )
        self._search_actions_layout = QHBoxLayout(
            self._search_actions_container
        )
        self._search_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._search_actions_layout.setSpacing(6)

        self._auxiliary_minimized_container = QWidget(search_row)
        self._auxiliary_minimized_container.setObjectName(
            "auxiliaryMinimizedContainer"
        )
        self._auxiliary_minimized_layout = QHBoxLayout(
            self._auxiliary_minimized_container
        )
        self._auxiliary_minimized_layout.setContentsMargins(0, 0, 0, 0)
        self._auxiliary_minimized_layout.setSpacing(6)
        self._auxiliary_minimized_container.hide()
        self._search_actions_layout.addWidget(
            self._auxiliary_minimized_container,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self._search_actions_container.show()
        main_layout.addWidget(search_row, 0)

        playlist_strip = QFrame()
        playlist_strip.setObjectName("playlistStrip")
        playlist_strip_layout = QVBoxLayout(playlist_strip)
        # The main column already shares the outer 8px content inset with the
        # player bar; do not add the rail width a second time here.
        # The carousel cards are 104px high.  Moving their content start
        # down by 10px balances the gap below the cards against the gap under
        # the search row while keeping the strip's fixed outer height.
        playlist_strip_layout.setContentsMargins(0, 15, 9, 0)
        playlist_strip_layout.setSpacing(3)
        playlist_header = QHBoxLayout()
        playlist_header.setContentsMargins(0, 0, 0, 0)
        playlist_header.setSpacing(4)
        playlist_header.addStretch()

        playlist_menu_button = HoverCircleMenuButton()
        playlist_menu_button.setObjectName("plainActionButton")
        playlist_menu_button.setText("•••")
        playlist_menu_button.setToolTip("Playlist actions")
        playlist_menu_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        playlist_menu = QMenu(playlist_menu_button)
        playlist_menu.addAction("New playlist", self._create_playlist)
        playlist_menu.addAction("Rename playlist", self._rename_playlist)
        playlist_menu.addAction("Change artwork", self._set_playlist_cover)
        playlist_menu.addAction("Delete playlist", self._delete_playlist)
        playlist_menu.addSeparator()
        playlist_menu.addAction(
            "Add selected track",
            self._add_selected_track_to_playlist,
        )
        playlist_menu.addAction(
            "Remove selected playlist track",
            self._remove_selected_playlist_track,
        )
        playlist_menu.addSeparator()
        master_volume_menu = playlist_menu.addMenu("Master volume")
        master_volume_widget = QWidget(master_volume_menu)
        master_volume_widget.setMinimumWidth(212)
        master_volume_layout = QVBoxLayout(master_volume_widget)
        master_volume_layout.setContentsMargins(12, 10, 12, 10)
        master_volume_layout.setSpacing(6)
        self.master_volume_label = QLabel(master_volume_widget)
        master_volume_layout.addWidget(self.master_volume_label)
        self.master_volume_slider = QSlider(
            Qt.Orientation.Horizontal,
            master_volume_widget,
        )
        self.master_volume_slider.setRange(0, 100)
        self.master_volume_slider.setValue(self._master_volume_percent)
        self.master_volume_slider.valueChanged.connect(
            self._set_master_volume_percent
        )
        master_volume_layout.addWidget(self.master_volume_slider)
        self._update_master_volume_label()
        master_volume_action = QWidgetAction(master_volume_menu)
        master_volume_action.setDefaultWidget(master_volume_widget)
        master_volume_menu.addAction(master_volume_action)
        self.liquid_glass_action = playlist_menu.addAction(
            "Liquid glass panels",
        )
        self.liquid_glass_action.setCheckable(True)
        self.liquid_glass_action.setChecked(self._liquid_glass_enabled)
        self.liquid_glass_action.toggled.connect(
            self._set_liquid_glass_enabled
        )
        playlist_menu.addSeparator()
        playlist_menu.addAction(
            "Spotify settings",
            lambda: self._open_spotify_settings(),
        )
        playlist_menu.addSeparator()
        playlist_menu.addAction(
            "Reload application code",
            self._restart_application,
        )
        playlist_menu_button.setMenu(playlist_menu)
        playlist_menu_button.setProperty("topMenu", True)
        playlist_menu_button.setFixedSize(32, 32)
        self._search_actions_layout.addWidget(
            playlist_menu_button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        # The shared plain-action stylesheet intentionally removes minimum
        # sizes; restore a square hit area for the top-right menu button.
        playlist_menu_button.setMinimumSize(32, 32)
        QTimer.singleShot(0, self._position_search_actions)
        playlist_strip_layout.addLayout(playlist_header)

        self.playlist_scroll = QScrollArea()
        self.playlist_scroll.setHorizontalScrollBar(
            RoundedScrollBar(Qt.Orientation.Horizontal)
        )
        self.playlist_scroll.setWidgetResizable(True)
        self.playlist_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.playlist_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.playlist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.playlist_scroll.viewport().setAutoFillBackground(False)

        self.playlist_scroll_left_button = QToolButton()
        self.playlist_scroll_left_button.setObjectName(
            "playlistScrollButton"
        )
        self.playlist_scroll_left_button.setIcon(
            svg_icon(PLAYLIST_SCROLL_LEFT_ICON, size=24)
        )
        self.playlist_scroll_left_button.setIconSize(QSize(24, 24))
        self.playlist_scroll_left_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.playlist_scroll_left_button.setToolTip("Scroll playlists left")
        self.playlist_scroll_left_button.setFixedSize(32, 42)
        self.playlist_scroll_left_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.playlist_scroll_left_button.clicked.connect(
            lambda: self._scroll_playlists(-1)
        )
        self.playlist_scroll_left_button.hide()

        self.playlist_scroll_right_button = QToolButton()
        self.playlist_scroll_right_button.setObjectName(
            "playlistScrollButton"
        )
        self.playlist_scroll_right_button.setIcon(
            svg_icon(PLAYLIST_SCROLL_RIGHT_ICON, size=24)
        )
        self.playlist_scroll_right_button.setIconSize(QSize(24, 24))
        self.playlist_scroll_right_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.playlist_scroll_right_button.setToolTip(
            "Scroll playlists right"
        )
        self.playlist_scroll_right_button.setFixedSize(32, 42)
        self.playlist_scroll_right_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.playlist_scroll_right_button.clicked.connect(
            lambda: self._scroll_playlists(1)
        )
        self.playlist_scroll_right_button.hide()

        self.playlist_carousel = QWidget()
        self.playlist_carousel.setAutoFillBackground(False)
        self.playlist_carousel.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.playlist_carousel_layout = QHBoxLayout(self.playlist_carousel)
        # Match the search row's visual center.  The smaller inset keeps the
        # card group (and its optional navigation arrows) from drifting right.
        self.playlist_carousel_layout.setContentsMargins(20, 0, 0, 0)
        # Keep the carousel compact while preserving a small breathing space
        # between the card surfaces.
        self.playlist_carousel_layout.setSpacing(-16)
        self.playlist_scroll.setWidget(self.playlist_carousel)

        playlist_scroll_container = QWidget()
        playlist_scroll_container.setObjectName("playlistScrollContainer")
        playlist_scroll_container_layout = QHBoxLayout(
            playlist_scroll_container
        )
        playlist_scroll_container_layout.setContentsMargins(0, 0, 0, 0)
        playlist_scroll_container_layout.setSpacing(0)
        playlist_scroll_container_layout.addWidget(self.playlist_scroll, 1)
        self._playlist_scroll_container = playlist_scroll_container
        # Navigation controls float above the scroll area.  They must not be
        # children of the carousel layout, otherwise their appearance changes
        # the available width and moves the centered card group.
        self.playlist_scroll_left_button.setParent(playlist_scroll_container)
        self.playlist_scroll_right_button.setParent(playlist_scroll_container)
        self._position_playlist_navigation()
        playlist_strip_layout.addWidget(playlist_scroll_container)

        playlist_scroll_bar = self.playlist_scroll.horizontalScrollBar()
        self._playlist_scroll_animation = QPropertyAnimation(
            playlist_scroll_bar,
            b"value",
            self,
        )
        self._playlist_scroll_animation.setDuration(360)
        self._playlist_scroll_animation.setEasingCurve(
            QEasingCurve(QEasingCurve.Type.InOutCubic)
        )
        playlist_scroll_bar.valueChanged.connect(
            self._update_playlist_scroll_buttons
        )
        playlist_scroll_bar.rangeChanged.connect(
            lambda _minimum, _maximum: self._update_playlist_scroll_buttons()
        )
        self._update_playlist_scroll_buttons()
        QTimer.singleShot(0, self._position_playlist_navigation)
        # Leave enough vertical room for the cover and its caption; the old
        # viewport was a few pixels shorter than the card itself.
        playlist_strip.setFixedHeight(140)
        main_layout.addWidget(playlist_strip)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        library_widget = self._build_library_panel()
        self._library_panel = library_widget
        self.playlist_list = QListWidget(app_root)
        self.playlist_list.itemSelectionChanged.connect(
            self._handle_playlist_selection
        )
        self.playlist_list.hide()
        self.playlist_track_list = QListWidget(app_root)
        self.playlist_track_list.hide()
        queue_panel = self._build_queue_panel()
        self._queue_panel = queue_panel

        splitter.addWidget(library_widget)
        splitter.addWidget(queue_panel)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 285])
        main_layout.addWidget(splitter, 1)
        body_layout.addWidget(main_column, 1)
        sidebar.setGeometry(
            0,
            sidebar_top_offset,
            sidebar_width,
            sidebar_height,
        )
        sidebar.raise_()
        content_layout.addWidget(body, 1)
        self._content_body = body
        self._content_body_opacity = QGraphicsOpacityEffect(body)
        self._content_body_opacity.setOpacity(1.0)
        body.setGraphicsEffect(self._content_body_opacity)
        self._content_body_opacity_animation = QPropertyAnimation(
            self._content_body_opacity,
            b"opacity",
            self,
        )
        self._content_body_opacity_animation.setDuration(300)

        self._map_blur_animation = QPropertyAnimation(
            self._map_blur,
            b"blurRadius",
            self,
        )
        self._map_blur_animation.setDuration(300)
        self._player_bar = self._build_player_bar()
        self._player_bar.setParent(app_root)
        self._player_bar.show()
        self.map_exit_button = RailIconButton(
            MAP_ICON,
            tooltip="Return to library",
            variant="map",
            icon_size=RailIconButton.ICON_SIZE,
            parent=app_root,
        )
        self.map_exit_button.setObjectName("mapExitButton")
        self.map_exit_button.clicked.connect(
            lambda: self._set_music_map_mode("background")
        )
        self.map_exit_button.hide()
        self.queue_dialog = QueueDialog(self)
        self.queue_dialog.track_play_requested.connect(
            self._play_queued_track
        )
        self.setCentralWidget(app_root)
        self.statusBar().showMessage("Ready")
        self.statusBar().hide()
        self._set_music_map_mode("background", animated=False)

    def _build_player_bar(self) -> QFrame:
        player_bar = QFrame()
        self._player_bar = player_bar
        player_bar.setObjectName("playerBar")
        player_bar.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        player_bar.customContextMenuRequested.connect(
            self._show_current_track_context_menu
        )
        layout = QHBoxLayout(player_bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        self.player_cover = QLabel("♫")
        self.player_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.player_cover.setFixedSize(38, 38)
        self.player_cover.setStyleSheet(
            "background: #2A2A2D; border-radius: 10px; color: #D8D8D8;"
        )
        layout.addWidget(self.player_cover)

        metadata_layout = QVBoxLayout()
        metadata_layout.setContentsMargins(0, 2, 0, 0)
        metadata_layout.setSpacing(0)
        self.player_title_label = MarqueeLabel("Nothing playing")
        self.player_title_label.setObjectName("playerTitle")
        self.player_title_label.setFixedHeight(18)
        self.player_artist_label = QLabel("Choose a track or playlist")
        self.player_artist_label.setObjectName("playerArtist")
        self.player_artist_label.setFixedHeight(14)
        metadata_layout.addWidget(self.player_title_label)
        metadata_layout.addWidget(self.player_artist_label)
        layout.addLayout(metadata_layout, 2)

        center_layout = QVBoxLayout()
        center_layout.setSpacing(1)
        control_layout = QHBoxLayout()
        control_layout.setSpacing(4)
        control_layout.addStretch()

        self.playback_mode_button = SvgIconButton(
            SEQUENTIAL_ICON,
            tooltip="Playback order: sequential",
            diameter=30,
            flat=True,
            icon_offset_y=1,
            parent=player_bar,
        )
        self.playback_mode_button.clicked.connect(
            self._cycle_playback_mode
        )
        control_layout.addWidget(
            self.playback_mode_button,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )

        previous_button = SvgIconButton(
            PREVIOUS_ICON,
            tooltip="Previous track",
            diameter=36,
            flat=True,
            icon_offset_y=-1,
            parent=player_bar,
        )
        previous_button.clicked.connect(self._go_previous)
        control_layout.addWidget(
            previous_button,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )

        self.player_play_button = SvgIconButton(
            PLAY_ICON,
            tooltip="Play or pause",
            diameter=48,
            flat=True,
            icon_offset_y=-7,
            flat_background_inset=7,
            parent=player_bar,
        )
        self.player_play_button.clicked.connect(self._toggle_playback)
        control_layout.addWidget(
            self.player_play_button,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )

        next_button = SvgIconButton(
            NEXT_ICON,
            tooltip="Next track",
            diameter=36,
            flat=True,
            icon_offset_y=-1,
            parent=player_bar,
        )
        next_button.clicked.connect(self._go_next)
        control_layout.addWidget(
            next_button,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )

        self.repeat_button = SvgIconButton(
            REPEAT_OFF_ICON,
            tooltip="Repeat: off",
            diameter=32,
            flat=True,
            parent=player_bar,
        )
        self.repeat_button.clicked.connect(
            self._cycle_repeat_mode
        )
        control_layout.addWidget(
            self.repeat_button,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        control_layout.addStretch()
        center_layout.addLayout(control_layout)

        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(6)
        self.player_position_label = QLabel("0:00")
        self.player_duration_label = QLabel("0:00")
        self.player_progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.player_progress_slider.setObjectName("playerProgressSlider")
        self.player_progress_slider.setRange(0, 1000)
        self.player_progress_slider.sliderReleased.connect(self._seek_player)
        progress_layout.addWidget(self.player_position_label)
        progress_layout.addWidget(self.player_progress_slider, 1)
        progress_layout.addWidget(self.player_duration_label)
        center_layout.addLayout(progress_layout)
        layout.addLayout(center_layout, 5)

        next_track_layout = QVBoxLayout()
        next_track_layout.setContentsMargins(0, 4, 0, 0)
        next_track_layout.setSpacing(0)
        next_caption = QLabel("Next")
        next_caption.setObjectName("nextTrackCaption")
        self.next_track_title_label = MarqueeLabel("Nothing next")
        self.next_track_title_label.setObjectName("nextTrackTitle")
        self.next_track_artist_label = QLabel("")
        self.next_track_artist_label.setObjectName("nextTrackArtist")
        next_track_layout.addWidget(next_caption)
        next_track_layout.addWidget(self.next_track_title_label)
        next_track_layout.addWidget(self.next_track_artist_label)
        layout.addLayout(next_track_layout, 1)

        self.like_button = SvgIconButton(
            HEART_ICON,
            tooltip="Like current track",
            diameter=30,
            flat=True,
            parent=player_bar,
        )
        self.like_button.clicked.connect(self._toggle_like_current_track)
        layout.addWidget(self.like_button)

        player_menu_button = HoverCircleMenuButton(parent=player_bar)
        player_menu_button.setObjectName("plainActionButton")
        player_menu_button.setProperty("topMenu", True)
        player_menu_button.setText("•••")
        player_menu_button.setToolTip("Playback actions")
        player_menu_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        player_menu = QMenu(player_menu_button)
        player_menu.addAction(
            "Skip and tune recommendations",
            self._skip_current_track,
        )
        player_menu.addAction(
            "Not now (14 days)",
            self._snooze_current_track,
        )
        player_menu.addAction(
            "Dislike current track",
            self._dislike_current_track,
        )
        player_menu.addAction(
            "Don't recommend current track",
            self._do_not_recommend_current_track,
        )
        player_menu.addAction(
            "Allow recommendations again",
            self._allow_recommend_current_track,
        )
        self.track_radio_action = player_menu.addAction(
            "Track radio",
        )
        self.track_radio_action.setCheckable(True)
        self.track_radio_action.setChecked(self._track_radio_enabled)
        self.track_radio_action.toggled.connect(
            self._set_track_radio_enabled
        )
        player_menu.addAction("Stop playback", self._stop_playback)
        player_menu.addAction("Save current track", self._save_current_track)
        player_menu_button.setMenu(player_menu)
        layout.addWidget(player_menu_button)

        volume_button = SvgIconButton(
            VOLUME_ICON,
            tooltip="Volume",
            diameter=30,
            flat=True,
            parent=player_bar,
        )
        volume_button.setEnabled(False)
        layout.addWidget(volume_button)

        self.volume_slider = FadingVolumeSlider()
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setFixedWidth(96)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(DEFAULT_VOLUME_PERCENT)
        self.volume_slider.valueChanged.connect(self._handle_volume_changed)
        layout.addWidget(self.volume_slider)

        self._update_playback_mode_controls()
        self._update_like_button()
        player_bar.setFixedHeight(62)
        return player_bar

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "content_overlay"):
            return

        root_rect = self.centralWidget().rect()
        self.map_layer.setGeometry(root_rect)
        self.content_overlay.setGeometry(root_rect)
        if hasattr(self, "_player_bar"):
            bar_height = self._player_bar.height()
            self._player_bar.setGeometry(
                8,
                root_rect.height() - bar_height - 8,
                max(0, root_rect.width() - 16),
                bar_height,
            )
        if hasattr(self, "map_exit_button"):
            self.map_exit_button.setGeometry(
                16,
                16,
                RailIconButton.BUTTON_SIZE,
                RailIconButton.BUTTON_SIZE,
            )
        self._position_search_actions()
        self._position_playlist_navigation()

    def _position_search_actions(self) -> None:
        """Pin top-row actions to the right without affecting search centering."""

        row = self._search_row
        container = self._search_actions_container
        if row is None or container is None:
            return

        layout = container.layout()
        if layout is not None:
            layout.activate()
            width = layout.sizeHint().width()
        else:
            width = container.sizeHint().width()
        width = max(0, width)
        if width <= 0:
            return
        container.setGeometry(
            max(0, row.width() - width),
            0,
            width,
            row.height(),
        )
        container.raise_()

    def _position_playlist_navigation(self) -> None:
        """Keep optional carousel arrows close to the visible card group."""

        container = getattr(self, "_playlist_scroll_container", None)
        if container is None:
            return

        self.playlist_carousel_layout.activate()
        button_width = self.playlist_scroll_left_button.width()
        button_height = self.playlist_scroll_left_button.height()
        top = max(0, (container.height() - button_height) // 2)

        card_widgets = [
            item.widget()
            for index in range(self.playlist_carousel_layout.count())
            if (item := self.playlist_carousel_layout.itemAt(index)) is not None
            and item.widget() is not None
        ]
        if card_widgets:
            visible_card_bounds = []
            for card in card_widgets:
                geometry = card.geometry()
                mapped_left = self.playlist_carousel.mapTo(
                    container,
                    QPoint(geometry.left(), geometry.center().y()),
                ).x()
                mapped_right = self.playlist_carousel.mapTo(
                    container,
                    QPoint(geometry.right(), geometry.center().y()),
                ).x()
                if mapped_right > 0 and mapped_left < container.width():
                    visible_card_bounds.append(
                        (
                            max(0, mapped_left),
                            min(container.width(), mapped_right),
                        )
                    )

            if visible_card_bounds:
                first_left = min(
                    bounds[0] for bounds in visible_card_bounds
                )
                last_right = max(
                    bounds[1] for bounds in visible_card_bounds
                )
            else:
                first_left = 0
                last_right = container.width()
            navigation_gap = 14
            left_x = first_left - button_width - navigation_gap
            right_x = last_right + navigation_gap
        else:
            left_x = 4
            right_x = container.width() - button_width - 4

        max_x = max(0, container.width() - button_width)
        self.playlist_scroll_left_button.setGeometry(
            max(0, min(max_x, left_x)),
            top,
            button_width,
            button_height,
        )
        self.playlist_scroll_right_button.setGeometry(
            max(0, min(max_x, right_x)),
            top,
            button_width,
            button_height,
        )
        self.playlist_scroll_left_button.raise_()
        self.playlist_scroll_right_button.raise_()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() == Qt.Key.Key_Escape
            and getattr(self, "_music_map_mode", "background") == "focus"
        ):
            self._set_music_map_mode("background")
            return
        super().keyPressEvent(event)

    def _set_music_map_mode(
        self,
        mode: str,
        *,
        animated: bool = True,
    ) -> None:
        if mode not in MAP_MODES:
            raise ValueError(f"Unknown music map mode: {mode}")

        self._music_map_mode = mode
        self.music_map.set_mode(mode)
        self.map_cycle_button.setToolTip(
            {
                "background": "Open interactive music graph",
                "focus": "Return to library",
                "hidden": "Show music graph background",
            }[mode]
        )

        target_opacity = {
            "background": 0.34,
            "focus": 0.96,
            "hidden": 0.0,
        }[mode]
        target_body_opacity = 0.0 if mode == "focus" else 1.0
        target_blur_radius = 0.0 if mode == "focus" else 4.5
        self.map_layer.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            mode != "focus",
        )
        self.content_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            mode == "focus",
        )
        if not animated:
            self._map_opacity.setOpacity(target_opacity)
            self._content_body_opacity.setOpacity(target_body_opacity)
            self._map_blur.setBlurRadius(target_blur_radius)
            self.map_layer.setVisible(mode != "hidden")
            self.map_exit_button.setVisible(mode == "focus")
            if mode == "focus":
                self.map_layer.raise_()
                self._player_bar.raise_()
                self.map_exit_button.raise_()
            else:
                self.map_layer.lower()
                self._player_bar.raise_()
            return

        self.map_layer.show()
        self.map_exit_button.setVisible(mode == "focus")
        self._map_opacity_animation.stop()
        self._map_opacity_animation.setStartValue(
            self._map_opacity.opacity()
        )
        self._map_opacity_animation.setEndValue(target_opacity)
        self._map_opacity_animation.start()
        self._content_body_opacity_animation.stop()
        self._content_body_opacity_animation.setStartValue(
            self._content_body_opacity.opacity()
        )
        self._content_body_opacity_animation.setEndValue(
            target_body_opacity
        )
        self._content_body_opacity_animation.start()
        self._map_blur_animation.stop()
        self._map_blur_animation.setStartValue(
            self._map_blur.blurRadius()
        )
        self._map_blur_animation.setEndValue(target_blur_radius)
        self._map_blur_animation.start()
        if mode == "focus":
            self.map_layer.raise_()
            self._player_bar.raise_()
            self.map_exit_button.raise_()
        else:
            self.map_layer.lower()
            self._player_bar.raise_()

    def _toggle_music_map(self) -> None:
        next_mode = {
            "background": "focus",
            "focus": "hidden",
            "hidden": "background",
        }[self._music_map_mode]
        self._set_music_map_mode(
            next_mode
        )

    def _refresh_music_map(
        self,
        tracks: list[Track] | None = None,
    ) -> None:
        if tracks is None:
            tracks = list(self.store.list_tracks())
        self.music_map.set_tracks(tracks)

    def _select_track_from_map(self, track_id: str) -> None:
        for row_index in range(self.track_table.rowCount()):
            title_item = self.track_table.item(row_index, 0)
            if title_item is None:
                continue
            if title_item.data(Qt.ItemDataRole.UserRole) == track_id:
                self.track_table.setCurrentCell(row_index, 0)
                self.track_table.scrollToItem(title_item)
                return

    def _build_library_panel(self) -> QWidget:
        panel = LiquidGlassPanel()
        panel.setObjectName("libraryPanel")
        panel.setProperty(
            "liquidGlass",
            "true" if self._liquid_glass_enabled else "false",
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 8, 0, 4)
        layout.setSpacing(10)

        self.library_title_label = QLabel("Music library")
        self.library_title_label.setObjectName("appTitle")
        library_header = QHBoxLayout()
        library_header.setContentsMargins(8, 0, 0, 0)
        library_header.setSpacing(8)
        library_header.addWidget(
            self.library_title_label,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        self.library_count_label = QLabel("0 tracks")
        self.library_count_label.setObjectName("sectionCaption")
        library_header.addWidget(
            self.library_count_label,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        library_header.addStretch()
        layout.addLayout(library_header)

        self.track_table = HoverTableWidget()
        self.track_table.setObjectName("libraryTable")
        self.track_table.setVerticalScrollBar(
            RoundedScrollBar(Qt.Orientation.Vertical)
        )
        self.track_table.setColumnCount(7)
        header = LibraryHeaderView(
            Qt.Orientation.Horizontal,
            self.track_table,
        )
        self.track_table.setHorizontalHeader(header)
        self.track_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.track_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.track_table.setHorizontalHeaderLabels(
            [
                "#",
                "Title",
                "Genres",
                "Added",
                "Duration",
                "",
                "Analysis",
            ]
        )
        self.track_table.setShowGrid(False)
        self.track_table.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )
        self.track_table.verticalHeader().setVisible(False)
        self.track_table.verticalHeader().setDefaultSectionSize(62)
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Interactive,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            5,
            QHeaderView.ResizeMode.Fixed,
        )
        header.resizeSection(2, 120)
        # Give the metadata columns a little more room so their headers sit
        # slightly closer to the title column instead of hugging the edge.
        header.resizeSection(3, 112)
        header.resizeSection(4, 72)
        header.resizeSection(5, 44)
        header.resizeSection(0, 50)
        # Keep the custom row rendering while allowing the library columns to
        # be sorted through the existing _handle_library_sort implementation.
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter
        )
        header.setFixedHeight(36)
        header.setSectionsClickable(True)
        header.setMouseTracking(True)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        # The custom header paints one centered chevron above the active
        # label; keep Qt's edge-aligned indicator disabled to avoid a double
        # arrow in the same section.
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._handle_library_sort)
        index_header = self.track_table.horizontalHeaderItem(0)
        if index_header is not None:
            index_header.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )
        self.track_table.setColumnHidden(5, True)
        self.track_table.setColumnHidden(6, True)
        self.track_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.track_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.track_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.track_table.setAlternatingRowColors(False)
        self._hovered_track_row = -1
        self.track_table.row_hovered.connect(self._set_track_row_hover)
        self.track_table.cellEntered.connect(
            lambda row, _column: self._set_track_row_hover(row)
        )
        self.track_table.itemSelectionChanged.connect(
            self._handle_track_selection
        )
        self.track_table.row_double_clicked.connect(
            self._play_track_from_table_row
        )
        self.track_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.track_table.customContextMenuRequested.connect(
            self._show_track_context_menu
        )

        layout.addWidget(self.track_table)

        return panel

    def _set_track_row_hover(self, row_index: int) -> None:
        if row_index == self._hovered_track_row:
            return

        previous_row = self._hovered_track_row
        self._hovered_track_row = row_index
        self._refresh_track_row_visuals((previous_row, row_index))

    def _refresh_track_row_visuals(
        self,
        row_indices: tuple[int, ...] | None = None,
    ) -> None:
        """Keep the row background and its embedded widgets in one state."""

        if row_indices is None:
            row_indices = tuple(range(self.track_table.rowCount()))

        for row_index in dict.fromkeys(row_indices):
            if row_index < 0 or row_index >= self.track_table.rowCount():
                continue
            selected = row_index == self.track_table.currentRow()
            hovered = row_index == self._hovered_track_row
            state = "selected" if selected else "hover" if hovered else ""
            row_color = (
                QColor("#303334")
                if selected
                else QColor(255, 255, 255, 18)
            )
            background = (
                QBrush(row_color)
                if state
                else QBrush()
            )

            for column in range(self.track_table.columnCount()):
                item = self.track_table.item(row_index, column)
                if item is not None:
                    item.setBackground(background)

                cell_widget = self.track_table.cellWidget(
                    row_index,
                    column,
                )
                if cell_widget is not None:
                    cell_widget.setProperty("rowState", state)
                    cell_widget.style().unpolish(cell_widget)
                    cell_widget.style().polish(cell_widget)
                    cell_widget.update()

            index_widget = self.track_table.cellWidget(row_index, 0)
            if isinstance(index_widget, TrackNumberPlayWidget):
                index_widget.set_play_visible(bool(state))

    def _build_queue_panel(self) -> QWidget:
        panel = LiquidGlassPanel()
        panel.setObjectName("queuePanel")
        panel.setProperty(
            "liquidGlass",
            "true" if self._liquid_glass_enabled else "false",
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 9, 8, 4)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        queue_title = QLabel("Queue")
        queue_title.setObjectName("appTitle")
        header.addWidget(queue_title)
        header.addStretch()
        self.queue_count_label = QLabel("0 tracks")
        self.queue_count_label.setObjectName("sectionCaption")
        header.addWidget(self.queue_count_label)
        layout.addLayout(header)

        self.queue_list = QListWidget()
        self.queue_list.setObjectName("queueList")
        self.queue_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.queue_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.queue_list.itemDoubleClicked.connect(
            self._play_queued_item
        )
        layout.addWidget(self.queue_list, 1)

        queue_actions = QHBoxLayout()
        queue_actions.setSpacing(6)
        clear_button = QPushButton("Clear upcoming")
        clear_button.clicked.connect(self._clear_upcoming_queue)
        queue_actions.addStretch()
        queue_actions.addWidget(clear_button)
        layout.addLayout(queue_actions)

        panel.setMinimumWidth(270)
        panel.setMaximumWidth(300)

        return panel

    def _set_liquid_glass_enabled(self, enabled: bool) -> None:
        """Switch the two main panels between glass and solid backgrounds."""

        self._liquid_glass_enabled = bool(enabled)
        property_value = "true" if self._liquid_glass_enabled else "false"
        for panel in (
            getattr(self, "_library_panel", None),
            getattr(self, "_queue_panel", None),
        ):
            if panel is None:
                continue
            panel.setProperty("liquidGlass", property_value)
            panel.style().unpolish(panel)
            panel.style().polish(panel)
            panel.update()

    def _load_library(self, *, refresh_map: bool = True) -> None:
        tracks = list(self.store.list_tracks())
        self._library_tracks = tracks

        if self.selected_playlist_id is None:
            self._set_visible_tracks(
                tracks,
                title="Music library",
            )
        else:
            self._load_selected_playlist_tracks()

        self._load_queue()
        self._load_history()
        if refresh_map:
            self._refresh_music_map(tracks)
        self.statusBar().showMessage("Library refreshed")

    def _set_visible_tracks(
        self,
        tracks: list[Track],
        *,
        title: str,
    ) -> None:
        """Render either the main library or a playlist in the shared table."""

        self._track_scope_tracks = list(tracks)
        if hasattr(self, "track_table"):
            # Column 5 is reserved for the playlist-only remove action.  It is
            # hidden in the library so the normal table keeps its original
            # proportions.
            self.track_table.setColumnHidden(
                5,
                self.selected_playlist_id is None,
            )
        self._render_visible_tracks(title)

    def _render_visible_tracks(self, title: str) -> None:
        """Render the current library/playlist scope with active search."""

        self._cancel_track_batch_loading()
        self._track_table_generation += 1
        generation = self._track_table_generation
        filtered_tracks = self._filter_library_tracks(
            self._track_scope_tracks
        )
        self._visible_tracks = self._sort_tracks(filtered_tracks)
        self.track_table.clearSelection()
        self.selected_track_id = None
        self._hovered_track_row = -1
        self.track_table.setRowCount(0)
        initial_tracks = self._visible_tracks[:INITIAL_TRACK_BATCH_SIZE]
        self.track_table.setRowCount(len(initial_tracks))

        for row_index, track in enumerate(initial_tracks):
            self._populate_track_row(row_index, track)

        self.library_title_label.setText(title)
        self.library_count_label.setText(
            f"{len(self._visible_tracks)} track"
            f"{'s' if len(self._visible_tracks) != 1 else ''}"
        )
        self._refresh_track_row_visuals()
        self._start_track_batch_loading(generation, len(initial_tracks))
        # Defer recommendation work until after the first batch is painted.
        QTimer.singleShot(0, self._load_recommendations)

    def _handle_library_search_changed(self, text: str) -> None:
        self._library_search_query = text.strip()
        self.library_search_clear.setVisible(
            bool(self._library_search_query)
        )
        self._render_visible_tracks(self.library_title_label.text())

    def _focus_library_search(self) -> None:
        self.library_search_input.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.library_search_input.selectAll()

    def _filter_library_tracks(
        self,
        tracks: list[Track],
    ) -> list[Track]:
        query = self._library_search_query.casefold()
        if not query:
            return list(tracks)

        return [
            track
            for track in tracks
            if (
                query in track.title.casefold()
                or query in track.artist.casefold()
            )
        ]

    def _handle_library_sort(self, column: int) -> None:
        if column not in {1, 2, 3, 4}:
            return

        if self._library_sort_column == column:
            self._library_sort_descending = (
                not self._library_sort_descending
            )
        else:
            self._library_sort_column = column
            # Added uses newest-first for the initial downward indicator;
            # text and duration start in their natural ascending order.
            self._library_sort_descending = column == 3

        # The requested visual convention is a downward triangle on the first
        # click, then upward on the reverse order. Added intentionally maps
        # that first click to newest-first.
        if column == 3:
            indicator_order = (
                Qt.SortOrder.DescendingOrder
                if self._library_sort_descending
                else Qt.SortOrder.AscendingOrder
            )
        else:
            indicator_order = (
                Qt.SortOrder.AscendingOrder
                if self._library_sort_descending
                else Qt.SortOrder.DescendingOrder
            )
        self.track_table.horizontalHeader().setSortIndicator(
            column,
            indicator_order,
        )
        self.track_table.horizontalHeader().viewport().update()
        self._render_visible_tracks(self.library_title_label.text())

    def _sort_tracks(self, tracks: list[Track]) -> list[Track]:
        if self._library_sort_column is None:
            return list(tracks)

        column = self._library_sort_column

        def sort_key(track: Track) -> object:
            if column == 1:
                return (
                    track.title.casefold(),
                    track.artist.casefold(),
                )
            if column == 2:
                return (
                    self._format_display_genres(track).casefold(),
                    track.title.casefold(),
                )
            if column == 4:
                return (
                    track.duration_ms
                    if track.duration_ms is not None
                    else -1,
                    track.title.casefold(),
                )

            created_at = track.created_at
            timestamp = getattr(created_at, "timestamp", None)
            if callable(timestamp):
                return timestamp()
            return str(created_at)

        return sorted(
            tracks,
            key=sort_key,
            reverse=self._library_sort_descending,
        )

    def _cancel_track_batch_loading(self) -> None:
        if self._track_batch_task is not None:
            self._track_batch_task.cancel()
            self._track_batch_task = None

    def _start_track_batch_loading(
        self,
        generation: int,
        start_index: int,
    ) -> None:
        if start_index >= len(self._visible_tracks):
            self._track_batch_task = None
            return

        task = TrackBatchTask(
            self._visible_tracks,
            start_index,
            generation,
            DEFERRED_TRACK_BATCH_SIZE,
        )
        task.signals.batch_ready.connect(self._append_track_batch)
        task.signals.finished.connect(self._finish_track_batch_loading)
        self._track_batch_task = task
        self._track_batch_pool.start(task)

    def _append_track_batch(
        self,
        generation: int,
        start_index: int,
        batch: object,
    ) -> None:
        if generation != self._track_table_generation:
            return

        if not isinstance(batch, (list, tuple)):
            return

        tracks = tuple(
            track
            for track in batch
            if isinstance(track, Track)
        )
        if not tracks:
            return

        if start_index != self.track_table.rowCount():
            # A direct edit (import/delete) superseded this loader.
            self._track_table_generation += 1
            return

        first_row = self.track_table.rowCount()
        self.track_table.setRowCount(first_row + len(tracks))
        for offset, track in enumerate(tracks):
            self._populate_track_row(first_row + offset, track)
        self._refresh_track_row_visuals(
            tuple(
                range(first_row, first_row + len(tracks))
            )
        )

    def _finish_track_batch_loading(self, generation: int) -> None:
        if generation == self._track_table_generation:
            self._track_batch_task = None

    def _show_main_library(self) -> None:
        self.selected_playlist_id = None
        self.playlist_list.blockSignals(True)
        self.playlist_list.clearSelection()
        self.playlist_list.blockSignals(False)
        self._set_visible_tracks(
            self._library_tracks,
            title="Music library",
        )
        self._populate_playlist_carousel(
            self.playlist_management_service.list_playlists()
        )
        self.statusBar().showMessage("Music library")

    def _load_history(self) -> None:
        if not hasattr(self, "history_list"):
            return

        recent_tracks: list[Track] = []
        seen_track_ids: set[str] = set()
        interactions = sorted(
            (
                interaction
                for interaction in self.store.list_interactions()
                if interaction.user_id == self.user_id
                and interaction.interaction_type
                in {
                    InteractionType.PLAY,
                    InteractionType.PLAY_START,
                }
            ),
            key=lambda interaction: interaction.created_at,
            reverse=True,
        )

        for interaction in interactions:
            if interaction.track_id in seen_track_ids:
                continue
            track = self.store.get_track(interaction.track_id)
            if track is None:
                continue
            seen_track_ids.add(track.id)
            recent_tracks.append(track)
            if len(recent_tracks) == 16:
                break

        self.history_list.clear()
        if not recent_tracks:
            empty_item = QListWidgetItem("No recently played tracks")
            empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.history_list.addItem(empty_item)
            return

        for track in recent_tracks:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, track.id)
            item.setSizeHint(QSize(0, 44))
            self.history_list.addItem(item)
            identity = TrackIdentityWidget(
                track.title,
                track.artist,
                compact=True,
            )
            identity.play_requested.connect(
                lambda track_id=track.id: self._play_track_now(track_id)
            )
            self.history_list.setItemWidget(item, identity)

    def _play_history_item(self, item: QListWidgetItem) -> None:
        track_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(track_id, str):
            self._play_track_now(track_id)

    def _populate_track_row(
        self,
        row_index: int,
        track: Track,
    ) -> None:
        number_item = QTableWidgetItem()
        number_item.setData(
            Qt.ItemDataRole.UserRole,
            track.id,
        )

        self.track_table.setItem(
            row_index,
            0,
            number_item,
        )
        index_widget = TrackNumberPlayWidget(row_index + 1)
        index_widget.play_requested.connect(
            lambda track_id=track.id, row=row_index: (
                self.track_table.selectRow(row),
                self._play_track_now(track_id),
            )
        )
        self.track_table.setCellWidget(row_index, 0, index_widget)
        self.track_table.register_row_widget(index_widget, row_index)
        track_identity = TrackIdentityWidget(
            track.title,
            track.artist,
            cover_path=track.cover_path,
            include_play_button=False,
        )
        track_identity.play_requested.connect(
            lambda track_id=track.id: self._play_track_now(track_id)
        )
        track_identity.set_search_query(self._library_search_query)
        self.track_table.setItem(row_index, 1, QTableWidgetItem())
        self.track_table.setCellWidget(row_index, 1, track_identity)
        self.track_table.register_row_widget(track_identity, row_index)
        remove_button: QToolButton | None = None
        if self.selected_playlist_id is not None:
            remove_button = QToolButton()
            remove_button.setObjectName("playlistRemoveButton")
            remove_button.setText("×")
            remove_button.setToolTip("Remove from playlist")
            remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_button.setAutoRaise(True)
            remove_button.clicked.connect(
                lambda _checked=False, track_id=track.id: (
                    self._remove_playlist_track(track_id)
                )
            )
        if remove_button is None:
            self.track_table.removeCellWidget(row_index, 5)
        else:
            self.track_table.setCellWidget(row_index, 5, remove_button)
            self.track_table.register_row_widget(remove_button, row_index)
        self.track_table.setItem(
            row_index,
            2,
            QTableWidgetItem(
                self._format_display_genres(track)
            ),
        )
        self.track_table.setItem(
            row_index,
            3,
            QTableWidgetItem(self._format_added_date(track.created_at)),
        )
        self.track_table.setItem(
            row_index,
            4,
            QTableWidgetItem(self._format_duration(track.duration_ms)),
        )
        for column in (2, 3):
            item = self.track_table.item(row_index, column)
            if item is not None:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft
                    | Qt.AlignmentFlag.AlignVCenter
                )
        duration_item = self.track_table.item(row_index, 4)
        if duration_item is not None:
            duration_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter
                | Qt.AlignmentFlag.AlignVCenter
            )

        self.track_table.setItem(
            row_index,
            6,
            QTableWidgetItem(
                self._genre_statuses.get(
                    track.id,
                    "Not analyzed",
                )
            ),
        )

    def _append_library_track(self, track: Track) -> None:
        for index, item in enumerate(self._library_tracks):
            if item.id == track.id:
                self._library_tracks[index] = track
                break
        else:
            self._library_tracks.append(track)

        if self.selected_playlist_id is not None:
            self._load_selected_playlist_tracks()
            return
        self._set_visible_tracks(
            self._library_tracks,
            title=self.library_title_label.text(),
        )

    def _update_library_track_row(self, track: Track) -> None:
        self._library_tracks = [
            track if item.id == track.id else item
            for item in self._library_tracks
        ]
        self._track_scope_tracks = [
            track if item.id == track.id else item
            for item in self._track_scope_tracks
        ]

        in_scope = any(
            item.id == track.id
            for item in self._track_scope_tracks
        )
        is_visible = any(item.id == track.id for item in self._visible_tracks)
        matches_search = self._track_matches_search(track)
        if (
            self._library_search_query
            and in_scope
            and is_visible != matches_search
        ):
            self._render_visible_tracks(self.library_title_label.text())
            return

        for row_index in range(self.track_table.rowCount()):
            title_item = self.track_table.item(row_index, 0)
            if title_item is None:
                continue
            if title_item.data(Qt.ItemDataRole.UserRole) != track.id:
                continue

            self._populate_track_row(row_index, track)
            return

    def _remove_library_track_row(self, track_id: str) -> None:
        self._cancel_track_batch_loading()
        self._track_table_generation += 1
        self._track_scope_tracks = [
            track
            for track in self._track_scope_tracks
            if track.id != track_id
        ]
        self._visible_tracks = [
            track
            for track in self._visible_tracks
            if track.id != track_id
        ]
        for row_index in range(self.track_table.rowCount()):
            title_item = self.track_table.item(row_index, 0)
            if title_item is None:
                continue
            if title_item.data(Qt.ItemDataRole.UserRole) != track_id:
                continue

            self.track_table.removeRow(row_index)
            self.library_count_label.setText(
                f"{len(self._visible_tracks)} track"
                f"{'s' if len(self._visible_tracks) != 1 else ''}"
            )
            return

    def _track_matches_search(self, track: Track) -> bool:
        query = self._library_search_query.casefold()
        return (
            not query
            or query in track.title.casefold()
            or query in track.artist.casefold()
        )

    @staticmethod
    def _format_display_genres(
        track: Track,
    ) -> str:
        if track.detected_genres:
            visible_genres = []
            for prediction in track.detected_genres:
                parent_genre = prediction.parent_genre
                if parent_genre in visible_genres:
                    continue
                visible_genres.append(parent_genre)
                if len(visible_genres) == 2:
                    break
            hidden_count = (
                len({
                    prediction.parent_genre
                    for prediction in track.detected_genres
                })
                - len(visible_genres)
            )
        else:
            visible_genres = list(track.genres[:2])
            hidden_count = len(track.genres) - len(
                visible_genres
            )

        text = ", ".join(visible_genres)

        if hidden_count > 0:
            text = f"{text} (+{hidden_count} more)"

        return text

    def _load_recommendations(self) -> None:
        # Recommendations still power Now sessions and track radio; this old
        # sidebar no longer renders a duplicate text list.
        if not hasattr(self, "recommendation_list"):
            return

        if self.session_mood_name == MY_WAVE_SESSION_NAME:
            context = RecommendationContext.my_wave()
        elif self.selected_mood_name is not None:
            context = RecommendationContext.mood(
                MOOD_PRESETS[self.selected_mood_name],
                mood_name=self.selected_mood_name,
            )
        elif self.selected_track_id is not None:
            context = RecommendationContext.track_radio(
                self.selected_track_id
            )
        else:
            context = RecommendationContext()

        self._recommendation_generation += 1
        generation = self._recommendation_generation
        if self._recommendation_task is not None:
            self._recommendation_task.cancel()

        self.recommendation_list.clear()
        self.recommendation_list.addItem("Loading recommendations…")

        task = RecommendationTask(
            lambda: self.recommendation_service.get_recommendations(
                user_id=self.user_id,
                limit=10,
                context=context,
            ),
            generation,
            batch_size=5,
        )
        task.signals.batch_ready.connect(
            self._handle_recommendation_batch
        )
        task.signals.finished.connect(
            self._finish_recommendation_loading
        )
        task.signals.error_occurred.connect(
            self._handle_recommendation_error
        )
        self._recommendation_task = task
        self._recommendation_pool.start(task)

    def _handle_recommendation_batch(
        self,
        generation: int,
        batch: object,
    ) -> None:
        if generation != self._recommendation_generation:
            return

        if (
            self.recommendation_list.count() == 1
            and self.recommendation_list.item(0) is not None
            and self.recommendation_list.item(0).text()
            == "Loading recommendations…"
        ):
            self.recommendation_list.clear()

        shown_recommendations: list[Recommendation] = []
        for recommendation in batch:
            if not isinstance(recommendation, Recommendation):
                continue

            track = recommendation.track
            text = (
                f"{track.artist} — {track.title} "
                f"(match: {recommendation.match_score:.2f})"
            )
            self.recommendation_list.addItem(text)
            shown_recommendations.append(recommendation)

        self._record_recommendation_impressions(shown_recommendations)

    def _record_recommendation_impressions(
        self,
        recommendations: list[Recommendation] | tuple[Recommendation, ...],
    ) -> None:
        if not recommendations:
            return
        try:
            self.recommendation_analytics_service.record_impressions(
                self.user_id,
                recommendations,
            )
        except (OSError, RuntimeError, ValueError):
            # Telemetry must never interrupt playback or a UI refresh if a
            # track disappears during a background operation.
            return

    def _finish_recommendation_loading(self, generation: int) -> None:
        if generation != self._recommendation_generation:
            return

        self._recommendation_task = None
        if (
            self.recommendation_list.count() == 1
            and self.recommendation_list.item(0) is not None
            and self.recommendation_list.item(0).text()
            == "Loading recommendations…"
        ):
            self.recommendation_list.clear()
            self.recommendation_list.addItem("No recommendations yet")

    def _handle_recommendation_error(
        self,
        generation: int,
        message: str,
    ) -> None:
        if generation != self._recommendation_generation:
            return

        self._recommendation_task = None
        self.recommendation_list.clear()
        self.recommendation_list.addItem(
            f"Recommendations unavailable: {message}"
        )

    def _start_mood_session(self) -> None:
        if self.selected_mood_name is None:
            QMessageBox.information(
                self,
                "Choose a mood",
                "Choose a mood before starting a Now session.",
            )
            return

        target_mood = MOOD_PRESETS[self.selected_mood_name]
        recommendations = self.recommendation_service.get_recommendations(
            user_id=self.user_id,
            limit=30,
            context=RecommendationContext.mood(
                target_mood,
                mood_name=self.selected_mood_name,
            ),
        )
        track_ids = [
            recommendation.track.id
            for recommendation in recommendations
            if (
                recommendation.track.mood is not None
                and
                recommendation.track.local_path
                and Path(recommendation.track.local_path).exists()
            )
        ]

        if not track_ids:
            QMessageBox.information(
                self,
                "Session unavailable",
                "No analyzed local tracks match this mood yet.",
            )
            return

        self._record_recommendation_impressions(
            tuple(
                recommendation
                for recommendation in recommendations
                if recommendation.track.id in track_ids
            )
        )
        self.session_mood_name = self.selected_mood_name
        self.playback_queue_service.start(
            track_ids,
            mode=QueueMode.SESSION,
        )
        self._play_current_queue_track()
        self.statusBar().showMessage(
            f"Now session started: {self.selected_mood_name.title()}"
        )

    def _start_mood_session_from_card(self, mood_name: str) -> None:
        if mood_name == MY_WAVE_SESSION_NAME:
            self._start_my_wave_session()
            return
        self.selected_mood_name = mood_name
        self._start_mood_session()

    def _start_my_wave_session(self) -> None:
        """Start a personalized mood session based on listening history."""

        try:
            recommendations = self.recommendation_service.get_recommendations(
                user_id=self.user_id,
                limit=30,
                context=RecommendationContext.my_wave(),
            )
        except (RuntimeError, ValueError) as error:
            QMessageBox.warning(
                self,
                "My Wave unavailable",
                str(error),
            )
            return

        track_ids = [
            recommendation.track.id
            for recommendation in recommendations
            if (
                recommendation.track.local_path
                and Path(recommendation.track.local_path).exists()
            )
        ]
        if not track_ids:
            QMessageBox.information(
                self,
                "My Wave unavailable",
                "Analyze or add a few local tracks to build your wave.",
            )
            return

        self._record_recommendation_impressions(
            tuple(
                recommendation
                for recommendation in recommendations
                if recommendation.track.id in track_ids
            )
        )
        self.selected_mood_name = None
        self.session_mood_name = MY_WAVE_SESSION_NAME
        self.playback_queue_service.start(
            track_ids,
            mode=QueueMode.SESSION,
        )
        self._play_current_queue_track()
        self.statusBar().showMessage("My Wave session started")

    def _cycle_playback_mode(self) -> None:
        """Cycle sequential, shuffle and smart-shuffle library playback."""

        try:
            current_index = LIBRARY_PLAYBACK_MODES.index(
                self._playback_mode
            )
        except ValueError:
            current_index = 0

        self._playback_mode = LIBRARY_PLAYBACK_MODES[
            (current_index + 1) % len(LIBRARY_PLAYBACK_MODES)
        ]
        self._track_radio_enabled = False
        self._update_playback_mode_controls()

        if self.current_track_id is not None:
            self._start_library_queue(
                self.current_track_id,
                restart=False,
            )

        self.statusBar().showMessage(
            f"Playback mode: {self._playback_mode_label()}"
        )

    def _toggle_track_radio(self) -> None:
        """Toggle a replenishable radio stream seeded by the current track."""

        self._set_track_radio_enabled(not self._track_radio_enabled)

    def _set_track_radio_enabled(self, enabled: bool) -> None:
        if self._track_radio_enabled == enabled:
            self._update_playback_mode_controls()
            return

        self._track_radio_enabled = enabled
        self._update_playback_mode_controls()

        if self.current_track_id is not None:
            self._start_library_queue(
                self.current_track_id,
                restart=False,
            )

        state = "on" if self._track_radio_enabled else "off"
        self.statusBar().showMessage(f"Track radio: {state}")

    def _cycle_repeat_mode(self) -> None:
        try:
            current_index = REPEAT_MODES.index(self._repeat_mode)
        except ValueError:
            current_index = 0

        self._repeat_mode = REPEAT_MODES[
            (current_index + 1) % len(REPEAT_MODES)
        ]
        self.playback_queue_service.set_repeat_mode(self._repeat_mode)
        self._update_playback_mode_controls()
        self.statusBar().showMessage(
            f"Repeat: {self._repeat_mode_label()}"
        )

    def _playback_mode_label(self) -> str:
        return {
            QueueMode.NORMAL: "sequential",
            QueueMode.SHUFFLE: "shuffle",
            QueueMode.SMART_SHUFFLE: "smart shuffle",
        }.get(self._playback_mode, "sequential")

    def _repeat_mode_label(self) -> str:
        return {
            RepeatMode.OFF: "off",
            RepeatMode.QUEUE: "playlist",
            RepeatMode.TRACK: "track",
        }[self._repeat_mode]

    def _update_playback_mode_controls(self) -> None:
        if not hasattr(self, "playback_mode_button"):
            return

        mode_icons = {
            QueueMode.NORMAL: SEQUENTIAL_ICON,
            QueueMode.SHUFFLE: SHUFFLE_ICON,
            QueueMode.SMART_SHUFFLE: SMART_SHUFFLE_ICON,
        }
        mode_icon = mode_icons.get(
            self._playback_mode,
            SEQUENTIAL_ICON,
        )
        self.playback_mode_button.set_svg(
            mode_icon
            if self._playback_mode == QueueMode.NORMAL
            else mode_icon.replace("#D8D8D8", "#5DD8B7")
        )
        self.playback_mode_button.setToolTip(
            "Playback order: "
            f"{self._playback_mode_label()} (click to change)"
        )

        repeat_icons = {
            RepeatMode.OFF: REPEAT_OFF_ICON,
            RepeatMode.QUEUE: REPEAT_QUEUE_ICON,
            RepeatMode.TRACK: REPEAT_TRACK_ICON,
        }
        self.repeat_button.set_svg(repeat_icons[self._repeat_mode])
        self.repeat_button.setToolTip(
            "Repeat: "
            f"{self._repeat_mode_label()} (click to change)"
        )

        if hasattr(self, "track_radio_action"):
            self.track_radio_action.setChecked(
                self._track_radio_enabled
            )

    def _start_library_queue(
        self,
        track_id: str,
        *,
        restart: bool = True,
    ) -> None:
        """Build a new library queue for the selected playback mode."""

        track = self.store.get_track(track_id)
        if track is None:
            return

        manual_track_ids = self._manual_queue_snapshot()
        if self._track_radio_enabled:
            self._start_recommendation_queue(
                track.id,
                restart=restart,
                manual_track_ids=manual_track_ids,
            )
            return

        self._cancel_radio_recommendations()
        if self.selected_playlist_id is not None:
            self._start_playlist_queue(
                shuffle=self._playback_mode == QueueMode.SHUFFLE,
                smart=self._playback_mode == QueueMode.SMART_SHUFFLE,
                playlist_id=self.selected_playlist_id,
                start_track_id=track.id,
            )
            return

        manual_id_set = set(manual_track_ids)
        library_tracks = list(self.store.list_tracks())
        # Keep the queue in the same order the library currently advertises.
        # ``MusicStore.list_tracks`` has its own artist/title order and would
        # otherwise ignore a user's active Title/Genres/Added/Duration sort.
        ordered_library_tracks = self._sort_tracks(library_tracks)
        library_track_ids = [item.id for item in ordered_library_tracks]

        try:
            selected_index = library_track_ids.index(track.id)
        except ValueError:
            library_track_ids.insert(0, track.id)
            selected_index = 0

        if self._playback_mode == QueueMode.NORMAL:
            # Starting a track from the library follows the visible library
            # order from that track onward; it must not jump back to row one.
            candidate_ids = library_track_ids[selected_index + 1 :]
        else:
            candidate_ids = [
                item_id
                for item_id in library_track_ids
                if item_id != track.id
            ]

        remaining_track_ids = [
            item_id
            for item_id in candidate_ids
            if item_id not in manual_id_set
        ]
        if self._playback_mode == QueueMode.SHUFFLE:
            random.shuffle(remaining_track_ids)
        elif self._playback_mode == QueueMode.SMART_SHUFFLE:
            remaining_track_ids = self._build_smart_library_sequence(
                track.id,
                library_tracks,
                remaining_track_ids,
            )

        self.session_mood_name = None
        self.playback_queue_service.start(
            (track.id, *remaining_track_ids),
            mode=self._playback_mode,
        )
        self._restore_manual_queue(manual_track_ids)
        if restart:
            self._play_current_queue_track()
        else:
            self._load_queue()

    def _manual_queue_snapshot(self) -> tuple[str, ...]:
        queue = self.playback_queue_service.queue
        if queue is None:
            return ()
        return queue.queued_track_ids

    def _restore_manual_queue(
        self,
        track_ids: tuple[str, ...],
    ) -> None:
        for track_id in track_ids:
            self.playback_queue_service.enqueue(track_id)

    def _build_smart_library_sequence(
        self,
        seed_track_id: str,
        library_tracks: list[Track],
        remaining_track_ids: list[str],
    ) -> list[str]:
        """Mix random library order with tracks similar to the seed."""

        available_ids = set(remaining_track_ids)
        similar_ids: list[str] = []
        for recommendation in self._get_track_radio_recommendations(
            seed_track_id,
            limit=min(30, len(remaining_track_ids)),
        ):
            recommendation_id = recommendation.track.id
            if recommendation_id in available_ids and (
                recommendation_id not in similar_ids
            ):
                similar_ids.append(recommendation_id)

        random.shuffle(similar_ids)
        similar_id_set = set(similar_ids)
        random_ids = [
            track.id
            for track in library_tracks
            if track.id in available_ids
            and track.id not in similar_id_set
        ]
        random.shuffle(random_ids)

        mixed_ids: list[str] = []
        while similar_ids or random_ids:
            use_similar = bool(similar_ids) and (
                not random_ids or random.random() < 0.65
            )
            if use_similar:
                mixed_ids.append(similar_ids.pop())
            elif random_ids:
                mixed_ids.append(random_ids.pop())

        return mixed_ids

    def _start_recommendation_queue(
        self,
        track_id: str,
        *,
        restart: bool = True,
        manual_track_ids: tuple[str, ...] | None = None,
    ) -> None:
        """Start a library track with a replenishable radio queue."""

        track = self.store.get_track(track_id)
        if track is None:
            return

        if manual_track_ids is None:
            manual_track_ids = self._manual_queue_snapshot()

        self.session_mood_name = None
        self._track_radio_enabled = True
        self._update_playback_mode_controls()
        self._cancel_radio_recommendations()
        self.playback_queue_service.start(
            (track.id,),
            mode=QueueMode.RECOMMENDATIONS,
        )
        self._restore_manual_queue(manual_track_ids)
        if restart:
            self._play_current_queue_track()
        else:
            self._load_queue()
        # Start playback first.  Filling the radio queue happens in the
        # background and appends tracks in visible batches as they arrive.
        self._replenish_recommendation_queue(force=True)

    def _replenish_recommendation_queue(self, *, force: bool = False) -> None:
        """Schedule automatic tracks without blocking the current playback."""

        queue = self.playback_queue_service.queue
        if queue is None or queue.mode != QueueMode.RECOMMENDATIONS:
            return

        remaining_count = len(queue.remaining_track_ids)
        if not force and remaining_count >= RECOMMENDATION_REFILL_THRESHOLD:
            return

        if self._radio_recommendation_inflight:
            return

        tracks_needed = RECOMMENDATION_QUEUE_SIZE - remaining_count
        if tracks_needed <= 0 or queue.current_track_id is None:
            return

        seed_track_id = queue.current_track_id
        self._radio_recommendation_generation += 1
        generation = self._radio_recommendation_generation
        task = RecommendationTask(
            lambda: self._get_radio_recommendations(
                seed_track_id,
                limit=max(RECOMMENDATION_QUEUE_SIZE, tracks_needed),
            ),
            generation,
            batch_size=5,
        )
        task.signals.batch_ready.connect(
            lambda task_generation, batch, seed=seed_track_id: (
                self._handle_radio_recommendation_batch(
                    task_generation,
                    seed,
                    batch,
                )
            )
        )
        task.signals.finished.connect(
            self._finish_radio_recommendation_loading
        )
        task.signals.error_occurred.connect(
            self._handle_radio_recommendation_error
        )
        self._radio_recommendation_task = task
        self._radio_recommendation_inflight = True
        self._radio_recommendation_pool.start(task)

    def _handle_radio_recommendation_batch(
        self,
        generation: int,
        seed_track_id: str,
        batch: object,
    ) -> None:
        if generation != self._radio_recommendation_generation:
            return

        queue = self.playback_queue_service.queue
        if (
            queue is None
            or queue.mode != QueueMode.RECOMMENDATIONS
            or queue.current_track_id != seed_track_id
        ):
            return

        occupied_ids = {
            queue.current_track_id,
            *queue.remaining_track_ids,
            *queue.queued_track_ids,
        }
        additions: list[str] = []
        shown_recommendations: list[Recommendation] = []
        for recommendation in batch:
            if not isinstance(recommendation, Recommendation):
                continue

            track = recommendation.track
            if track.id in occupied_ids:
                continue
            if not track.local_path or not Path(track.local_path).exists():
                continue

            additions.append(track.id)
            shown_recommendations.append(recommendation)
            occupied_ids.add(track.id)
            if len(queue.remaining_track_ids) + len(additions) >= (
                RECOMMENDATION_QUEUE_SIZE
            ):
                break

        if additions:
            self._record_recommendation_impressions(shown_recommendations)
            self.playback_queue_service.append_remaining(additions)
            self._load_queue()

    def _finish_radio_recommendation_loading(self, generation: int) -> None:
        if generation != self._radio_recommendation_generation:
            return

        self._radio_recommendation_task = None
        self._radio_recommendation_inflight = False

    def _handle_radio_recommendation_error(
        self,
        generation: int,
        message: str,
    ) -> None:
        if generation != self._radio_recommendation_generation:
            return

        self._radio_recommendation_task = None
        self._radio_recommendation_inflight = False
        self.statusBar().showMessage(
            f"Recommendations unavailable: {message}"
        )

    def _cancel_radio_recommendations(self) -> None:
        self._radio_recommendation_generation += 1
        if self._radio_recommendation_task is not None:
            self._radio_recommendation_task.cancel()
        self._radio_recommendation_task = None
        self._radio_recommendation_inflight = False
        self._radio_wait_attempts = 0
        self._radio_wait_seed_track_id = None

    def _get_radio_recommendations(
        self,
        seed_track_id: str,
        *,
        limit: int,
    ) -> list[Recommendation]:
        """Combine similar-track radio with popularity fallback."""

        recommendations = self._get_track_radio_recommendations(
            seed_track_id,
            limit=limit,
        )

        if len(recommendations) >= limit:
            return recommendations

        try:
            fallback = self.recommendation_service.get_recommendations(
                user_id=self.user_id,
                limit=limit,
                context=RecommendationContext(),
            )
        except (RuntimeError, ValueError):
            fallback = []

        seen_ids = {
            recommendation.track.id
            for recommendation in recommendations
        }
        for recommendation in fallback:
            if recommendation.track.id in seen_ids:
                continue
            seen_ids.add(recommendation.track.id)
            recommendations.append(recommendation)
            if len(recommendations) == limit:
                break

        # Keep the stream close to the seed track without making every
        # transition deterministic or too narrowly matched.
        random.shuffle(recommendations)
        return recommendations

    def _get_track_radio_recommendations(
        self,
        seed_track_id: str,
        *,
        limit: int,
    ) -> list[Recommendation]:
        try:
            return list(
                self.recommendation_service.get_recommendations(
                    user_id=self.user_id,
                    limit=limit,
                    context=RecommendationContext.track_radio(
                        seed_track_id
                    ),
                )
            )
        except (RuntimeError, ValueError):
            return []

    def _replenish_mood_session(self) -> None:
        if self.session_mood_name is None:
            return

        queue = self.playback_queue_service.queue
        if queue is None or queue.mode != QueueMode.SESSION:
            return

        upcoming_count = len(
            self.playback_queue_service.upcoming_track_ids()
        )
        if upcoming_count > 5:
            return

        if self.session_mood_name == MY_WAVE_SESSION_NAME:
            context = RecommendationContext.my_wave()
        else:
            target_mood = MOOD_PRESETS[self.session_mood_name]
            context = RecommendationContext.mood(
                target_mood,
                mood_name=self.session_mood_name,
            )
        recommendations = self.recommendation_service.get_recommendations(
            user_id=self.user_id,
            limit=10,
            context=context,
        )
        existing_ids = {
            queue.current_track_id,
            *self.playback_queue_service.upcoming_track_ids(),
        }

        shown_recommendations: list[Recommendation] = []
        for recommendation in recommendations:
            track = recommendation.track
            if track.id in existing_ids:
                continue
            if not track.local_path or not Path(track.local_path).exists():
                continue

            self.playback_queue_service.enqueue(track.id)
            existing_ids.add(track.id)
            shown_recommendations.append(recommendation)

        self._record_recommendation_impressions(shown_recommendations)

    def _load_queue(self) -> None:
        queue = self.playback_queue_service.queue
        track_ids = (
            tuple(self.playback_queue_service.upcoming_track_ids())
            if queue is not None
            else ()
        )

        self._queue_render_generation += 1
        generation = self._queue_render_generation
        self._queue_render_track_ids = track_ids
        self._queue_render_index = 0

        next_track = next(
            (
                track
                for track_id in track_ids[:4]
                if (track := self.store.get_track(track_id)) is not None
            ),
            None,
        )
        if next_track is not None:
            self.next_track_title_label.setText(next_track.title)
            self.next_track_artist_label.setText(next_track.artist)
        else:
            self.next_track_title_label.setText("Nothing next")
            self.next_track_artist_label.setText("")

        if hasattr(self, "queue_count_label"):
            self.queue_count_label.setText(
                f"{len(track_ids)} track{'s' if len(track_ids) != 1 else ''}"
            )

        if hasattr(self, "queue_list"):
            self.queue_list.clear()
            if not track_ids:
                empty_item = QListWidgetItem("Nothing queued")
                empty_item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.queue_list.addItem(empty_item)
        if self.queue_dialog.isVisible():
            self.queue_dialog.begin_tracks(len(track_ids))
        if track_ids:
            QTimer.singleShot(
                0,
                lambda: self._append_queue_render_batch(generation),
            )

    def _append_queue_render_batch(self, generation: int) -> None:
        """Render a small queue slice, yielding to playback between slices."""

        if generation != self._queue_render_generation:
            return

        track_ids = self._queue_render_track_ids
        start = self._queue_render_index
        if start >= len(track_ids):
            return

        end = min(start + QUEUE_RENDER_BATCH_SIZE, len(track_ids))
        tracks = [
            track
            for track_id in track_ids[start:end]
            if (track := self.store.get_track(track_id)) is not None
        ]
        self._queue_render_index = end

        if hasattr(self, "queue_list"):
            for track in tracks:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, track.id)
                item.setSizeHint(QSize(0, 46))
                self.queue_list.addItem(item)
                identity = TrackIdentityWidget(
                    track.title,
                    track.artist,
                    cover_path=track.cover_path,
                    compact=True,
                )
                identity.play_requested.connect(
                    lambda track_id=track.id: self._play_queued_track(track_id)
                )
                self.queue_list.setItemWidget(item, identity)

        if self.queue_dialog.isVisible():
            self.queue_dialog.append_tracks(
                [(track.title, track.artist) for track in tracks],
                [track.id for track in tracks],
            )

        if self._queue_render_index < len(track_ids):
            QTimer.singleShot(
                QUEUE_RENDER_INTERVAL_MS,
                lambda: self._append_queue_render_batch(generation),
            )

    def _play_queued_item(self, item: QListWidgetItem) -> None:
        track_id = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(track_id, str):
            self._play_queued_track(track_id)

    def _play_queued_track(self, track_id: str) -> None:
        """Play a queue item without rebuilding the library/playlist queue."""

        if self.store.get_track(track_id) is None:
            return

        queue = self.playback_queue_service.jump_to(track_id)
        if queue is None or queue.current_track_id is None:
            return

        self._play_current_queue_track()

    def _clear_upcoming_queue(self) -> None:
        self.playback_queue_service.clear_upcoming()
        self._load_queue()
        self.statusBar().showMessage("Upcoming queue cleared")

    def _show_queue(self) -> None:
        self._show_auxiliary_dialog(self.queue_dialog)
        self._load_queue()

    def _show_track_context_menu(self, position: object) -> None:
        index = self.track_table.indexAt(position)
        if not index.isValid():
            return

        title_item = self.track_table.item(index.row(), 0)

        if title_item is None:
            return

        track_id = title_item.data(Qt.ItemDataRole.UserRole)

        if not isinstance(track_id, str):
            return

        menu = self._build_track_context_menu(track_id)
        menu.exec(self.track_table.viewport().mapToGlobal(position))

    def _show_current_track_context_menu(self, position: object) -> None:
        if self.current_track_id is None:
            return

        menu = self._build_track_context_menu(self.current_track_id)
        menu.exec(self._player_bar.mapToGlobal(position))

    def _build_track_context_menu(self, track_id: str) -> QMenu:
        menu = QMenu(self)
        play_action = menu.addAction("Play now")
        play_action.triggered.connect(
            lambda checked=False, value=track_id: self._play_track_now(value)
        )
        queue_action = menu.addAction("Add to queue")
        queue_action.triggered.connect(
            lambda checked=False, value=track_id: self._enqueue_track(value)
        )
        radio_action = menu.addAction("Track radio")
        radio_action.setToolTip(
            "Play this track and build a stream of similar tracks"
        )
        radio_action.triggered.connect(
            lambda checked=False, value=track_id: (
                self._start_track_radio_from_context(value)
            )
        )
        playlists_menu = menu.addMenu("Add to playlist")

        for playlist in self.playlist_management_service.list_playlists():
            playlist_action = playlists_menu.addAction(playlist.name)
            playlist_action.triggered.connect(
                lambda checked=False,
                playlist_id=playlist.id,
                selected_track_id=track_id: self._add_track_to_playlist(
                    playlist_id,
                    selected_track_id,
                )
            )
        menu.addSeparator()
        feedback_menu = menu.addMenu("Tune recommendations")
        feedback_menu.addAction(
            "Not now (14 days)",
            lambda checked=False, value=track_id: self._record_track_feedback(
                value,
                InteractionType.SNOOZE,
                advance=False,
            ),
        )
        feedback_menu.addAction(
            "Dislike",
            lambda checked=False, value=track_id: self._record_track_feedback(
                value,
                InteractionType.DISLIKE,
                advance=False,
            ),
        )
        feedback_menu.addAction(
            "Don't recommend this track",
            lambda checked=False, value=track_id: self._record_track_feedback(
                value,
                InteractionType.DO_NOT_RECOMMEND,
                advance=False,
            ),
        )
        feedback_menu.addAction(
            "Allow recommendations again",
            lambda checked=False, value=track_id: self._record_track_feedback(
                value,
                InteractionType.ALLOW_RECOMMEND,
                advance=False,
            ),
        )
        menu.addSeparator()
        analyze_action = menu.addAction("Analyze genres")
        analyze_action.triggered.connect(
            lambda checked=False, value=track_id: self._run_track_action(
                value,
                self._analyze_selected_track,
            )
        )
        edit_action = menu.addAction("Edit metadata")
        edit_action.triggered.connect(
            lambda checked=False, value=track_id: self._run_track_action(
                value,
                self._edit_selected_track,
            )
        )
        delete_action = menu.addAction("Delete track")
        delete_action.triggered.connect(
            lambda checked=False, value=track_id: self._run_track_action(
                value,
                self._delete_selected_track,
            )
        )
        return menu

    def _run_track_action(
        self,
        track_id: str,
        action: Callable[[], None],
    ) -> None:
        self._select_track_from_map(track_id)
        self.selected_track_id = track_id
        action()

    def _play_track_now(self, track_id: str) -> None:
        if self.store.get_track(track_id) is None:
            return

        self._start_library_queue(track_id)

    def _start_track_radio_from_context(self, track_id: str) -> None:
        """Start track radio directly from a library row's context menu."""

        if self.store.get_track(track_id) is None:
            return

        self._start_recommendation_queue(track_id)

    def _enqueue_selected_track(self) -> None:
        if self.selected_track_id is None:
            return
        self._enqueue_track(self.selected_track_id)

    def _enqueue_track(self, track_id: str) -> None:
        track = self.store.get_track(track_id)

        if track is None:
            QMessageBox.warning(
                self,
                "Queue failed",
                "Track was not found.",
            )
            return

        self.playback_queue_service.enqueue(track.id)
        self._load_queue()
        self.statusBar().showMessage(
            f"Added to queue: {track.artist} — {track.title}"
        )

    def _enqueue_playlist(self, playlist_id: str) -> None:
        playlist = self._resolve_playlist(playlist_id)
        if playlist is None:
            return

        tracks = self.playlist_management_service.get_playlist_tracks(
            playlist.id
        )
        if not tracks:
            QMessageBox.information(
                self,
                "Playlist is empty",
                "Add at least one track before adding it to the queue.",
            )
            return

        for track in tracks:
            self.playback_queue_service.enqueue(track.id)

        self._load_queue()
        self.statusBar().showMessage(
            f"Added playlist to queue: {playlist.name}"
        )

    def _load_playlists(self) -> None:
        playlists = self.playlist_management_service.list_playlists()
        selected_playlist_id = self.selected_playlist_id

        signals_blocked = self.playlist_list.blockSignals(True)
        self.playlist_list.clear()

        for playlist in playlists:
            item = QListWidgetItem(playlist.name)
            item.setData(Qt.ItemDataRole.UserRole, playlist.id)
            self.playlist_list.addItem(item)

            if playlist.id == selected_playlist_id:
                self.playlist_list.setCurrentItem(item)

        if not playlists:
            self.selected_playlist_id = None
            self.playlist_track_list.clear()
        elif selected_playlist_id is not None and not any(
            playlist.id == selected_playlist_id
            for playlist in playlists
        ):
            self.selected_playlist_id = None
            self.playlist_list.clearSelection()

        self.playlist_list.blockSignals(signals_blocked)

        self._populate_playlist_carousel(playlists)
        if self.selected_playlist_id is not None:
            self._load_selected_playlist_tracks()

    def _scroll_playlists(self, direction: int) -> None:
        if self._playlist_page_count > 1:
            self._set_playlist_page(self._playlist_page_index + direction)
            return

        scroll_bar = self.playlist_scroll.horizontalScrollBar()
        step = max(1, scroll_bar.pageStep() // 2)
        current_value = scroll_bar.value()
        target_value = max(
            scroll_bar.minimum(),
            min(scroll_bar.maximum(), current_value + direction * step),
        )
        if target_value == current_value:
            return

        self._playlist_scroll_animation.stop()
        self._playlist_scroll_animation.setStartValue(current_value)
        self._playlist_scroll_animation.setEndValue(target_value)
        self._playlist_scroll_animation.start()

    def _set_playlist_page(self, page_index: int) -> None:
        if self._playlist_page_count <= 1:
            return

        page_index = max(
            0,
            min(self._playlist_page_count - 1, page_index),
        )
        if page_index == self._playlist_page_index:
            return

        self._playlist_page_index = page_index
        self._playlist_scroll_animation.stop()
        self.playlist_scroll.horizontalScrollBar().setValue(0)
        self._populate_playlist_carousel(self._playlist_page_items)

    def _update_playlist_scroll_buttons(self) -> None:
        if not hasattr(self, "playlist_scroll"):
            return

        if self._playlist_page_count > 1:
            # The arrows float above the carousel.  Hide the control when
            # there is no page in that direction instead of leaving a dead
            # arrow at the edge of the window.
            self.playlist_scroll_left_button.setVisible(
                self._playlist_page_index > 0
            )
            self.playlist_scroll_left_button.setEnabled(
                self._playlist_page_index > 0
            )
            self.playlist_scroll_right_button.setVisible(
                self._playlist_page_index
                < self._playlist_page_count - 1
            )
            self.playlist_scroll_right_button.setEnabled(
                self._playlist_page_index
                < self._playlist_page_count - 1
            )
            return

        scroll_bar = self.playlist_scroll.horizontalScrollBar()
        has_overflow = scroll_bar.maximum() > 0
        at_start = scroll_bar.value() <= scroll_bar.minimum()
        at_end = scroll_bar.value() >= scroll_bar.maximum()

        self.playlist_scroll_left_button.setVisible(
            has_overflow and not at_start
        )
        self.playlist_scroll_left_button.setEnabled(
            has_overflow and not at_start
        )
        self.playlist_scroll_right_button.setVisible(
            has_overflow and not at_end
        )
        self.playlist_scroll_right_button.setEnabled(
            has_overflow and not at_end
        )

    def _scroll_playlists_to_end(self) -> None:
        if self._playlist_page_count > 1:
            self._set_playlist_page(self._playlist_page_count - 1)
            return

        scroll_bar = self.playlist_scroll.horizontalScrollBar()
        current_value = scroll_bar.value()
        target_value = scroll_bar.maximum()
        if target_value <= current_value:
            return

        self._playlist_scroll_animation.stop()
        self._playlist_scroll_animation.setStartValue(current_value)
        self._playlist_scroll_animation.setEndValue(target_value)
        self._playlist_scroll_animation.start()

    def _populate_playlist_carousel(
        self,
        playlists: list[Playlist],
    ) -> None:
        # Keep newly created playlists at the beginning of the user cards so
        # the latest one is immediately visible after Create playlist.
        playlists = sorted(
            playlists,
            key=lambda playlist: playlist.created_at,
            reverse=True,
        )
        self._playlist_page_items = playlists
        self._playlist_page_specs = self._build_playlist_page_specs(
            len(playlists)
        )
        self._playlist_page_count = len(self._playlist_page_specs)
        self._playlist_page_index = min(
            self._playlist_page_index,
            self._playlist_page_count - 1,
        )
        (
            page_start,
            page_end,
            show_main_library,
            show_mood,
            show_create,
        ) = self._playlist_page_specs[self._playlist_page_index]
        visible_playlists = playlists[page_start:page_end]

        while self.playlist_carousel_layout.count():
            item = self.playlist_carousel_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.playlist_carousel_layout.addStretch(1)

        show_left = self._playlist_page_count > 1 and self._playlist_page_index > 0
        show_right = (
            self._playlist_page_count > 1
            and self._playlist_page_index < self._playlist_page_count - 1
        )

        if show_main_library:
            main_library_card = MainLibraryCard()
            main_library_card.set_selected(self.selected_playlist_id is None)
            main_library_card.activated.connect(self._show_main_library)
            self.playlist_carousel_layout.addWidget(main_library_card)

        if show_mood:
            mood_card = MoodPlaylistCard(tuple(MOOD_PRESETS))
            mood_card.mood_selected.connect(self._start_mood_session_from_card)
            mood_card.my_wave_selected.connect(self._start_my_wave_session)
            self.playlist_carousel_layout.addWidget(mood_card)

        if show_create:
            create_card = CreatePlaylistCard()
            create_card.activated.connect(self._create_playlist)
            self.playlist_carousel_layout.addWidget(create_card)

        for playlist in visible_playlists:
            card = PlaylistCard(
                playlist_id=playlist.id,
                name=playlist.name,
                cover_path=playlist.cover_path,
            )
            card.set_selected(playlist.id == self.selected_playlist_id)
            card.activated.connect(self._select_playlist_from_carousel)
            card.context_requested.connect(
                self._show_playlist_context_menu
            )
            self.playlist_carousel_layout.addWidget(card)

        self.playlist_carousel_layout.addStretch(1)
        self.playlist_scroll_left_button.setVisible(show_left)
        self.playlist_scroll_right_button.setVisible(show_right)
        self._position_playlist_navigation()
        QTimer.singleShot(0, self._update_playlist_scroll_buttons)
        QTimer.singleShot(0, self._position_playlist_navigation)

    @staticmethod
    def _build_playlist_page_specs(
        playlist_count: int,
    ) -> list[tuple[int, int, bool, bool, bool]]:
        """Return playlist ranges whose rendered card count is at most seven.

        Main library, Mood, and Create playlist occupy the first three slots.
        Later pages contain only user playlists, leaving the utility cards
        fixed at the beginning while ensuring every page stays within the
        seven-card limit.
        """

        utility_count = 3  # Main library + Mood + Create playlist
        first_page_capacity = PLAYLISTS_PER_PAGE - utility_count

        if playlist_count <= first_page_capacity:
            return [(0, playlist_count, True, True, True)]

        specs: list[tuple[int, int, bool, bool, bool]] = []
        first_end = min(playlist_count, first_page_capacity)
        specs.append((0, first_end, True, True, True))

        remaining = playlist_count - first_end
        page_count = (remaining + PLAYLISTS_PER_PAGE - 1) // PLAYLISTS_PER_PAGE
        cursor = first_end

        for page_index in range(page_count):
            chunk_size = min(PLAYLISTS_PER_PAGE, remaining)
            remaining -= chunk_size

            specs.append(
                (
                    cursor,
                    cursor + chunk_size,
                    False,
                    False,
                    False,
                )
            )
            cursor += chunk_size

        return specs

    def _select_playlist_from_carousel(self, playlist_id: str) -> None:
        """Open a playlist card, including when it is already selected.

        The hidden list is the source of the selection signal.  Qt does not
        emit ``itemSelectionChanged`` when the user clicks the already-current
        item, which made a newly created/selected playlist card look inert.
        Refresh that scope explicitly in this case while keeping the list and
        carousel selection in sync.
        """

        for index in range(self.playlist_list.count()):
            item = self.playlist_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == playlist_id:
                if (
                    self.selected_playlist_id == playlist_id
                    and self.playlist_list.currentRow() == index
                ):
                    self._load_selected_playlist_tracks()
                    self._populate_playlist_carousel(
                        self.playlist_management_service.list_playlists()
                    )
                    return
                self.playlist_list.setCurrentItem(item)
                return

        # A card can outlive a library refresh by one event loop turn.  Do not
        # silently swallow its click if the playlist is still in the store.
        if self.store.get_playlist(playlist_id) is not None:
            self.selected_playlist_id = playlist_id
            self._load_selected_playlist_tracks()

    def _show_playlist_context_menu(
        self,
        playlist_id: str,
        global_position: object,
    ) -> None:
        playlist = self.store.get_playlist(playlist_id)
        if playlist is None:
            return

        menu = self._build_playlist_context_menu(playlist_id)
        menu.exec(global_position)

    def _build_playlist_context_menu(self, playlist_id: str) -> QMenu:
        menu = QMenu(self)

        play_action = menu.addAction("Play playlist")
        play_action.triggered.connect(
            lambda checked=False: self._start_playlist_queue(
                playlist_id=playlist_id,
                shuffle=False,
            )
        )
        shuffle_action = menu.addAction("Shuffle playlist")
        shuffle_action.triggered.connect(
            lambda checked=False: self._start_playlist_queue(
                playlist_id=playlist_id,
                shuffle=True,
            )
        )
        smart_shuffle_action = menu.addAction(
            "Smart shuffle playlist"
        )
        smart_shuffle_action.triggered.connect(
            lambda checked=False: self._start_playlist_queue(
                playlist_id=playlist_id,
                shuffle=False,
                smart=True,
            )
        )
        menu.addAction(
            "Add playlist to queue",
            lambda: self._enqueue_playlist(playlist_id),
        )
        menu.addSeparator()
        menu.addAction(
            "Rename playlist",
            lambda: self._rename_playlist(playlist_id),
        )
        menu.addAction(
            "Change artwork",
            lambda: self._set_playlist_cover(playlist_id),
        )
        menu.addSeparator()
        menu.addAction(
            "Delete playlist",
            lambda: self._delete_playlist(playlist_id),
        )
        return menu

    def _set_playlist_cover(
        self,
        playlist_id: str | None = None,
    ) -> None:
        playlist = self._resolve_playlist(playlist_id)
        if playlist is None:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose playlist artwork",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not file_path:
            return

        try:
            self.playlist_management_service.set_cover(
                playlist.id,
                Path(file_path),
            )
        except (FileNotFoundError, OSError, ValueError) as error:
            QMessageBox.warning(self, "Artwork failed", str(error))
            return

        self._load_playlists()

    def _handle_playlist_selection(self) -> None:
        selected_items = self.playlist_list.selectedItems()

        if not selected_items:
            self._show_main_library()
            return

        playlist_id = selected_items[0].data(
            Qt.ItemDataRole.UserRole
        )

        if not isinstance(playlist_id, str):
            return

        self.selected_playlist_id = playlist_id
        self._load_selected_playlist_tracks()
        self._populate_playlist_carousel(
            self.playlist_management_service.list_playlists()
        )

    def _load_selected_playlist_tracks(self) -> None:
        self.playlist_track_list.clear()

        if self.selected_playlist_id is None:
            return

        playlist = self.store.get_playlist(self.selected_playlist_id)
        if playlist is None:
            self._show_main_library()
            return

        tracks = self.playlist_management_service.get_playlist_tracks(
            self.selected_playlist_id
        )

        self._set_visible_tracks(
            tracks,
            title=playlist.name,
        )

    def _create_playlist(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "New playlist",
            "Playlist name:",
        )

        if not accepted:
            return

        try:
            playlist = self.playlist_management_service.create_playlist(name)
        except ValueError as error:
            QMessageBox.warning(self, "Playlist failed", str(error))
            return

        self.selected_playlist_id = playlist.id
        # New playlists are sorted to the front of the carousel.  Keep the
        # user on the first page so the newly created card is visible instead
        # of jumping to the old last page.
        self._playlist_page_index = 0
        self._playlist_scroll_animation.stop()
        self._load_playlists()
        self.playlist_scroll.horizontalScrollBar().setValue(0)

    def _rename_playlist(
        self,
        playlist_id: str | None = None,
    ) -> None:
        playlist = self._resolve_playlist(playlist_id)

        if playlist is None:
            return

        name, accepted = QInputDialog.getText(
            self,
            "Rename playlist",
            "Playlist name:",
            text=playlist.name,
        )

        if not accepted:
            return

        try:
            self.playlist_management_service.rename_playlist(
                playlist.id,
                name,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Playlist failed", str(error))
            return

        self._load_playlists()

    def _delete_playlist(
        self,
        playlist_id: str | None = None,
    ) -> None:
        playlist = self._resolve_playlist(playlist_id)

        if playlist is None:
            return

        confirmation = QMessageBox.question(
            self,
            "Delete playlist",
            f"Delete playlist '{playlist.name}'?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        was_open = self.selected_playlist_id == playlist.id
        self.playlist_management_service.delete_playlist(playlist.id)
        if was_open:
            self.selected_playlist_id = None
        self._load_playlists()
        if was_open:
            self._show_main_library()

    def _add_selected_track_to_playlist(self) -> None:
        if self.selected_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a library track first.",
            )
            return

        if self.selected_playlist_id is None:
            QMessageBox.warning(
                self,
                "No playlist selected",
                "Select a playlist first.",
            )
            return

        self._add_track_to_playlist(
            self.selected_playlist_id,
            self.selected_track_id,
        )

    def _add_track_to_playlist(
        self,
        playlist_id: str,
        track_id: str,
    ) -> None:
        try:
            self.playlist_management_service.add_track(
                playlist_id,
                track_id,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Playlist failed", str(error))
            return

        if playlist_id == self.selected_playlist_id:
            self._load_selected_playlist_tracks()

        self.statusBar().showMessage("Track added to playlist")

    def _remove_selected_playlist_track(self) -> None:
        if self.selected_playlist_id is None:
            QMessageBox.warning(
                self,
                "No playlist selected",
                "Select a playlist first.",
            )
            return

        row = self.track_table.currentRow()
        title_item = self.track_table.item(row, 0)
        track_id = (
            title_item.data(Qt.ItemDataRole.UserRole)
            if title_item is not None
            else None
        )
        if not isinstance(track_id, str):
            QMessageBox.warning(
                self,
                "No playlist track selected",
                "Select a playlist track first.",
            )
            return

        self._remove_playlist_track(track_id)

    def _remove_playlist_track(self, track_id: str) -> None:
        """Remove one track from the open playlist and refresh its table."""

        if self.selected_playlist_id is None:
            return

        try:
            self.playlist_management_service.remove_track(
                self.selected_playlist_id,
                track_id,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Playlist failed", str(error))
            return

        self._load_selected_playlist_tracks()
        self.statusBar().showMessage("Track removed from playlist")

    def _play_playlist(self) -> None:
        self._start_playlist_queue(shuffle=False)

    def _shuffle_playlist(self) -> None:
        self._start_playlist_queue(shuffle=True)

    def _smart_shuffle_playlist(self) -> None:
        self._start_playlist_queue(
            shuffle=False,
            smart=True,
        )

    def _start_playlist_queue(
        self,
        *,
        shuffle: bool,
        smart: bool = False,
        playlist_id: str | None = None,
        start_track_id: str | None = None,
    ) -> None:
        playlist = self._resolve_playlist(playlist_id)

        if playlist is None:
            return

        tracks = self.playlist_management_service.get_playlist_tracks(
            playlist.id
        )
        # A playlist keeps its saved order until the user explicitly chooses
        # another library sort; playback should follow the same visible order
        # as the table when that sort is active.
        tracks = self._sort_tracks(tracks)

        if not tracks:
            QMessageBox.information(
                self,
                "Playlist is empty",
                "Add at least one track before playback.",
            )
            return

        manual_track_ids = self._manual_queue_snapshot()
        track_ids = [track.id for track in tracks]

        if start_track_id is not None and start_track_id in track_ids:
            start_index = track_ids.index(start_track_id)
            if shuffle or smart:
                track_ids = [
                    start_track_id,
                    *(
                        track_id
                        for track_id in track_ids
                        if track_id != start_track_id
                    ),
                ]
            else:
                track_ids = track_ids[start_index:]

        if smart:
            library_tracks = list(self.store.list_tracks())
            similarity_index = TrackSimilarityIndex(
                library_tracks,
            )
            track_ids = list(
                SmartShuffleBuilder(
                    library_tracks,
                    similarity_index,
                ).build(track_ids)
            )
        elif shuffle:
            first_track_id = track_ids[0] if start_track_id else None
            remaining_ids = track_ids[1:] if first_track_id else track_ids
            random.shuffle(remaining_ids)
            track_ids = (
                [first_track_id, *remaining_ids]
                if first_track_id is not None
                else remaining_ids
            )

        manual_id_set = set(manual_track_ids)
        if track_ids:
            track_ids = [
                track_ids[0],
                *(
                    track_id
                    for track_id in track_ids[1:]
                    if track_id not in manual_id_set
                ),
            ]

        self._playback_mode = (
            QueueMode.SMART_SHUFFLE
            if smart
            else QueueMode.SHUFFLE
            if shuffle
            else QueueMode.NORMAL
        )
        self._track_radio_enabled = False
        self._update_playback_mode_controls()
        self.playback_queue_service.start(
            track_ids,
            mode=(
                QueueMode.SMART_SHUFFLE
                if smart
                else (
                    QueueMode.SHUFFLE
                    if shuffle
                    else QueueMode.NORMAL
                )
            ),
            source_playlist_id=playlist.id,
        )
        self._restore_manual_queue(manual_track_ids)
        self._load_queue()
        self._play_current_queue_track()

    def _get_selected_playlist(self) -> Playlist | None:
        if self.selected_playlist_id is None:
            QMessageBox.warning(
                self,
                "No playlist selected",
                "Select a playlist first.",
            )
            return None

        playlist = self.store.get_playlist(self.selected_playlist_id)

        if playlist is None:
            QMessageBox.warning(
                self,
                "Playlist failed",
                "Playlist was not found.",
            )
            return None

        return playlist

    def _resolve_playlist(
        self,
        playlist_id: str | None,
    ) -> Playlist | None:
        if playlist_id is None:
            return self._get_selected_playlist()

        playlist = self.store.get_playlist(playlist_id)
        if playlist is None:
            QMessageBox.warning(
                self,
                "Playlist failed",
                "Playlist was not found.",
            )
            return None

        return playlist

    def _handle_track_selection(self) -> None:
        selected_items = self.track_table.selectedItems()

        if not selected_items:
            self.selected_track_id = None
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.queue_selected_button.setEnabled(False)
            self.analyze_genres_button.setEnabled(False)
            self._refresh_track_row_visuals()
            self._load_recommendations()
            return

        title_item = selected_items[0]

        self.selected_track_id = title_item.data(
            Qt.ItemDataRole.UserRole
        )
        self._refresh_track_row_visuals()
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.queue_selected_button.setEnabled(True)
        self.analyze_genres_button.setEnabled(
            self._genre_statuses.get(
                self.selected_track_id,
                "Not analyzed",
            )
            != "Queued"
        )

        track = self.store.get_track(self.selected_track_id)
        if track is not None:
            self.statusBar().showMessage(
                f"Selected: {track.artist} — {track.title}"
            )
        self._load_recommendations()

    def _play_track_from_table_row(self, row_index: int) -> None:
        """Play a library track when its row is double-clicked."""

        if row_index < 0 or row_index >= self.track_table.rowCount():
            return

        title_item = self.track_table.item(row_index, 0)
        if title_item is None:
            return

        track_id = title_item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(track_id, str):
            return

        self.track_table.selectRow(row_index)
        self._play_track_now(track_id)

    def _toggle_playback(self) -> None:
        state = self.media_player.playbackState()
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            return

        if self.current_track_id is not None:
            self.media_player.play()
            return

        self._play_selected_track()

    def _handle_playback_state_changed(
        self,
        state: QMediaPlayer.PlaybackState,
    ) -> None:
        self.player_play_button.set_svg(
            PAUSE_ICON
            if state == QMediaPlayer.PlaybackState.PlayingState
            else PLAY_ICON
        )

    def _handle_player_duration_changed(self, duration_ms: int) -> None:
        self._player_duration_ms = max(duration_ms, 0)
        self.player_duration_label.setText(
            self._format_duration(self._player_duration_ms)
        )

    def _handle_player_position_changed(self, position_ms: int) -> None:
        self.player_position_label.setText(
            self._format_duration(max(position_ms, 0))
        )
        self._accumulate_playback_time(position_ms)
        self._record_played_30_seconds()
        self._record_completed_listen(position_ms)
        if (
            self._player_duration_ms <= 0
            or self.player_progress_slider.isSliderDown()
        ):
            return

        self.player_progress_slider.setValue(
            round(position_ms * 1000 / self._player_duration_ms)
        )

    def _accumulate_playback_time(self, position_ms: int) -> None:
        """Track real playback time without counting seek jumps."""

        if self.current_track_id is None:
            return

        previous = self._current_track_last_position_ms
        self._current_track_last_position_ms = max(position_ms, 0)
        if previous is None:
            return

        delta_ms = position_ms - previous
        if 0 < delta_ms <= 5_000:
            self._current_track_played_ms += delta_ms

    def _record_playback_signal(
        self,
        interaction_type: InteractionType,
    ) -> None:
        """Persist passive playback telemetry without interrupting audio."""

        if self.current_track_id is None:
            return
        try:
            self.interaction_service.record(
                user_id=self.user_id,
                track_id=self.current_track_id,
                interaction_type=interaction_type,
                mood_context=self._get_active_mood_context(),
            )
        except ValueError as error:
            # Telemetry must never interrupt playback or surface a modal.
            self.statusBar().showMessage(f"Playback stat failed: {error}")

    def _record_played_30_seconds(self) -> None:
        """Record a positive signal after 30 seconds actually played."""

        if (
            self._current_track_played_30s_recorded
            or self.current_track_id is None
            or self._current_track_played_ms < 30_000
        ):
            return

        self._current_track_played_30s_recorded = True
        self._record_playback_signal(InteractionType.PLAYED_30S)

    def _record_completed_listen(self, position_ms: int) -> None:
        """Record a completed listen at 80% of real playback progress."""

        if self._current_track_listen_recorded or self.current_track_id is None:
            return
        duration_ms = self._player_duration_ms
        if duration_ms <= 0:
            track = self.store.get_track(self.current_track_id)
            duration_ms = track.duration_ms if track is not None else 0
        if duration_ms <= 0 or position_ms * 100 < duration_ms * 80:
            return
        if self._current_track_played_ms < duration_ms * 0.8:
            return

        self._current_track_listen_recorded = True
        self._record_playback_signal(InteractionType.COMPLETED_80)

    def _seek_player(self) -> None:
        if self._player_duration_ms <= 0:
            return

        position_ms = round(
            self.player_progress_slider.value()
            * self._player_duration_ms
            / self.player_progress_slider.maximum()
        )
        self.media_player.setPosition(position_ms)
        self._current_track_last_position_ms = position_ms
        self._record_playback_signal(InteractionType.SEEK)

    def _import_track(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select audio file",
            "",
            (
                "Audio files "
                "(*.mp3 *.wav *.flac *.m4a *.mp4 *.ogg *.opus)"
            ),
        )

        if not file_path:
            return

        source_path = Path(file_path)

        try:
            metadata = read_audio_metadata(source_path)
        except (FileNotFoundError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Import failed",
                str(error),
            )
            return

        metadata_dialog = TrackMetadataDialog(
            parent=self,
            file_path=source_path,
            metadata=metadata,
        )

        if (
            metadata_dialog.exec()
            != QDialog.DialogCode.Accepted
        ):
            return

        title, artist = (
            metadata_dialog.get_values()
        )

        try:
            track = self.ingestion_service.ingest(
                source_path,
                title=title,
                artist=artist,
                source="windows_import",
            )
        except (FileNotFoundError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Import failed",
                str(error),
            )
            return

        self._append_library_track(track)
        self._enqueue_genre_analysis(track)
        self._load_queue()
        self._maybe_refresh_recommendations()

        QMessageBox.information(
            self,
            "Import completed",
            (
                f"Added:\n"
                f"{track.artist} — {track.title}"
            ),
        )

    def _import_folder(self) -> None:
        """Import supported audio files from a local folder recursively."""

        folder_path = QFileDialog.getExistingDirectory(
            self,
            "Select local audio folder",
        )
        if not folder_path:
            return

        folder = Path(folder_path)
        audio_files = sorted(
            (
                path
                for path in folder.rglob("*")
                if path.is_file()
                and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
            ),
            key=lambda path: str(path).casefold(),
        )
        if not audio_files:
            QMessageBox.information(
                self,
                "Folder is empty",
                "No supported audio files were found in this folder.",
            )
            return

        imported_count = 0
        skipped_count = 0
        for source_path in audio_files:
            try:
                track = self.ingestion_service.ingest(
                    source_path,
                    fallback_title=source_path.stem,
                    source="windows_folder_import",
                )
            except (
                FileNotFoundError,
                OSError,
                ValueError,
            ):
                skipped_count += 1
                continue

            imported_count += 1
            self._append_library_track(track)
            self._enqueue_genre_analysis(track)

        self.library_count_label.setText(
            f"{self.track_table.rowCount()} tracks"
        )
        self._load_queue()
        self._maybe_refresh_recommendations()

        message = f"Imported {imported_count} track(s) from the folder."
        if skipped_count:
            message += f"\nSkipped {skipped_count} file(s)."
        QMessageBox.information(self, "Folder import completed", message)

    def _show_import_log(self) -> None:
        """Show a read-only history of successful library additions."""

        try:
            tracks = list(self.store.list_tracks())
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Import log unavailable",
                str(error),
            )
            return

        self._show_auxiliary_dialog(ImportLogDialog(tracks, self))

    def _open_library_maintenance(self) -> None:
        """Open the library-health, backup and restore center."""

        dialog = LibraryMaintenanceDialog(
            self,
            watch_config=self.watch_folder_service.config,
        )
        dialog.scan_requested.connect(
            lambda: self._scan_library_health(dialog)
        )
        dialog.zip_backup_requested.connect(
            lambda: self._create_library_zip_backup(dialog)
        )
        dialog.json_export_requested.connect(
            lambda: self._export_library_json(dialog)
        )
        dialog.restore_requested.connect(
            lambda: self._restore_library_zip_backup(dialog)
        )
        dialog.watch_folder_requested.connect(
            lambda: self._choose_watch_folder(dialog)
        )
        dialog.watch_sync_requested.connect(
            lambda: self._sync_watch_folder(dialog)
        )
        dialog.watch_disable_requested.connect(
            lambda: self._disable_watch_folder(dialog)
        )
        dialog.watch_update_metadata_toggled.connect(
            self._set_watch_folder_metadata_updates
        )
        self._show_auxiliary_dialog(dialog)

    def _choose_watch_folder(
        self,
        dialog: LibraryMaintenanceDialog,
    ) -> None:
        current = self.watch_folder_service.config.folder
        folder_path = QFileDialog.getExistingDirectory(
            dialog,
            "Choose watch folder",
            str(current or DATA_DIR.parent),
        )
        if not folder_path:
            return
        try:
            config = self.watch_folder_service.configure(
                Path(folder_path),
                update_metadata=dialog.watch_metadata_check.isChecked(),
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(dialog, "Watch folder failed", str(error))
            return
        dialog.set_watch_config(config)
        self.statusBar().showMessage(
            f"Watch folder enabled: {config.folder}"
        )
        self._sync_watch_folder(dialog)

    def _set_watch_folder_metadata_updates(self, enabled: bool) -> None:
        try:
            self.watch_folder_service.set_update_metadata(enabled)
        except OSError as error:
            self.statusBar().showMessage(
                f"Could not save watch-folder setting: {error}"
            )

    def _disable_watch_folder(
        self,
        dialog: LibraryMaintenanceDialog,
    ) -> None:
        config = self.watch_folder_service.disable()
        dialog.set_watch_config(config)
        self.statusBar().showMessage("Watch folder disabled")

    def _sync_watch_folder(
        self,
        dialog: LibraryMaintenanceDialog | None = None,
    ) -> None:
        if not self.watch_folder_service.config.enabled:
            if dialog is not None:
                dialog.set_watch_config(self.watch_folder_service.config)
            return
        if self._watch_sync_thread is not None:
            return

        thread = WatchFolderTaskThread(
            lambda: self.watch_folder_service.sync(
                self.ingestion_service,
                self.track_management_service,
            ),
            self,
        )
        self._watch_sync_thread = thread
        self._watch_sync_dialog = dialog
        thread.result_ready.connect(self._handle_watch_folder_report)
        thread.error_occurred.connect(
            lambda message: self._handle_watch_folder_error(dialog, message)
        )
        thread.finished.connect(self._finish_watch_folder_sync)
        thread.start()

    def _handle_watch_folder_report(self, result: object) -> None:
        if not isinstance(result, WatchFolderReport):
            return
        dialog = self._watch_sync_dialog
        if dialog is not None and dialog.isVisible():
            dialog.show_watch_report(result)
        if result.changed:
            for track in result.imported:
                self._append_library_track(track)
                self._enqueue_genre_analysis(track)
            self._load_library()
            self.statusBar().showMessage(
                "Watch folder: "
                f"{len(result.imported)} imported, "
                f"{len(result.updated)} updated, "
                f"{len(result.removed_files)} removed from source"
            )
        elif result.errors:
            self.statusBar().showMessage(
                f"Watch folder: {len(result.errors)} file(s) need attention"
            )

    def _handle_watch_folder_error(
        self,
        dialog: LibraryMaintenanceDialog | None,
        message: str,
    ) -> None:
        if dialog is not None and dialog.isVisible():
            dialog.watch_status.setText(f"Sync failed: {message}")
        self.statusBar().showMessage(f"Watch folder sync failed: {message}")

    def _finish_watch_folder_sync(self) -> None:
        thread = self._watch_sync_thread
        self._watch_sync_thread = None
        self._watch_sync_dialog = None
        if thread is not None:
            thread.deleteLater()

    def _show_statistics_dashboard(self) -> None:
        """Show the four-panel listening dashboard for the active user."""

        try:
            statistics = self.statistics_service.build(self.user_id)
            recommendation_metrics = self.recommendation_analytics_service.build(
                self.user_id
            )
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Statistics unavailable",
                str(error),
            )
            return

        track_catalog = tuple(self._library_tracks)
        if not track_catalog:
            track_catalog = tuple(self.store.list_tracks())
        self._show_auxiliary_dialog(
            ListeningStatisticsDialog(
                statistics,
                self,
                track_catalog=track_catalog,
                recommendation_metrics=recommendation_metrics,
            )
        )

    def _scan_library_health(
        self,
        dialog: LibraryMaintenanceDialog,
    ) -> None:
        if self._library_health_thread is not None:
            return

        dialog.set_scanning(True)
        thread = LibraryHealthTaskThread(
            self.library_health_service,
            self,
        )
        self._library_health_thread = thread
        thread.result_ready.connect(
            lambda report: self._handle_library_health_report(dialog, report)
        )
        thread.error_occurred.connect(dialog.show_scan_error)
        thread.finished.connect(self._finish_library_health_scan)
        thread.start()

    def _handle_library_health_report(
        self,
        dialog: LibraryMaintenanceDialog,
        report: object,
    ) -> None:
        if not isinstance(report, LibraryHealthReport):
            dialog.show_scan_error("The check returned an invalid result.")
            return
        if dialog.isVisible():
            dialog.show_report(report)

    def _finish_library_health_scan(self) -> None:
        thread = self._library_health_thread
        self._library_health_thread = None
        if thread is not None:
            thread.deleteLater()

    def _create_library_zip_backup(
        self,
        dialog: LibraryMaintenanceDialog,
    ) -> None:
        default_path = DATA_DIR.parent / "Musefy library backup.zip"
        filename, _ = QFileDialog.getSaveFileName(
            dialog,
            "Save full Musefy backup",
            str(default_path),
            "Musefy backups (*.zip)",
        )
        if not filename:
            return

        try:
            summary = self.library_backup_service.create_zip_backup(
                Path(filename),
            )
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(dialog, "Backup failed", str(error))
            return

        QMessageBox.information(
            dialog,
            "Backup created",
            (
                f"Full backup saved to:\n{summary.path}\n\n"
                f"{summary.track_count} track(s), "
                f"{summary.playlist_count} playlist(s), and "
                f"{summary.interaction_count} interaction(s) included."
            ),
        )

    def _export_library_json(
        self,
        dialog: LibraryMaintenanceDialog,
    ) -> None:
        default_path = DATA_DIR.parent / "Musefy library export.json"
        filename, _ = QFileDialog.getSaveFileName(
            dialog,
            "Export Musefy catalog as JSON",
            str(default_path),
            "Musefy JSON export (*.json)",
        )
        if not filename:
            return

        try:
            summary = self.library_backup_service.export_json(
                Path(filename),
            )
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(dialog, "Export failed", str(error))
            return

        QMessageBox.information(
            dialog,
            "JSON export created",
            (
                f"Catalog export saved to:\n{summary.path}\n\n"
                "It contains playlists, history, likes and analysis, but not "
                "the audio files. Use a full ZIP backup to restore a library."
            ),
        )

    def _restore_library_zip_backup(
        self,
        dialog: LibraryMaintenanceDialog,
    ) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            dialog,
            "Choose Musefy backup to restore",
            str(DATA_DIR.parent),
            "Musefy backups (*.zip)",
        )
        if not filename:
            return

        confirmation = QMessageBox.question(
            dialog,
            "Restore library backup",
            (
                "This replaces the current local library database, audio "
                "files and covers with the selected backup.\n\n"
                "Create a backup first if you need to keep current changes. "
                "Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        self.media_player.stop()
        engine.dispose()
        try:
            self.library_backup_service.restore_zip_backup(Path(filename))
            create_database()
            self._ensure_restored_current_user()
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(dialog, "Restore failed", str(error))
            return

        self.selected_track_id = None
        self.selected_playlist_id = None
        self.current_track_id = None
        self.playback_queue_service.clear()
        self.recommendation_service.refresh()
        self._load_playlists()
        self._load_library()
        self._load_recommendations()
        QMessageBox.information(
            dialog,
            "Backup restored",
            "The local library has been restored from the selected backup.",
        )

    def _ensure_restored_current_user(self) -> None:
        """Keep the active desktop profile usable after restoring another PC."""

        if self.store.get_user(self.user_id) is not None:
            return

        from app.domain.models import User

        self.store.add_user(
            User(
                id=self.user_id,
                display_name="Desktop User",
            )
        )

    def _import_from_youtube(self) -> None:
        spotify_provider = self.youtube_import_service.spotify_provider
        dialog = YouTubeSearchDialog(
            self,
            spotify_authenticated=spotify_provider.has_saved_credentials(),
            spotify_sync_enabled=self.spotify_fav_sync_service.is_enabled(),
        )
        dialog.source_requested.connect(
            lambda source: self._start_youtube_or_spotify_source(
                dialog,
                source,
            )
        )
        dialog.soundcloud_download_requested.connect(
            lambda source: self._start_soundcloud_search(
                dialog,
                source,
            )
        )
        dialog.soundcloud_import_requested.connect(
            lambda candidate: self._start_soundcloud_download(
                dialog,
                candidate,
            )
        )
        dialog.mp3party_download_requested.connect(
            lambda source: self._start_mp3party_search(
                dialog,
                source,
            )
        )
        dialog.mp3party_import_requested.connect(
            lambda candidate: self._start_mp3party_download(
                dialog,
                candidate,
            )
        )
        dialog.authenticate_requested.connect(
            lambda url: self._start_url_authentication(
                dialog,
                url,
            )
        )
        dialog.spotify_settings_requested.connect(
            lambda: self._open_spotify_settings(dialog)
        )
        dialog.spotify_sync_toggled.connect(
            lambda enabled: self._handle_spotify_sync_toggled(
                enabled,
                dialog,
            )
        )
        dialog.import_requested.connect(
            lambda candidate: (
                self._start_youtube_import(
                    dialog,
                    candidate,
                )
            )
        )
        dialog.playlist_import_requested.connect(
            lambda candidates: self._start_playlist_import(
                dialog,
                candidates,
            )
        )

        self._show_auxiliary_dialog(dialog)

    def _start_soundcloud_download(
        self,
        dialog: YouTubeSearchDialog,
        source: str | SoundCloudCandidate,
    ) -> None:
        if self._youtube_thread is not None:
            return

        dialog.set_busy(True, "Downloading from SoundCloud...")
        dialog.resume_progress("Downloading from SoundCloud...")

        thread = YouTubeTaskThread(
            lambda: self.soundcloud_import_service.download(source),
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_youtube_import_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_soundcloud_search(
        self,
        dialog: YouTubeSearchDialog,
        source: str,
    ) -> None:
        if self._youtube_thread is not None:
            return

        if self.soundcloud_import_service.is_playlist_url(source):
            self._start_soundcloud_playlist_load(dialog, source)
            return

        if self.soundcloud_import_service.is_supported_url(source):
            self._start_soundcloud_download(dialog, source)
            return

        dialog.set_busy(True, "Searching SoundCloud...")
        dialog.start_progress("Searching SoundCloud...")

        thread = YouTubeTaskThread(
            lambda: self.soundcloud_import_service.search(
                source,
                max_results=SoundCloudImportService.DEFAULT_SEARCH_RESULTS,
            ),
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_soundcloud_search_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_soundcloud_playlist_load(
        self,
        dialog: YouTubeSearchDialog,
        url: str,
    ) -> None:
        if self._youtube_thread is not None:
            return

        dialog.set_busy(True, "Loading SoundCloud playlist...")
        dialog.start_progress("Loading SoundCloud playlist...")

        thread = YouTubeTaskThread(
            lambda: self.soundcloud_import_service.playlist(url),
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_soundcloud_playlist_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_mp3party_search(
        self,
        dialog: YouTubeSearchDialog,
        source: str,
    ) -> None:
        if self._youtube_thread is not None:
            return

        if self.mp3party_import_service.is_supported_url(source):
            self._start_mp3party_download(dialog, source)
            return

        dialog.set_busy(True, "Searching MP3Party...")
        dialog.start_progress("Searching MP3Party...")

        thread = YouTubeTaskThread(
            lambda: self.mp3party_import_service.search(
                source,
                max_results=Mp3PartyImportService.DEFAULT_SEARCH_RESULTS,
            ),
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_mp3party_search_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_mp3party_download(
        self,
        dialog: YouTubeSearchDialog,
        source: str | Mp3PartyCandidate,
    ) -> None:
        if self._youtube_thread is not None:
            return

        dialog.set_busy(True, "Downloading from MP3Party...")
        dialog.resume_progress("Downloading from MP3Party...")

        thread = YouTubeTaskThread(
            lambda: self.mp3party_import_service.download(source),
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_youtube_import_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_youtube_or_spotify_source(
        self,
        dialog: YouTubeSearchDialog,
        source: str,
    ) -> None:
        """Route one input field to search or URL loading automatically."""

        if self.soundcloud_import_service.is_supported_url(source):
            self._start_soundcloud_search(dialog, source)
            return

        if self.mp3party_import_service.is_supported_url(source):
            self._start_mp3party_search(dialog, source)
            return

        if self.youtube_import_service.is_supported_url(source):
            self._start_url_load(dialog, source)
            return

        self._start_youtube_search(dialog, source)

    def _import_exported_playlist(self) -> None:
        export_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open exported playlist",
            str(PLAYLIST_EXPORTS_DIR),
            "Playlist exports (*.json)",
        )

        if not export_path:
            return

        spotify_provider = self.youtube_import_service.spotify_provider
        dialog = YouTubeSearchDialog(
            self,
            spotify_authenticated=spotify_provider.has_saved_credentials(),
            spotify_sync_enabled=self.spotify_fav_sync_service.is_enabled(),
        )
        dialog.set_busy(True, "Reading exported playlist...")
        dialog.start_progress("Reading exported playlist...")
        dialog.playlist_import_requested.connect(
            lambda candidates: self._start_youtube_playlist_import(
                dialog,
                candidates,
            )
        )
        dialog.spotify_settings_requested.connect(
            lambda: self._open_spotify_settings(dialog)
        )
        dialog.spotify_sync_toggled.connect(
            lambda enabled: self._handle_spotify_sync_toggled(
                enabled,
                dialog,
            )
        )

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.search_playlist_export(
                Path(export_path),
                on_progress=thread.search_progress_updated.emit,
                should_cancel=thread.is_cancelled,
            ),
            self,
        )
        thread.search_progress_updated.connect(
            dialog.update_search_progress
        )
        thread.result_ready.connect(
            lambda result: self._handle_exported_playlist_search_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)
        self._show_auxiliary_dialog(dialog)

    def _handle_exported_playlist_search_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, SpotifyPlaylistSearchResult):
            self._handle_youtube_error(
                dialog,
                "Exported playlist search returned an invalid result.",
            )
            return

        self._handle_spotify_search_result(dialog, result)

    def _start_youtube_search(
        self,
        dialog: YouTubeSearchDialog,
        query: str,
    ) -> None:
        if self._youtube_thread is not None:
            return

        dialog.set_busy(True, "Searching YouTube...")
        dialog.start_progress("Searching YouTube...")

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.search(
                query,
                should_cancel=thread.is_cancelled,
            ),
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_youtube_search_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_url_authentication(
        self,
        dialog: YouTubeSearchDialog,
        url: str,
    ) -> None:
        if self._youtube_thread is not None:
            return

        dialog.set_busy(True, "Authenticating Spotify...")
        dialog.start_progress("Connecting to Spotify...")

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.authenticate_url(url),
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_authentication_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_url_load(
        self,
        dialog: YouTubeSearchDialog,
        url: str,
    ) -> None:
        if self._youtube_thread is not None:
            return

        loading_message = (
            "Connecting to Spotify and reading tracks..."
            if "spotify" in url.casefold()
            else "Detecting and loading URL..."
        )
        dialog.set_busy(True, loading_message)
        dialog.start_progress(loading_message)

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.load_url(
                url,
                on_progress=thread.search_progress_updated.emit,
                should_cancel=thread.is_cancelled,
            ),
            self,
        )
        thread.search_progress_updated.connect(
            dialog.update_search_progress
        )
        thread.result_ready.connect(
            lambda result: self._handle_url_load_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_youtube_import(
        self,
        dialog: YouTubeSearchDialog,
        candidate: YouTubeCandidate,
    ) -> None:
        if self._youtube_thread is not None:
            return

        dialog.set_busy(True, "Downloading and importing...")
        dialog.resume_progress("Downloading and importing...")

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.download_and_import(
                candidate,
            ),
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_youtube_import_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_playlist_import(
        self,
        dialog: YouTubeSearchDialog,
        candidates: object,
    ) -> None:
        if isinstance(candidates, list) and not candidates:
            self._show_skipped_playlist_review(dialog)
            return

        if isinstance(candidates, list) and candidates and all(
            isinstance(candidate, SoundCloudCandidate)
            for candidate in candidates
        ):
            self._start_soundcloud_playlist_import(dialog, candidates)
            return

        if isinstance(candidates, list) and candidates and all(
            isinstance(candidate, Mp3PartyCandidate)
            for candidate in candidates
        ):
            self._start_mp3party_playlist_import(dialog, candidates)
            return

        self._start_youtube_playlist_import(dialog, candidates)

    def _show_skipped_playlist_review(
        self,
        dialog: YouTubeSearchDialog,
    ) -> None:
        """Keep an all-unchecked playlist actionable for alternate search."""

        failed = dialog.skipped_playlist_candidates
        unmatched = dialog.unmatched_playlist_tracks
        if not failed and not unmatched:
            return

        unmatched_positions = dialog.unmatched_playlist_positions
        failed_candidates = [candidate for candidate, _ in failed]
        dialog.set_candidates(
            failed_candidates,
            playlist=True,
            playlist_name=dialog.playlist_name,
            playlist_cover_url=dialog.playlist_cover_url,
            unmatched=unmatched,
            unmatched_positions=unmatched_positions,
        )
        dialog.set_busy(
            False,
            (
                f"{len(failed) + len(unmatched)} tracks were not selected "
                "or were not found."
            ),
        )

        result_dialog = PlaylistImportResultDialog(
            0,
            failed,
            dialog,
            unmatched=unmatched,
            unmatched_positions=unmatched_positions,
        )
        for provider in ("youtube", "soundcloud", "mp3party"):
            signal = getattr(
                result_dialog,
                f"{provider}_search_requested",
            )
            signal.connect(
                lambda provider=provider: QTimer.singleShot(
                    0,
                    lambda provider=provider: (
                        self._start_alternative_playlist_search(
                            dialog,
                            failed,
                            unmatched,
                            unmatched_positions,
                            provider,
                        )
                    ),
                )
            )
        result_dialog.exec()

    def _start_soundcloud_playlist_import(
        self,
        dialog: YouTubeSearchDialog,
        candidates: object,
    ) -> None:
        if self._youtube_thread is not None:
            return

        if not isinstance(candidates, list):
            self._handle_youtube_error(
                dialog,
                "SoundCloud playlist selection is invalid.",
            )
            return

        selected_candidates = [
            candidate
            for candidate in candidates
            if isinstance(candidate, SoundCloudCandidate)
        ]

        if not selected_candidates:
            return

        self._playlist_import_active = True
        dialog.set_busy(
            True,
            (
                "Downloading SoundCloud playlist: "
                f"0/{len(selected_candidates)}..."
            ),
        )
        dialog.resume_progress(
            "Downloading SoundCloud playlist: 0/"
            f"{len(selected_candidates)}...",
            total=len(selected_candidates),
        )

        def import_playlist() -> SoundCloudPlaylistImportResult:
            return self.soundcloud_import_service.download_and_import_playlist(
                selected_candidates,
                on_progress=thread.progress_updated.emit,
                on_track_imported=thread.track_imported.emit,
            )

        thread = YouTubeTaskThread(import_playlist, self)
        thread.track_imported.connect(
            lambda candidate, track: (
                self._handle_playlist_track_imported(
                    dialog,
                    candidate,
                    track,
                )
            )
        )
        thread.progress_updated.connect(
            dialog.update_playlist_download_progress
        )
        thread.result_ready.connect(
            lambda result: self._handle_soundcloud_playlist_import_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_playlist_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_mp3party_playlist_import(
        self,
        dialog: YouTubeSearchDialog,
        candidates: object,
    ) -> None:
        """Download selected MP3Party candidates with playlist progress."""

        if self._youtube_thread is not None:
            return

        if not isinstance(candidates, list):
            self._handle_youtube_error(
                dialog,
                "MP3Party playlist selection is invalid.",
            )
            return

        selected_candidates = [
            candidate
            for candidate in candidates
            if isinstance(candidate, Mp3PartyCandidate)
        ]
        if not selected_candidates:
            return

        self._playlist_import_active = True
        dialog.set_busy(
            True,
            (
                "Downloading MP3Party playlist: "
                f"0/{len(selected_candidates)}..."
            ),
        )
        dialog.resume_progress(
            "Downloading MP3Party playlist: 0/"
            f"{len(selected_candidates)}...",
            total=len(selected_candidates),
        )

        def import_playlist() -> Mp3PartyPlaylistImportResult:
            return self.mp3party_import_service.download_and_import_playlist(
                selected_candidates,
                on_progress=thread.progress_updated.emit,
                on_track_imported=thread.track_imported.emit,
            )

        thread = YouTubeTaskThread(import_playlist, self)
        thread.track_imported.connect(
            lambda candidate, track: (
                self._handle_playlist_track_imported(
                    dialog,
                    candidate,
                    track,
                )
            )
        )
        thread.progress_updated.connect(
            dialog.update_playlist_download_progress
        )
        thread.result_ready.connect(
            lambda result: self._handle_mp3party_playlist_import_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_playlist_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _open_spotify_settings(
        self,
        source_dialog: YouTubeSearchDialog | None = None,
    ) -> None:
        provider = self.youtube_import_service.spotify_provider
        settings_dialog = SpotifySettingsDialog(
            parent=self,
            authenticated=provider.has_saved_credentials(),
            sync_enabled=self.spotify_fav_sync_service.is_enabled(),
        )
        settings_dialog.authenticate_requested.connect(
            lambda: self._start_spotify_settings_auth(settings_dialog)
        )
        settings_dialog.sync_toggled.connect(
            self._handle_spotify_sync_toggled
        )
        settings_dialog.sync_requested.connect(
            lambda: self._start_spotify_sync_all(settings_dialog)
        )
        settings_dialog.finished.connect(
            lambda _result: self._handle_spotify_settings_closed(source_dialog)
        )

        self._show_auxiliary_dialog(settings_dialog)

    def _handle_spotify_settings_closed(
        self,
        source_dialog: YouTubeSearchDialog | None,
    ) -> None:
        if source_dialog is not None:
            provider = self.youtube_import_service.spotify_provider
            source_dialog.set_spotify_authenticated(
                provider.has_saved_credentials()
            )
            source_dialog.set_spotify_sync_enabled(
                self.spotify_fav_sync_service.is_enabled()
            )

    def _show_auxiliary_dialog(self, dialog: QDialog) -> None:
        """Show a modeless dialog and wire its in-app minimize affordance."""

        self._register_auxiliary_dialog(dialog)
        self._restore_auxiliary_dialog(dialog)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _register_auxiliary_dialog(self, dialog: QDialog) -> None:
        """Track a dialog so native minimize becomes an in-app chip."""

        if dialog.property("musefyAuxiliaryRegistered"):
            return

        dialog.setProperty("musefyAuxiliaryRegistered", True)
        dialog.installEventFilter(self)
        dialog.finished.connect(
            lambda _result, target=dialog: self._forget_auxiliary_dialog(target)
        )
        closed_signal = getattr(dialog, "closed", None)
        if closed_signal is not None:
            closed_signal.connect(
                lambda target=dialog: self._cancel_dialog_task(target)
            )

    def _cancel_dialog_task(self, dialog: QDialog) -> None:
        """Stop the task owned by a loader that was explicitly closed."""

        if self._youtube_thread_dialog is not dialog:
            return

        thread = self._youtube_thread
        if thread is not None and thread.isRunning():
            thread.cancel()
            # Detach the cancelled loader immediately.  Its in-flight
            # network request is still allowed to unwind safely, while a new
            # loader can be opened without inheriting the old busy state.
            self._youtube_thread = None
            self._youtube_thread_dialog = None

    def _forget_auxiliary_dialog(self, dialog: QDialog) -> None:
        """Remove a closed dialog's restore chip, if it still has one."""

        button = self._auxiliary_dialog_buttons.pop(dialog, None)
        if button is not None:
            layout = self._auxiliary_minimized_layout
            if layout is not None:
                layout.removeWidget(button)
            button.deleteLater()

        container = self._auxiliary_minimized_container
        if container is not None and not self._auxiliary_dialog_buttons:
            container.hide()
        self._position_search_actions()
        QTimer.singleShot(0, self._position_search_actions)

    def _minimize_auxiliary_dialog(self, dialog: QDialog) -> None:
        """Hide a dialog and expose a compact restore button in the top bar."""

        if dialog in self._auxiliary_dialog_buttons:
            return

        layout = self._auxiliary_minimized_layout
        container = self._auxiliary_minimized_container
        if layout is None or container is None:
            return

        title = dialog.windowTitle().strip() or "Auxiliary window"
        if len(title) > 28:
            title = f"{title[:27].rstrip()}…"

        button = QToolButton(container)
        button.setObjectName("auxiliaryMinimizedButton")
        button.setText(title)
        button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        button.setToolTip(f"Restore {dialog.windowTitle()}")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMaximumWidth(220)
        button.clicked.connect(
            lambda _checked=False, target=dialog: self._restore_auxiliary_dialog(
                target
            )
        )
        self._auxiliary_dialog_buttons[dialog] = button
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        container.show()
        self._position_search_actions()
        QTimer.singleShot(0, self._position_search_actions)

        dialog.setProperty("musefyAuxiliaryMinimized", True)
        # Clear the native minimized state before hiding so the OS does not
        # retain an additional taskbar item for a window represented in Musefy.
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        # A native showMinimized() can finish its own visibility update after
        # WindowStateChange is delivered.  Deferring the final hide by one
        # event-loop turn makes the in-app chip win that race consistently.
        QTimer.singleShot(
            0,
            lambda target=dialog: self._hide_minimized_auxiliary_dialog(target),
        )

    def _hide_minimized_auxiliary_dialog(self, dialog: QDialog) -> None:
        if (
            dialog in self._auxiliary_dialog_buttons
            and dialog.property("musefyAuxiliaryMinimized")
        ):
            dialog.setWindowState(Qt.WindowState.WindowNoState)
            dialog.hide()

    def _restore_auxiliary_dialog(self, dialog: QDialog) -> None:
        """Restore a dialog from its compact top-bar button."""

        was_minimized = bool(
            dialog.property("musefyAuxiliaryMinimized")
        )
        button = self._auxiliary_dialog_buttons.pop(dialog, None)
        if button is not None:
            layout = self._auxiliary_minimized_layout
            if layout is not None:
                layout.removeWidget(button)
            button.deleteLater()

        container = self._auxiliary_minimized_container
        if container is not None and not self._auxiliary_dialog_buttons:
            container.hide()
        self._position_search_actions()
        QTimer.singleShot(0, self._position_search_actions)

        dialog.setProperty("musefyAuxiliaryMinimized", False)
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        if was_minimized:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

    def eventFilter(self, watched: object, event: object) -> bool:
        if (
            isinstance(watched, QDialog)
            and watched.property("musefyAuxiliaryRegistered")
            and isinstance(event, QEvent)
            and event.type() == QEvent.Type.WindowStateChange
            and watched.windowState() & Qt.WindowState.WindowMinimized
        ):
            self._minimize_auxiliary_dialog(watched)
            return True

        return super().eventFilter(watched, event)

    def closeEvent(self, event: object) -> None:
        """Stop loader work before the main process is allowed to exit."""

        self._spotify_sync_timer.stop()
        self._watch_folder_timer.stop()
        for dialog in tuple(self._auxiliary_dialog_buttons):
            dialog.close()

        for thread in tuple(self._youtube_threads):
            if not thread.isRunning():
                continue
            thread.cancel()
            # Search services check the interruption flag between requests.
            # Give in-flight network calls a short grace period first.
            if not thread.wait(3_000):
                # The application is already shutting down; do not leave a
                # worker alive to block Qt's event loop indefinitely.
                thread.terminate()
                thread.wait(1_000)

        health_thread = self._library_health_thread
        # Fingerprinting is local CPU work and has no unsafe external side
        # effect, so it can be stopped as a last resort rather than letting
        # Qt destroy a live worker while the app exits.
        if (
            health_thread is not None
            and health_thread.isRunning()
            and not health_thread.wait(3_000)
        ):
            health_thread.terminate()
            health_thread.wait(1_000)

        watch_thread = self._watch_sync_thread
        if (
            watch_thread is not None
            and watch_thread.isRunning()
            and not watch_thread.wait(3_000)
        ):
            watch_thread.terminate()
            watch_thread.wait(1_000)

        if self._recommendation_task is not None:
            self._recommendation_task.cancel()
        self._cancel_radio_recommendations()
        self._genre_analysis_pool.clear()
        self._track_batch_pool.clear()
        self._recommendation_pool.clear()
        self._radio_recommendation_pool.clear()
        self._recommendation_pool.waitForDone(3_000)
        self._radio_recommendation_pool.waitForDone(3_000)
        self.media_player.stop()
        super().closeEvent(event)

    def _handle_spotify_sync_toggled(
        self,
        enabled: bool,
        source_dialog: YouTubeSearchDialog | None = None,
    ) -> None:
        provider = self.youtube_import_service.spotify_provider
        if enabled and not provider.has_saved_credentials():
            if source_dialog is not None:
                source_dialog.set_spotify_sync_enabled(False)

            answer = QMessageBox.question(
                source_dialog or self,
                "Spotify OAuth required",
                "Spotify fav sync needs Spotify OAuth. Open Spotify settings?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._open_spotify_settings(source_dialog)
            self.statusBar().showMessage(
                "Connect Spotify with OAuth before enabling fav sync."
            )
            return

        try:
            self.spotify_fav_sync_service.set_enabled(enabled)
        except OSError as error:
            self.statusBar().showMessage(
                f"Could not save Spotify fav sync setting: {error}"
            )
            return

        if enabled:
            self.statusBar().showMessage(
                "Spotify fav sync enabled. New saved tracks will be checked "
                "every 5 minutes."
            )
        else:
            self.statusBar().showMessage("Spotify fav sync disabled.")

    def _start_spotify_settings_auth(
        self,
        dialog: SpotifySettingsDialog,
    ) -> None:
        if self._youtube_thread is not None:
            return

        dialog.set_busy(True, "Opening Spotify OAuth...")
        dialog.start_progress("Connecting to Spotify...")
        thread = YouTubeTaskThread(
            self.youtube_import_service.reauthorize_spotify,
            self,
        )
        thread.result_ready.connect(
            lambda result: self._handle_spotify_settings_auth_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_spotify_settings_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _handle_spotify_settings_auth_result(
        self,
        dialog: SpotifySettingsDialog,
        result: object,
    ) -> None:
        if not isinstance(result, str):
            self._handle_spotify_settings_error(
                dialog,
                "Spotify OAuth returned an invalid result.",
            )
            return

        authenticated = (
            self.youtube_import_service.spotify_provider.has_saved_credentials()
        )
        dialog.set_authenticated(authenticated)
        dialog.set_busy(False, result)
        dialog.finish_progress(result)
        self.statusBar().showMessage(result)

    def _start_background_spotify_sync(self) -> None:
        if self._youtube_thread is not None:
            return
        if not self.spotify_fav_sync_service.is_enabled():
            return
        if not self.youtube_import_service.spotify_provider.has_saved_credentials():
            return

        self._start_spotify_sync(None, sync_all=False)

    def _start_spotify_sync_all(
        self,
        dialog: SpotifySettingsDialog,
    ) -> None:
        if self._youtube_thread is not None:
            return
        if not self.youtube_import_service.spotify_provider.has_saved_credentials():
            dialog.set_authenticated(False)
            dialog.set_busy(False, "Connect Spotify with OAuth first.")
            return

        self._start_spotify_sync(dialog, sync_all=True)

    def _start_spotify_sync(
        self,
        dialog: SpotifySettingsDialog | None,
        *,
        sync_all: bool,
    ) -> None:
        if dialog is not None:
            message = (
                "Reading saved Spotify tracks..."
                if sync_all
                else "Checking Spotify for new saved tracks..."
            )
            dialog.set_busy(
                True,
                message,
            )
            dialog.start_progress(message)

        def sync() -> object:
            if not sync_all:
                sync_result = (
                    self.spotify_fav_sync_service.sync_new_saved_tracks()
                )
                if not sync_result.new_tracks:
                    return sync_result

                search_result = self.youtube_import_service.search_playlist_tracks(
                    list(enumerate(sync_result.new_tracks)),
                    playlist_name="Spotify favorites",
                    on_progress=thread.search_progress_updated.emit,
                    should_cancel=thread.is_cancelled,
                )
                return sync_result, search_result

            sync_result = self.spotify_fav_sync_service.sync_all_saved_tracks()
            if not sync_result.new_tracks:
                return sync_result, None

            search_result = self.youtube_import_service.search_playlist_tracks(
                list(enumerate(sync_result.new_tracks)),
                playlist_name="Spotify favorites",
                on_progress=thread.search_progress_updated.emit,
                should_cancel=thread.is_cancelled,
            )
            return sync_result, search_result

        thread = YouTubeTaskThread(sync, self)
        if dialog is not None:
            thread.search_progress_updated.connect(
                dialog.update_search_progress
            )
        else:
            thread.search_progress_updated.connect(
                self._handle_spotify_sync_progress
            )
        thread.result_ready.connect(
            lambda result: self._handle_spotify_sync_result(
                dialog,
                result,
                sync_all=sync_all,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_spotify_sync_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _handle_spotify_sync_progress(
        self,
        completed: int,
        total: int,
        found: int,
        failed: int,
        current: str,
    ) -> None:
        """Keep background fav sync observable without opening a dialog."""

        message = f"Spotify fav sync: Searching {completed}/{total} · found {found}"
        if failed:
            message += f" · failed {failed}"
        if current:
            current = " ".join(current.split())
            if len(current) > 52:
                current = f"{current[:51].rstrip()}…"
            message += f" · {current}"
        self.statusBar().showMessage(message)

    def _handle_spotify_sync_result(
        self,
        dialog: SpotifySettingsDialog | None,
        result: object,
        *,
        sync_all: bool,
    ) -> None:
        if not sync_all and isinstance(result, SpotifyFavSyncResult):
            new_tracks = result.new_tracks
            if new_tracks:
                names = ", ".join(
                    track.title
                    for track in new_tracks[:3]
                )
                suffix = "" if len(new_tracks) <= 3 else "…"
                message = (
                    f"Spotify fav sync found {len(new_tracks)} new track(s): "
                    f"{names}{suffix}"
                )
            else:
                message = "Spotify fav sync: no new saved tracks."
            self.statusBar().showMessage(message)
            if dialog is not None:
                dialog.set_busy(False, message)
                dialog.finish_progress(message)
            return

        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], SpotifyFavSyncResult)
        ):
            self._handle_spotify_sync_error(
                dialog,
                "Spotify Sync All returned an invalid result.",
            )
            return

        sync_result, search_result = result
        sync_label = "Sync All" if sync_all else "Spotify fav sync"
        message = (
            f"{sync_label} found {len(sync_result.new_tracks)} "
            "saved track(s)."
        )
        if dialog is not None:
            dialog.set_busy(False, message)
            dialog.finish_progress(message)
            if sync_all:
                dialog.accept()
        else:
            self.statusBar().showMessage(message)

        if search_result is None:
            self.statusBar().showMessage(
                "Spotify Sync All: no saved tracks found."
                if sync_all
                else "Spotify fav sync: no new saved tracks."
            )
            return

        QTimer.singleShot(
            0,
            lambda: self._show_spotify_sync_results(search_result),
        )

    def _handle_spotify_settings_error(
        self,
        dialog: SpotifySettingsDialog,
        message: str,
    ) -> None:
        dialog.set_busy(False, "Spotify OAuth failed.")
        dialog.finish_progress("Spotify OAuth failed.")
        QMessageBox.warning(dialog, "Spotify OAuth failed", message)

    def _handle_spotify_sync_error(
        self,
        dialog: SpotifySettingsDialog | None,
        message: str,
    ) -> None:
        if dialog is not None:
            dialog.set_busy(False, "Spotify sync failed.")
            dialog.finish_progress("Spotify sync failed.")
            QMessageBox.warning(dialog, "Spotify sync failed", message)
        else:
            self.statusBar().showMessage(f"Spotify fav sync failed: {message}")

    def _show_spotify_sync_results(
        self,
        result: SpotifyPlaylistSearchResult,
    ) -> None:
        dialog = YouTubeSearchDialog(
            self,
            spotify_authenticated=True,
            spotify_sync_enabled=self.spotify_fav_sync_service.is_enabled(),
        )
        dialog.set_import_source("spotify_favorite")
        dialog.playlist_import_requested.connect(
            lambda candidates: self._start_playlist_import(dialog, candidates)
        )
        dialog.spotify_settings_requested.connect(
            lambda: self._open_spotify_settings(dialog)
        )
        dialog.spotify_sync_toggled.connect(
            lambda enabled: self._handle_spotify_sync_toggled(
                enabled,
                dialog,
            )
        )
        dialog.set_search_query(result.playlist_name)
        dialog.set_candidates(
            list(result.candidates),
            playlist=True,
            playlist_name=result.playlist_name,
            playlist_cover_url=result.cover_url,
            unmatched=result.failed,
            unmatched_positions=result.failed_positions,
        )
        self._show_auxiliary_dialog(dialog)

    def _start_youtube_playlist_import(
        self,
        dialog: YouTubeSearchDialog,
        candidates: object,
    ) -> None:
        if self._youtube_thread is not None:
            return

        if not isinstance(candidates, list):
            self._handle_youtube_error(
                dialog,
                "YouTube playlist selection is invalid.",
            )
            return

        selected_candidates = [
            candidate
            for candidate in candidates
            if isinstance(candidate, YouTubeCandidate)
        ]

        if not selected_candidates:
            return

        self._playlist_import_active = True
        dialog.set_busy(
            True,
            (
                "Downloading playlist: "
                f"0/{len(selected_candidates)}..."
            ),
        )
        dialog.resume_progress(
            "Downloading playlist: 0/"
            f"{len(selected_candidates)}...",
            total=len(selected_candidates),
        )
        import_source = dialog.import_source

        def import_playlist() -> YouTubePlaylistImportResult:
            return self.youtube_import_service.download_and_import_playlist(
                selected_candidates,
                source=import_source,
                on_progress=thread.progress_updated.emit,
                on_track_imported=thread.track_imported.emit,
            )

        thread = YouTubeTaskThread(import_playlist, self)
        thread.track_imported.connect(
            lambda candidate, track: (
                self._handle_playlist_track_imported(
                    dialog,
                    candidate,
                    track,
                )
            )
        )
        thread.progress_updated.connect(
            dialog.update_playlist_download_progress
        )
        thread.result_ready.connect(
            lambda result: self._handle_youtube_playlist_import_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_playlist_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _start_youtube_playlist_search(
        self,
        dialog: YouTubeSearchDialog,
        failed: tuple[tuple[YouTubeCandidate, str], ...],
        unmatched: tuple[tuple[SpotifyTrack, str], ...],
        unmatched_positions: tuple[int, ...],
    ) -> None:
        """Search fresh YouTube candidates for every failed playlist item."""

        retry_tracks: list[tuple[int, SpotifyTrack]] = []
        used_positions: set[int] = set()
        next_position = 0

        def allocate_position(position: int | None) -> int:
            nonlocal next_position
            if position is not None and position not in used_positions:
                used_positions.add(position)
                next_position = max(next_position, position + 1)
                return position

            while next_position in used_positions:
                next_position += 1
            allocated = next_position
            used_positions.add(allocated)
            next_position += 1
            return allocated

        for candidate, _ in failed:
            title = candidate.requested_title or candidate.title
            artist = candidate.requested_artist or candidate.channel_title
            retry_tracks.append(
                (
                    allocate_position(candidate.playlist_position),
                    SpotifyTrack(title=title, artist=artist),
                )
            )

        for index, (track, _) in enumerate(unmatched):
            position = (
                unmatched_positions[index]
                if index < len(unmatched_positions)
                else None
            )
            retry_tracks.append(
                (allocate_position(position), track)
            )

        if not retry_tracks:
            return

        retry_tracks.sort(key=lambda item: item[0])
        dialog.set_busy(
            True,
            f"Searching YouTube again: 0/{len(retry_tracks)}...",
        )
        dialog.start_progress(
            "Searching YouTube again...",
            total=len(retry_tracks),
        )

        def search_playlist() -> SpotifyPlaylistSearchResult:
            return self.youtube_import_service.search_playlist_tracks(
                retry_tracks,
                playlist_name=(
                    dialog.playlist_name or "YouTube playlist"
                ),
                cover_url=dialog.playlist_cover_url,
                on_progress=thread.search_progress_updated.emit,
                should_cancel=thread.is_cancelled,
            )

        thread = YouTubeTaskThread(search_playlist, self)
        thread.search_progress_updated.connect(
            dialog.update_search_progress
        )
        thread.result_ready.connect(
            lambda result: self._handle_youtube_playlist_search_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    @staticmethod
    def _playlist_retry_tracks(
        failed: tuple[
            tuple[
                YouTubeCandidate | SoundCloudCandidate | Mp3PartyCandidate,
                str,
            ],
            ...,
        ],
        unmatched: tuple[tuple[SpotifyTrack, str], ...],
        unmatched_positions: tuple[int, ...],
    ) -> list[tuple[int, SpotifyTrack]]:
        """Convert failure entries back into ordered Spotify-style queries."""

        retry_tracks: list[tuple[int, SpotifyTrack]] = []
        used_positions: set[int] = set()
        next_position = 0

        def allocate_position(position: int | None) -> int:
            nonlocal next_position
            if position is not None and position not in used_positions:
                used_positions.add(position)
                next_position = max(next_position, position + 1)
                return position

            while next_position in used_positions:
                next_position += 1
            allocated = next_position
            used_positions.add(allocated)
            next_position += 1
            return allocated

        for candidate, _ in failed:
            title = getattr(candidate, "requested_title", None) or candidate.title
            artist = (
                getattr(candidate, "requested_artist", None)
                or getattr(candidate, "artist", None)
                or getattr(candidate, "channel_title", None)
            )
            retry_tracks.append(
                (
                    allocate_position(getattr(candidate, "playlist_position", None)),
                    SpotifyTrack(title=title, artist=artist),
                )
            )

        for index, (track, _) in enumerate(unmatched):
            position = (
                unmatched_positions[index]
                if index < len(unmatched_positions)
                else None
            )
            retry_tracks.append((allocate_position(position), track))

        retry_tracks.sort(key=lambda item: item[0])
        return retry_tracks

    def _start_alternative_playlist_search(
        self,
        dialog: YouTubeSearchDialog,
        failed: tuple[
            tuple[
                YouTubeCandidate | SoundCloudCandidate | Mp3PartyCandidate,
                str,
            ],
            ...,
        ],
        unmatched: tuple[tuple[SpotifyTrack, str], ...],
        unmatched_positions: tuple[int, ...],
        provider: str,
    ) -> None:
        """Search every failed playlist item on the selected provider."""

        if provider not in {"youtube", "soundcloud", "mp3party"}:
            return
        if self._youtube_thread is not None:
            return

        retry_tracks = self._playlist_retry_tracks(
            failed,
            unmatched,
            unmatched_positions,
        )
        if not retry_tracks:
            return

        if provider == "youtube":
            service = self.youtube_import_service
            source_label = "YouTube tracks"
            status_label = "YouTube"
        elif provider == "soundcloud":
            service = self.soundcloud_import_service
            source_label = "SoundCloud tracks"
            status_label = "SoundCloud"
        else:
            service = self.mp3party_import_service
            source_label = "MP3Party tracks"
            status_label = "MP3Party"
        worker_limit = getattr(
            service,
            "search_workers",
            DEFAULT_SEARCH_WORKERS,
        )

        dialog.set_busy(
            True,
            f"Searching {status_label}: 0/{len(retry_tracks)}...",
        )
        dialog.start_progress(
            f"Searching {status_label}...",
            total=len(retry_tracks),
        )

        def search_playlist() -> AlternativePlaylistSearchResult:
            candidates_by_index: dict[
                int,
                YouTubeCandidate | SoundCloudCandidate | Mp3PartyCandidate,
            ] = {}
            failures_by_index: dict[int, tuple[SpotifyTrack, str]] = {}
            completed = 0

            def report(track: SpotifyTrack) -> None:
                thread.search_progress_updated.emit(
                    completed,
                    len(retry_tracks),
                    len(candidates_by_index),
                    len(failures_by_index),
                    track.title,
                )

            def search_one(
                index: int,
                position: int,
                track: SpotifyTrack,
            ) -> tuple[
                int,
                SpotifyTrack,
                YouTubeCandidate | SoundCloudCandidate | Mp3PartyCandidate
                | None,
                str | None,
            ]:
                if thread.is_cancelled():
                    raise OperationCancelled()
                try:
                    if provider == "youtube":
                        matches = service.search(track.search_query)
                    else:
                        matches = service.search(
                            track.search_query,
                            max_results=5,
                        )
                except (OSError, RuntimeError, ValueError) as error:
                    return index, track, None, str(error)

                if not matches:
                    return (
                        index,
                        track,
                        None,
                        f"No {status_label} match found.",
                    )

                match = matches[0]
                if isinstance(match, YouTubeCandidate):
                    match = replace(
                        match,
                        playlist_position=position,
                        requested_title=track.title,
                        requested_artist=track.artist,
                    )
                else:
                    match = replace(match, playlist_position=position)
                return index, track, match, None

            total = len(retry_tracks)
            thread.search_progress_updated.emit(
                0,
                total,
                0,
                0,
                (
                    "Starting parallel search "
                    f"({min(worker_limit, total)} workers)"
                ),
            )
            with ThreadPoolExecutor(
                max_workers=min(worker_limit, max(total, 1)),
                thread_name_prefix=f"musefy-{provider}-search",
            ) as executor:
                futures = {
                    executor.submit(search_one, index, position, track): index
                    for index, (position, track) in enumerate(retry_tracks)
                }

                for future in as_completed(futures):
                    if thread.is_cancelled():
                        for pending in futures:
                            pending.cancel()
                        raise OperationCancelled()

                    index, track, match, failure = future.result()
                    completed += 1
                    if match is not None:
                        candidates_by_index[index] = match
                    else:
                        failures_by_index[index] = (
                            track,
                            failure or "Search failed.",
                        )
                    report(track)

            candidates = tuple(
                candidates_by_index[index]
                for index in range(total)
                if index in candidates_by_index
            )
            search_failures = tuple(
                failures_by_index[index]
                for index in range(total)
                if index in failures_by_index
            )
            failed_positions = tuple(
                retry_tracks[index][0]
                for index in range(total)
                if index in failures_by_index
            )

            return AlternativePlaylistSearchResult(
                provider=provider,
                candidates=candidates,
                failed=search_failures,
                failed_positions=failed_positions,
            )

        thread = YouTubeTaskThread(search_playlist, self)
        thread.search_progress_updated.connect(
            dialog.update_search_progress
        )
        thread.result_ready.connect(
            lambda result: self._handle_alternative_playlist_search_result(
                dialog,
                result,
                source_label,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_youtube_error(
                dialog,
                message,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _handle_alternative_playlist_search_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
        source_label: str,
    ) -> None:
        if not isinstance(result, AlternativePlaylistSearchResult):
            self._handle_youtube_error(
                dialog,
                "Alternative source search returned an invalid result.",
            )
            return

        dialog.set_search_query(dialog.playlist_name or source_label)
        dialog.set_candidates(
            list(result.candidates),
            playlist=True,
            playlist_name=dialog.playlist_name,
            playlist_cover_url=dialog.playlist_cover_url,
            unmatched=result.failed,
            unmatched_positions=result.failed_positions,
            source_label=source_label,
        )

    def _start_youtube_thread(
        self,
        thread: YouTubeTaskThread,
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None,
    ) -> None:
        self._youtube_thread = thread
        self._youtube_thread_dialog = dialog
        self._youtube_threads.add(thread)
        thread.finished.connect(
            lambda worker=thread, target=dialog: self._finish_youtube_thread(
                worker,
                target,
            )
        )
        thread.cancelled.connect(
            lambda target=dialog: self._handle_youtube_cancelled(target)
        )
        thread.start()

    def _finish_youtube_thread(
        self,
        thread: YouTubeTaskThread,
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None,
    ) -> None:
        if thread is self._youtube_thread:
            self._youtube_thread = None
            self._youtube_thread_dialog = None
        self._youtube_threads.discard(thread)
        thread.deleteLater()

        if dialog is not None and dialog.isVisible():
            dialog.set_busy(False, dialog.status_label.text())

    def _handle_youtube_cancelled(
        self,
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None,
    ) -> None:
        if dialog is not None and dialog.isVisible():
            dialog.set_busy(False, "Operation cancelled.")

    def _handle_authentication_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, str):
            self._handle_youtube_error(
                dialog,
                "Authentication returned an invalid result.",
            )
            return

        dialog.set_spotify_authenticated(
            self.youtube_import_service.spotify_provider.has_saved_credentials()
        )
        dialog.set_busy(False, result)
        dialog.finish_progress(result)
        QMessageBox.information(
            dialog,
            "Authentication",
            result,
        )

    def _handle_url_load_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if isinstance(result, Track):
            self._handle_youtube_import_result(dialog, result)
            return

        if isinstance(
            result,
            (SpotifySearchResult, SpotifyPlaylistSearchResult),
        ):
            self._handle_spotify_search_result(dialog, result)
            return

        if isinstance(result, list):
            self._handle_youtube_playlist_result(dialog, result)
            return

        self._handle_youtube_error(
            dialog,
            "URL loading returned an invalid result.",
        )

    def _handle_youtube_search_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, list):
            self._handle_youtube_error(
                dialog,
                "YouTube search returned an invalid result.",
            )
            return

        candidates = [
            candidate
            for candidate in result
            if isinstance(candidate, YouTubeCandidate)
        ]
        dialog.set_candidates(candidates)

    def _handle_youtube_playlist_search_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, SpotifyPlaylistSearchResult):
            self._handle_youtube_error(
                dialog,
                "Retry search returned an invalid result.",
            )
            return

        dialog.set_search_query(result.playlist_name)
        playlist_name = dialog.playlist_name or None
        dialog.set_candidates(
            list(result.candidates),
            playlist=True,
            playlist_name=playlist_name,
            playlist_cover_url=result.cover_url,
            unmatched=result.failed,
            unmatched_positions=result.failed_positions,
        )

    def _handle_soundcloud_search_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, list):
            self._handle_youtube_error(
                dialog,
                "SoundCloud search returned an invalid result.",
            )
            return

        candidates = [
            candidate
            for candidate in result
            if isinstance(candidate, SoundCloudCandidate)
        ]
        dialog.set_candidates(
            candidates,
            source_label="SoundCloud tracks",
        )

    def _handle_mp3party_search_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, list):
            self._handle_youtube_error(
                dialog,
                "MP3Party search returned an invalid result.",
            )
            return

        candidates = [
            candidate
            for candidate in result
            if isinstance(candidate, Mp3PartyCandidate)
        ]
        dialog.set_candidates(
            candidates,
            source_label="MP3Party tracks",
        )

    def _handle_spotify_search_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if isinstance(result, SpotifySearchResult):
            dialog.set_search_query(result.query)
            dialog.set_candidates(list(result.candidates))
            return

        if isinstance(result, SpotifyPlaylistSearchResult):
            dialog.set_search_query(result.playlist_name)
            dialog.set_candidates(
                list(result.candidates),
                playlist=True,
                playlist_name=result.playlist_name,
                playlist_cover_url=result.cover_url,
                unmatched=result.failed,
                unmatched_positions=result.failed_positions,
            )
            return

        if not isinstance(
            result,
            (SpotifySearchResult, SpotifyPlaylistSearchResult),
        ):
            self._handle_youtube_error(
                dialog,
                "Spotify search returned an invalid result.",
            )

    def _handle_youtube_playlist_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, list):
            self._handle_youtube_error(
                dialog,
                "YouTube playlist returned an invalid result.",
            )
            return

        candidates = [
            candidate
            for candidate in result
            if isinstance(candidate, YouTubeCandidate)
        ]
        dialog.set_candidates(
            candidates,
            playlist=True,
        )

    def _handle_youtube_import_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, Track):
            self._handle_youtube_error(
                dialog,
                "Track import returned an invalid result.",
            )
            return

        track = result
        dialog.accept()
        self._append_library_track(track)
        self._enqueue_genre_analysis(track)
        self._load_queue()
        self._maybe_refresh_recommendations()

        QMessageBox.information(
            self,
            "Track import completed",
            (
                f"Added to Library:\n"
                f"{track.artist} — {track.title}"
            ),
        )

    def _handle_youtube_playlist_import_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        self._playlist_import_active = False

        if not isinstance(result, YouTubePlaylistImportResult):
            self._handle_youtube_error(
                dialog,
                "YouTube playlist import returned an invalid result.",
            )
            return

        self._load_queue()
        QTimer.singleShot(
            0,
            self._maybe_refresh_recommendations,
        )

        unmatched = dialog.unmatched_playlist_tracks
        skipped = dialog.skipped_playlist_candidates
        failed = (*result.failed, *skipped)
        if failed or unmatched:
            failed_candidates = [
                candidate for candidate, _ in failed
            ]
            dialog.set_candidates(
                failed_candidates,
                playlist=True,
                playlist_name=dialog.playlist_name,
                playlist_cover_url=dialog.playlist_cover_url,
                unmatched=unmatched,
                unmatched_positions=dialog.unmatched_playlist_positions,
            )
            dialog.set_busy(
                False,
                (
                    f"{len(failed_candidates) + len(unmatched)} "
                    "tracks failed, were not found, or were not selected."
                ),
            )

            result_dialog = PlaylistImportResultDialog(
                len(result.imported),
                failed,
                dialog,
                unmatched=unmatched,
                unmatched_positions=dialog.unmatched_playlist_positions,
            )
            result_dialog.youtube_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_youtube_playlist_search(
                        dialog,
                        failed,
                        unmatched,
                        dialog.unmatched_playlist_positions,
                    ),
                )
            )
            result_dialog.soundcloud_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_alternative_playlist_search(
                        dialog,
                        failed,
                        unmatched,
                        dialog.unmatched_playlist_positions,
                        "soundcloud",
                    ),
                )
            )
            result_dialog.mp3party_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_alternative_playlist_search(
                        dialog,
                        failed,
                        unmatched,
                        dialog.unmatched_playlist_positions,
                        "mp3party",
                    ),
                )
            )
            result_dialog.retry_requested.connect(
                lambda candidates: QTimer.singleShot(
                    0,
                    lambda: self._start_youtube_playlist_import(
                        dialog,
                        candidates,
                    ),
                )
            )
            result_dialog.exec()
            if not failed and not unmatched:
                dialog.accept()
            return

        dialog.accept()

        message = (
            f"Imported {len(result.imported)} playlist tracks."
        )
        if dialog.playlist_name:
            message += (
                f"\nLocal playlist: {dialog.playlist_name}"
            )

        QMessageBox.information(
            self,
            "Playlist import completed",
            message,
        )

    def _handle_soundcloud_playlist_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        if not isinstance(result, SoundCloudPlaylist):
            self._handle_youtube_error(
                dialog,
                "SoundCloud playlist returned an invalid result.",
            )
            return

        dialog.set_search_query(result.name)
        dialog.set_candidates(
            list(result.candidates),
            playlist=True,
            playlist_name=result.name,
            playlist_cover_url=result.cover_url,
            source_label="SoundCloud tracks",
        )

    def _handle_soundcloud_playlist_import_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        self._playlist_import_active = False

        if not isinstance(result, SoundCloudPlaylistImportResult):
            self._handle_youtube_error(
                dialog,
                "SoundCloud playlist import returned an invalid result.",
            )
            return

        self._load_queue()
        QTimer.singleShot(
            0,
            self._maybe_refresh_recommendations,
        )

        skipped = dialog.skipped_playlist_candidates
        failed = (*result.failed, *skipped)
        if failed:
            failed_candidates = [
                candidate for candidate, _ in failed
            ]
            dialog.set_candidates(
                failed_candidates,
                playlist=True,
                playlist_name=dialog.playlist_name,
                playlist_cover_url=dialog.playlist_cover_url,
                source_label="SoundCloud tracks",
            )
            dialog.set_busy(
                False,
                f"{len(failed_candidates)} tracks failed.",
            )

            result_dialog = PlaylistImportResultDialog(
                len(result.imported),
                failed,
                dialog,
            )
            result_dialog.youtube_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_alternative_playlist_search(
                        dialog,
                        failed,
                        (),
                        (),
                        "youtube",
                    ),
                )
            )
            result_dialog.soundcloud_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_soundcloud_playlist_import(
                        dialog,
                        [candidate for candidate, _ in failed],
                    ),
                )
            )
            result_dialog.mp3party_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_alternative_playlist_search(
                        dialog,
                        failed,
                        (),
                        (),
                        "mp3party",
                    ),
                )
            )
            result_dialog.exec()
            if not failed:
                dialog.accept()
            return

        dialog.accept()

        message = f"Imported {len(result.imported)} playlist tracks."
        if dialog.playlist_name:
            message += f"\nLocal playlist: {dialog.playlist_name}"

        QMessageBox.information(
            self,
            "Playlist import completed",
            message,
        )

    def _handle_mp3party_playlist_import_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        self._playlist_import_active = False

        if not isinstance(result, Mp3PartyPlaylistImportResult):
            self._handle_youtube_error(
                dialog,
                "MP3Party playlist import returned an invalid result.",
            )
            return

        self._load_queue()
        QTimer.singleShot(
            0,
            self._maybe_refresh_recommendations,
        )

        skipped = dialog.skipped_playlist_candidates
        failed = (*result.failed, *skipped)
        if failed:
            failed_candidates = [
                candidate for candidate, _ in failed
            ]
            dialog.set_candidates(
                failed_candidates,
                playlist=True,
                playlist_name=dialog.playlist_name,
                playlist_cover_url=dialog.playlist_cover_url,
                source_label="MP3Party tracks",
            )
            dialog.set_busy(
                False,
                f"{len(failed_candidates)} tracks failed.",
            )

            result_dialog = PlaylistImportResultDialog(
                len(result.imported),
                failed,
                dialog,
            )
            result_dialog.youtube_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_alternative_playlist_search(
                        dialog,
                        failed,
                        (),
                        (),
                        "youtube",
                    ),
                )
            )
            result_dialog.soundcloud_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_alternative_playlist_search(
                        dialog,
                        failed,
                        (),
                        (),
                        "soundcloud",
                    ),
                )
            )
            result_dialog.mp3party_search_requested.connect(
                lambda: QTimer.singleShot(
                    0,
                    lambda: self._start_mp3party_playlist_import(
                        dialog,
                        [candidate for candidate, _ in failed],
                    ),
                )
            )
            result_dialog.exec()
            if not failed:
                dialog.accept()
            return

        dialog.accept()

        message = f"Imported {len(result.imported)} playlist tracks."
        if dialog.playlist_name:
            message += f"\nLocal playlist: {dialog.playlist_name}"

        QMessageBox.information(
            self,
            "Playlist import completed",
            message,
        )

    def _handle_playlist_track_imported(
        self,
        dialog: YouTubeSearchDialog,
        candidate: YouTubeCandidate | SoundCloudCandidate | Mp3PartyCandidate,
        track: object,
    ) -> None:
        if not isinstance(track, Track):
            return

        self._append_library_track(track)
        self._enqueue_genre_analysis(track)

        if dialog.playlist_name and candidate.playlist_position is not None:
            if dialog.local_playlist_id is None:
                playlist = (
                    self.playlist_management_service.create_playlist(
                        dialog.playlist_name
                    )
                )
                dialog.set_local_playlist_id(playlist.id)
                self._assign_exported_playlist_cover(
                    playlist.id,
                    dialog.playlist_cover_url,
                )

            dialog.remember_imported_playlist_track(
                candidate.playlist_position,
                track.id,
            )
            self.playlist_management_service.replace_tracks(
                dialog.local_playlist_id,
                dialog.imported_playlist_track_ids(),
            )

    def _assign_exported_playlist_cover(
        self,
        playlist_id: str,
        cover_url: str | None,
    ) -> None:
        if not cover_url:
            return

        try:
            self.playlist_management_service.set_cover_from_url(
                playlist_id,
                cover_url,
            )
        except (OSError, ValueError):
            self.statusBar().showMessage(
                "Playlist imported without its cover image."
            )
            return

        self._load_playlists()

    def _enqueue_genre_analysis(
        self,
        track: Track,
    ) -> None:
        if not track.local_path:
            self._genre_statuses[track.id] = (
                "No local file"
            )
            return

        self._analysis_pending_track_ids.add(track.id)
        self._genre_statuses[track.id] = "Queued"
        self._set_genre_status(track.id, "Queued")
        if self.selected_track_id == track.id:
            self.analyze_genres_button.setEnabled(False)

        task = GenreAnalysisTask(
            service=self._genre_analysis_service,
            track_id=track.id,
            audio_path=Path(track.local_path),
        )
        task.signals.result_ready.connect(
            self._handle_genre_analysis_result
        )
        task.signals.error_occurred.connect(
            self._handle_genre_analysis_error
        )

        self._genre_analysis_pool.start(task)
        self.statusBar().showMessage(
            f"Track analysis queued: {track.title}"
        )

    def _analyze_selected_track(self) -> None:
        if self.selected_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        track = self.store.get_track(
            self.selected_track_id
        )

        if track is None:
            QMessageBox.warning(
                self,
                "Analysis failed",
                "Track was not found.",
            )
            return

        if self._genre_statuses.get(track.id) == "Queued":
            return

        self._enqueue_genre_analysis(track)

    def _reanalyze_all_genres(self) -> None:
        tracks = list(self.store.list_tracks())
        local_tracks = [
            track
            for track in tracks
            if track.local_path
            and Path(track.local_path).exists()
        ]

        if not local_tracks:
            QMessageBox.information(
                self,
                "No local tracks",
                "There are no local tracks available for analysis.",
            )
            return

        answer = QMessageBox.question(
            self,
            "Reanalyze all tracks",
            (
                f"Analyze {len(local_tracks)} local tracks?\n"
                "The current detected genres and mood will be replaced."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._genre_batch_track_ids = {
            track.id
            for track in local_tracks
        }
        self._genre_batch_completed = 0
        self._genre_batch_total = len(local_tracks)
        self.reanalyze_genres_button.setEnabled(False)

        for track in local_tracks:
            self._enqueue_genre_analysis(track)

        self.statusBar().showMessage(
            f"Genre reanalysis queued: 0/{self._genre_batch_total}"
        )

    def _finish_genre_batch_item(
        self,
        track_id: str,
    ) -> bool:
        if track_id not in self._genre_batch_track_ids:
            return False

        self._genre_batch_track_ids.remove(track_id)
        self._genre_batch_completed += 1

        if self._genre_batch_track_ids:
            self.statusBar().showMessage(
                "Genre reanalysis progress: "
                f"{self._genre_batch_completed}/"
                f"{self._genre_batch_total}"
            )
        else:
            self.reanalyze_genres_button.setEnabled(True)
            self.statusBar().showMessage(
                "Genre reanalysis completed: "
                f"{self._genre_batch_total} tracks"
            )

        return True

    def _set_genre_status(
        self,
        track_id: str,
        status: str,
    ) -> None:
        for row_index in range(
            self.track_table.rowCount()
        ):
            title_item = self.track_table.item(
                row_index,
                0,
            )

            if title_item is None:
                continue

            if title_item.data(
                Qt.ItemDataRole.UserRole
            ) != track_id:
                continue

            self.track_table.setItem(
                row_index,
                4,
                QTableWidgetItem(status),
            )
            return

    def _maybe_refresh_recommendations(self) -> None:
        if self._playlist_import_active:
            return

        if self._analysis_pending_track_ids:
            return

        self._load_recommendations()

    def _handle_genre_analysis_result(
        self,
        track_id: str,
        analysis_result: object,
    ) -> None:
        if not isinstance(analysis_result, TrackAnalysisResult):
            self._handle_genre_analysis_error(
                track_id,
                "Track analysis returned an invalid result.",
            )
            return

        predictions = list(
            analysis_result.genre_result.genres
        )

        detected_genres = tuple(
            DetectedGenre(
                genre=prediction.genre,
                parent_genre=prediction.parent_genre,
                subgenre=prediction.subgenre,
                score=prediction.score,
                rank=prediction.rank,
                rank_weight=prediction.rank_weight,
                weighted_score=prediction.weighted_score,
            )
            for prediction in predictions
            if isinstance(prediction, GenrePrediction)
        )

        try:
            updated_track = (
                self.track_management_service.update_detected_genres(
                    track_id=track_id,
                    detected_genres=detected_genres,
                    track_embedding=tuple(
                        float(value)
                        for value in analysis_result.genre_result.track_embedding
                    ),
                    mood=analysis_result.mood_result.mood,
                )
            )
            self.recommendation_service.update_track(updated_track)
        except (OSError, RuntimeError, ValueError) as error:
            self._handle_genre_analysis_error(
                track_id,
                str(error),
            )
            return

        self._analysis_pending_track_ids.discard(track_id)
        self._genre_statuses[track_id] = "Completed"
        self._genre_predictions[track_id] = (
            analysis_result
        )
        self._update_library_track_row(updated_track)
        self._refresh_music_map()
        if self.selected_track_id == track_id:
            self.analyze_genres_button.setEnabled(True)

        is_batch_item = self._finish_genre_batch_item(track_id)
        self._maybe_refresh_recommendations()

        if is_batch_item:
            return

        track = self.store.get_track(track_id)
        track_name = (
            track.title
            if track is not None
            else track_id
        )

        self.statusBar().showMessage(
            f"Track analysis completed: {track_name}"
        )

    def _unload_idle_models(self) -> None:
        if self._genre_analysis_pool.activeThreadCount() != 0:
            return

        self._genre_analysis_service.unload_idle_models()

    def _handle_genre_analysis_error(
        self,
        track_id: str,
        message: str,
    ) -> None:
        self._analysis_pending_track_ids.discard(track_id)
        self._genre_statuses[track_id] = "Failed"
        track = self.store.get_track(track_id)
        if track is not None:
            self._update_library_track_row(track)
        else:
            self._set_genre_status(track_id, "Failed")
        if self.selected_track_id == track_id:
            self.analyze_genres_button.setEnabled(True)
        is_batch_item = self._finish_genre_batch_item(track_id)
        self._maybe_refresh_recommendations()
        if is_batch_item:
            return
        self.statusBar().showMessage(
            f"Track analysis failed: {message}"
        )

    @staticmethod
    def _handle_youtube_error(
        dialog: YouTubeSearchDialog,
        message: str,
    ) -> None:
        dialog.show_error(message)

    def _handle_youtube_playlist_error(
        self,
        dialog: YouTubeSearchDialog,
        message: str,
    ) -> None:
        self._playlist_import_active = False
        self._maybe_refresh_recommendations()
        self._handle_youtube_error(dialog, message)

    def _edit_selected_track(self) -> None:
        if self.selected_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        track = self.store.get_track(
            self.selected_track_id
        )

        if track is None:
            QMessageBox.warning(
                self,
                "Edit failed",
                "Track was not found.",
            )
            return

        metadata_dialog = TrackMetadataDialog(
            parent=self,
            title=track.title,
            artist=track.artist,
        )

        if (
            metadata_dialog.exec()
            != QDialog.DialogCode.Accepted
        ):
            return

        title, artist = (
            metadata_dialog.get_values()
        )

        if (
            self.current_track_id == track.id
            and
            self.media_player.playbackState()
            != QMediaPlayer.PlaybackState.StoppedState
        ):
            self.media_player.stop()

        try:
            updated_track = (
                self.track_management_service.update_metadata(
                    track_id=track.id,
                    title=title,
                    artist=artist,
                    genres=track.genres,
                )
            )
        except (
            FileNotFoundError,
            OSError,
            ValueError,
        ) as error:
            QMessageBox.warning(
                self,
                "Edit failed",
                str(error),
            )
            return

        self._update_library_track_row(updated_track)
        self._load_recommendations()

        QMessageBox.information(
            self,
            "Track updated",
            (
                f"Updated:\n"
                f"{updated_track.artist} — "
                f"{updated_track.title}"
            ),
        )

    def _delete_selected_track(self) -> None:
        if self.selected_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        track = self.store.get_track(
            self.selected_track_id
        )

        if track is None:
            QMessageBox.warning(
                self,
                "Delete failed",
                "Track was not found.",
            )
            return

        confirmation = QMessageBox.question(
            self,
            "Delete track",
            (
                f"Delete {track.artist} — {track.title}?\n\n"
                "The audio file, track record, and interactions "
                "will be removed."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        if (
            self.current_track_id == track.id
            and self.media_player.playbackState() != (
            QMediaPlayer.PlaybackState.StoppedState
            )
        ):
            self.media_player.stop()

        try:
            self.track_management_service.delete_track(
                self.selected_track_id
            )
        except (FileNotFoundError, OSError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Delete failed",
                str(error),
            )
            return

        self.recommendation_service.remove_track(track.id)
        self._remove_library_track_row(track.id)
        self._library_tracks = [
            item for item in self._library_tracks
            if item.id != track.id
        ]
        if self.selected_playlist_id is not None:
            self._load_selected_playlist_tracks()
        self._refresh_music_map()
        self.selected_track_id = None
        if self.current_track_id == track.id:
            self.current_track_id = None
            self.playback_queue_service.clear()
        self._load_queue()
        self._load_recommendations()
        self.statusBar().showMessage(
            f"Deleted: {track.artist} — {track.title}"
        )

    def _play_selected_track(self) -> None:
        if self.selected_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        self._start_library_queue(self.selected_track_id)

    def _go_previous(self) -> None:
        if self.media_player.position() >= PREVIOUS_RESTART_THRESHOLD_MS:
            self.media_player.setPosition(0)
            self.statusBar().showMessage("Track restarted")
            return

        queue = self.playback_queue_service.previous()
        if queue is None or queue.current_track_id is None:
            self.statusBar().showMessage("No previous track")
            return

        self._play_current_queue_track()

    def _go_next(self) -> None:
        if self.playback_queue_service.queue is None:
            self.statusBar().showMessage("No next track")
            return

        self._play_next_from_queue()

    def _play_queue(self) -> None:
        queue = self.playback_queue_service.queue

        if queue is None:
            QMessageBox.information(
                self,
                "Queue is empty",
                "Add a track to the queue first.",
            )
            return

        if queue.current_track_id is None:
            self._play_next_from_queue()
            return

        self._play_current_queue_track()

    def _play_current_queue_track(self) -> None:
        queue = self.playback_queue_service.queue

        if queue is None or queue.current_track_id is None:
            self._play_next_from_queue()
            return

        self._play_track(queue.current_track_id)

    def _play_next_from_queue(self) -> None:
        queue = self.playback_queue_service.queue
        if (
            queue is not None
            and queue.mode == QueueMode.RECOMMENDATIONS
            and not self.playback_queue_service.upcoming_track_ids()
        ):
            # A radio queue is intentionally filled lazily.  If a listener
            # reaches the end before the worker has produced its first batch,
            # briefly wait for that batch instead of declaring the queue done.
            self._radio_wait_seed_track_id = queue.current_track_id
            self._wait_for_radio_track()
            return

        self._radio_wait_attempts = 0
        self._radio_wait_seed_track_id = None
        while True:
            queue = self.playback_queue_service.advance()

            if queue is None:
                self.current_track_id = None
                self.media_player.stop()
                self._load_queue()
                self.statusBar().showMessage("Queue finished")
                return

            if queue.mode == QueueMode.RECOMMENDATIONS:
                self._replenish_recommendation_queue()

            if (
                queue.current_track_id is not None
                and self._play_track(queue.current_track_id)
            ):
                # Keep the transport button deterministic even when the
                # backend needs a moment after changing the media source.
                self.media_player.play()
                return

    def _wait_for_radio_track(self) -> None:
        queue = self.playback_queue_service.queue
        if (
            queue is None
            or queue.mode != QueueMode.RECOMMENDATIONS
            or queue.current_track_id != self._radio_wait_seed_track_id
        ):
            self._radio_wait_attempts = 0
            self._radio_wait_seed_track_id = None
            return

        if self.playback_queue_service.upcoming_track_ids():
            self._radio_wait_attempts = 0
            self._radio_wait_seed_track_id = None
            self._play_next_from_queue()
            return

        if self._radio_wait_attempts >= 20:
            self._radio_wait_attempts = 0
            self._radio_wait_seed_track_id = None
            self.statusBar().showMessage(
                "No more recommendations available"
            )
            return

        self._radio_wait_attempts += 1
        self._replenish_recommendation_queue(force=True)
        self.statusBar().showMessage("Finding the next recommendation…")
        QTimer.singleShot(250, self._wait_for_radio_track)

    def _play_track(self, track_id: str) -> bool:
        track = self.store.get_track(track_id)

        if track is None or not track.local_path:
            self.statusBar().showMessage(
                f"Skipped unavailable track: {track_id}"
            )
            return False

        audio_path = Path(track.local_path)

        if not audio_path.exists():
            self.statusBar().showMessage(
                f"Skipped missing file: {audio_path}"
            )
            return False

        source_url = QUrl.fromLocalFile(str(audio_path.resolve()))
        self._player_duration_ms = 0
        self.player_position_label.setText("0:00")
        self.player_duration_label.setText("0:00")
        self.player_progress_slider.setValue(0)
        self._current_track_played_ms = 0
        self._current_track_last_position_ms = None
        self._current_track_played_30s_recorded = False
        self._current_track_listen_recorded = False
        self._current_track_early_exit_recorded = False
        self.media_player.setSource(source_url)
        self.media_player.play()
        self.current_track_id = track.id
        self._radio_wait_attempts = 0
        self._radio_wait_seed_track_id = None
        self.player_title_label.setText(track.title)
        self.player_title_label.setToolTip(track.title)
        self.player_artist_label.setText(track.artist)
        self.player_artist_label.setToolTip(track.artist)
        self.player_cover.setText("")
        self.player_cover.setPixmap(
            track_cover_pixmap(track.title, track.cover_path, 46)
        )
        self._update_like_button()

        self._record_playback_signal(InteractionType.PLAY_START)

        self._load_history()
        self._load_queue()
        self._load_recommendations()
        self.statusBar().showMessage(
            f"Playing: {track.artist} — {track.title}"
        )
        return True

    def _stop_playback(self) -> None:
        self._record_early_exit_if_needed()
        self.media_player.stop()
        self.statusBar().showMessage(
            "Playback stopped"
        )

    def _skip_current_track(self) -> None:
        interaction_type = InteractionType.SKIP
        if (
            self._player_duration_ms > 0
            and self._current_track_played_ms < 30_000
        ):
            interaction_type = InteractionType.SKIP_UNDER_30S
        self._record_interaction(interaction_type)

    def _snooze_current_track(self) -> None:
        self._record_interaction(InteractionType.SNOOZE)

    def _dislike_current_track(self) -> None:
        self._record_interaction(InteractionType.DISLIKE)

    def _do_not_recommend_current_track(self) -> None:
        self._record_interaction(InteractionType.DO_NOT_RECOMMEND)

    def _allow_recommend_current_track(self) -> None:
        self._record_interaction(InteractionType.ALLOW_RECOMMEND)

    def _save_current_track(self) -> None:
        self._record_interaction(InteractionType.SAVE)

    def _update_like_button(self) -> None:
        if not hasattr(self, "like_button"):
            return

        is_liked = False
        if self.current_track_id is not None:
            try:
                is_liked = self.interaction_service.is_liked(
                    self.user_id,
                    self.current_track_id,
                )
            except ValueError:
                is_liked = False

        self.like_button.set_svg(
            HEART_LIKED_ICON if is_liked else HEART_ICON
        )
        self.like_button.setToolTip(
            "Unlike current track" if is_liked else "Like current track"
        )

    def _toggle_like_current_track(self) -> None:
        if self.current_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        try:
            if self.interaction_service.is_liked(
                self.user_id,
                self.current_track_id,
            ):
                self.interaction_service.remove_like(
                    self.user_id,
                    self.current_track_id,
                )
                message = "Removed from liked tracks"
            else:
                self.interaction_service.record(
                    user_id=self.user_id,
                    track_id=self.current_track_id,
                    interaction_type=InteractionType.LIKE,
                    mood_context=self._get_active_mood_context(),
                )
                message = "Added to liked tracks"
        except ValueError as error:
            QMessageBox.warning(
                self,
                "Like failed",
                str(error),
            )
            return

        self._update_like_button()
        self._load_recommendations()
        self.statusBar().showMessage(message)

    def _handle_player_error(
        self,
        error: QMediaPlayer.Error,
        error_string: str,
    ) -> None:
        message = error_string or "Unknown playback error"

        self.statusBar().showMessage(
            f"Playback error: {message}"
        )

    def _handle_media_status_changed(
        self,
        status: QMediaPlayer.MediaStatus,
    ) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._repeat_mode == RepeatMode.TRACK:
                self._current_track_listen_recorded = False
                self._current_track_played_30s_recorded = False
                self._current_track_played_ms = 0
                self._current_track_last_position_ms = 0
                self.media_player.setPosition(0)
                self.media_player.play()
                self._record_playback_signal(InteractionType.REPEAT)
                self._record_playback_signal(InteractionType.PLAY_START)
                return

            if self._repeat_mode == RepeatMode.QUEUE:
                queue = self.playback_queue_service.restart_cycle()
                if queue is not None:
                    if queue.mode == QueueMode.RECOMMENDATIONS:
                        self._replenish_recommendation_queue(
                            force=True
                        )
                    self._load_queue()
                    self._play_current_queue_track()
                    return

            self._replenish_mood_session()
            self._play_next_from_queue()

    def _handle_volume_changed(
        self,
        value: int,
    ) -> None:
        self.audio_output.setVolume(
            self._output_volume(value, self._master_volume_percent)
        )

        self.statusBar().showMessage(
            f"Volume: {value}%"
        )

    def _set_master_volume_percent(self, value: int) -> None:
        """Persist the master gain and apply it to the current volume."""

        master_volume = self._clamp_master_volume_percent(value)
        self._master_volume_percent = master_volume
        self._volume_settings.setValue(
            "playback/master_volume_percent",
            master_volume,
        )
        self._update_master_volume_label()
        if hasattr(self, "volume_slider"):
            self._handle_volume_changed(self.volume_slider.value())

    def _update_master_volume_label(self) -> None:
        if hasattr(self, "master_volume_label"):
            self.master_volume_label.setText(
                f"Master volume: {self._master_volume_percent}%"
            )

    @staticmethod
    def _clamp_master_volume_percent(value: int) -> int:
        return max(0, min(int(value), 100))

    @staticmethod
    def _output_volume(value: int, master_volume: int = 100) -> float:
        normalized = max(0, min(value, 100)) / 100
        if normalized <= 0.5:
            # The first half is deliberately gentle, giving the user a
            # useful range for quiet listening.
            quiet_position = normalized / 0.5
            response = 0.5 * quiet_position**2
        else:
            # Above 50%, move through the audible range more decisively
            # while retaining the 20% higher maximum gain.
            loud_position = (normalized - 0.5) / 0.5
            response = 0.5 + 0.5 * loud_position**0.72
        master_gain = max(0, min(master_volume, 100)) / 100
        return response * MAX_AUDIO_GAIN * master_gain

    def _get_active_mood_context(self) -> str | None:
        queue = self.playback_queue_service.queue

        if (
            queue is None
            or queue.mode != QueueMode.SESSION
        ):
            return None

        return self.session_mood_name

    def _record_interaction(
        self,
        interaction_type: InteractionType,
    ) -> None:
        if self.current_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        is_skip_signal = interaction_type in {
            InteractionType.SKIP,
            InteractionType.SKIP_UNDER_30S,
        }
        if is_skip_signal:
            self._current_track_early_exit_recorded = True

        self._record_track_feedback(
            self.current_track_id,
            interaction_type,
            advance=interaction_type
            in {
                InteractionType.SKIP,
                InteractionType.SKIP_UNDER_30S,
                InteractionType.SNOOZE,
                InteractionType.DO_NOT_RECOMMEND,
            },
        )

    def _record_early_exit_if_needed(self) -> None:
        if (
            self._current_track_early_exit_recorded
            or self.current_track_id is None
            or self._player_duration_ms <= 0
            or self._current_track_played_ms >= 30_000
        ):
            return
        self._current_track_early_exit_recorded = True
        self._record_playback_signal(InteractionType.SKIP_UNDER_30S)

    def _record_track_feedback(
        self,
        track_id: str,
        interaction_type: InteractionType,
        *,
        advance: bool,
    ) -> None:
        """Record explicit feedback without interrupting the player."""

        try:
            result = self.interaction_service.record(
                user_id=self.user_id,
                track_id=track_id,
                interaction_type=interaction_type,
                mood_context=self._get_active_mood_context(),
            )
        except ValueError as error:
            self.statusBar().showMessage(f"Feedback failed: {error}")
            return

        self._load_recommendations()
        if advance and track_id == self.current_track_id:
            self._play_next_from_queue()

        status = "recorded" if result.created else "already recorded"
        self.statusBar().showMessage(
            f"Feedback {status}: {interaction_type.value}"
        )

    def _refresh_content(self) -> None:
        self.recommendation_service.refresh()
        self._load_library()
        self._load_recommendations()

    def _restart_application(self) -> None:
        """Restart this process so edited Python modules are re-imported."""

        if getattr(sys, "frozen", False):
            os.execv(sys.executable, [sys.executable])
            return

        os.execv(
            sys.executable,
            [sys.executable, "-m", "app.desktop"],
        )

    @staticmethod
    def _format_duration(
        duration_ms: int | None,
    ) -> str:
        if duration_ms is None:
            return "Unknown"

        total_seconds = duration_ms // 1000
        minutes, seconds = divmod(total_seconds, 60)

        return f"{minutes}:{seconds:02d}"

    @staticmethod
    def _format_added_date(created_at: object) -> str:
        if not hasattr(created_at, "strftime"):
            return "Unknown"

        if getattr(created_at, "tzinfo", None) is not None:
            created_at = created_at.astimezone()

        return created_at.strftime("%d %b %Y")
