import os
import random
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QSettings,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QKeyEvent,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QShortcut,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
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
    QScrollBar,
    QSlider,
    QSplitter,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from app.domain.genres import popular_user_genres
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
from app.domain.recommendations import (
    RecommendationContext,
    RecommendationMode,
)
from app.ingestion.audio import (
    SUPPORTED_AUDIO_EXTENSIONS,
    AudioIngestionService,
)
from app.ingestion.metadata import read_audio_metadata
from app.recommenders.feedback import suppressed_track_ids
from app.recommenders.radio import build_radio_sequence
from app.recommenders.smart_shuffle import SmartShuffleBuilder
from app.services.interactions import InteractionService
from app.services.library_maintenance import (
    LibraryBackupService,
    LibraryHealthReport,
    LibraryHealthService,
)
from app.services.loudness import (
    LOUDNESS_ANALYSIS_VERSION,
    LoudnessAnalysis,
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
from app.services.spotify_favorites_import import (
    SpotifyFavoritesImportResult,
    SpotifyFavoritesImportService,
)
from app.services.spotify_history_import import (
    SpotifyListeningHistoryImportResult,
    SpotifyListeningHistoryImportService,
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
from app.storage.paths import (
    DATA_DIR,
    MUSIC_MAP_SNAPSHOT_METADATA_PATH,
    MUSIC_MAP_SNAPSHOT_PATH,
    PLAYLIST_EXPORTS_DIR,
)
from app.storage.protocols import MusicStore
from app.ui.auxiliary_dialogs import AuxiliaryDialogManager
from app.ui.components import (
    ADD_TO_QUEUE_ICON,
    CLEAR_ICON,
    HEART_ICON,
    HEART_LIKED_ICON,
    IMPORT_ICON,
    JSON_ICON,
    LIBRARY_ICON,
    LOCAL_FILE_ICON,
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
    ClickableMarqueeLabel,
    CreatePlaylistCard,
    FadingVolumeSlider,
    HoverCircleMenuButton,
    LibraryHeaderView,
    LiquidGlassPanel,
    MainLibraryCard,
    PlaylistCard,
    QueueDialog,
    RailIconButton,
    RoundedScrollBar,
    SvgIconButton,
    TrackIdentityWidget,
    TrackNumberPlayWidget,
    WavePlaylistCard,
    generate_playlist_artwork_svg,
    svg_icon,
    track_cover_pixmap,
)
from app.ui.dialogs import (
    AnalysisProgressDialog,
    ImportLogDialog,
    LibraryMaintenanceDialog,
    ListeningStatisticsDialog,
    PlaylistDuplicateChoiceDialog,
    PlaylistImportResultDialog,
    PlaylistMergeChoiceDialog,
    SpotifySettingsDialog,
    TrackMetadataDialog,
    YouTubeSearchDialog,
)
from app.ui.global_hotkeys import GlobalMediaHotkeys
from app.ui.music_map import MapBuildResult, MusicMapWidget
from app.ui.playback_metrics import reached_completion_threshold
from app.ui.theme import DARK_THEME
from app.ui.virtual_track_table import VirtualTrackTable
from app.ui.workers import (
    AlternativePlaylistSearchResult,
    GenreAnalysisTask,
    LazyGenreAnalysisService,
    LibraryHealthTaskThread,
    LoudnessAnalysisTask,
    MusicMapTask,
    RecommendationAnalyticsTask,
    RecommendationTask,
    WatchFolderTaskThread,
    YouTubeTaskThread,
)

if TYPE_CHECKING:
    from app.ml.genre_analysis import GenreAnalysisService

MAX_AUDIO_GAIN = 0.3432
DEFAULT_VOLUME_PERCENT = 50
DEFAULT_MASTER_VOLUME_PERCENT = 100
RECOMMENDATION_QUEUE_SIZE = 12
RECOMMENDATION_REFILL_THRESHOLD = 4
RADIO_RECOMMENDATION_BATCH_SIZE = 4
MOOD_SESSION_INITIAL_QUEUE_SIZE = 12
MOOD_SESSION_REFILL_SIZE = 10
MOOD_SESSION_REFILL_THRESHOLD = 5
MOOD_SESSION_WAIT_ATTEMPTS = 80
TRACK_WIDGET_BUFFER_ROWS = 4
TRACK_MATERIALIZE_INTERVAL_MS = 16
TRACK_HOVER_INTERVAL_MS = 16
PARALLEL_GENRE_ANALYSIS_WORKERS = 2
GENRE_MODEL_RELEASE_RETRY_MS = 100
QUEUE_RENDER_BATCH_SIZE = 12
QUEUE_RENDER_INTERVAL_MS = 12
QUEUE_VISIBLE_TRACK_LIMIT = 50
# A carousel page never shows more than seven playlist-sized cards.  The
# navigation cards (Main library and Wave) count towards this limit, as does
# the Create playlist card on the last page.
PLAYLISTS_PER_PAGE = 7
SCROLL_EDGE_TOLERANCE = 2
PREVIOUS_RESTART_THRESHOLD_MS = 5_000
DEFAULT_LIBRARY_SORT_COLUMN = 4  # Added
DEFAULT_LIBRARY_SORT_DESCENDING = True
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
MAP_TRACK_PERCENTAGES = tuple(range(10, 101, 10))
MY_WAVE_SESSION_NAME = "my_wave"


class _AuxiliaryTabsFadeOverlay(QWidget):
    """Paint soft masks over chips that continue outside the tab viewport."""

    _FADE_WIDTH = 22
    _BACKGROUND = QColor("#07090B")

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._fade_left = False
        self._fade_right = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setStyleSheet("background: transparent;")

    def set_fade_edges(self, *, left: bool, right: bool) -> None:
        if self._fade_left == left and self._fade_right == right:
            return
        self._fade_left = left
        self._fade_right = right
        self.update()

    def paintEvent(self, _event: object) -> None:
        if not self._fade_left and not self._fade_right:
            return

        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        width = min(self._FADE_WIDTH, max(1, self.width() // 3))
        transparent = QColor(self._BACKGROUND)
        transparent.setAlpha(0)

        if self._fade_left:
            gradient = QLinearGradient(0, 0, width, 0)
            gradient.setColorAt(0.0, self._BACKGROUND)
            gradient.setColorAt(1.0, transparent)
            painter.fillRect(0, 0, width, self.height(), gradient)

        if self._fade_right:
            gradient = QLinearGradient(
                self.width() - width,
                0,
                self.width(),
                0,
            )
            gradient.setColorAt(0.0, transparent)
            gradient.setColorAt(1.0, self._BACKGROUND)
            painter.fillRect(
                self.width() - width,
                0,
                width,
                self.height(),
                gradient,
            )

        painter.end()


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
        self.track_management_service = track_management_service
        self.youtube_import_service = youtube_import_service
        self.spotify_fav_sync_service = SpotifyFavSyncService(
            youtube_import_service.spotify_provider
        )
        self.spotify_favorites_import_service = SpotifyFavoritesImportService(
            store,
            youtube_import_service.spotify_provider,
        )
        self.spotify_history_import_service = SpotifyListeningHistoryImportService(
            store
        )
        self.soundcloud_import_service = soundcloud_import_service
        self.mp3party_import_service = mp3party_import_service
        self.playback_queue_service = playback_queue_service
        self.playlist_management_service = playlist_management_service
        self.user_id = user_id
        self.selected_track_id: str | None = None
        self.selected_playlist_id: str | None = None
        self.selected_mood_name: str | None = None
        self.selected_genre_name: str | None = None
        self.session_mood_name: str | None = None
        self.session_genre_name: str | None = None
        self.current_track_id: str | None = None
        self._last_end_of_media_track_id: str | None = None
        self._media_ready_for_end_of_media = False
        self._current_track_listen_recorded = False
        self._current_track_played_30s_recorded = False
        self._current_track_played_ms = 0
        self._current_track_last_position_ms: int | None = None
        self._current_track_early_exit_recorded = False
        self._current_track_seeked_to_completion = False
        self._library_tracks: list[Track] = []
        self._track_scope_tracks: list[Track] = []
        self._visible_tracks: list[Track] = []
        self._materialized_track_rows: set[int] = set()
        self._materializing_track_rows = False
        self._selected_track_row = -1
        self._pending_hovered_track_row = -1
        self._library_search_query = ""
        self._music_map_source_tracks: list[Track] = []
        self._music_map_tracks: list[Track] = []
        self._music_map_signature: tuple[tuple[str, int], ...] = ()
        self._music_map_generation = 0
        self._music_map_task: MusicMapTask | None = None
        self._music_map_build_pending = False
        self._music_map_build_failed = False
        self._is_shutting_down = False
        # The main library is newest-first by default.  Playlist views clear
        # this state so their saved order remains untouched.
        self._library_sort_column: int | None = DEFAULT_LIBRARY_SORT_COLUMN
        self._library_sort_descending = DEFAULT_LIBRARY_SORT_DESCENDING
        self._add_tracks_mode = False
        self._add_tracks_target_playlist_id: str | None = None
        self._add_tracks_selected_ids: set[str] = set()
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
        self._recommendation_impression_session_id: str | None = None
        self._recommendation_impression_position = 0
        self._recommendation_impression_playlist_id: str | None = None
        self._mood_session_task: RecommendationTask | None = None
        self._mood_session_generation = 0
        self._mood_session_impression_session_id: str | None = None
        self._mood_session_impression_position = 0
        self._mood_session_playlist_id: str | None = None
        self._mood_session_result_generation: int | None = None
        self._mood_session_pending_name: str | None = None
        self._mood_session_pending_mode: RecommendationMode | None = None
        self._mood_refill_task: RecommendationTask | None = None
        self._mood_refill_generation = 0
        self._mood_refill_inflight = False
        self._mood_refill_added_count = 0
        self._mood_refill_exhausted = False
        self._mood_wait_attempts = 0
        self._mood_wait_track_id: str | None = None
        self._mood_session_seen_track_ids: set[str] = set()
        self._radio_recommendation_task: RecommendationTask | None = None
        self._radio_recommendation_generation = 0
        self._radio_recommendation_inflight = False
        self._radio_session_seen_track_ids: set[str] = set()
        self._radio_impression_session_id: str | None = None
        self._radio_impression_position = 0
        self._radio_impression_playlist_id: str | None = None
        self._radio_wait_attempts = 0
        self._radio_wait_seed_track_id: str | None = None
        self._queue_render_generation = 0
        self._queue_render_track_ids: tuple[str, ...] = ()
        self._queue_render_index = 0
        self._auxiliary_minimized_container: QScrollArea | None = None
        self._auxiliary_minimized_layout: QHBoxLayout | None = None
        self._auxiliary_tabs_fade_overlay: _AuxiliaryTabsFadeOverlay | None = None
        self._auxiliary_tabs_wrapper: QWidget | None = None
        self._auxiliary_scroll_left_button: QToolButton | None = None
        self._auxiliary_scroll_right_button: QToolButton | None = None
        self._auxiliary_dialogs: AuxiliaryDialogManager | None = None
        self._search_row: QWidget | None = None
        self._search_actions_container: QWidget | None = None
        self._genre_statuses: dict[str, str] = {}
        self._genre_predictions: dict[str, object] = {}
        self._genre_batch_track_ids: set[str] = set()
        self._genre_batch_completed = 0
        self._genre_batch_total = 0
        self._analysis_pending_track_ids: set[str] = set()
        self._genre_analysis_tasks: set[GenreAnalysisTask] = set()
        self._genre_model_release_requested = False
        self._analysis_progress_dialog: AnalysisProgressDialog | None = None
        self._analysis_total = 0
        self._analysis_completed = 0
        self._playlist_import_active = False
        self._library_refresh_pending = False
        self._music_map_mode = "background"
        self._liquid_glass_enabled = True
        self._playback_mode = QueueMode.NORMAL
        self._track_radio_enabled = False
        self._radio_anchor_track_id: str | None = None
        self._repeat_mode = RepeatMode.OFF
        self._player_duration_ms = 0
        self._pending_restore_position_ms: int | None = None
        self._current_track_loudness_gain_db = 0.0
        self._volume_settings = QSettings("Musefy", "Musefy")
        self._master_volume_percent = self._clamp_master_volume_percent(
            self._volume_settings.value(
                "playback/master_volume_percent",
                DEFAULT_MASTER_VOLUME_PERCENT,
                type=int,
            )
        )
        self._playback_state_settings = QSettings("Musefy", "Musefy")
        self._music_map_background_enabled = bool(
            self._playback_state_settings.value(
                "appearance/music_map_background",
                True,
                type=bool,
            )
        )
        self._show_track_covers = bool(
            self._playback_state_settings.value(
                "appearance/library_track_covers",
                True,
                type=bool,
            )
        )
        self._music_map_track_percentage = self._clamp_music_map_percentage(
            self._playback_state_settings.value(
                "appearance/music_map_track_percentage",
                100,
                type=int,
            )
        )
        self._loudness_normalization_enabled = bool(
            self._volume_settings.value(
                "playback/loudness_normalization",
                True,
                type=bool,
            )
        )
        self._loudness_analysis_tasks: set[LoudnessAnalysisTask] = set()
        self._loudness_pending_track_ids: set[str] = set()
        self._loudness_analysis_total = 0
        self._loudness_analysis_completed = 0
        self._loudness_analysis_failed = 0
        self._parallel_genre_analysis_enabled = bool(
            self._playback_state_settings.value(
                "performance/parallel_genre_analysis",
                False,
                type=bool,
            )
        )
        self._gpu_optimized_genre_analysis_enabled = bool(
            self._playback_state_settings.value(
                "performance/gpu_optimized_genre_analysis",
                False,
                type=bool,
            )
        )
        self._genre_analysis_service = LazyGenreAnalysisService(
            lambda: self._create_genre_analysis_service(
                gpu_optimized=self._gpu_optimized_genre_analysis_enabled,
            ),
        )
        self.library_health_service = LibraryHealthService(store)
        self.library_backup_service = LibraryBackupService(store)
        self.statistics_service = ListeningStatisticsService(store)
        self.recommendation_analytics_service = RecommendationAnalyticsService(store)
        self.watch_folder_service = WatchFolderService(store)
        self._watch_sync_thread: WatchFolderTaskThread | None = None
        self._watch_sync_dialog: LibraryMaintenanceDialog | None = None
        self._watch_folder_timer = QTimer(self)
        self._watch_folder_timer.setInterval(20_000)
        self._watch_folder_timer.timeout.connect(self._sync_watch_folder)
        self._watch_folder_timer.start()
        self._genre_analysis_pool = QThreadPool(self)
        # Keep the safe single-worker mode as the default. Parallel analysis is
        # an explicit opt-in because it can increase GPU/RAM pressure.
        self._genre_analysis_pool.setMaxThreadCount(
            PARALLEL_GENRE_ANALYSIS_WORKERS
            if self._parallel_genre_analysis_enabled
            else 1
        )
        self._track_materialize_timer = QTimer(self)
        self._track_materialize_timer.setSingleShot(True)
        self._track_materialize_timer.setInterval(TRACK_MATERIALIZE_INTERVAL_MS)
        self._track_materialize_timer.timeout.connect(
            self._materialize_visible_track_rows
        )
        self._track_hover_timer = QTimer(self)
        self._track_hover_timer.setSingleShot(True)
        self._track_hover_timer.setInterval(TRACK_HOVER_INTERVAL_MS)
        self._track_hover_timer.timeout.connect(self._apply_pending_track_row_hover)
        self._library_refresh_timer = QTimer(self)
        self._library_refresh_timer.setSingleShot(True)
        self._library_refresh_timer.setInterval(80)
        self._library_refresh_timer.timeout.connect(self._flush_library_refresh)
        self._music_map_pool = QThreadPool(self)
        self._music_map_pool.setMaxThreadCount(1)
        # Recommendation scoring can scan the whole library or lazily build
        # the similarity index.  Keep it off the GUI thread and let radio and
        # sidebar suggestions progress independently.
        self._recommendation_pool = QThreadPool(self)
        self._recommendation_pool.setMaxThreadCount(1)
        self._mood_recommendation_pool = QThreadPool(self)
        self._mood_recommendation_pool.setMaxThreadCount(1)
        # Feature snapshots touch SQLite for every shown recommendation.  Keep
        # that telemetry away from the GUI and separate from recommendation
        # calculation so persistence cannot delay a new session/refill.
        self._recommendation_analytics_pool = QThreadPool(self)
        self._recommendation_analytics_pool.setMaxThreadCount(1)
        self._radio_recommendation_pool = QThreadPool(self)
        self._radio_recommendation_pool.setMaxThreadCount(1)
        self._loudness_analysis_pool = QThreadPool(self)
        self._loudness_analysis_pool.setMaxThreadCount(1)
        self._model_idle_timer = QTimer(self)
        self._model_idle_timer.setInterval(60_000)
        self._model_idle_timer.timeout.connect(self._unload_idle_models)
        self._model_idle_timer.start()
        self._genre_model_release_timer = QTimer(self)
        self._genre_model_release_timer.setSingleShot(True)
        self._genre_model_release_timer.setInterval(
            GENRE_MODEL_RELEASE_RETRY_MS
        )
        self._genre_model_release_timer.timeout.connect(
            self._release_cancelled_genre_models
        )

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(
            self._output_volume(
                DEFAULT_VOLUME_PERCENT,
                self._master_volume_percent,
            )
        )

        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.errorOccurred.connect(self._handle_player_error)
        self.media_player.mediaStatusChanged.connect(self._handle_media_status_changed)
        self.media_player.positionChanged.connect(self._handle_player_position_changed)
        self.media_player.durationChanged.connect(self._handle_player_duration_changed)
        self.media_player.playbackStateChanged.connect(
            self._handle_playback_state_changed
        )

        self.setWindowTitle("Musefy")
        self.resize(1240, 800)
        self.setStyleSheet(DARK_THEME)

        self._build_interface()
        if (
            self._auxiliary_minimized_container is None
            or self._auxiliary_minimized_layout is None
        ):
            raise RuntimeError("Auxiliary dialog area was not initialized.")
        self._auxiliary_dialogs = AuxiliaryDialogManager(
            container=self._auxiliary_minimized_container,
            layout=self._auxiliary_minimized_layout,
            reposition=self._position_search_actions,
            cancel_task=self._cancel_dialog_task,
            parent=self,
        )
        self._find_shortcut = QShortcut(
            QKeySequence("Ctrl+F"),
            self,
        )
        self._find_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._find_shortcut.setAutoRepeat(False)
        self._find_shortcut.activated.connect(self._focus_library_search)
        self._space_shortcut = QShortcut(
            QKeySequence(Qt.Key.Key_Space),
            self,
        )
        self._space_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._space_shortcut.setAutoRepeat(False)
        self._space_shortcut.activated.connect(self._toggle_playback)
        self._global_media_hotkeys = GlobalMediaHotkeys(
            on_play_pause=self._toggle_playback,
            on_previous=self._go_previous,
            on_next=self._go_next,
        )
        if not self._global_media_hotkeys.is_active:
            self._media_play_pause_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_MediaTogglePlayPause),
                self,
            )
            self._media_play_pause_shortcut.setContext(
                Qt.ShortcutContext.ApplicationShortcut
            )
            self._media_play_pause_shortcut.setAutoRepeat(False)
            self._media_play_pause_shortcut.activated.connect(self._toggle_playback)
            self._media_next_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_MediaNext),
                self,
            )
            self._media_next_shortcut.setContext(
                Qt.ShortcutContext.ApplicationShortcut
            )
            self._media_next_shortcut.setAutoRepeat(False)
            self._media_next_shortcut.activated.connect(self._go_next)
            self._media_previous_shortcut = QShortcut(
                QKeySequence(Qt.Key.Key_MediaPrevious),
                self,
            )
            self._media_previous_shortcut.setContext(
                Qt.ShortcutContext.ApplicationShortcut
            )
            self._media_previous_shortcut.setAutoRepeat(False)
            self._media_previous_shortcut.activated.connect(self._go_previous)
        # Prepare the first library view before the window is shown, so the
        # user never sees an empty shell while the initial track table and
        # playlist cards are being built.  The optional ML ranker is loaded
        # independently by the desktop entrypoint after first paint.
        self._load_playlists()
        self._load_library(refresh_map=False)
        # Let Qt finish painting the ready library before restoring playback.
        # The map is intentionally built lazily when the user first opens it.
        QTimer.singleShot(0, self._finish_initial_load)

    def _finish_initial_load(self) -> None:
        if self._is_shutting_down:
            return
        self._restore_playback_state()

    def _build_interface(self) -> None:
        app_root = QWidget()
        app_root.setObjectName("appRoot")

        self.map_layer = QWidget(app_root)
        self.map_layer.setObjectName("mapLayer")
        self.map_layer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        map_layout = QVBoxLayout(self.map_layer)
        map_layout.setContentsMargins(0, 0, 0, 0)
        self.music_map = MusicMapWidget(self.map_layer)
        self.music_map.track_activated.connect(self._select_track_from_map)
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
        self.content_overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        content_layout = QVBoxLayout(self.content_overlay)
        content_layout.setContentsMargins(8, 8, 8, 78)
        content_layout.setSpacing(8)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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
        exported_action = import_menu.addAction(
            "Playlist JSON", self._import_exported_playlist
        )
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
            "Reanalyze library", self._reanalyze_all_genres
        )
        library_menu.addSeparator()
        library_menu.addAction(
            "Library health & backup…",
            self._open_library_maintenance,
        )
        library_menu.addAction(
            "Import log",
            self._show_import_log,
        )
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
        sidebar_layout.addWidget(
            self.map_cycle_button, 0, Qt.AlignmentFlag.AlignHCenter
        )

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
        search_icon.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        search_frame_layout.addWidget(search_icon)

        self.library_search_input = QLineEdit()
        self.library_search_input.setObjectName("librarySearchInput")
        self.library_search_input.setPlaceholderText("Search title or artist")
        self.library_search_input.setClearButtonEnabled(False)
        self.library_search_input.setToolTip("Search title or artist (Ctrl+F)")
        self.library_search_input.textChanged.connect(
            self._handle_library_search_changed
        )
        search_frame_layout.addWidget(self.library_search_input, 1)

        self.library_search_clear = QToolButton()
        self.library_search_clear.setObjectName("librarySearchClear")
        self.library_search_clear.setIcon(svg_icon(CLEAR_ICON, size=18))
        self.library_search_clear.setIconSize(QSize(18, 18))
        self.library_search_clear.setToolTip("Clear search")
        self.library_search_clear.setAutoRaise(True)
        self.library_search_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.library_search_clear.setFixedSize(26, 26)
        self.library_search_clear.clicked.connect(self.library_search_input.clear)
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
        self._search_actions_container.setObjectName("searchActionsContainer")
        self._search_actions_layout = QHBoxLayout(self._search_actions_container)
        self._search_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._search_actions_layout.setSpacing(6)

        self._auxiliary_tabs_wrapper = QWidget(search_row)
        self._auxiliary_tabs_wrapper.setObjectName("auxiliaryTabsWrapper")
        self._auxiliary_tabs_wrapper.setFixedSize(418, 38)
        auxiliary_tabs_layout = QHBoxLayout(self._auxiliary_tabs_wrapper)
        auxiliary_tabs_layout.setContentsMargins(0, 0, 0, 0)
        auxiliary_tabs_layout.setSpacing(4)

        self._auxiliary_scroll_left_button = QToolButton(self._auxiliary_tabs_wrapper)
        self._auxiliary_scroll_left_button.setObjectName("auxiliaryScrollButton")
        self._auxiliary_scroll_left_button.setIcon(
            svg_icon(PLAYLIST_SCROLL_LEFT_ICON, size=18)
        )
        self._auxiliary_scroll_left_button.setIconSize(QSize(18, 18))
        self._auxiliary_scroll_left_button.setToolTip("Scroll minimized tabs left")
        self._auxiliary_scroll_left_button.setAutoRaise(True)
        self._auxiliary_scroll_left_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._auxiliary_scroll_left_button.setFixedSize(32, 32)
        self._auxiliary_scroll_left_button.clicked.connect(
            lambda: self._scroll_auxiliary_tabs(-1)
        )
        self._auxiliary_scroll_left_button.hide()
        auxiliary_tabs_layout.addWidget(self._auxiliary_scroll_left_button)

        self._auxiliary_minimized_container = QScrollArea(self._auxiliary_tabs_wrapper)
        self._auxiliary_minimized_container.setObjectName("auxiliaryMinimizedContainer")
        self._auxiliary_minimized_container.setFixedSize(
            AuxiliaryDialogManager.TAB_WIDTH * 2 + AuxiliaryDialogManager.TAB_SPACING,
            38,
        )
        self._auxiliary_minimized_container.setWidgetResizable(False)
        self._auxiliary_minimized_container.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._auxiliary_minimized_container.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._auxiliary_minimized_container.setFrameShape(QFrame.Shape.NoFrame)
        self._auxiliary_minimized_container.setViewportMargins(0, 0, 0, 0)
        self._auxiliary_minimized_container.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._auxiliary_minimized_container.viewport().setAutoFillBackground(False)
        minimized_content = QWidget()
        minimized_content.setObjectName("auxiliaryMinimizedContent")
        minimized_content.setFixedHeight(34)
        self._auxiliary_minimized_layout = QHBoxLayout(minimized_content)
        self._auxiliary_minimized_layout.setContentsMargins(0, 0, 0, 0)
        self._auxiliary_minimized_layout.setSpacing(AuxiliaryDialogManager.TAB_SPACING)
        self._auxiliary_minimized_container.setWidget(minimized_content)
        self._auxiliary_tabs_fade_overlay = _AuxiliaryTabsFadeOverlay(
            self._auxiliary_minimized_container.viewport()
        )
        self._auxiliary_tabs_fade_overlay.raise_()
        self._auxiliary_minimized_container.hide()

        auxiliary_tabs_layout.addWidget(
            self._auxiliary_minimized_container,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )

        self._auxiliary_scroll_right_button = QToolButton(self._auxiliary_tabs_wrapper)
        self._auxiliary_scroll_right_button.setObjectName("auxiliaryScrollButton")
        self._auxiliary_scroll_right_button.setIcon(
            svg_icon(PLAYLIST_SCROLL_RIGHT_ICON, size=18)
        )
        self._auxiliary_scroll_right_button.setIconSize(QSize(18, 18))
        self._auxiliary_scroll_right_button.setToolTip("Scroll minimized tabs right")
        self._auxiliary_scroll_right_button.setAutoRaise(True)
        self._auxiliary_scroll_right_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._auxiliary_scroll_right_button.setFixedSize(32, 32)
        self._auxiliary_scroll_right_button.clicked.connect(
            lambda: self._scroll_auxiliary_tabs(1)
        )
        self._auxiliary_scroll_right_button.hide()
        auxiliary_tabs_layout.addWidget(self._auxiliary_scroll_right_button)

        auxiliary_scroll_bar = self._auxiliary_minimized_container.horizontalScrollBar()
        auxiliary_scroll_bar.valueChanged.connect(
            lambda _value: self._update_auxiliary_scroll_buttons()
        )
        auxiliary_scroll_bar.rangeChanged.connect(
            lambda _minimum, _maximum: self._update_auxiliary_scroll_buttons()
        )
        self._search_actions_layout.addWidget(
            self._auxiliary_tabs_wrapper,
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
        playlist_menu_button.setToolTip("Settings and tools")
        playlist_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        playlist_menu = QMenu(playlist_menu_button)
        audio_menu = playlist_menu.addMenu("Audio & playback")
        audio_menu.addAction(
            "Analyze loudness of library",
            lambda _checked=False: self._analyze_missing_loudness(),
        )
        audio_menu.addSeparator()
        self.loudness_normalization_action = audio_menu.addAction(
            "Loudness normalization",
        )
        self.loudness_normalization_action.setCheckable(True)
        self.loudness_normalization_action.setChecked(
            self._loudness_normalization_enabled
        )
        self.loudness_normalization_action.setToolTip(
            "Match track loudness while protecting against clipping"
        )
        self.loudness_normalization_action.toggled.connect(
            self._set_loudness_normalization_enabled
        )
        audio_menu.addSeparator()
        master_volume_menu = audio_menu.addMenu("Master volume")
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

        appearance_menu = playlist_menu.addMenu("Appearance")
        self.liquid_glass_action = appearance_menu.addAction(
            "Liquid glass panels",
        )
        self.liquid_glass_action.setCheckable(True)
        self.liquid_glass_action.setChecked(self._liquid_glass_enabled)
        self.liquid_glass_action.toggled.connect(self._set_liquid_glass_enabled)
        self.music_map_background_action = appearance_menu.addAction(
            "Music graph background",
        )
        self.music_map_background_action.setCheckable(True)
        self.music_map_background_action.setChecked(self._music_map_background_enabled)
        self.music_map_background_action.toggled.connect(
            self._set_music_map_background_enabled
        )
        self.track_covers_action = appearance_menu.addAction(
            "Track covers in library and playlists",
        )
        self.track_covers_action.setCheckable(True)
        self.track_covers_action.setChecked(self._show_track_covers)
        self.track_covers_action.toggled.connect(self._set_track_covers_enabled)

        analysis_menu = playlist_menu.addMenu("Analysis")
        self.parallel_genre_analysis_action = analysis_menu.addAction(
            "Parallel genre analysis"
        )
        self.parallel_genre_analysis_action.setCheckable(True)
        self.parallel_genre_analysis_action.setChecked(
            self._parallel_genre_analysis_enabled
        )
        self.parallel_genre_analysis_action.setToolTip(
            "Use two background workers; this may increase GPU and RAM usage"
        )
        self.parallel_genre_analysis_action.toggled.connect(
            self._set_parallel_genre_analysis_enabled
        )
        self.gpu_optimized_genre_analysis_action = analysis_menu.addAction(
            "GPU-optimized genre analysis"
        )
        self.gpu_optimized_genre_analysis_action.setCheckable(True)
        self.gpu_optimized_genre_analysis_action.setChecked(
            self._gpu_optimized_genre_analysis_enabled
        )
        self.gpu_optimized_genre_analysis_action.setToolTip(
            "Batch neural inference on the GPU; may increase VRAM usage"
        )
        self.gpu_optimized_genre_analysis_action.toggled.connect(
            self._set_gpu_optimized_genre_analysis_enabled
        )

        integrations_menu = playlist_menu.addMenu("Integrations")
        integrations_menu.addAction(
            "Spotify settings",
            lambda: self._open_spotify_settings(),
        )

        application_menu = playlist_menu.addMenu("Application")
        application_menu.addAction(
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
        self.playlist_scroll_left_button.setObjectName("playlistScrollButton")
        self.playlist_scroll_left_button.setIcon(
            svg_icon(PLAYLIST_SCROLL_LEFT_ICON, size=24)
        )
        self.playlist_scroll_left_button.setIconSize(QSize(24, 24))
        self.playlist_scroll_left_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.playlist_scroll_left_button.setToolTip("Scroll playlists left")
        self.playlist_scroll_left_button.setFixedSize(32, 42)
        self.playlist_scroll_left_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.playlist_scroll_left_button.clicked.connect(
            lambda: self._scroll_playlists(-1)
        )
        self.playlist_scroll_left_button.hide()

        self.playlist_scroll_right_button = QToolButton()
        self.playlist_scroll_right_button.setObjectName("playlistScrollButton")
        self.playlist_scroll_right_button.setIcon(
            svg_icon(PLAYLIST_SCROLL_RIGHT_ICON, size=24)
        )
        self.playlist_scroll_right_button.setIconSize(QSize(24, 24))
        self.playlist_scroll_right_button.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
        )
        self.playlist_scroll_right_button.setToolTip("Scroll playlists right")
        self.playlist_scroll_right_button.setFixedSize(32, 42)
        self.playlist_scroll_right_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.playlist_scroll_right_button.clicked.connect(
            lambda: self._scroll_playlists(1)
        )
        self.playlist_scroll_right_button.hide()

        self.playlist_carousel = QWidget()
        self.playlist_carousel.setAutoFillBackground(False)
        self.playlist_carousel.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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
        playlist_scroll_container_layout = QHBoxLayout(playlist_scroll_container)
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
        playlist_scroll_bar.valueChanged.connect(self._update_playlist_scroll_buttons)
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
        self.playlist_list.itemSelectionChanged.connect(self._handle_playlist_selection)
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
        self.map_track_percentage_combo = QComboBox(app_root)
        self.map_track_percentage_combo.setObjectName("mapTrackPercentageCombo")
        self.map_track_percentage_combo.setFixedSize(166, 32)
        self.map_track_percentage_combo.setToolTip(
            "Choose how many analyzed tracks to use when building the map"
        )
        for percentage in MAP_TRACK_PERCENTAGES:
            self.map_track_percentage_combo.addItem(
                f"Map tracks: {percentage}%",
                percentage,
            )
        self.map_track_percentage_combo.setCurrentIndex(
            MAP_TRACK_PERCENTAGES.index(self._music_map_track_percentage)
        )
        self.map_track_percentage_combo.currentIndexChanged.connect(
            self._set_music_map_track_percentage
        )
        self.map_track_percentage_combo.hide()
        self.queue_dialog = QueueDialog(self)
        self.queue_dialog.track_play_requested.connect(self._play_queued_track)
        self.setCentralWidget(app_root)
        self.statusBar().showMessage("Ready")
        self.statusBar().hide()
        self._set_music_map_mode(
            "background" if self._music_map_background_enabled else "hidden",
            animated=False,
        )

    def _build_player_bar(self) -> QFrame:
        player_bar = QFrame()
        self._player_bar = player_bar
        player_bar.setObjectName("playerBar")
        player_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        player_bar.customContextMenuRequested.connect(
            self._show_current_track_context_menu
        )
        layout = QHBoxLayout(player_bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(10)

        left_panel = QWidget(player_bar)
        left_layout = QHBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.player_cover = QLabel("♫")
        self.player_cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.player_cover.setFixedSize(38, 38)
        self.player_cover.setStyleSheet(
            "background: #2A2A2D; border-radius: 10px; color: #D8D8D8;"
        )
        left_layout.addWidget(self.player_cover)

        metadata_layout = QVBoxLayout()
        metadata_layout.setContentsMargins(0, 2, 0, 0)
        metadata_layout.setSpacing(0)
        self.player_title_label = ClickableMarqueeLabel("Nothing playing")
        self.player_title_label.setObjectName("playerTitle")
        self.player_title_label.setToolTip("Track actions")
        self.player_title_label.clicked.connect(self._show_current_track_action_menu)
        self.player_title_label.setFixedHeight(18)
        self.player_artist_label = QLabel("Choose a track or playlist")
        self.player_artist_label.setObjectName("playerArtist")
        self.player_artist_label.setFixedHeight(14)
        metadata_layout.addWidget(self.player_title_label)
        metadata_layout.addWidget(self.player_artist_label)
        left_layout.addLayout(metadata_layout, 1)
        left_panel.setMinimumWidth(220)
        layout.addWidget(left_panel, 1, Qt.AlignmentFlag.AlignVCenter)

        center_panel = QWidget(player_bar)
        center_panel.setMinimumWidth(320)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
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
        self.playback_mode_button.clicked.connect(self._cycle_playback_mode)
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
        self.repeat_button.clicked.connect(self._cycle_repeat_mode)
        control_layout.addWidget(
            self.repeat_button,
            0,
            Qt.AlignmentFlag.AlignBottom,
        )
        control_layout.addStretch()
        center_layout.addLayout(control_layout)

        progress_panel = QWidget(center_panel)
        progress_panel.setObjectName("playerProgressPanel")
        progress_panel.setFixedWidth(440)
        progress_layout = QHBoxLayout(progress_panel)
        progress_layout.setContentsMargins(0, 0, 0, 0)
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
        center_layout.addWidget(
            progress_panel,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        layout.addWidget(center_panel, 3, Qt.AlignmentFlag.AlignVCenter)

        right_panel = QWidget(player_bar)
        right_layout = QHBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addStretch()

        self.like_button = SvgIconButton(
            HEART_ICON,
            tooltip="Like current track",
            diameter=30,
            flat=True,
            parent=player_bar,
        )
        self.like_button.clicked.connect(self._toggle_like_current_track)
        right_layout.addWidget(self.like_button)

        player_menu_button = HoverCircleMenuButton(parent=player_bar)
        player_menu_button.setObjectName("plainActionButton")
        player_menu_button.setProperty("topMenu", True)
        player_menu_button.setText("•••")
        player_menu_button.setToolTip("Playback actions")
        player_menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
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
        self.track_radio_action.toggled.connect(self._set_track_radio_enabled)
        player_menu.addAction("Stop playback", self._stop_playback)
        player_menu_button.setMenu(player_menu)
        right_layout.addWidget(player_menu_button)

        volume_button = SvgIconButton(
            VOLUME_ICON,
            tooltip="Volume",
            diameter=30,
            flat=True,
            parent=player_bar,
        )
        volume_button.setEnabled(False)
        right_layout.addWidget(volume_button)

        self.volume_slider = FadingVolumeSlider()
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setFixedWidth(96)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(DEFAULT_VOLUME_PERCENT)
        self.volume_slider.valueChanged.connect(self._handle_volume_changed)
        right_layout.addWidget(self.volume_slider)
        right_panel.setMinimumWidth(220)
        layout.addWidget(right_panel, 1, Qt.AlignmentFlag.AlignVCenter)

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
        if hasattr(self, "map_track_percentage_combo"):
            combo = self.map_track_percentage_combo
            combo.setGeometry(
                max(16, root_rect.width() - combo.width() - 16),
                16,
                combo.width(),
                combo.height(),
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
            menu_item = layout.itemAt(layout.count() - 1)
            menu_widget = menu_item.widget() if menu_item is not None else None
            menu_width = (
                max(
                    32,
                    menu_widget.sizeHint().width(),
                    menu_widget.minimumSizeHint().width(),
                )
                if menu_widget is not None
                else 0
            )
        else:
            width = container.sizeHint().width()
            menu_width = 0
        spacing = layout.spacing() if layout is not None else 0
        show_tabs = bool(
            self._auxiliary_dialogs is not None
            and self._auxiliary_dialogs.preferred_width()
        )
        if show_tabs and self._auxiliary_tabs_wrapper is not None:
            # The wrapper used to stay 418px wide even when the window was
            # narrower.  That let its right arrow and the last chip spill out
            # of the top row and get clipped by the window edge.
            available_tabs_width = max(
                0,
                row.width() - menu_width - spacing,
            )
            tabs_wrapper_width = min(418, available_tabs_width)
            self._auxiliary_tabs_wrapper.setFixedWidth(tabs_wrapper_width)

            tabs_layout = self._auxiliary_tabs_wrapper.layout()
            if (
                tabs_layout is not None
                and self._auxiliary_minimized_container is not None
            ):
                tabs_layout.activate()
                reserved_width = 0
                for index in (0, tabs_layout.count() - 1):
                    if 0 <= index < tabs_layout.count():
                        item = tabs_layout.itemAt(index)
                        widget = item.widget() if item is not None else None
                        if widget is not None:
                            reserved_width += widget.width()
                reserved_width += (
                    max(0, tabs_layout.count() - 1) * tabs_layout.spacing()
                )
                self._auxiliary_minimized_container.setFixedWidth(
                    max(1, tabs_wrapper_width - reserved_width)
                )

            width = tabs_wrapper_width + spacing + menu_width
        else:
            width = menu_width

        width = min(max(0, width), max(0, row.width()))
        if width <= 0:
            return

        if self._auxiliary_tabs_wrapper is not None:
            self._auxiliary_tabs_wrapper.setVisible(
                bool(
                    self._auxiliary_dialogs is not None
                    and self._auxiliary_dialogs.preferred_width()
                )
            )

        right_inset = 4 if show_tabs else 0
        container.setGeometry(
            max(0, row.width() - width - right_inset),
            -2,
            width,
            row.height(),
        )
        container.raise_()
        if self._auxiliary_dialogs is not None:
            self._auxiliary_dialogs.refresh_layout()
        if (
            self._auxiliary_tabs_fade_overlay is not None
            and self._auxiliary_minimized_container is not None
        ):
            viewport = self._auxiliary_minimized_container.viewport()
            self._auxiliary_tabs_fade_overlay.setGeometry(viewport.rect())
            self._auxiliary_tabs_fade_overlay.raise_()
        self._snap_auxiliary_tabs_to_boundary()
        self._update_auxiliary_scroll_buttons()

    def _scroll_auxiliary_tabs(self, direction: int) -> None:
        if self._auxiliary_minimized_container is None:
            return

        scroll_bar = self._auxiliary_minimized_container.horizontalScrollBar()
        scroll_range = scroll_bar.maximum() - scroll_bar.minimum()
        if scroll_range <= SCROLL_EDGE_TOLERANCE:
            scroll_bar.setValue(scroll_bar.minimum())
            return

        # Scroll only to chip boundaries.  A pixel-based page step can land
        # in the middle of a short chip, which is what made the tabs appear
        # clipped after pressing an arrow.
        boundaries = self._auxiliary_scroll_boundaries(scroll_bar)
        current_value = scroll_bar.value()
        ordered_boundaries = sorted(boundaries)
        if direction > 0:
            candidates = [
                value
                for value in ordered_boundaries
                if value > current_value + SCROLL_EDGE_TOLERANCE
            ]
            target_value = candidates[0] if candidates else scroll_bar.maximum()
        else:
            candidates = [
                value
                for value in ordered_boundaries
                if value < current_value - SCROLL_EDGE_TOLERANCE
            ]
            target_value = candidates[-1] if candidates else scroll_bar.minimum()

        target_value = max(
            scroll_bar.minimum(),
            min(scroll_bar.maximum(), target_value),
        )
        scroll_bar.setValue(target_value)

    def _auxiliary_scroll_boundaries(self, scroll_bar: QScrollBar) -> set[int]:
        boundaries = {scroll_bar.minimum(), scroll_bar.maximum()}
        if self._auxiliary_minimized_layout is not None:
            for index in range(self._auxiliary_minimized_layout.count()):
                item = self._auxiliary_minimized_layout.itemAt(index)
                widget = item.widget() if item is not None else None
                if widget is not None:
                    boundaries.add(widget.geometry().left())
        return {
            max(scroll_bar.minimum(), min(scroll_bar.maximum(), value))
            for value in boundaries
        }

    def _snap_auxiliary_tabs_to_boundary(self) -> None:
        """Prevent a resize/reflow from leaving a chip partially visible."""

        if self._auxiliary_minimized_container is None:
            return

        scroll_bar = self._auxiliary_minimized_container.horizontalScrollBar()
        if scroll_bar.maximum() - scroll_bar.minimum() <= SCROLL_EDGE_TOLERANCE:
            scroll_bar.setValue(scroll_bar.minimum())
            return

        boundaries = self._auxiliary_scroll_boundaries(scroll_bar)
        current_value = scroll_bar.value()
        target_value = min(
            boundaries,
            key=lambda value: (abs(value - current_value), value),
        )
        if target_value != current_value:
            scroll_bar.setValue(target_value)

    def _update_auxiliary_scroll_buttons(self) -> None:
        if (
            self._auxiliary_minimized_container is None
            or self._auxiliary_scroll_left_button is None
            or self._auxiliary_scroll_right_button is None
        ):
            return

        scroll_bar = self._auxiliary_minimized_container.horizontalScrollBar()
        minimum = scroll_bar.minimum()
        maximum = scroll_bar.maximum()
        value = scroll_bar.value()
        scroll_range = maximum - minimum
        if scroll_range <= SCROLL_EDGE_TOLERANCE:
            if value != minimum:
                scroll_bar.setValue(minimum)
            has_overflow = False
            at_start = True
            at_end = True
        else:
            # Snap away the tiny one/two-pixel zone at either edge.  Without
            # this, the arrow can stay active even though no whole tab can be
            # revealed anymore.
            at_start = value <= minimum + SCROLL_EDGE_TOLERANCE
            at_end = value >= maximum - SCROLL_EDGE_TOLERANCE
            if at_start and value != minimum:
                scroll_bar.setValue(minimum)
                value = minimum
            elif at_end and value != maximum:
                scroll_bar.setValue(maximum)
                value = maximum
            has_overflow = True
        show_tabs = bool(
            self._auxiliary_dialogs is not None
            and self._auxiliary_dialogs.preferred_width()
        )

        if self._auxiliary_tabs_fade_overlay is not None:
            self._auxiliary_tabs_fade_overlay.set_fade_edges(
                left=show_tabs and has_overflow and not at_start,
                right=show_tabs and has_overflow and not at_end,
            )
        self._auxiliary_scroll_left_button.setVisible(
            show_tabs and has_overflow and not at_start
        )
        self._auxiliary_scroll_left_button.setEnabled(
            show_tabs and has_overflow and not at_start
        )
        self._auxiliary_scroll_right_button.setVisible(
            show_tabs and has_overflow and not at_end
        )
        self._auxiliary_scroll_right_button.setEnabled(
            show_tabs and has_overflow and not at_end
        )

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
                first_left = min(bounds[0] for bounds in visible_card_bounds)
                last_right = max(bounds[1] for bounds in visible_card_bounds)
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

        if mode == "focus":
            self._ensure_music_map_ready()

        self._music_map_mode = mode
        self._music_map_background_enabled = mode != "hidden"
        self._playback_state_settings.setValue(
            "appearance/music_map_background",
            self._music_map_background_enabled,
        )
        music_map_action = getattr(
            self,
            "music_map_background_action",
            None,
        )
        if music_map_action is not None:
            signals_blocked = music_map_action.blockSignals(True)
            try:
                music_map_action.setChecked(self._music_map_background_enabled)
            finally:
                music_map_action.blockSignals(signals_blocked)
        self.music_map.set_mode(mode)
        if mode == "background" and self.music_map.has_map_data_for(
            self._music_map_signature
        ):
            self.music_map.capture_snapshot()
            self._save_music_map_snapshot()
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
            self.map_track_percentage_combo.setVisible(mode == "focus")
            if mode == "focus":
                self.map_layer.raise_()
                self._player_bar.raise_()
                self.map_exit_button.raise_()
                self.map_track_percentage_combo.raise_()
            else:
                self.map_layer.lower()
                self._player_bar.raise_()
            return

        self.map_layer.show()
        self.map_exit_button.setVisible(mode == "focus")
        self.map_track_percentage_combo.setVisible(mode == "focus")
        self._map_opacity_animation.stop()
        self._map_opacity_animation.setStartValue(self._map_opacity.opacity())
        self._map_opacity_animation.setEndValue(target_opacity)
        self._map_opacity_animation.start()
        self._content_body_opacity_animation.stop()
        self._content_body_opacity_animation.setStartValue(
            self._content_body_opacity.opacity()
        )
        self._content_body_opacity_animation.setEndValue(target_body_opacity)
        self._content_body_opacity_animation.start()
        self._map_blur_animation.stop()
        self._map_blur_animation.setStartValue(self._map_blur.blurRadius())
        self._map_blur_animation.setEndValue(target_blur_radius)
        self._map_blur_animation.start()
        if mode == "focus":
            self.map_layer.raise_()
            self._player_bar.raise_()
            self.map_exit_button.raise_()
            self.map_track_percentage_combo.raise_()
        else:
            self.map_layer.lower()
            self._player_bar.raise_()

    def _toggle_music_map(self) -> None:
        next_mode = {
            "background": "focus",
            "focus": "hidden",
            "hidden": "background",
        }[self._music_map_mode]
        self._set_music_map_mode(next_mode)

    def _set_music_map_background_enabled(self, enabled: bool) -> None:
        """Show or hide the music graph behind the main library."""
        target_mode = "background" if enabled else "hidden"
        if self._music_map_mode != target_mode:
            self._set_music_map_mode(target_mode)
        else:
            self._music_map_background_enabled = bool(enabled)
            self._playback_state_settings.setValue(
                "appearance/music_map_background",
                self._music_map_background_enabled,
            )

    def _refresh_music_map(
        self,
        tracks: list[Track] | None = None,
    ) -> None:
        if tracks is None:
            tracks = list(self.store.list_tracks())
        self._music_map_source_tracks = list(tracks)
        self._music_map_tracks = MusicMapWidget.select_tracks_for_percentage(
            self._music_map_source_tracks,
            self._music_map_track_percentage,
        )
        signature = MusicMapWidget.track_signature(self._music_map_tracks)
        if signature == self._music_map_signature:
            return

        self._music_map_signature = signature
        # Keep the last rendered graph visible in the background.  The map
        # data is intentionally allowed to become stale here; opening the
        # interactive map will detect the signature change and rebuild it.

    @staticmethod
    def _clamp_music_map_percentage(value: int) -> int:
        return value if value in MAP_TRACK_PERCENTAGES else 100

    def _set_music_map_track_percentage(self, index: int) -> None:
        percentage = self.map_track_percentage_combo.itemData(index)
        if not isinstance(percentage, int):
            return

        self._music_map_track_percentage = percentage
        self._playback_state_settings.setValue(
            "appearance/music_map_track_percentage",
            percentage,
        )
        self._refresh_music_map(self._music_map_source_tracks)
        if self._music_map_mode == "focus":
            self._ensure_music_map_ready()

    def _ensure_music_map_ready(self) -> None:
        if self.music_map.has_map_data_for(self._music_map_signature):
            if not self.music_map.has_snapshot():
                self.music_map.capture_snapshot()
                self._save_music_map_snapshot()
            return
        self._start_music_map_build()

    def _start_music_map_build(self) -> None:
        if self._music_map_task is not None:
            self._music_map_build_pending = True
            return

        self._music_map_generation += 1
        generation = self._music_map_generation
        self._music_map_build_failed = False
        task = MusicMapTask(self._music_map_tracks, generation)
        task.signals.result_ready.connect(self._handle_music_map_result)
        task.signals.error_occurred.connect(self._handle_music_map_error)
        task.signals.finished.connect(self._handle_music_map_finished)
        self._music_map_task = task
        self.music_map.set_loading(True)
        self.statusBar().showMessage("Building music map…")
        self._music_map_pool.start(task)

    def _handle_music_map_result(
        self,
        generation: int,
        result: MapBuildResult,
    ) -> None:
        if generation != self._music_map_generation:
            return
        self._music_map_build_failed = False
        if result.signature != self._music_map_signature:
            return

        self.music_map.apply_map_data(result)
        self.music_map.capture_snapshot()
        self._save_music_map_snapshot()
        self.statusBar().showMessage("Music map ready")

    def _save_music_map_snapshot(self) -> None:
        self.music_map.save_snapshot(
            MUSIC_MAP_SNAPSHOT_PATH,
            MUSIC_MAP_SNAPSHOT_METADATA_PATH,
        )

    def _handle_music_map_error(
        self,
        generation: int,
        message: str,
    ) -> None:
        if generation != self._music_map_generation:
            return
        self._music_map_build_failed = True
        self.music_map.set_loading(False)
        self.statusBar().showMessage(f"Music map could not be built: {message}")

    def _handle_music_map_finished(self, generation: int) -> None:
        if generation != self._music_map_generation:
            return
        self._music_map_task = None
        if self._music_map_build_pending:
            self._music_map_build_pending = False
            self._start_music_map_build()

    def _select_track_from_map(self, track_id: str) -> None:
        for row_index, track in enumerate(self._visible_tracks):
            if track.id == track_id:
                index = self.track_table.model().index(row_index, 0)
                self.track_table.setCurrentIndex(index)
                self.track_table.scrollTo(index)
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
        self.analyze_playlist_button = QPushButton("Analyze missing")
        self.analyze_playlist_button.setObjectName("analyzePlaylistButton")
        self.analyze_playlist_button.setToolTip(
            "Analyze every unanalyzed track in the current view"
        )
        self.analyze_playlist_button.clicked.connect(
            lambda _checked=False: self._analyze_missing_tracks()
        )
        library_header.addWidget(self.analyze_playlist_button)
        self.add_tracks_button = QPushButton("Add tracks")
        self.add_tracks_button.setObjectName("addTracksButton")
        self.add_tracks_button.setToolTip("Choose tracks from the music library")
        self.add_tracks_button.clicked.connect(self._begin_add_tracks_mode)
        library_header.addWidget(self.add_tracks_button)
        self.add_selected_tracks_button = QPushButton("Add selected")
        self.add_selected_tracks_button.setObjectName("addSelectedTracksButton")
        self.add_selected_tracks_button.clicked.connect(self._finish_add_tracks_mode)
        library_header.addWidget(self.add_selected_tracks_button)
        self.cancel_add_tracks_button = QPushButton("Cancel")
        self.cancel_add_tracks_button.setObjectName("cancelAddTracksButton")
        self.cancel_add_tracks_button.clicked.connect(self._cancel_add_tracks_mode)
        library_header.addWidget(self.cancel_add_tracks_button)
        layout.addLayout(library_header)

        self.track_table = VirtualTrackTable()
        self.track_table.setObjectName("libraryTable")
        self.track_table.setVerticalScrollBar(RoundedScrollBar(Qt.Orientation.Vertical))
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
        self.track_table.setShowGrid(False)
        self.track_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.track_table.verticalHeader().setVisible(False)
        self.track_table.verticalHeader().setDefaultSectionSize(62)
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Fixed,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Fixed,
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Interactive,
        )
        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.Fixed,
        )
        header.setSectionResizeMode(
            5,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            6,
            QHeaderView.ResizeMode.Fixed,
        )
        header.setSectionResizeMode(
            7,
            QHeaderView.ResizeMode.Fixed,
        )
        header.setSectionResizeMode(
            8,
            QHeaderView.ResizeMode.Fixed,
        )
        header.resizeSection(1, 48)
        # Give the metadata columns a little more room so their headers sit
        # slightly closer to the title column instead of hugging the edge.
        header.resizeSection(3, 112)
        header.resizeSection(4, 112)
        header.resizeSection(5, 44)
        header.resizeSection(6, 44)
        header.resizeSection(7, 44)
        header.resizeSection(8, 44)
        header.resizeSection(0, 44)
        # Keep the custom row rendering while allowing the library columns to
        # be sorted through the existing _handle_library_sort implementation.
        header.setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setFixedHeight(36)
        header.setSectionsClickable(True)
        header.setMouseTracking(True)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        # The custom header paints one centered chevron above the active
        # label; keep Qt's edge-aligned indicator disabled to avoid a double
        # arrow in the same section.
        header.setSortIndicatorShown(False)
        header.setSortIndicator(
            DEFAULT_LIBRARY_SORT_COLUMN,
            Qt.SortOrder.DescendingOrder,
        )
        header.sectionClicked.connect(self._handle_library_sort)
        self.track_table.setColumnHidden(
            1,
            not self._show_track_covers,
        )
        self.track_table.setColumnHidden(6, True)
        self.track_table.setColumnHidden(7, True)
        self.track_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.track_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.track_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.track_table.setAlternatingRowColors(False)
        self._hovered_track_row = -1
        self.track_table.row_hovered.connect(self._set_track_row_hover)
        self.track_table.selectionModel().selectionChanged.connect(
            lambda _selected, _deselected: self._handle_track_selection()
        )
        self.track_table.row_play_requested.connect(self._play_track_from_table_row)
        self.track_table.row_double_clicked.connect(self._play_track_from_table_row)
        self.track_table.row_clicked.connect(self._handle_track_row_clicked)
        self.track_table.row_check_requested.connect(self._handle_track_row_clicked)
        self.track_table.row_queue_requested.connect(self._enqueue_track_from_table_row)
        self.track_table.row_remove_requested.connect(self._remove_track_from_table_row)
        self.track_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.track_table.customContextMenuRequested.connect(
            self._show_track_context_menu
        )

        self._update_add_tracks_controls()
        layout.addWidget(self.track_table)

        return panel

    def _set_track_row_hover(self, row_index: int) -> None:
        """Remember hover state without creating or styling row widgets."""

        self._hovered_track_row = row_index

    def _apply_pending_track_row_hover(self) -> None:
        row_index = self._pending_hovered_track_row
        if row_index == self._hovered_track_row:
            return

        previous_row = self._hovered_track_row
        self._hovered_track_row = row_index
        self._refresh_track_row_visuals((previous_row, row_index))

    def _refresh_track_row_visuals(
        self,
        row_indices: tuple[int, ...] | None = None,
    ) -> None:
        """Ask the delegate to repaint only; rows have no embedded widgets."""

        if row_indices is None:
            self.track_table.viewport().update()
            return
        for row_index in dict.fromkeys(row_indices):
            self.track_table.refresh_row(row_index)

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
        self.queue_source_label = QLabel("")
        self.queue_source_label.setObjectName("sectionCaption")
        self.queue_source_label.setMaximumWidth(150)
        self.queue_source_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        header.addWidget(self.queue_source_label)
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
        self.queue_list.itemDoubleClicked.connect(self._play_queued_item)
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

    def _queue_source_text(self) -> str:
        """Return a compact human-readable name for the active queue source."""

        queue = self.playback_queue_service.queue
        if queue is None:
            return ""

        if queue.source_playlist_id is not None:
            playlist = self.store.get_playlist(queue.source_playlist_id)
            return (
                f"Playlist · {playlist.name}"
                if playlist is not None
                else "Playlist"
            )

        if queue.mode == QueueMode.RECOMMENDATIONS:
            anchor_track_id = self._radio_anchor_track_id or queue.current_track_id
            anchor_track = (
                self.store.get_track(anchor_track_id)
                if anchor_track_id is not None
                else None
            )
            return (
                f"Radio · {anchor_track.title}"
                if anchor_track is not None
                else "Track radio"
            )

        if queue.mode == QueueMode.SESSION:
            if self.session_mood_name == MY_WAVE_SESSION_NAME:
                return "My Wave"
            if self.session_mood_name is not None:
                return f"Wave · {self.session_mood_name}"
            if self.session_genre_name is not None:
                return f"Genre · {self.session_genre_name}"
            return "Wave"

        if queue.mode == QueueMode.SHUFFLE:
            return "Library shuffle"
        if queue.mode == QueueMode.SMART_SHUFFLE:
            return "Smart shuffle"
        return "Library"

    def _update_queue_source_label(self) -> None:
        if not hasattr(self, "queue_source_label"):
            return

        source = self._queue_source_text()
        self.queue_source_label.setText(f"· {source}" if source else "")
        self.queue_source_label.setToolTip(source)
        if hasattr(self, "queue_dialog"):
            self.queue_dialog.set_source(source)

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

    def _set_track_covers_enabled(self, enabled: bool) -> None:
        """Toggle track artwork in library and playlist tables."""

        self._show_track_covers = bool(enabled)
        self._playback_state_settings.setValue(
            "appearance/library_track_covers",
            self._show_track_covers,
        )
        if hasattr(self, "track_table"):
            self.track_table.setColumnHidden(
                1,
                not self._show_track_covers,
            )
            self._render_visible_tracks(self.library_title_label.text())

    def _set_parallel_genre_analysis_enabled(self, enabled: bool) -> None:
        """Choose between safe sequential and faster parallel analysis."""

        self._parallel_genre_analysis_enabled = bool(enabled)
        self._playback_state_settings.setValue(
            "performance/parallel_genre_analysis",
            self._parallel_genre_analysis_enabled,
        )
        self._genre_analysis_pool.setMaxThreadCount(
            PARALLEL_GENRE_ANALYSIS_WORKERS
            if self._parallel_genre_analysis_enabled
            else 1
        )
        if self._parallel_genre_analysis_enabled:
            self.statusBar().showMessage(
                "Parallel genre analysis enabled (2 workers; higher GPU/RAM usage)"
            )
        else:
            self.statusBar().showMessage(
                "Sequential genre analysis enabled (lower GPU/RAM usage)"
            )

    def _set_gpu_optimized_genre_analysis_enabled(self, enabled: bool) -> None:
        """Toggle batched neural inference for subsequent track analyses."""

        self._gpu_optimized_genre_analysis_enabled = bool(enabled)
        self._playback_state_settings.setValue(
            "performance/gpu_optimized_genre_analysis",
            self._gpu_optimized_genre_analysis_enabled,
        )
        self._genre_analysis_service.set_gpu_optimized(
            self._gpu_optimized_genre_analysis_enabled
        )
        if self._gpu_optimized_genre_analysis_enabled:
            self.statusBar().showMessage(
                "GPU-optimized genre analysis enabled (batched inference)"
            )
        else:
            self.statusBar().showMessage(
                "Standard genre analysis enabled"
            )

    def _load_library(self, *, refresh_map: bool = True) -> None:
        tracks = list(self.store.list_tracks())
        self._library_tracks = tracks
        self._music_map_source_tracks = list(tracks)
        if not refresh_map:
            self._music_map_tracks = (
                MusicMapWidget.select_tracks_for_percentage(
                    tracks,
                    self._music_map_track_percentage,
                )
            )
            self._music_map_signature = MusicMapWidget.track_signature(
                self._music_map_tracks
            )
            self.music_map.load_snapshot(
                MUSIC_MAP_SNAPSHOT_PATH,
                MUSIC_MAP_SNAPSHOT_METADATA_PATH,
                self._music_map_signature,
            )

        if self.selected_playlist_id is None:
            title = (
                self._add_tracks_view_title()
                if self._add_tracks_mode
                else "Music library"
            )
            self._set_visible_tracks(
                tracks,
                title=title,
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

        self._library_refresh_timer.stop()
        self._library_refresh_pending = False
        self._track_scope_tracks = list(tracks)
        if hasattr(self, "track_table"):
            # Keep the track table clean: playlist tracks are removed through
            # the existing playlist actions, not with a per-row cross button.
            self.track_table.setColumnHidden(
                1,
                not self._show_track_covers and not self._add_tracks_mode,
            )
            self.track_table.setColumnHidden(6, True)
            self._update_add_tracks_controls()
        self._render_visible_tracks(title)

    def _render_visible_tracks(self, title: str) -> None:
        """Render the current library/playlist scope with active search."""

        self._cancel_track_materialization()
        self._track_hover_timer.stop()
        self._pending_hovered_track_row = -1
        filtered_tracks = self._filter_library_tracks(self._track_scope_tracks)
        self._visible_tracks = self._sort_tracks(filtered_tracks)
        self.track_table.clearSelection()
        self.selected_track_id = None
        self._selected_track_row = -1
        self._hovered_track_row = -1
        self.track_table.set_search_query(self._library_search_query)
        self.track_table.set_tracks(
            self._visible_tracks,
            add_mode=self._add_tracks_mode,
            playlist_open=self.selected_playlist_id is not None,
            show_covers=self._show_track_covers,
            selected_ids=self._add_tracks_selected_ids,
            text_for_track=self._track_table_text,
        )

        self.library_title_label.setText(title)
        self.library_count_label.setText(
            f"{len(self._visible_tracks)} track"
            f"{'s' if len(self._visible_tracks) != 1 else ''}"
        )
        # Defer recommendation work until after the first visible rows paint.
        QTimer.singleShot(0, self._load_recommendations)

    def _schedule_library_refresh(self) -> None:
        """Coalesce repeated imports into one table rebuild."""

        self._library_refresh_pending = True
        if self._playlist_import_active:
            return
        self._library_refresh_timer.start()

    def _flush_library_refresh(self) -> None:
        """Refresh the current view after a burst of imported tracks."""

        if self._playlist_import_active:
            return

        self._library_refresh_pending = False
        if self.selected_playlist_id is not None:
            self._load_selected_playlist_tracks()
            return

        self._set_visible_tracks(
            self._library_tracks,
            title=self.library_title_label.text(),
        )

    def _handle_library_search_changed(self, text: str) -> None:
        self._library_search_query = text.strip()
        self.library_search_clear.setVisible(bool(self._library_search_query))
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
            if (query in track.title.casefold() or query in track.artist.casefold())
        ]

    def _handle_library_sort(self, column: int) -> None:
        if column not in {2, 3, 4, 5}:
            return

        if self._library_sort_column == column:
            self._library_sort_descending = not self._library_sort_descending
        else:
            self._library_sort_column = column
            # Added uses newest-first for the initial downward indicator;
            # text and duration start in their natural ascending order.
            self._library_sort_descending = column == 4

        # The requested visual convention is a downward triangle on the first
        # click, then upward on the reverse order. Added intentionally maps
        # that first click to newest-first.
        if column == 4:
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

    def _reset_library_sort(self) -> None:
        """Clear the active table sort when changing the track scope."""

        self._library_sort_column = None
        self._library_sort_descending = False
        header = self.track_table.horizontalHeader()
        header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        header.viewport().update()

    def _set_default_library_sort(self) -> None:
        """Restore newest-first ordering when returning to the main library."""

        self._library_sort_column = DEFAULT_LIBRARY_SORT_COLUMN
        self._library_sort_descending = DEFAULT_LIBRARY_SORT_DESCENDING
        if not hasattr(self, "track_table"):
            return

        header = self.track_table.horizontalHeader()
        header.setSortIndicator(
            DEFAULT_LIBRARY_SORT_COLUMN,
            Qt.SortOrder.DescendingOrder,
        )
        header.viewport().update()

    def _sort_tracks(self, tracks: list[Track]) -> list[Track]:
        if self._library_sort_column is None:
            return list(tracks)

        column = self._library_sort_column

        def sort_key(track: Track) -> object:
            if column == 2:
                return (
                    track.title.casefold(),
                    track.artist.casefold(),
                )
            if column == 3:
                return (
                    self._format_display_genres(track).casefold(),
                    track.title.casefold(),
                )
            if column == 5:
                return (
                    track.duration_ms if track.duration_ms is not None else -1,
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

    def _cancel_track_materialization(self) -> None:
        self._track_materialize_timer.stop()

    def _schedule_visible_track_materialization(self) -> None:
        """Schedule controls for the current viewport without scroll churn."""

        if self._materializing_track_rows or not self._visible_tracks:
            return
        self._track_materialize_timer.start()

    def _visible_track_row_indices(self) -> set[int]:
        row_count = self.track_table.rowCount()
        if row_count <= 0:
            return set()

        viewport_height = max(0, self.track_table.viewport().height() - 1)
        first_row = self.track_table.rowAt(0)
        last_row = self.track_table.rowAt(viewport_height)
        first_row = max(first_row, 0)
        if last_row < 0:
            last_row = min(row_count - 1, first_row + 12)

        start = max(0, first_row - TRACK_WIDGET_BUFFER_ROWS)
        end = min(row_count, last_row + TRACK_WIDGET_BUFFER_ROWS + 1)
        return set(range(start, end))

    def _materialize_visible_track_rows(self) -> None:
        """Keep only a small widget window alive around the viewport."""

        if self._materializing_track_rows:
            return

        desired_rows = self._visible_track_row_indices()
        stale_rows = self._materialized_track_rows - desired_rows
        new_rows = desired_rows - self._materialized_track_rows
        if not stale_rows and not new_rows:
            return

        self._materializing_track_rows = True
        changed_rows = stale_rows | new_rows
        table_signals_blocked = self.track_table.blockSignals(True)
        table_updates_enabled = self.track_table.updatesEnabled()
        self.track_table.setUpdatesEnabled(False)
        try:
            for row_index in sorted(stale_rows):
                self._unmaterialize_track_row(row_index)

            for row_index in sorted(new_rows):
                if row_index >= len(self._visible_tracks):
                    continue
                self._populate_track_row_widgets(
                    row_index,
                    self._visible_tracks[row_index],
                )
                self._materialized_track_rows.add(row_index)
        finally:
            self.track_table.setUpdatesEnabled(table_updates_enabled)
            self.track_table.blockSignals(table_signals_blocked)
            self._materializing_track_rows = False

        self._refresh_track_row_visuals(tuple(changed_rows))
        self.statusBar().showMessage("Library ready")

    def _show_main_library(self) -> None:
        was_playlist_open = self.selected_playlist_id is not None
        if self._add_tracks_mode:
            self._clear_add_tracks_mode_state()
        if was_playlist_open:
            self._reset_library_sort()
        self.selected_playlist_id = None
        if was_playlist_open:
            self._set_default_library_sort()
        self.playlist_list.blockSignals(True)
        self.playlist_list.clearSelection()
        self.playlist_list.blockSignals(False)
        self._set_visible_tracks(
            self._library_tracks,
            title=(
                self._add_tracks_view_title()
                if self._add_tracks_mode
                else "Music library"
            ),
        )
        self._update_playlist_carousel_selection()
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

        # The library catalog is already kept in memory.  Resolving every
        # history row through ``get_track`` opens a separate database session
        # for each item whenever playback advances.
        tracks_by_id = {track.id: track for track in self._library_tracks}
        for interaction in interactions:
            if interaction.track_id in seen_track_ids:
                continue
            track = tracks_by_id.get(interaction.track_id)
            if track is None:
                # Keep history resilient to a library refresh that has not
                # reached the in-memory catalog yet.
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
        """Update one row, materializing controls only when needed."""

        was_materialized = row_index in self._materialized_track_rows
        if was_materialized:
            self._unmaterialize_track_row(row_index)
        self._populate_track_row_items(row_index, track)
        if was_materialized:
            self._populate_track_row_widgets(row_index, track)
            self._materialized_track_rows.add(row_index)

    def _populate_track_row_items(
        self,
        row_index: int,
        track: Track,
    ) -> None:
        """Populate the lightweight data items used by every table row."""

        number_item = QTableWidgetItem(str(row_index + 1))
        number_item.setData(
            Qt.ItemDataRole.UserRole,
            track.id,
        )
        number_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self.track_table.setItem(row_index, 0, number_item)

        self.track_table.setItem(
            row_index,
            2,
            QTableWidgetItem(track.title),
        )
        self.track_table.setItem(
            row_index,
            3,
            QTableWidgetItem(self._format_display_genres(track)),
        )
        self.track_table.setItem(
            row_index,
            4,
            QTableWidgetItem(self._format_added_date(track.created_at)),
        )
        self.track_table.setItem(
            row_index,
            5,
            QTableWidgetItem(self._format_duration(track.duration_ms)),
        )
        for column in (3, 4):
            item = self.track_table.item(row_index, column)
            if item is not None:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
        duration_item = self.track_table.item(row_index, 5)
        if duration_item is not None:
            duration_item.setTextAlignment(
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            )

        self.track_table.setItem(
            row_index,
            7,
            QTableWidgetItem(
                self._genre_statuses.get(
                    track.id,
                    self._genre_status_for_track(track),
                )
            ),
        )

    def _populate_track_row_widgets(
        self,
        row_index: int,
        track: Track,
    ) -> None:
        index_widget = TrackNumberPlayWidget(row_index + 1)
        index_widget.play_requested.connect(
            lambda track_id=track.id, row=row_index: (
                self.track_table.selectRow(row),
                self._play_track_now(track_id),
            )
        )
        self.track_table.setCellWidget(row_index, 0, index_widget)
        self.track_table.register_row_widget(index_widget, row_index)
        if self._add_tracks_mode:
            checkbox_container = QWidget()
            checkbox_layout = QHBoxLayout(checkbox_container)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            checkbox = QCheckBox()
            checkbox.setObjectName("playlistTrackCheck")
            checkbox.setToolTip("Add this track to the playlist")
            checkbox.setChecked(track.id in self._add_tracks_selected_ids)
            checkbox.toggled.connect(
                lambda checked, track_id=track.id: self._set_add_track_selected(
                    track_id, checked
                )
            )
            checkbox_layout.addWidget(checkbox)
            self.track_table.setCellWidget(
                row_index,
                1,
                checkbox_container,
            )
            self.track_table.register_row_widget(
                checkbox_container,
                row_index,
            )
        else:
            self.track_table.removeCellWidget(row_index, 1)
        track_identity = TrackIdentityWidget(
            track.title,
            track.artist,
            cover_path=track.cover_path,
            show_cover=self._show_track_covers,
            include_play_button=False,
        )
        track_identity.play_requested.connect(
            lambda track_id=track.id: self._play_track_now(track_id)
        )
        track_identity.set_search_query(self._library_search_query)
        self.track_table.setCellWidget(row_index, 2, track_identity)
        self.track_table.register_row_widget(track_identity, row_index)
        # The lightweight title/number items are the fallback for rows outside
        # the viewport.  TrackIdentityWidget is intentionally translucent, so
        # leave no duplicate text beneath it while this row is materialized.
        for column in (0, 2):
            item = self.track_table.item(row_index, column)
            if item is not None:
                item.setText("")
        remove_button: QToolButton | None = None
        remove_container: QWidget | None = None
        if self.selected_playlist_id is not None:
            remove_button = QToolButton()
            remove_button.setObjectName("playlistRemoveButton")
            remove_button.setText("×")
            remove_button.setToolTip("Remove from playlist")
            remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
            remove_button.setAutoRaise(True)
            remove_button.clicked.connect(
                lambda _checked=False, track_id=track.id: self._remove_playlist_track(
                    track_id
                )
            )
            remove_container = QWidget()
            remove_layout = QHBoxLayout(remove_container)
            remove_layout.setContentsMargins(0, 0, 0, 0)
            remove_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            remove_layout.addWidget(remove_button)
        if remove_container is None:
            self.track_table.removeCellWidget(row_index, 6)
        else:
            self.track_table.setCellWidget(row_index, 6, remove_container)
            self.track_table.register_row_widget(remove_container, row_index)
        queue_button = QToolButton()
        queue_button.setObjectName("trackQueueButton")
        queue_button.setIcon(svg_icon(ADD_TO_QUEUE_ICON, size=22))
        queue_button.setIconSize(QSize(22, 22))
        queue_button.setToolTip("Add to queue")
        queue_button.setAccessibleName("Add track to queue")
        queue_button.setCursor(Qt.CursorShape.PointingHandCursor)
        queue_button.setAutoRaise(True)
        queue_button.clicked.connect(
            lambda _checked=False, track_id=track.id: self._enqueue_track(track_id)
        )
        queue_container = QWidget()
        queue_layout = QHBoxLayout(queue_container)
        queue_layout.setContentsMargins(0, 0, 0, 0)
        queue_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        queue_layout.addWidget(queue_button)
        self.track_table.setCellWidget(row_index, 8, queue_container)
        self.track_table.register_row_widget(queue_container, row_index)

    def _unmaterialize_track_row(self, row_index: int) -> None:
        """Remove expensive controls from one row outside the viewport."""

        self.track_table.clear_row_widgets_for_row(row_index)
        for column in (0, 1, 2, 6, 8):
            widget = self.track_table.cellWidget(row_index, column)
            if widget is None:
                continue
            self.track_table.removeCellWidget(row_index, column)
            try:
                widget.deleteLater()
            except RuntimeError:
                pass
        self._materialized_track_rows.discard(row_index)
        if row_index < len(self._visible_tracks):
            self._populate_track_row_items(
                row_index,
                self._visible_tracks[row_index],
            )

    def _append_library_track(self, track: Track) -> None:
        for index, item in enumerate(self._library_tracks):
            if item.id == track.id:
                self._library_tracks[index] = track
                break
        else:
            self._library_tracks.append(track)

        self._enqueue_loudness_analysis(track)
        self._schedule_library_refresh()

    def _track_table_text(
        self,
        track: Track,
    ) -> tuple[str, str, str, str]:
        """Prepare metadata only for rows currently painted by the view."""

        return (
            self._format_display_genres(track),
            self._format_added_date(track.created_at),
            self._format_duration(track.duration_ms),
            self._genre_statuses.get(
                track.id,
                self._genre_status_for_track(track),
            ),
        )

    def _track_at_table_row(self, row_index: int) -> Track | None:
        if 0 <= row_index < len(self._visible_tracks):
            return self._visible_tracks[row_index]
        return None

    def _update_library_track_row(self, track: Track) -> None:
        self._library_tracks = [
            track if item.id == track.id else item for item in self._library_tracks
        ]
        self._music_map_source_tracks = [
            track
            if item.id == track.id
            else item
            for item in self._music_map_source_tracks
        ]
        self._track_scope_tracks = [
            track if item.id == track.id else item for item in self._track_scope_tracks
        ]
        self._visible_tracks = [
            track if item.id == track.id else item for item in self._visible_tracks
        ]

        in_scope = any(item.id == track.id for item in self._track_scope_tracks)
        is_visible = any(item.id == track.id for item in self._visible_tracks)
        matches_search = self._track_matches_search(track)
        if self._library_search_query and in_scope and is_visible != matches_search:
            self._render_visible_tracks(self.library_title_label.text())
            return

        updated_rows = [
            row_index
            for row_index, visible_track in enumerate(self._visible_tracks)
            if visible_track.id == track.id
        ]
        for row_index in updated_rows:
            self.track_table.update_row(
                row_index,
                track,
            )

        self._update_add_tracks_controls()
        if updated_rows:
            return

    def _remove_library_track_row(self, track_id: str) -> None:
        self._track_scope_tracks = [
            track for track in self._track_scope_tracks if track.id != track_id
        ]
        self._visible_tracks = [
            track for track in self._visible_tracks if track.id != track_id
        ]
        self._render_visible_tracks(self.library_title_label.text())

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
        detected_parent_genres = list(
            dict.fromkeys(
                prediction.parent_genre.strip()
                for prediction in track.detected_genres
                if prediction.parent_genre.strip()
            )
        )
        if detected_parent_genres:
            visible_genres = detected_parent_genres[:2]
            hidden_count = len(detected_parent_genres) - len(visible_genres)
        else:
            visible_genres = list(track.genres[:2])
            hidden_count = len(track.genres) - len(visible_genres)

        text = ", ".join(visible_genres)

        if hidden_count > 0:
            text = f"{text} (+{hidden_count} more)"

        return text

    @staticmethod
    def _track_has_analysis(track: Track) -> bool:
        """Use the persisted embedding as the single analysis marker."""

        return track.track_embedding is not None

    def _genre_status_for_track(self, track: Track) -> str:
        if self._track_has_analysis(track):
            return "Completed"
        return "Not analyzed"

    def _load_recommendations(self) -> None:
        # Recommendations still power Now sessions and track radio; this old
        # sidebar no longer renders a duplicate text list.
        if not hasattr(self, "recommendation_list"):
            return

        if self.session_mood_name is not None or self.session_genre_name is not None:
            # Session queues have their own producer and refill policy.  A
            # second sidebar request on every track change competes with it
            # for CPU and can delay the next session track.
            self._recommendation_generation += 1
            if self._recommendation_task is not None:
                self._recommendation_task.cancel()
            self._recommendation_task = None
            self.recommendation_list.clear()
            return

        if self._track_radio_enabled:
            # Track radio owns the live recommendation stream.  Recomputing a
            # second sidebar feed on every track change only competes with
            # the radio worker for CPU and makes playback feel sluggish.
            self._recommendation_generation += 1
            if self._recommendation_task is not None:
                self._recommendation_task.cancel()
            self._recommendation_task = None
            self.recommendation_list.clear()
            return

        if self.session_mood_name == MY_WAVE_SESSION_NAME:
            context = RecommendationContext.my_wave()
        elif self.session_genre_name is not None:
            context = RecommendationContext.genre(self.session_genre_name)
        elif self.selected_mood_name is not None:
            context = RecommendationContext.mood(
                MOOD_PRESETS[self.selected_mood_name],
                mood_name=self.selected_mood_name,
            )
        elif self.selected_genre_name is not None:
            context = RecommendationContext.genre(self.selected_genre_name)
        elif self.selected_track_id is not None:
            context = RecommendationContext.track_radio(self.selected_track_id)
        else:
            context = RecommendationContext()

        self._recommendation_generation += 1
        generation = self._recommendation_generation
        self._recommendation_impression_session_id = (
            f"sidebar-{generation}-{uuid4().hex}"
        )
        self._recommendation_impression_position = 0
        playlist_id = self._active_playlist_context_id()
        self._recommendation_impression_playlist_id = playlist_id
        if self._recommendation_task is not None:
            self._recommendation_task.cancel()

        self.recommendation_list.clear()
        self.recommendation_list.addItem("Loading recommendations…")

        fetcher = lambda: self.recommendation_service.get_recommendations(
            user_id=self.user_id,
            limit=10,
            context=context,
            playlist_id=playlist_id,
        )
        cancellable_fetcher = None
        if context.mode in {
            RecommendationMode.MOOD,
            RecommendationMode.GENRE,
            RecommendationMode.MY_WAVE,
        }:
            cancellable_fetcher = lambda should_cancel: (
                self.recommendation_service.get_recommendations(
                    user_id=self.user_id,
                    limit=10,
                    context=context,
                    playlist_id=playlist_id,
                    should_cancel=should_cancel,
                )
            )

        task = RecommendationTask(
            fetcher,
            generation,
            batch_size=5,
            cancellable_fetcher=cancellable_fetcher,
        )
        task.signals.batch_ready.connect(self._handle_recommendation_batch)
        task.signals.finished.connect(self._finish_recommendation_loading)
        task.signals.error_occurred.connect(self._handle_recommendation_error)
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
            and self.recommendation_list.item(0).text() == "Loading recommendations…"
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

        if self._record_recommendation_impressions(
            shown_recommendations,
            session_id=self._recommendation_impression_session_id,
            position_offset=self._recommendation_impression_position,
            playlist_id=self._recommendation_impression_playlist_id,
        ):
            self._recommendation_impression_position += len(shown_recommendations)

    def _record_recommendation_impressions(
        self,
        recommendations: list[Recommendation] | tuple[Recommendation, ...],
        *,
        session_id: str | None = None,
        position_offset: int = 0,
        playlist_id: str | None = None,
    ) -> bool:
        if not recommendations:
            return False
        task = RecommendationAnalyticsTask(
            self.recommendation_analytics_service,
            self.user_id,
            recommendations,
            session_id=session_id,
            playlist_id=playlist_id,
            position_offset=position_offset,
        )
        self._recommendation_analytics_pool.start(task)
        return True

    def _finish_recommendation_loading(self, generation: int) -> None:
        if generation != self._recommendation_generation:
            return

        self._recommendation_task = None
        if (
            self.recommendation_list.count() == 1
            and self.recommendation_list.item(0) is not None
            and self.recommendation_list.item(0).text() == "Loading recommendations…"
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
        self.recommendation_list.addItem(f"Recommendations unavailable: {message}")

    def _start_mood_session(self) -> None:
        if self.selected_mood_name is None:
            QMessageBox.information(
                self,
                "Choose a mood",
                "Choose a mood before starting a Now session.",
            )
            return

        mood_name = self.selected_mood_name
        self.selected_genre_name = None
        self._schedule_mood_session(
            context=RecommendationContext.mood(
                MOOD_PRESETS[mood_name],
                mood_name=mood_name,
            ),
            session_name=mood_name,
            unavailable_message="No analyzed local tracks match this mood yet.",
        )

    def _start_mood_session_from_card(self, mood_name: str) -> None:
        if mood_name == MY_WAVE_SESSION_NAME:
            self._start_my_wave_session()
            return
        self.selected_mood_name = mood_name
        self.selected_genre_name = None
        self._start_mood_session()

    def _start_genre_session_from_card(self, genre_name: str) -> None:
        self.selected_genre_name = genre_name
        self.selected_mood_name = None
        self._schedule_mood_session(
            context=RecommendationContext.genre(genre_name),
            session_name=genre_name,
            unavailable_message=(f"No local tracks match the genre {genre_name}."),
        )

    def _start_my_wave_session(self) -> None:
        """Start a personalized mood session based on listening history."""

        self.selected_mood_name = None
        self.selected_genre_name = None
        self._schedule_mood_session(
            context=RecommendationContext.my_wave(),
            session_name=MY_WAVE_SESSION_NAME,
            unavailable_message=(
                "Analyze or add a few local tracks to build your wave."
            ),
        )

    def _schedule_mood_session(
        self,
        *,
        context: RecommendationContext,
        session_name: str,
        unavailable_message: str,
    ) -> None:
        """Calculate and start a Mood/My Wave session away from the GUI thread."""

        if self._mood_session_task is not None:
            self._mood_session_task.cancel()
        self._cancel_mood_refill()

        self._mood_session_generation += 1
        generation = self._mood_session_generation
        self._mood_session_impression_session_id = f"mood-{generation}-{uuid4().hex}"
        self._mood_session_impression_position = 0
        self._mood_session_playlist_id = self._active_playlist_context_id()
        self._mood_session_result_generation = None
        self._mood_session_pending_name = session_name
        self._mood_session_pending_mode = context.mode
        self._mood_session_seen_track_ids.clear()
        # Start every session with the same small visible slice.  Mood and
        # genre sessions used to calculate 30 tracks up front, which made the
        # first queue feel frozen even though the rest can be refilled lazily.
        initial_limit = MOOD_SESSION_INITIAL_QUEUE_SIZE

        task = RecommendationTask(
            lambda: (),
            generation,
            batch_size=initial_limit,
            cancellable_fetcher=lambda should_cancel: (
                self.recommendation_service.get_recommendations(
                    user_id=self.user_id,
                    limit=initial_limit,
                    context=context,
                    playlist_id=self._mood_session_playlist_id,
                    should_cancel=should_cancel,
                )
            ),
        )
        task.signals.batch_ready.connect(
            lambda task_generation, batch, name=session_name: (
                self._handle_mood_session_batch(
                    task_generation,
                    name,
                    unavailable_message,
                    batch,
                )
            )
        )
        task.signals.finished.connect(self._finish_mood_session_loading)
        task.signals.error_occurred.connect(self._handle_mood_session_error)
        self._mood_session_task = task
        self.statusBar().showMessage(
            "Preparing My Wave…"
            if session_name == MY_WAVE_SESSION_NAME
            else f"Preparing {session_name.title()} session…"
        )
        self._mood_recommendation_pool.start(task)

    def _handle_mood_session_batch(
        self,
        generation: int,
        session_name: str,
        unavailable_message: str,
        batch: object,
    ) -> None:
        if generation != self._mood_session_generation:
            return

        self._mood_session_result_generation = generation
        session_mode = self._mood_session_pending_mode or (
            RecommendationMode.MY_WAVE
            if session_name == MY_WAVE_SESSION_NAME
            else RecommendationMode.MOOD
        )
        recommendations = tuple(
            recommendation
            for recommendation in batch
            if isinstance(recommendation, Recommendation)
        )
        track_ids = [
            recommendation.track.id
            for recommendation in recommendations
            if (
                (
                    session_mode
                    in {
                        RecommendationMode.MY_WAVE,
                        RecommendationMode.GENRE,
                    }
                    or recommendation.track.mood is not None
                )
                and recommendation.track.local_path
                and Path(recommendation.track.local_path).exists()
            )
        ]
        if not track_ids:
            QMessageBox.information(
                self,
                "Session unavailable",
                unavailable_message,
            )
            return

        self._mood_session_seen_track_ids = set(track_ids)

        shown_recommendations = tuple(
            recommendation
            for recommendation in recommendations
            if recommendation.track.id in track_ids
        )
        if self._record_recommendation_impressions(
            shown_recommendations,
            session_id=self._mood_session_impression_session_id,
            position_offset=self._mood_session_impression_position,
            playlist_id=self._mood_session_playlist_id,
        ):
            self._mood_session_impression_position += len(shown_recommendations)
        self.selected_mood_name = (
            session_name if session_mode == RecommendationMode.MOOD else None
        )
        self.selected_genre_name = (
            session_name if session_mode == RecommendationMode.GENRE else None
        )
        self.session_mood_name = (
            session_name
            if session_mode
            in {
                RecommendationMode.MOOD,
                RecommendationMode.MY_WAVE,
            }
            else None
        )
        self.session_genre_name = (
            session_name if session_mode == RecommendationMode.GENRE else None
        )
        self.playback_queue_service.start(
            track_ids,
            mode=QueueMode.SESSION,
        )
        self._play_current_queue_track()
        self.statusBar().showMessage(
            "My Wave session started"
            if session_name == MY_WAVE_SESSION_NAME
            else f"Now session started: {session_name.title()}"
        )

    def _finish_mood_session_loading(self, generation: int) -> None:
        if generation != self._mood_session_generation:
            return

        if self._mood_session_result_generation != generation:
            session_name = self._mood_session_pending_name
            session_mode = self._mood_session_pending_mode
            title = (
                "My Wave unavailable"
                if session_name == MY_WAVE_SESSION_NAME
                else "Genre unavailable"
                if session_mode == RecommendationMode.GENRE
                else "Session unavailable"
            )
            message = (
                "Analyze or add a few local tracks to build your wave."
                if session_name == MY_WAVE_SESSION_NAME
                else "No local tracks match the selected genre."
                if session_mode == RecommendationMode.GENRE
                else "No analyzed local tracks match this mood yet."
            )
            QMessageBox.information(self, title, message)

        self._mood_session_task = None
        self._mood_session_pending_name = None
        self._mood_session_pending_mode = None
        self._mood_session_result_generation = None
        if self.session_mood_name is not None or self.session_genre_name is not None:
            self._load_queue()

    def _handle_mood_session_error(
        self,
        generation: int,
        message: str,
    ) -> None:
        if generation != self._mood_session_generation:
            return

        session_name = self._mood_session_pending_name
        session_mode = self._mood_session_pending_mode
        self._mood_session_task = None
        self._mood_session_pending_name = None
        self._mood_session_pending_mode = None
        self._mood_session_result_generation = None
        if message:
            QMessageBox.warning(
                self,
                "My Wave unavailable"
                if session_name == MY_WAVE_SESSION_NAME
                else "Genre unavailable"
                if session_mode == RecommendationMode.GENRE
                else "Session unavailable",
                message,
            )

    def _cycle_playback_mode(self) -> None:
        """Cycle sequential, shuffle and smart-shuffle library playback."""

        try:
            current_index = LIBRARY_PLAYBACK_MODES.index(self._playback_mode)
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

        self.statusBar().showMessage(f"Playback mode: {self._playback_mode_label()}")

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

        self._repeat_mode = REPEAT_MODES[(current_index + 1) % len(REPEAT_MODES)]
        self.playback_queue_service.set_repeat_mode(self._repeat_mode)
        self._update_playback_mode_controls()
        self.statusBar().showMessage(f"Repeat: {self._repeat_mode_label()}")

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
            f"Playback order: {self._playback_mode_label()} (click to change)"
        )

        repeat_icons = {
            RepeatMode.OFF: REPEAT_OFF_ICON,
            RepeatMode.QUEUE: REPEAT_QUEUE_ICON,
            RepeatMode.TRACK: REPEAT_TRACK_ICON,
        }
        self.repeat_button.set_svg(repeat_icons[self._repeat_mode])
        self.repeat_button.setToolTip(
            f"Repeat: {self._repeat_mode_label()} (click to change)"
        )

        if hasattr(self, "track_radio_action"):
            self.track_radio_action.setChecked(self._track_radio_enabled)

    def _start_library_queue(
        self,
        track_id: str,
        *,
        restart: bool = True,
        preserve_manual_queue: bool = True,
    ) -> None:
        """Build a new library queue for the selected playback mode."""

        track = self.store.get_track(track_id)
        if track is None:
            return

        if not self._is_playable_track(track):
            self.statusBar().showMessage(
                f"Not downloaded: {track.artist} — {track.title}"
            )
            return

        self._cancel_mood_session()
        manual_track_ids = (
            self._manual_queue_snapshot()
            if preserve_manual_queue
            else ()
        )
        if self._track_radio_enabled:
            self._start_recommendation_queue(
                track.id,
                restart=restart,
                manual_track_ids=manual_track_ids,
            )
            return

        self._cancel_radio_recommendations()
        self._radio_impression_session_id = None
        self._radio_impression_position = 0
        self._radio_anchor_track_id = None
        if self.selected_playlist_id is not None:
            self._start_playlist_queue(
                shuffle=self._playback_mode == QueueMode.SHUFFLE,
                smart=self._playback_mode == QueueMode.SMART_SHUFFLE,
                playlist_id=self.selected_playlist_id,
                start_track_id=track.id,
                preserve_manual_queue=preserve_manual_queue,
            )
            return

        manual_id_set = set(manual_track_ids)
        library_tracks = [
            item
            for item in self.store.list_tracks()
            if self._is_playable_track(item)
        ]
        # Keep the queue in the same order the library currently advertises.
        # ``MusicStore.list_tracks`` has its own artist/title order and would
        # otherwise ignore a user's active Title/Genres/Added/Duration sort.
        ordered_library_tracks = self._sort_tracks(library_tracks)
        visible_track_ids = {item.id for item in self._visible_tracks}
        if track.id in visible_track_ids:
            # A row click should use exactly the order currently visible in
            # the table, including the active search/filter result.
            ordered_library_tracks = [
                item
                for item in self._visible_tracks
                if self._is_playable_track(item)
            ]
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
                item_id for item_id in library_track_ids if item_id != track.id
            ]

        remaining_track_ids = [
            item_id for item_id in candidate_ids if item_id not in manual_id_set
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
        self.session_genre_name = None
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
            if track.id in available_ids and track.id not in similar_id_set
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

        self._radio_impression_playlist_id = (
            self._active_playlist_context_id()
        )
        self._cancel_mood_session()
        if manual_track_ids is None:
            manual_track_ids = self._manual_queue_snapshot()

        self.session_mood_name = None
        self.session_genre_name = None
        self._track_radio_enabled = True
        self._radio_anchor_track_id = track.id
        self._radio_impression_session_id = f"radio-{uuid4().hex}"
        self._radio_impression_position = 0
        self._update_playback_mode_controls()
        self._recommendation_generation += 1
        if self._recommendation_task is not None:
            self._recommendation_task.cancel()
        self._recommendation_task = None
        self._cancel_radio_recommendations()
        self._radio_session_seen_track_ids = {track.id}
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

        tracks_needed = min(
            RECOMMENDATION_QUEUE_SIZE - remaining_count,
            RADIO_RECOMMENDATION_BATCH_SIZE,
        )
        if tracks_needed <= 0 or queue.current_track_id is None:
            return

        anchor_track_id = self._radio_anchor_track_id or queue.current_track_id
        previous_track_id = queue.current_track_id
        occupied_ids = {
            queue.current_track_id,
            *queue.remaining_track_ids,
            *queue.queued_track_ids,
            *self._radio_session_seen_track_ids,
        }
        self._radio_recommendation_generation += 1
        generation = self._radio_recommendation_generation
        task = RecommendationTask(
            lambda: (),
            generation,
            batch_size=RADIO_RECOMMENDATION_BATCH_SIZE,
            cancellable_fetcher=lambda should_cancel: self._get_radio_recommendations(
                anchor_track_id,
                previous_track_id=previous_track_id,
                limit=tracks_needed,
                excluded_track_ids=occupied_ids,
                should_cancel=should_cancel,
            ),
        )
        task.signals.batch_ready.connect(
            lambda task_generation, batch, anchor=anchor_track_id, previous=previous_track_id: (
                self._handle_radio_recommendation_batch(
                    task_generation,
                    anchor,
                    previous,
                    batch,
                )
            )
        )
        task.signals.finished.connect(self._finish_radio_recommendation_loading)
        task.signals.error_occurred.connect(self._handle_radio_recommendation_error)
        self._radio_recommendation_task = task
        self._radio_recommendation_inflight = True
        self._radio_recommendation_pool.start(task)

    def _handle_radio_recommendation_batch(
        self,
        generation: int,
        anchor_track_id: str,
        previous_track_id: str | None,
        batch: object,
    ) -> None:
        if generation != self._radio_recommendation_generation:
            return

        queue = self.playback_queue_service.queue
        if (
            queue is None
            or queue.mode != QueueMode.RECOMMENDATIONS
            or queue.current_track_id != previous_track_id
            or self._radio_anchor_track_id != anchor_track_id
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
            if (
                track.id in occupied_ids
                or track.id in self._radio_session_seen_track_ids
            ):
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
            self._radio_session_seen_track_ids.update(additions)
            if self._record_recommendation_impressions(
                shown_recommendations,
                session_id=self._radio_impression_session_id,
                position_offset=self._radio_impression_position,
                playlist_id=self._radio_impression_playlist_id,
            ):
                self._radio_impression_position += len(shown_recommendations)
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
        self.statusBar().showMessage(f"Recommendations unavailable: {message}")

    def _cancel_radio_recommendations(self) -> None:
        self._radio_recommendation_generation += 1
        if self._radio_recommendation_task is not None:
            self._radio_recommendation_task.cancel()
        self._radio_recommendation_task = None
        self._radio_recommendation_inflight = False
        self._radio_session_seen_track_ids.clear()
        self._radio_wait_attempts = 0
        self._radio_wait_seed_track_id = None

    def _get_radio_recommendations(
        self,
        anchor_track_id: str,
        *,
        previous_track_id: str | None = None,
        limit: int,
        excluded_track_ids: set[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[Recommendation]:
        """Combine anchored radio with fallback and arrange the sequence."""

        excluded_ids = set(excluded_track_ids or ())
        _, radio_skipped_ids = suppressed_track_ids(
            self.user_id,
            list(self.store.list_interactions(user_id=self.user_id)),
            now=datetime.now(UTC),
            context=f"track_radio:{anchor_track_id.casefold()}",
        )
        excluded_ids.update(radio_skipped_ids)
        recommendations = self._get_track_radio_recommendations(
            anchor_track_id,
            limit=limit,
            excluded_track_ids=excluded_ids,
            should_cancel=should_cancel,
        )

        if should_cancel is not None and should_cancel():
            raise RuntimeError("Recommendation calculation cancelled")

        if len(recommendations) < limit:
            try:
                fallback = self.recommendation_service.get_recommendations(
                    user_id=self.user_id,
                    limit=limit,
                    context=RecommendationContext(),
                    should_cancel=should_cancel,
                    playlist_id=self._radio_impression_playlist_id,
                )
            except (RuntimeError, ValueError):
                fallback = []

            seen_ids = {recommendation.track.id for recommendation in recommendations}
            for recommendation in fallback:
                if should_cancel is not None and should_cancel():
                    raise RuntimeError("Recommendation calculation cancelled")
                if (
                    recommendation.track.id in seen_ids
                    or recommendation.track.id in excluded_ids
                ):
                    continue
                seen_ids.add(recommendation.track.id)
                recommendations.append(recommendation)
                if len(recommendations) == limit:
                    break

        previous_track = (
            self.store.get_track(previous_track_id)
            if previous_track_id is not None
            else None
        )
        return build_radio_sequence(
            recommendations,
            limit=limit,
            initial_artist=(
                previous_track.artist if previous_track is not None else None
            ),
        )

    def _get_track_radio_recommendations(
        self,
        seed_track_id: str,
        *,
        limit: int,
        excluded_track_ids: set[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[Recommendation]:
        try:
            return list(
                self.recommendation_service.get_recommendations(
                    user_id=self.user_id,
                    limit=limit,
                    context=RecommendationContext.track_radio(seed_track_id),
                    excluded_track_ids=excluded_track_ids,
                    should_cancel=should_cancel,
                    playlist_id=self._radio_impression_playlist_id,
                )
            )
        except RuntimeError:
            if should_cancel is not None and should_cancel():
                raise
            return []
        except ValueError:
            return []

    def _replenish_mood_session(self) -> None:
        if self.session_mood_name is None and self.session_genre_name is None:
            return

        queue = self.playback_queue_service.queue
        if queue is None or queue.mode != QueueMode.SESSION:
            return

        upcoming_count = len(self.playback_queue_service.upcoming_track_ids())
        if (
            upcoming_count > MOOD_SESSION_REFILL_THRESHOLD
            or self._mood_refill_inflight
            or self._mood_refill_exhausted
        ):
            return

        if self.session_mood_name == MY_WAVE_SESSION_NAME:
            context = RecommendationContext.my_wave()
        elif self.session_genre_name is not None:
            context = RecommendationContext.genre(self.session_genre_name)
        else:
            target_mood = MOOD_PRESETS[self.session_mood_name]
            context = RecommendationContext.mood(
                target_mood,
                mood_name=self.session_mood_name,
            )
        excluded_track_ids = {
            queue.current_track_id,
            *self.playback_queue_service.upcoming_track_ids(),
            *self._mood_session_seen_track_ids,
        }
        self._mood_refill_generation += 1
        generation = self._mood_refill_generation
        self._mood_refill_added_count = 0
        task = RecommendationTask(
            lambda: (),
            generation,
            batch_size=MOOD_SESSION_REFILL_SIZE,
            cancellable_fetcher=lambda should_cancel: (
                self.recommendation_service.get_recommendations(
                    user_id=self.user_id,
                    limit=MOOD_SESSION_REFILL_SIZE,
                    context=context,
                    should_cancel=should_cancel,
                    excluded_track_ids=excluded_track_ids,
                    playlist_id=self._mood_session_playlist_id,
                )
            ),
        )
        task.signals.batch_ready.connect(self._handle_mood_refill_batch)
        task.signals.finished.connect(self._finish_mood_refill)
        task.signals.error_occurred.connect(self._handle_mood_refill_error)
        self._mood_refill_task = task
        self._mood_refill_inflight = True
        self._mood_recommendation_pool.start(task)

    def _handle_mood_refill_batch(
        self,
        generation: int,
        batch: object,
    ) -> None:
        if generation != self._mood_refill_generation:
            return

        queue = self.playback_queue_service.queue
        if queue is None or queue.mode != QueueMode.SESSION:
            return

        existing_ids = {
            queue.current_track_id,
            *self.playback_queue_service.upcoming_track_ids(),
            *self._mood_session_seen_track_ids,
        }

        additions: list[str] = []
        shown_recommendations: list[Recommendation] = []
        for recommendation in batch:
            if not isinstance(recommendation, Recommendation):
                continue
            track = recommendation.track
            if track.id in existing_ids:
                continue
            if not track.local_path or not Path(track.local_path).exists():
                continue

            additions.append(track.id)
            existing_ids.add(track.id)
            shown_recommendations.append(recommendation)

        if additions:
            self.playback_queue_service.append_remaining(additions)
            self._mood_session_seen_track_ids.update(additions)
            # Paint the new upcoming tracks before synchronous impression
            # persistence so the queue reflects the refill immediately.
            self._load_queue()

        if self._record_recommendation_impressions(
            shown_recommendations,
            session_id=self._mood_session_impression_session_id,
            position_offset=self._mood_session_impression_position,
            playlist_id=self._mood_session_playlist_id,
        ):
            self._mood_session_impression_position += len(shown_recommendations)
        if shown_recommendations:
            self._mood_refill_added_count += len(shown_recommendations)
            self._mood_refill_exhausted = False

    def _finish_mood_refill(self, generation: int) -> None:
        if generation != self._mood_refill_generation:
            return

        self._mood_refill_task = None
        self._mood_refill_inflight = False
        self._mood_refill_exhausted = self._mood_refill_added_count == 0
        if self._mood_wait_track_id is not None and self._mood_refill_exhausted:
            self._mood_wait_attempts = 0
            self._mood_wait_track_id = None
            self.statusBar().showMessage("No more tracks available for this Wave")

    def _handle_mood_refill_error(
        self,
        generation: int,
        message: str,
    ) -> None:
        if generation != self._mood_refill_generation:
            return

        self._mood_refill_task = None
        self._mood_refill_inflight = False
        self._mood_refill_exhausted = True
        self._mood_wait_attempts = 0
        self._mood_wait_track_id = None
        if message:
            self.statusBar().showMessage(f"Mood session refill unavailable: {message}")

    def _cancel_mood_refill(self) -> None:
        self._mood_refill_generation += 1
        if self._mood_refill_task is not None:
            self._mood_refill_task.cancel()
        self._mood_refill_task = None
        self._mood_refill_inflight = False
        self._mood_refill_added_count = 0
        self._mood_refill_exhausted = False
        self._mood_wait_attempts = 0
        self._mood_wait_track_id = None

    def _cancel_mood_session(self) -> None:
        self._mood_session_generation += 1
        if self._mood_session_task is not None:
            self._mood_session_task.cancel()
        self._mood_session_task = None
        self._mood_session_pending_name = None
        self._mood_session_pending_mode = None
        self._mood_session_result_generation = None
        self._mood_session_seen_track_ids.clear()
        self._cancel_mood_refill()

    def _load_queue(self) -> None:
        queue = self.playback_queue_service.queue
        self._update_queue_source_label()
        all_track_ids = (
            tuple(self.playback_queue_service.upcoming_track_ids())
            if queue is not None
            else ()
        )
        track_ids = all_track_ids[:QUEUE_VISIBLE_TRACK_LIMIT]

        self._queue_render_generation += 1
        generation = self._queue_render_generation
        self._queue_render_track_ids = track_ids
        self._queue_render_index = 0

        if hasattr(self, "queue_count_label"):
            if len(all_track_ids) > len(track_ids):
                self.queue_count_label.setText(
                    f"Next {len(track_ids)} of {len(all_track_ids)}"
                )
            else:
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
        # Queue entries are drawn from the already loaded catalog.  Falling
        # back to the store keeps stale queues usable, but the normal path no
        # longer opens one database session per visible queue row.
        tracks_by_id = {track.id: track for track in self._library_tracks}
        tracks = [
            track
            for track_id in track_ids[start:end]
            if (track := tracks_by_id.get(track_id)) is not None
            or (track := self.store.get_track(track_id)) is not None
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
                    show_cover=False,
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

        track_id = self.track_table.track_id_at(index.row())

        if not isinstance(track_id, str):
            return

        menu = self._build_track_context_menu(track_id)
        menu.exec(self.track_table.viewport().mapToGlobal(position))

    def _show_current_track_context_menu(self, position: object) -> None:
        if self.current_track_id is None:
            return

        menu = self._build_track_context_menu(self.current_track_id)
        menu.exec(self._player_bar.mapToGlobal(position))

    def _show_current_track_action_menu(self) -> None:
        """Open track actions when the playing title is clicked."""

        if self.current_track_id is None:
            return

        menu = self._build_track_context_menu(self.current_track_id)
        anchor = QPoint(
            0,
            self.player_title_label.height(),
        )
        menu.exec(self.player_title_label.mapToGlobal(anchor))

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
        radio_action.setToolTip("Play this track and build a stream of similar tracks")
        radio_action.triggered.connect(
            lambda checked=False, value=track_id: self._start_track_radio_from_context(
                value
            )
        )
        playlists_menu = menu.addMenu("Add to playlist")

        for playlist in self.playlist_management_service.list_playlists():
            playlist_action = playlists_menu.addAction(playlist.name)
            playlist_action.triggered.connect(
                lambda checked=False, playlist_id=playlist.id, selected_track_id=track_id: (
                    self._add_track_to_playlist(
                        playlist_id,
                        selected_track_id,
                    )
                )
            )
        replacement_action = menu.addAction("Find replacement")
        replacement_action.setToolTip(
            "Search for another file using this track's artist and title"
        )
        replacement_action.triggered.connect(
            lambda checked=False, value=track_id: self._open_track_replacement_search(
                value
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
        track = self.store.get_track(track_id)
        if track is None:
            return
        if not self._is_playable_track(track):
            self.statusBar().showMessage(
                f"Not downloaded: {track.artist} — {track.title}"
            )
            return

        # Playing a track directly always starts the regular library/playlist
        # queue.  Track radio remains available only through its explicit
        # action, so a previous radio session cannot hijack normal playback.
        if self._track_radio_enabled:
            self._track_radio_enabled = False
            self._update_playback_mode_controls()

        self._start_library_queue(
            track_id,
            preserve_manual_queue=False,
        )

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

        if not self._is_playable_track(track):
            self.statusBar().showMessage(
                f"Not downloaded, not added: {track.artist} — {track.title}"
            )
            return

        self.playback_queue_service.enqueue(track.id)
        self._load_queue()
        self.statusBar().showMessage(f"Added to queue: {track.artist} — {track.title}")

    def _enqueue_playlist(self, playlist_id: str) -> None:
        playlist = self._resolve_playlist(playlist_id)
        if playlist is None:
            return

        tracks = self.playlist_management_service.get_playlist_tracks(playlist.id)
        if not tracks:
            QMessageBox.information(
                self,
                "Playlist is empty",
                "Add at least one track before adding it to the queue.",
            )
            return

        playable_tracks = [
            track for track in tracks if self._is_playable_track(track)
        ]
        skipped_count = len(tracks) - len(playable_tracks)
        if not playable_tracks:
            QMessageBox.information(
                self,
                "No downloaded tracks",
                "This playlist has no downloaded audio files.",
            )
            return

        for track in playable_tracks:
            self.playback_queue_service.enqueue(track.id)

        self._load_queue()
        suffix = f"; skipped {skipped_count} unavailable" if skipped_count else ""
        self.statusBar().showMessage(
            f"Added playlist to queue: {playlist.name}{suffix}"
        )

    def _merge_playlist(self, target_playlist_id: str) -> None:
        target_playlist = self._resolve_playlist(target_playlist_id)
        if target_playlist is None:
            return

        source_playlists = [
            playlist
            for playlist in self.playlist_management_service.list_playlists()
            if playlist.id != target_playlist.id
        ]
        if not source_playlists:
            QMessageBox.information(
                self,
                "Merge playlists",
                "Create another playlist before merging.",
            )
            return

        source_options = [
            f"{index + 1}. {playlist.name}"
            for index, playlist in enumerate(source_playlists)
        ]
        selected_option, accepted = QInputDialog.getItem(
            self,
            "Merge playlists",
            f"Choose a playlist to merge into “{target_playlist.name}”:",
            source_options,
            0,
            False,
        )
        if not accepted:
            return

        try:
            source_index = source_options.index(selected_option)
        except ValueError:
            return
        source_playlist = source_playlists[source_index]

        target_tracks = self.playlist_management_service.get_playlist_tracks(
            target_playlist.id
        )
        source_tracks = self.playlist_management_service.get_playlist_tracks(
            source_playlist.id
        )
        if not source_tracks:
            QMessageBox.information(
                self,
                "Merge playlists",
                f"Playlist “{source_playlist.name}” is empty.",
            )
            return

        seen_track_ids = {track.id for track in target_tracks}
        duplicate_count = 0
        for track in source_tracks:
            if track.id in seen_track_ids:
                duplicate_count += 1
            else:
                seen_track_ids.add(track.id)

        include_duplicates = False
        if duplicate_count:
            choice_dialog = PlaylistMergeChoiceDialog(
                target_name=target_playlist.name,
                source_name=source_playlist.name,
                source_count=len(source_tracks),
                duplicate_count=duplicate_count,
                parent=self,
            )
            if choice_dialog.exec() != QDialog.DialogCode.Accepted:
                return
            include_duplicates = (
                choice_dialog.choice == PlaylistMergeChoiceDialog.MERGE_ALL
            )

        try:
            merged_tracks = self.playlist_management_service.merge_playlists(
                target_playlist.id,
                source_playlist.id,
                include_duplicates=include_duplicates,
            )
        except ValueError as error:
            QMessageBox.warning(self, "Merge failed", str(error))
            return

        added_count = len(merged_tracks) - len(target_tracks)
        skipped_count = len(source_tracks) - added_count
        self.selected_playlist_id = target_playlist.id
        self._load_playlists()

        message = (
            f"Merged “{source_playlist.name}” into "
            f"“{target_playlist.name}”: {added_count} track(s) added."
        )
        if skipped_count:
            message += f" {skipped_count} duplicate(s) skipped."
        self.statusBar().showMessage(message)

    def _add_tracks_view_title(self) -> str:
        playlist_id = self._add_tracks_target_playlist_id
        playlist = (
            self.store.get_playlist(playlist_id) if playlist_id is not None else None
        )
        if playlist is None:
            return "Music library"
        return f'Add tracks to "{playlist.name}"'

    def _update_add_tracks_controls(self) -> None:
        if not hasattr(self, "add_tracks_button"):
            return

        in_playlist = self.selected_playlist_id is not None
        missing_tracks = (
            self._tracks_needing_analysis() if not self._add_tracks_mode else []
        )
        self.analyze_playlist_button.setVisible(
            not self._add_tracks_mode and bool(missing_tracks)
        )
        self.analyze_playlist_button.setText(
            (
                f"Analyze missing ({len(missing_tracks)})"
                if missing_tracks
                else "Analyze missing"
            )
        )
        self.analyze_playlist_button.setEnabled(
            not self._add_tracks_mode and bool(missing_tracks)
        )
        self.add_tracks_button.setVisible(in_playlist and not self._add_tracks_mode)
        self.add_selected_tracks_button.setVisible(self._add_tracks_mode)
        self.add_selected_tracks_button.setEnabled(
            self._add_tracks_mode and bool(self._add_tracks_selected_ids)
        )
        self.add_selected_tracks_button.setText(
            (
                f"Add selected ({len(self._add_tracks_selected_ids)})"
                if self._add_tracks_selected_ids
                else "Add selected"
            )
        )
        self.cancel_add_tracks_button.setVisible(self._add_tracks_mode)

    def _tracks_needing_analysis(
        self,
        playlist_id: str | None = None,
    ) -> list[Track]:
        """Return each unanalyzed track in the current scope once."""

        target_playlist_id = (
            playlist_id if playlist_id is not None else self.selected_playlist_id
        )
        if target_playlist_id is None:
            tracks_in_scope = list(self.store.list_tracks())
        else:
            try:
                tracks_in_scope = self.playlist_management_service.get_playlist_tracks(
                    target_playlist_id
                )
            except ValueError:
                return []

        tracks: list[Track] = []
        seen_track_ids: set[str] = set()
        for track in tracks_in_scope:
            if track.id in seen_track_ids:
                continue
            seen_track_ids.add(track.id)
            if self._track_has_analysis(track):
                continue
            if track.id in self._analysis_pending_track_ids:
                continue
            if not track.local_path or not Path(track.local_path).is_file():
                continue
            tracks.append(track)
        return tracks

    def _analyze_missing_tracks(
        self,
        playlist_id: str | None = None,
    ) -> None:
        target_playlist_id = (
            playlist_id if playlist_id is not None else self.selected_playlist_id
        )
        tracks = self._tracks_needing_analysis(target_playlist_id)
        if not tracks:
            self.statusBar().showMessage(
                (
                    "This playlist has no unanalyzed local tracks."
                    if target_playlist_id is not None
                    else "The library has no unanalyzed local tracks."
                )
            )
            return

        for track in tracks:
            self._enqueue_genre_analysis(track)

        self._update_add_tracks_controls()
        self.statusBar().showMessage(
            (
                "Playlist analysis queued: "
                if target_playlist_id is not None
                else "Library analysis queued: "
            )
            + f"{len(tracks)} track(s)"
        )

    def _set_add_track_selected(
        self,
        track_id: str,
        selected: bool,
    ) -> None:
        if not self._add_tracks_mode:
            return
        if selected:
            self._add_tracks_selected_ids.add(track_id)
        else:
            self._add_tracks_selected_ids.discard(track_id)
        self.track_table.set_selected_ids(self._add_tracks_selected_ids)
        self._update_add_tracks_controls()
        for row_index, track in enumerate(self._visible_tracks):
            if track.id == track_id:
                self.track_table.refresh_row(row_index)

    def _begin_add_tracks_mode(self) -> None:
        playlist_id = self.selected_playlist_id
        if playlist_id is None:
            return

        playlist = self.store.get_playlist(playlist_id)
        if playlist is None:
            return

        self._add_tracks_mode = True
        self._add_tracks_target_playlist_id = playlist.id
        self._add_tracks_selected_ids.clear()
        self._reset_library_sort()
        self.selected_playlist_id = None
        self.playlist_list.blockSignals(True)
        self.playlist_list.clearSelection()
        self.playlist_list.blockSignals(False)
        self._set_visible_tracks(
            self._library_tracks,
            title=self._add_tracks_view_title(),
        )
        self._update_playlist_carousel_selection()
        self._update_add_tracks_controls()
        self.statusBar().showMessage(
            f"Choose tracks to add to playlist: {playlist.name}"
        )

    def _finish_add_tracks_mode(self) -> None:
        playlist_id = self._add_tracks_target_playlist_id
        if playlist_id is None:
            return

        playlist = self.store.get_playlist(playlist_id)
        if playlist is None:
            self._cancel_add_tracks_mode()
            return

        selected_ids = set(self._add_tracks_selected_ids)
        existing_ids = {
            entry.track_id for entry in self.store.list_playlist_entries(playlist.id)
        }
        ordered_ids = [
            track.id for track in self._library_tracks if track.id in selected_ids
        ]
        duplicate_count = len(selected_ids & existing_ids)
        add_duplicates = False
        if duplicate_count:
            choice_dialog = PlaylistDuplicateChoiceDialog(
                playlist_name=playlist.name,
                selected_count=len(selected_ids),
                duplicate_count=duplicate_count,
                parent=self,
            )
            if choice_dialog.exec() != QDialog.DialogCode.Accepted:
                return
            add_duplicates = (
                choice_dialog.choice == PlaylistDuplicateChoiceDialog.ADD_ALL
            )

        errors: list[str] = []
        added_count = 0
        skipped_count = 0
        for track_id in ordered_ids:
            if not add_duplicates and track_id in existing_ids:
                skipped_count += 1
                continue
            try:
                self.playlist_management_service.add_track(
                    playlist.id,
                    track_id,
                )
            except ValueError as error:
                errors.append(str(error))
            else:
                existing_ids.add(track_id)
                added_count += 1

        self._clear_add_tracks_mode_state()
        self.selected_playlist_id = playlist.id
        self._load_playlists()
        message = f"Added {added_count} track(s) to {playlist.name}"
        if skipped_count:
            message += f"; skipped {skipped_count} already in playlist"
        elif add_duplicates and duplicate_count:
            message += f"; included {duplicate_count} duplicate(s)"
        self.statusBar().showMessage(message)
        if errors:
            QMessageBox.warning(
                self,
                "Some tracks were not added",
                "\n".join(errors),
            )

    def _cancel_add_tracks_mode(self) -> None:
        playlist_id = self._add_tracks_target_playlist_id
        self._clear_add_tracks_mode_state()

        if playlist_id is not None and self.store.get_playlist(playlist_id):
            self.selected_playlist_id = playlist_id
            self._load_playlists()
            return

        self.selected_playlist_id = None
        self._load_playlists()
        self._show_main_library()

    def _clear_add_tracks_mode_state(self) -> None:
        self._add_tracks_mode = False
        self._add_tracks_target_playlist_id = None
        self._add_tracks_selected_ids.clear()

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
            playlist.id == selected_playlist_id for playlist in playlists
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
        minimum = scroll_bar.minimum()
        maximum = scroll_bar.maximum()
        if maximum - minimum <= SCROLL_EDGE_TOLERANCE:
            scroll_bar.setValue(minimum)
            return
        step = max(1, scroll_bar.pageStep() // 2)
        current_value = scroll_bar.value()
        if direction < 0 and current_value <= minimum + SCROLL_EDGE_TOLERANCE:
            scroll_bar.setValue(minimum)
            return
        if direction > 0 and current_value >= maximum - SCROLL_EDGE_TOLERANCE:
            scroll_bar.setValue(maximum)
            return
        target_value = max(
            minimum,
            min(maximum, current_value + direction * step),
        )
        if direction < 0 and target_value <= minimum + SCROLL_EDGE_TOLERANCE:
            target_value = minimum
        elif direction > 0 and target_value >= maximum - SCROLL_EDGE_TOLERANCE:
            target_value = maximum
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
            self.playlist_scroll_left_button.setVisible(self._playlist_page_index > 0)
            self.playlist_scroll_left_button.setEnabled(self._playlist_page_index > 0)
            self.playlist_scroll_right_button.setVisible(
                self._playlist_page_index < self._playlist_page_count - 1
            )
            self.playlist_scroll_right_button.setEnabled(
                self._playlist_page_index < self._playlist_page_count - 1
            )
            return

        scroll_bar = self.playlist_scroll.horizontalScrollBar()
        minimum = scroll_bar.minimum()
        maximum = scroll_bar.maximum()
        value = scroll_bar.value()
        scroll_range = maximum - minimum
        if scroll_range <= SCROLL_EDGE_TOLERANCE:
            if value != minimum:
                scroll_bar.setValue(minimum)
            has_overflow = False
            at_start = True
            at_end = True
        else:
            at_start = value <= minimum + SCROLL_EDGE_TOLERANCE
            at_end = value >= maximum - SCROLL_EDGE_TOLERANCE
            if at_start and value != minimum:
                scroll_bar.setValue(minimum)
                value = minimum
            elif at_end and value != maximum:
                scroll_bar.setValue(maximum)
                value = maximum
            has_overflow = True

        self.playlist_scroll_left_button.setVisible(has_overflow and not at_start)
        self.playlist_scroll_left_button.setEnabled(has_overflow and not at_start)
        self.playlist_scroll_right_button.setVisible(has_overflow and not at_end)
        self.playlist_scroll_right_button.setEnabled(has_overflow and not at_end)

    def _scroll_playlists_to_end(self) -> None:
        if self._playlist_page_count > 1:
            self._set_playlist_page(self._playlist_page_count - 1)
            return

        scroll_bar = self.playlist_scroll.horizontalScrollBar()
        current_value = scroll_bar.value()
        target_value = scroll_bar.maximum()
        if target_value - scroll_bar.minimum() <= SCROLL_EDGE_TOLERANCE:
            scroll_bar.setValue(scroll_bar.minimum())
            return
        if target_value - current_value <= SCROLL_EDGE_TOLERANCE:
            scroll_bar.setValue(target_value)
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
        self._playlist_page_specs = self._build_playlist_page_specs(len(playlists))
        self._playlist_page_count = len(self._playlist_page_specs)
        self._playlist_page_index = min(
            self._playlist_page_index,
            self._playlist_page_count - 1,
        )
        (
            page_start,
            page_end,
            show_main_library,
            show_wave,
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

        if show_wave:
            wave_card = WavePlaylistCard(
                tuple(MOOD_PRESETS),
                popular_user_genres(
                    list(self.store.list_tracks()),
                    list(self.store.list_interactions()),
                    self.user_id,
                    limit=len(MOOD_PRESETS),
                ),
            )
            wave_card.mood_selected.connect(self._start_mood_session_from_card)
            wave_card.genre_selected.connect(self._start_genre_session_from_card)
            wave_card.my_wave_selected.connect(self._start_my_wave_session)
            wave_card.set_selected(
                self.selected_mood_name is not None
                or self.selected_genre_name is not None
                or self.session_mood_name is not None
                or self.session_genre_name is not None
            )
            self.playlist_carousel_layout.addWidget(wave_card)

        if show_create:
            create_card = CreatePlaylistCard()
            create_card.activated.connect(self._create_playlist)
            self.playlist_carousel_layout.addWidget(create_card)

        for playlist in visible_playlists:
            playlist = self._ensure_playlist_cover(playlist)
            card = PlaylistCard(
                playlist_id=playlist.id,
                name=playlist.name,
                cover_path=playlist.cover_path,
            )
            card.set_selected(playlist.id == self.selected_playlist_id)
            card.activated.connect(self._select_playlist_from_carousel)
            card.context_requested.connect(self._show_playlist_context_menu)
            self.playlist_carousel_layout.addWidget(card)

        self.playlist_carousel_layout.addStretch(1)
        self.playlist_scroll_left_button.setVisible(show_left)
        self.playlist_scroll_right_button.setVisible(show_right)
        self._position_playlist_navigation()
        QTimer.singleShot(0, self._update_playlist_scroll_buttons)
        QTimer.singleShot(0, self._position_playlist_navigation)

    def _update_playlist_carousel_selection(self) -> None:
        """Update visible cards without rebuilding the carousel widgets."""

        if not hasattr(self, "playlist_carousel_layout"):
            return

        for index in range(self.playlist_carousel_layout.count()):
            widget = self.playlist_carousel_layout.itemAt(index).widget()
            if isinstance(widget, MainLibraryCard):
                widget.set_selected(self.selected_playlist_id is None)
            elif isinstance(widget, WavePlaylistCard):
                widget.set_selected(
                    self.selected_mood_name is not None
                    or self.selected_genre_name is not None
                    or self.session_mood_name is not None
                    or self.session_genre_name is not None
                )
            elif isinstance(widget, PlaylistCard):
                widget.set_selected(widget.playlist_id == self.selected_playlist_id)

    def _ensure_playlist_cover(self, playlist: Playlist) -> Playlist:
        """Create and persist fallback artwork the first time it is shown."""

        try:
            return self.playlist_management_service.ensure_generated_cover(
                playlist.id,
                generate_playlist_artwork_svg,
            )
        except (OSError, ValueError):
            # Keep the visual fallback available even if the cover directory
            # cannot be written.  A later refresh can try persistence again.
            return playlist

    @staticmethod
    def _build_playlist_page_specs(
        playlist_count: int,
    ) -> list[tuple[int, int, bool, bool, bool]]:
        """Return playlist ranges whose rendered card count is at most seven.

        Main library, Wave, and Create playlist occupy the first three slots.
        Later pages contain only user playlists, leaving the utility cards
        fixed at the beginning while ensuring every page stays within the
        seven-card limit.
        """

        utility_count = 3  # Main library + Wave + Create playlist
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

        if self._add_tracks_mode:
            self._clear_add_tracks_mode_state()

        for index in range(self.playlist_list.count()):
            item = self.playlist_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == playlist_id:
                if (
                    self.selected_playlist_id == playlist_id
                    and self.playlist_list.currentRow() == index
                ):
                    self._load_selected_playlist_tracks()
                    self._update_playlist_carousel_selection()
                    return
                self.playlist_list.setCurrentItem(item)
                return

        # A card can outlive a library refresh by one event loop turn.  Do not
        # silently swallow its click if the playlist is still in the store.
        if self.store.get_playlist(playlist_id) is not None:
            if self.selected_playlist_id != playlist_id:
                self._reset_library_sort()
            self.selected_playlist_id = playlist_id
            self._load_selected_playlist_tracks()
            self._update_playlist_carousel_selection()

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
        smart_shuffle_action = menu.addAction("Smart shuffle playlist")
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
        menu.addAction(
            "Analyze missing tracks",
            lambda: self._analyze_missing_tracks(playlist_id),
        )
        menu.addAction(
            "Merge another playlist into this one",
            lambda: self._merge_playlist(playlist_id),
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
        menu.addAction(
            "Regenerate artwork",
            lambda: self._regenerate_playlist_cover(playlist_id),
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
        if self._add_tracks_mode:
            self._clear_add_tracks_mode_state()

        selected_items = self.playlist_list.selectedItems()

        if not selected_items:
            self._show_main_library()
            return

        playlist_id = selected_items[0].data(Qt.ItemDataRole.UserRole)

        if not isinstance(playlist_id, str):
            return

        if self.selected_playlist_id != playlist_id:
            self._reset_library_sort()
        self.selected_playlist_id = playlist_id
        self._load_selected_playlist_tracks()
        self._update_playlist_carousel_selection()

    def _load_selected_playlist_tracks(self) -> None:
        self.playlist_track_list.clear()

        if self.selected_playlist_id is None:
            return

        playlist = self.store.get_playlist(self.selected_playlist_id)
        if playlist is None:
            self._show_main_library()
            return

        # The library catalog is already in memory.  Reuse it for playlist
        # membership resolution instead of opening one database session per
        # track (the old service path was an N+1 query on every switch).
        tracks_by_id = {track.id: track for track in self._library_tracks}
        tracks: list[Track] = []
        for entry in self.store.list_playlist_entries(self.selected_playlist_id):
            track = tracks_by_id.get(entry.track_id)
            if track is None:
                # Keep stale/partially refreshed libraries usable without
                # making the normal path pay for another query per row.
                track = self.store.get_track(entry.track_id)
            if track is not None:
                tracks.append(track)

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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
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
        track_id = self.track_table.track_id_at(row)
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
        preserve_manual_queue: bool = True,
    ) -> None:
        playlist = self._resolve_playlist(playlist_id)

        if playlist is None:
            return

        self._cancel_mood_session()
        tracks = self.playlist_management_service.get_playlist_tracks(playlist.id)
        # A playlist keeps its saved order until the user explicitly chooses
        # another library sort; playback should follow the same visible order
        # as the table when that sort is active.
        tracks = self._sort_tracks(tracks)
        tracks = [
            track for track in tracks if self._is_playable_track(track)
        ]

        if not tracks:
            QMessageBox.information(
                self,
                "No downloaded tracks",
                "This playlist has no downloaded audio files.",
            )
            return

        _, skipped_track_ids = suppressed_track_ids(
            self.user_id,
            list(self.store.list_interactions(user_id=self.user_id)),
            now=datetime.now(UTC),
            context=f"playlist:{playlist.id.casefold()}",
        )
        if skipped_track_ids:
            filtered_tracks = [
                track
                for track in tracks
                if track.id not in skipped_track_ids
                or track.id == start_track_id
            ]
            if filtered_tracks:
                tracks = filtered_tracks

        manual_track_ids = (
            self._manual_queue_snapshot()
            if preserve_manual_queue
            else ()
        )
        track_ids = [track.id for track in tracks]

        if start_track_id is not None and start_track_id in track_ids:
            start_index = track_ids.index(start_track_id)
            if shuffle or smart:
                track_ids = [
                    start_track_id,
                    *(track_id for track_id in track_ids if track_id != start_track_id),
                ]
            else:
                track_ids = track_ids[start_index:]

        if smart:
            library_tracks = list(self.store.list_tracks())
            # TrackSimilarityService answers seed queries with a cached NumPy
            # search.  Building TrackSimilarityIndex here would calculate and
            # sort every library pair on each smart-shuffle start.
            similarity_provider = self.recommendation_service.track_radio
            if similarity_provider is None:
                from app.recommenders.similarity import TrackSimilarityIndex

                similarity_provider = TrackSimilarityIndex(library_tracks)
            track_ids = list(
                SmartShuffleBuilder(
                    library_tracks,
                    similarity_provider,
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
                else (QueueMode.SHUFFLE if shuffle else QueueMode.NORMAL)
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

    def _active_playlist_context_id(self) -> str | None:
        """Return the explicit playlist context active at recommendation time."""

        if (
            self.selected_playlist_id is not None
            and self.store.get_playlist(self.selected_playlist_id) is not None
        ):
            return self.selected_playlist_id

        queue = self.playback_queue_service.queue
        playlist_id = queue.source_playlist_id if queue is not None else None
        if (
            playlist_id is not None
            and self.store.get_playlist(playlist_id) is not None
        ):
            return playlist_id
        return None

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
        previous_row = self._selected_track_row
        row = self.track_table.currentRow()
        track = self._track_at_table_row(row)

        if track is None:
            self.selected_track_id = None
            self._selected_track_row = -1
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.queue_selected_button.setEnabled(False)
            self.analyze_genres_button.setEnabled(False)
            self._refresh_track_row_visuals((previous_row,))
            self._load_recommendations()
            return

        self.selected_track_id = track.id
        self._selected_track_row = row
        self._refresh_track_row_visuals((previous_row, self._selected_track_row))
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

        selected_track = self.store.get_track(self.selected_track_id)
        if selected_track is not None:
            self.statusBar().showMessage(
                f"Selected: {selected_track.artist} — {selected_track.title}"
            )
        self._load_recommendations()

    def _play_track_from_table_row(self, row_index: int) -> None:
        """Play a library track when its row is double-clicked."""

        if row_index < 0 or row_index >= self.track_table.rowCount():
            return

        track = self._track_at_table_row(row_index)
        if track is None:
            return

        self.track_table.setCurrentIndex(self.track_table.model().index(row_index, 0))
        self._play_track_now(track.id)

    def _enqueue_track_from_table_row(self, row_index: int) -> None:
        track = self._track_at_table_row(row_index)
        if track is not None:
            self._enqueue_track(track.id)

    def _remove_track_from_table_row(self, row_index: int) -> None:
        track = self._track_at_table_row(row_index)
        if track is not None:
            self._remove_playlist_track(track.id)

    def _handle_track_row_clicked(self, row_index: int) -> None:
        """Toggle track selection when the add-to-playlist mode is active."""

        if not self._add_tracks_mode:
            return
        if row_index < 0 or row_index >= self.track_table.rowCount():
            return

        track = self._track_at_table_row(row_index)
        if track is None:
            return

        self._set_add_track_selected(
            track.id,
            track.id not in self._add_tracks_selected_ids,
        )

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
        normalized_duration_ms = max(duration_ms, 0)
        # QMediaPlayer can briefly report zero while a new local source is
        # being opened.  Keep the duration already known from the track
        # metadata instead of making the progress bar disappear during that
        # transition.
        if normalized_duration_ms == 0 and self._player_duration_ms > 0:
            return

        self._player_duration_ms = normalized_duration_ms
        self.player_duration_label.setText(
            self._format_duration(self._player_duration_ms)
        )
        self._apply_pending_restore_position()

    def _apply_pending_restore_position(self) -> None:
        if self._pending_restore_position_ms is None or self._player_duration_ms <= 0:
            return

        position_ms = min(
            self._pending_restore_position_ms,
            self._player_duration_ms,
        )
        self.media_player.setPosition(position_ms)
        self._current_track_last_position_ms = position_ms
        self._pending_restore_position_ms = None

    def _handle_player_position_changed(self, position_ms: int) -> None:
        self.player_position_label.setText(self._format_duration(max(position_ms, 0)))
        self._accumulate_playback_time(position_ms)
        self._record_played_30_seconds()
        self._record_completed_listen(position_ms)
        if self._player_duration_ms <= 0 and self.current_track_id is not None:
            current_track = self.store.get_track(self.current_track_id)
            current_duration_ms = (
                max(int(current_track.duration_ms or 0), 0)
                if current_track is not None
                else 0
            )
            if current_duration_ms > 0:
                self._handle_player_duration_changed(current_duration_ms)
        if self._player_duration_ms <= 0 or self.player_progress_slider.isSliderDown():
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
                mood_context=self._get_active_recommendation_context(),
                recommendation_session_id=(
                    self._get_active_recommendation_session_id()
                ),
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
        """Record a completed listen at the 80% position threshold."""

        if self._current_track_listen_recorded or self.current_track_id is None:
            return
        duration_ms = self._player_duration_ms
        if duration_ms <= 0:
            track = self.store.get_track(self.current_track_id)
            duration_ms = track.duration_ms if track is not None else 0
        if not reached_completion_threshold(position_ms, duration_ms):
            return
        if (
            not self._current_track_seeked_to_completion
            and self._current_track_played_ms < duration_ms * 0.8
        ):
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
        if reached_completion_threshold(position_ms, self._player_duration_ms):
            self._current_track_seeked_to_completion = True
            self._record_completed_listen(position_ms)

    def _import_track(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select audio file",
            "",
            ("Audio files (*.mp3 *.wav *.flac *.m4a *.mp4 *.ogg *.opus)"),
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

        if metadata_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        title, artist = metadata_dialog.get_values()

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
            (f"Added:\n{track.artist} — {track.title}"),
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
                if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
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

        self.library_count_label.setText(f"{self.track_table.rowCount()} tracks")
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
        dialog.scan_requested.connect(lambda: self._scan_library_health(dialog))
        dialog.delete_missing_requested.connect(
            lambda: self._delete_missing_library_records(dialog)
        )
        dialog.zip_backup_requested.connect(
            lambda: self._create_library_zip_backup(dialog)
        )
        dialog.json_export_requested.connect(lambda: self._export_library_json(dialog))
        dialog.restore_requested.connect(
            lambda: self._restore_library_zip_backup(dialog)
        )
        dialog.watch_folder_requested.connect(lambda: self._choose_watch_folder(dialog))
        dialog.watch_sync_requested.connect(lambda: self._sync_watch_folder(dialog))
        dialog.watch_disable_requested.connect(
            lambda: self._disable_watch_folder(dialog)
        )
        dialog.watch_update_metadata_toggled.connect(
            self._set_watch_folder_metadata_updates
        )
        dialog.compact_preferences_requested.connect(
            lambda: self._compact_preference_history(dialog)
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
        self.statusBar().showMessage(f"Watch folder enabled: {config.folder}")
        self._sync_watch_folder(dialog)

    def _set_watch_folder_metadata_updates(self, enabled: bool) -> None:
        try:
            self.watch_folder_service.set_update_metadata(enabled)
        except OSError as error:
            self.statusBar().showMessage(
                f"Could not save watch-folder setting: {error}"
            )

    def _compact_preference_history(
        self,
        dialog: LibraryMaintenanceDialog,
    ) -> None:
        try:
            plan = self.interaction_service.preference_compaction_plan()
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(dialog, "Cleanup unavailable", str(error))
            return

        if plan.redundant_records == 0:
            QMessageBox.information(
                dialog,
                "No duplicate preferences",
                "There are no redundant like or dislike records.",
            )
            return

        confirmation = QMessageBox.question(
            dialog,
            "Clean duplicate preferences",
            (
                f"Remove {plan.redundant_records} redundant preference "
                f"record(s) across {plan.affected_tracks} track(s)?\n\n"
                "The latest state for each track will remain. Playback "
                "history, playlists and audio files will not change. "
                "A backup is recommended first."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        dialog.compact_preferences_button.setEnabled(False)
        try:
            removed_count = self.interaction_service.compact_preference_history()
        except (OSError, RuntimeError, ValueError) as error:
            QMessageBox.warning(dialog, "Cleanup failed", str(error))
            return
        finally:
            dialog.compact_preferences_button.setEnabled(True)

        self._load_history()
        self._load_recommendations()
        self.statusBar().showMessage(
            f"Removed {removed_count} duplicate preference record(s)"
        )
        QMessageBox.information(
            dialog,
            "Cleanup complete",
            f"Removed {removed_count} duplicate preference record(s).",
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

    def _delete_missing_library_records(
        self,
        dialog: LibraryMaintenanceDialog,
    ) -> None:
        track_ids = dialog.missing_track_ids
        if not track_ids:
            return

        confirmation = QMessageBox.question(
            dialog,
            "Delete missing records",
            (
                f"Delete {len(track_ids)} database record(s) whose audio "
                "files are missing?\n\n"
                "The records will be removed from playlists, history and "
                "recommendation data. Files that still exist will not be "
                "touched."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmation != QMessageBox.StandardButton.Yes:
            return

        removed = 0
        errors: list[str] = []
        for track_id in track_ids:
            try:
                self.track_management_service.delete_track(track_id)
                self.recommendation_service.remove_track(track_id)
            except (FileNotFoundError, OSError, ValueError) as error:
                errors.append(str(error))
            else:
                removed += 1

        self.selected_track_id = None
        self._load_library()
        self._load_history()
        self._load_recommendations()
        self.statusBar().showMessage(f"Removed {removed} missing track record(s)")

        if errors:
            QMessageBox.warning(
                dialog,
                "Some records were not removed",
                "\n".join(errors),
            )

        self._scan_library_health(dialog)

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

    def _regenerate_playlist_cover(self, playlist_id: str) -> None:
        playlist = self._resolve_playlist(playlist_id)
        if playlist is None:
            return

        try:
            self.playlist_management_service.set_generated_cover(
                playlist.id,
                generate_playlist_artwork_svg(),
            )
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, "Artwork failed", str(error))
            return

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

    def _import_from_youtube(
        self,
        initial_query: str | None = None,
    ) -> None:
        spotify_provider = self.youtube_import_service.spotify_provider
        dialog = YouTubeSearchDialog(
            self,
            spotify_authenticated=spotify_provider.has_saved_credentials(),
        )
        if initial_query:
            dialog.source_edit.setText(initial_query)
            dialog.source_edit.selectAll()
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
        dialog.spotify_sync_requested.connect(
            lambda: self._start_spotify_sync_last(dialog)
        )
        dialog.spotify_sync_all_requested.connect(
            lambda: self._start_spotify_sync_all(dialog)
        )
        dialog.import_requested.connect(
            lambda candidate: self._start_youtube_import(
                dialog,
                candidate,
            )
        )
        dialog.playlist_import_requested.connect(
            lambda candidates: self._start_playlist_import(
                dialog,
                candidates,
            )
        )

        self._show_auxiliary_dialog(dialog)

    def _open_track_replacement_search(self, track_id: str) -> None:
        track = self.store.get_track(track_id)
        if track is None:
            return

        self._import_from_youtube(
            initial_query=f"{track.artist} - {track.title}",
        )

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
        dialog.spotify_sync_requested.connect(
            lambda: self._start_spotify_sync_last(dialog)
        )
        dialog.spotify_sync_all_requested.connect(
            lambda: self._start_spotify_sync_all(dialog)
        )

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.search_playlist_export(
                Path(export_path),
                on_progress=thread.search_progress_updated.emit,
                should_cancel=thread.is_cancelled,
            ),
            self,
        )
        thread.search_progress_updated.connect(dialog.update_search_progress)
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
        thread.search_progress_updated.connect(dialog.update_search_progress)
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
                source=dialog.import_source,
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

        if (
            isinstance(candidates, list)
            and candidates
            and all(
                isinstance(candidate, SoundCloudCandidate) for candidate in candidates
            )
        ):
            self._start_soundcloud_playlist_import(dialog, candidates)
            return

        if (
            isinstance(candidates, list)
            and candidates
            and all(
                isinstance(candidate, Mp3PartyCandidate) for candidate in candidates
            )
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
                    lambda provider=provider: self._start_alternative_playlist_search(
                        dialog,
                        failed,
                        unmatched,
                        unmatched_positions,
                        provider,
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
            (f"Downloading SoundCloud playlist: 0/{len(selected_candidates)}..."),
        )
        dialog.resume_progress(
            f"Downloading SoundCloud playlist: 0/{len(selected_candidates)}...",
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
            lambda candidate, track: self._handle_playlist_track_imported(
                dialog,
                candidate,
                track,
            )
        )
        thread.progress_updated.connect(dialog.update_playlist_download_progress)
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
            (f"Downloading MP3Party playlist: 0/{len(selected_candidates)}..."),
        )
        dialog.resume_progress(
            f"Downloading MP3Party playlist: 0/{len(selected_candidates)}...",
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
            lambda candidate, track: self._handle_playlist_track_imported(
                dialog,
                candidate,
                track,
            )
        )
        thread.progress_updated.connect(dialog.update_playlist_download_progress)
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
            preserve_added_dates=(
                source_dialog.preserve_spotify_added_dates
                if source_dialog is not None
                else False
            ),
        )
        settings_dialog.authenticate_requested.connect(
            lambda: self._start_spotify_settings_auth(settings_dialog)
        )
        settings_dialog.spotify_favorites_import_requested.connect(
            lambda: self._start_spotify_favorites_import(settings_dialog)
        )
        settings_dialog.spotify_history_import_requested.connect(
            lambda: self._start_spotify_history_import(settings_dialog)
        )
        settings_dialog.sync_requested.connect(
            lambda: self._start_spotify_sync_last(settings_dialog)
        )
        settings_dialog.sync_all_requested.connect(
            lambda: self._start_spotify_sync_all(settings_dialog)
        )
        settings_dialog.finished.connect(
            lambda _result: self._handle_spotify_settings_closed(
                source_dialog,
                settings_dialog,
            )
        )

        self._show_auxiliary_dialog(settings_dialog)

    def _handle_spotify_settings_closed(
        self,
        source_dialog: YouTubeSearchDialog | None,
        settings_dialog: SpotifySettingsDialog,
    ) -> None:
        if source_dialog is not None:
            provider = self.youtube_import_service.spotify_provider
            source_dialog.set_spotify_authenticated(provider.has_saved_credentials())
            source_dialog.set_preserve_spotify_added_dates(
                settings_dialog.preserve_added_dates
            )

    def _show_auxiliary_dialog(self, dialog: QDialog) -> None:
        if self._auxiliary_dialogs is None:
            raise RuntimeError("Auxiliary dialog manager is not initialized.")
        self._auxiliary_dialogs.show(dialog)

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

    def eventFilter(self, watched: object, event: object) -> bool:
        if self._auxiliary_dialogs is not None and self._auxiliary_dialogs.event_filter(
            watched,
            event,
        ):
            return True

        return super().eventFilter(watched, event)

    @staticmethod
    def _read_setting_string(
        settings: QSettings,
        key: str,
    ) -> str:
        value = settings.value(key, "")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _read_setting_string_list(
        settings: QSettings,
        key: str,
    ) -> tuple[str, ...]:
        value = settings.value(key, [])
        if isinstance(value, str):
            values = (value,)
        elif isinstance(value, (list, tuple)):
            values = tuple(str(item) for item in value)
        else:
            values = ()

        return tuple(item.strip() for item in values if item.strip())

    def _save_playback_state(self) -> None:
        """Persist the current player and queue snapshot for the next launch."""

        settings = self._playback_state_settings
        queue = self.playback_queue_service.queue
        last_track_id = self.current_track_id
        if last_track_id is None and queue is not None:
            last_track_id = queue.current_track_id
        if last_track_id:
            settings.setValue("playback/last_track_id", last_track_id)
            settings.setValue(
                "playback/position_ms",
                max(int(self.media_player.position()), 0),
            )
        else:
            settings.remove("playback/position_ms")

        settings.setValue("playback/repeat_mode", self._repeat_mode.value)
        settings.setValue("playback/queue_active", queue is not None)
        if queue is not None:
            settings.setValue(
                "playback/queue/current_track_id",
                queue.current_track_id or "",
            )
            settings.setValue(
                "playback/queue/remaining_track_ids",
                list(queue.remaining_track_ids),
            )
            settings.setValue(
                "playback/queue/queued_track_ids",
                list(queue.queued_track_ids),
            )
            settings.setValue("playback/queue/mode", queue.mode.value)
            settings.setValue(
                "playback/queue/source_playlist_id",
                queue.source_playlist_id or "",
            )

        settings.sync()

    @staticmethod
    def _is_playable_track(track: Track) -> bool:
        return bool(track.local_path and Path(track.local_path).is_file())

    def _track_has_local_audio(self, track_id: str) -> bool:
        track = self.store.get_track(track_id)
        return bool(track is not None and self._is_playable_track(track))

    def _apply_restored_queue_mode(self, mode: QueueMode) -> None:
        self.session_mood_name = None
        self.session_genre_name = None
        self.selected_mood_name = None
        self.selected_genre_name = None
        self._track_radio_enabled = mode == QueueMode.RECOMMENDATIONS
        self._radio_anchor_track_id = (
            self.playback_queue_service.queue.current_track_id
            if self._track_radio_enabled
            and self.playback_queue_service.queue is not None
            else None
        )
        restored_queue = self.playback_queue_service.queue
        self._radio_session_seen_track_ids = (
            {
                restored_track_id
                for restored_track_id in (
                    restored_queue.current_track_id,
                    *restored_queue.queued_track_ids,
                    *restored_queue.remaining_track_ids,
                )
                if restored_track_id is not None
            }
            if self._track_radio_enabled and restored_queue is not None
            else set()
        )
        self._radio_impression_session_id = (
            f"radio-resume-{uuid4().hex}" if self._track_radio_enabled else None
        )
        self._radio_impression_position = 0
        self._playback_mode = (
            mode if mode in LIBRARY_PLAYBACK_MODES else QueueMode.NORMAL
        )
        self._update_playback_mode_controls()

    def _restore_playback_state(self) -> None:
        """Resume the last queue after the library is available."""

        settings = self._playback_state_settings
        saved_position_ms = max(
            settings.value("playback/position_ms", 0, type=int),
            0,
        )
        self._pending_restore_position_ms = saved_position_ms
        repeat_value = self._read_setting_string(
            settings,
            "playback/repeat_mode",
        )
        try:
            self._repeat_mode = RepeatMode(repeat_value)
        except ValueError:
            self._repeat_mode = RepeatMode.OFF
        self.playback_queue_service.set_repeat_mode(self._repeat_mode)

        queue_active = bool(settings.value("playback/queue_active", False, type=bool))
        current_track_id = (
            self._read_setting_string(
                settings,
                "playback/queue/current_track_id",
            )
            or None
        )
        if current_track_id is not None and not self._track_has_local_audio(
            current_track_id
        ):
            current_track_id = None

        mode_value = self._read_setting_string(
            settings,
            "playback/queue/mode",
        )
        try:
            queue_mode = QueueMode(mode_value)
        except ValueError:
            queue_mode = QueueMode.NORMAL

        if queue_active:
            try:
                queue = self.playback_queue_service.restore(
                    current_track_id,
                    self._read_setting_string_list(
                        settings,
                        "playback/queue/remaining_track_ids",
                    ),
                    self._read_setting_string_list(
                        settings,
                        "playback/queue/queued_track_ids",
                    ),
                    mode=queue_mode,
                    source_playlist_id=(
                        self._read_setting_string(
                            settings,
                            "playback/queue/source_playlist_id",
                        )
                        or None
                    ),
                )
            except ValueError:
                queue = None
            if queue is not None:
                self._apply_restored_queue_mode(queue.mode)
                self._load_queue()
                if queue.current_track_id is not None:
                    self._play_track(
                        queue.current_track_id,
                        autoplay=False,
                    )
                    self._apply_pending_restore_position()
                else:
                    self._pending_restore_position_ms = None
                return

        last_track_id = self._read_setting_string(
            settings,
            "playback/last_track_id",
        )
        if not last_track_id or not self._track_has_local_audio(last_track_id):
            self._pending_restore_position_ms = None
            return

        self._apply_restored_queue_mode(QueueMode.NORMAL)
        self.playback_queue_service.start(
            (last_track_id,),
            mode=QueueMode.NORMAL,
        )
        self._load_queue()
        self._play_track(last_track_id, autoplay=False)
        self._apply_pending_restore_position()

    def closeEvent(self, event: object) -> None:
        """Stop loader work before the main process is allowed to exit."""

        if self._is_shutting_down:
            return

        self._is_shutting_down = True
        self._global_media_hotkeys.unregister()
        # Capture the queue and current media position before stopping the
        # player or allowing any shutdown callback to change the UI state.
        self._save_playback_state()
        self._watch_folder_timer.stop()
        self._model_idle_timer.stop()
        if self._auxiliary_dialogs is not None:
            self._auxiliary_dialogs.close_all()

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
        self._cancel_mood_session()
        self._cancel_radio_recommendations()
        self._cancel_genre_analysis_tasks()
        self._cancel_loudness_analysis()
        self._cancel_track_materialization()
        self._music_map_pool.clear()
        self._recommendation_pool.clear()
        self._mood_recommendation_pool.clear()
        self._recommendation_analytics_pool.clear()
        self._radio_recommendation_pool.clear()
        self._genre_analysis_pool.waitForDone()
        self._release_cancelled_genre_models()
        self._music_map_pool.waitForDone(3_000)
        self._recommendation_pool.waitForDone(3_000)
        self._mood_recommendation_pool.waitForDone(3_000)
        self._recommendation_analytics_pool.waitForDone(3_000)
        self._radio_recommendation_pool.waitForDone(3_000)
        self._loudness_analysis_pool.waitForDone(3_000)
        if self.music_map.has_map_data_for(self._music_map_signature):
            self.music_map.capture_snapshot()
            self._save_music_map_snapshot()
        self.media_player.stop()
        super().closeEvent(event)

    def _start_spotify_sync_last(
        self,
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None = None,
    ) -> None:
        """Run one explicit incremental Spotify sync from the UI."""

        self._start_spotify_sync_requested(dialog, sync_all=False)

    def _start_spotify_favorites_import(
        self,
        dialog: SpotifySettingsDialog,
    ) -> None:
        """Import Spotify favorites as recommendation metadata only."""

        if self._youtube_thread is not None:
            return

        provider = self.youtube_import_service.spotify_provider
        if not provider.has_saved_credentials():
            dialog.set_authenticated(False)
            dialog.set_busy(False, "Connect Spotify with OAuth first.")
            self.statusBar().showMessage(
                "Connect Spotify with OAuth before importing favorites."
            )
            return

        message = "Importing Spotify favorite metadata for recommendations..."
        dialog.set_busy(True, message)
        dialog.start_progress(message)

        def import_favorites() -> SpotifyFavoritesImportResult:
            return self.spotify_favorites_import_service.import_all(
                self.user_id,
                on_progress=(
                    lambda completed, total, current: (
                        thread.search_progress_updated.emit(
                            completed,
                            total,
                            completed,
                            0,
                            current,
                        )
                    )
                ),
                should_cancel=thread.is_cancelled,
            )

        thread = YouTubeTaskThread(import_favorites, self)
        thread.search_progress_updated.connect(
            lambda completed, total, _found, _failed, current: (
                dialog.update_metadata_import_progress(
                    completed,
                    total,
                    current,
                )
            )
        )
        thread.result_ready.connect(
            lambda result: self._handle_spotify_favorites_import_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda error: self._handle_spotify_favorites_import_error(
                dialog,
                error,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _handle_spotify_favorites_import_result(
        self,
        dialog: SpotifySettingsDialog,
        result: object,
    ) -> None:
        if not isinstance(result, SpotifyFavoritesImportResult):
            self._handle_spotify_favorites_import_error(
                dialog,
                "Spotify favorites import returned an invalid result.",
            )
            return

        message = (
            f"Imported {result.imported_metadata} and updated "
            f"{result.updated_metadata} Spotify metadata record(s) for "
            "recommendations. Audio was not downloaded."
        )
        dialog.set_busy(False, message)
        dialog.finish_progress(message)
        self.statusBar().showMessage(message)

    def _handle_spotify_favorites_import_error(
        self,
        dialog: SpotifySettingsDialog,
        message: str,
    ) -> None:
        failure_message = "Spotify metadata import failed."
        dialog.set_busy(False, failure_message)
        dialog.finish_progress(failure_message)
        QMessageBox.warning(
            dialog,
            "Spotify metadata import failed",
            message,
        )

    def _start_spotify_history_import(
        self,
        dialog: SpotifySettingsDialog,
    ) -> None:
        """Import a Spotify Extended Streaming History JSON/ZIP file."""

        if self._youtube_thread is not None:
            return

        file_path, _ = QFileDialog.getOpenFileName(
            dialog,
            "Select Spotify Extended Streaming History",
            "",
            "Spotify history (*.json *.zip);;JSON files (*.json);;ZIP files (*.zip)",
        )
        if not file_path:
            return

        message = "Importing Spotify listening history..."
        dialog.set_busy(True, message)
        dialog.start_progress(message)

        def import_history() -> SpotifyListeningHistoryImportResult:
            return self.spotify_history_import_service.import_path(
                Path(file_path),
                on_progress=(
                    lambda completed, total, current: (
                        thread.search_progress_updated.emit(
                            completed,
                            total,
                            completed,
                            0,
                            current,
                        )
                    )
                ),
                should_cancel=thread.is_cancelled,
            )

        thread = YouTubeTaskThread(import_history, self)
        thread.search_progress_updated.connect(
            lambda completed, total, _found, _failed, current: (
                dialog.update_history_import_progress(
                    completed,
                    total,
                    current,
                )
            )
        )
        thread.result_ready.connect(
            lambda result: self._handle_spotify_history_import_result(
                dialog,
                result,
            )
        )
        thread.error_occurred.connect(
            lambda error: self._handle_spotify_history_import_error(
                dialog,
                error,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _handle_spotify_history_import_result(
        self,
        dialog: SpotifySettingsDialog,
        result: object,
    ) -> None:
        if not isinstance(result, SpotifyListeningHistoryImportResult):
            self._handle_spotify_history_import_error(
                dialog,
                "Spotify listening history import returned an invalid result.",
            )
            return

        message = (
            f"Imported {result.imported_stats} new and updated "
            f"{result.updated_stats} listening-stat record(s) from "
            f"{result.total_entries} history entr(y/ies). "
            "Audio was not downloaded."
        )
        if result.skipped_entries:
            message += f" Skipped {result.skipped_entries} entr(y/ies)."
        dialog.set_busy(False, message)
        dialog.finish_progress(message)
        self.statusBar().showMessage(message)

    def _handle_spotify_history_import_error(
        self,
        dialog: SpotifySettingsDialog,
        message: str,
    ) -> None:
        failure_message = "Spotify listening history import failed."
        dialog.set_busy(False, failure_message)
        dialog.finish_progress(failure_message)
        QMessageBox.warning(
            dialog,
            "Spotify listening history import failed",
            message,
        )

    def _start_spotify_sync_all(
        self,
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None = None,
    ) -> None:
        """Run an explicit full Spotify saved-track sync from the UI."""

        self._start_spotify_sync_requested(dialog, sync_all=True)

    def _start_spotify_sync_requested(
        self,
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None,
        *,
        sync_all: bool,
    ) -> None:
        sync_label = "Sync All" if sync_all else "Sync Last"

        if self._youtube_thread is not None:
            return

        provider = self.youtube_import_service.spotify_provider
        if not provider.has_saved_credentials():
            if isinstance(dialog, YouTubeSearchDialog):
                dialog.set_spotify_authenticated(False)
            if dialog is not None:
                dialog.set_busy(False, "Connect Spotify with OAuth first.")
            self.statusBar().showMessage(
                f"Connect Spotify with OAuth before using {sync_label}."
            )
            return

        preserve_added_dates = (
            dialog.preserve_spotify_added_dates
            if isinstance(dialog, YouTubeSearchDialog)
            else (
                dialog.preserve_added_dates
                if isinstance(dialog, SpotifySettingsDialog)
                else False
            )
        )
        track_range = (
            dialog.track_range if isinstance(dialog, SpotifySettingsDialog) else None
        )
        self._start_spotify_sync(
            dialog,
            sync_all=sync_all,
            preserve_added_dates=preserve_added_dates,
            track_range=track_range,
        )

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

    def _start_spotify_sync(
        self,
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None,
        *,
        sync_all: bool = False,
        preserve_added_dates: bool = False,
        track_range: tuple[int, int] | None = None,
    ) -> None:
        sync_label = "Sync All" if sync_all else "Sync Last"
        if dialog is not None:
            range_suffix = (
                f" ({track_range[0]}–{track_range[1]})"
                if sync_all and track_range is not None
                else ""
            )
            message = (
                f"Reading Spotify saved tracks{range_suffix} in their Spotify order..."
                if sync_all
                else "Reading tracks added since the previous Sync Last..."
            )
            dialog.set_busy(True, message)
            dialog.start_progress(message)

        def sync() -> object:
            sync_method = lambda: (
                self.spotify_fav_sync_service.sync_all_saved_tracks(
                    track_range=track_range,
                )
                if sync_all
                else self.spotify_fav_sync_service.sync_last_saved_tracks
            )
            sync_result = sync_method()
            if not sync_result.new_tracks:
                return sync_result

            search_result = self.youtube_import_service.search_playlist_tracks(
                list(enumerate(sync_result.new_tracks)),
                playlist_name=f"Spotify favorites · {sync_label}",
                on_progress=thread.search_progress_updated.emit,
                should_cancel=thread.is_cancelled,
            )
            return sync_result, search_result

        thread = YouTubeTaskThread(sync, self)
        if dialog is not None:
            thread.search_progress_updated.connect(dialog.update_search_progress)
        else:
            thread.search_progress_updated.connect(
                lambda completed, total, found, failed, current: (
                    self._handle_spotify_sync_progress(
                        sync_label,
                        completed,
                        total,
                        found,
                        failed,
                        current,
                    )
                )
            )
        thread.result_ready.connect(
            lambda result: self._handle_spotify_sync_result(
                dialog,
                result,
                sync_label,
                preserve_added_dates,
            )
        )
        thread.error_occurred.connect(
            lambda message: self._handle_spotify_sync_error(
                dialog,
                message,
                sync_label,
            )
        )
        self._start_youtube_thread(thread, dialog)

    def _handle_spotify_sync_progress(
        self,
        sync_label: str,
        completed: int,
        total: int,
        found: int,
        failed: int,
        current: str,
    ) -> None:
        """Keep an explicit sync observable without opening a dialog."""

        message = f"{sync_label}: Searching {completed}/{total} · found {found}"
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
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None,
        result: object,
        sync_label: str,
        preserve_added_dates: bool = False,
    ) -> None:
        if isinstance(result, SpotifyFavSyncResult):
            if result.new_tracks:
                names = ", ".join(track.title for track in result.new_tracks[:3])
                suffix = "" if len(result.new_tracks) <= 3 else "…"
                if sync_label == "Sync All":
                    message = (
                        f"{sync_label} loaded {len(result.new_tracks)} "
                        f"saved track(s): {names}{suffix}"
                    )
                else:
                    message = (
                        f"{sync_label} found {len(result.new_tracks)} "
                        f"new track(s): {names}{suffix}"
                    )
            else:
                message = (
                    f"{sync_label}: no saved tracks."
                    if sync_label == "Sync All"
                    else f"{sync_label}: no new saved tracks."
                )
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
                f"{sync_label} returned an invalid result.",
                sync_label,
            )
            return

        sync_result, search_result = result
        message = (
            f"{sync_label} loaded {len(sync_result.new_tracks)} saved track(s)."
            if sync_label == "Sync All"
            else (f"{sync_label} found {len(sync_result.new_tracks)} saved track(s).")
        )
        if dialog is not None:
            dialog.set_busy(False, message)
            dialog.finish_progress(message)
        else:
            self.statusBar().showMessage(message)

        if search_result is None:
            self.statusBar().showMessage(
                (
                    f"{sync_label}: no saved tracks."
                    if sync_label == "Sync All"
                    else f"{sync_label}: no new saved tracks."
                )
            )
            return

        QTimer.singleShot(
            0,
            lambda: self._show_spotify_sync_results(
                search_result,
                dialog=(dialog if isinstance(dialog, YouTubeSearchDialog) else None),
                preserve_added_dates=preserve_added_dates,
            ),
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
        dialog: YouTubeSearchDialog | SpotifySettingsDialog | None,
        message: str,
        sync_label: str = "Sync Last",
    ) -> None:
        if dialog is not None:
            dialog.set_busy(False, "Spotify sync failed.")
            dialog.finish_progress("Spotify sync failed.")
            QMessageBox.warning(dialog, "Spotify sync failed", message)
        else:
            self.statusBar().showMessage(f"{sync_label} failed: {message}")

    def _show_spotify_sync_results(
        self,
        result: SpotifyPlaylistSearchResult,
        dialog: YouTubeSearchDialog | None = None,
        *,
        preserve_added_dates: bool = False,
    ) -> None:
        if dialog is None:
            dialog = YouTubeSearchDialog(
                self,
                spotify_authenticated=True,
                spotify_preserve_added_dates=preserve_added_dates,
            )
            dialog.set_import_source("spotify_favorite")
            dialog.playlist_import_requested.connect(
                lambda candidates: self._start_playlist_import(
                    dialog,
                    candidates,
                )
            )
            dialog.spotify_settings_requested.connect(
                lambda: self._open_spotify_settings(dialog)
            )
            dialog.spotify_sync_requested.connect(
                lambda: self._start_spotify_sync_last(dialog)
            )
            dialog.spotify_sync_all_requested.connect(
                lambda: self._start_spotify_sync_all(dialog)
            )

        dialog.set_import_source("spotify_favorite")
        dialog.set_preserve_spotify_added_dates(preserve_added_dates)
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
            (f"Downloading playlist: 0/{len(selected_candidates)}..."),
        )
        dialog.resume_progress(
            f"Downloading playlist: 0/{len(selected_candidates)}...",
            total=len(selected_candidates),
        )
        import_source = dialog.import_source
        preserve_added_dates = (
            import_source == "spotify_favorite" and dialog.preserve_spotify_added_dates
        )

        def import_playlist() -> YouTubePlaylistImportResult:
            return self.youtube_import_service.download_and_import_playlist(
                selected_candidates,
                source=import_source,
                preserve_added_dates=preserve_added_dates,
                on_progress=thread.progress_updated.emit,
                on_track_imported=thread.track_imported.emit,
            )

        thread = YouTubeTaskThread(import_playlist, self)
        thread.track_imported.connect(
            lambda candidate, track: self._handle_playlist_track_imported(
                dialog,
                candidate,
                track,
            )
        )
        thread.progress_updated.connect(dialog.update_playlist_download_progress)
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
                    SpotifyTrack(
                        title=title,
                        artist=artist,
                        added_at=candidate.spotify_added_at,
                        cover_url=candidate.cover_url,
                    ),
                )
            )

        for index, (track, _) in enumerate(unmatched):
            position = (
                unmatched_positions[index] if index < len(unmatched_positions) else None
            )
            retry_tracks.append((allocate_position(position), track))

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
                playlist_name=(dialog.playlist_name or "YouTube playlist"),
                cover_url=dialog.playlist_cover_url,
                on_progress=thread.search_progress_updated.emit,
                should_cancel=thread.is_cancelled,
            )

        thread = YouTubeTaskThread(search_playlist, self)
        thread.search_progress_updated.connect(dialog.update_search_progress)
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
                    SpotifyTrack(
                        title=title,
                        artist=artist,
                        cover_url=getattr(candidate, "cover_url", None),
                    ),
                )
            )

        for index, (track, _) in enumerate(unmatched):
            position = (
                unmatched_positions[index] if index < len(unmatched_positions) else None
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
                YouTubeCandidate | SoundCloudCandidate | Mp3PartyCandidate | None,
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
                (f"Starting parallel search ({min(worker_limit, total)} workers)"),
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
        thread.search_progress_updated.connect(dialog.update_search_progress)
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
            candidate for candidate in result if isinstance(candidate, YouTubeCandidate)
        ]
        dialog.set_import_source("youtube")
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
            dialog.set_import_source("spotify")
            dialog.set_search_query(result.query)
            dialog.set_candidates(list(result.candidates))
            return

        if isinstance(result, SpotifyPlaylistSearchResult):
            dialog.set_import_source("spotify")
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
            candidate for candidate in result if isinstance(candidate, YouTubeCandidate)
        ]
        dialog.set_import_source("youtube")
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
            (f"Added to Library:\n{track.artist} — {track.title}"),
        )

    def _handle_youtube_playlist_import_result(
        self,
        dialog: YouTubeSearchDialog,
        result: object,
    ) -> None:
        self._playlist_import_active = False
        self._schedule_library_refresh()

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
            failed_candidates = [candidate for candidate, _ in failed]
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

        message = f"Imported {len(result.imported)} playlist tracks."
        if dialog.playlist_name:
            message += f"\nLocal playlist: {dialog.playlist_name}"

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
        self._schedule_library_refresh()

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
            failed_candidates = [candidate for candidate, _ in failed]
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
        self._schedule_library_refresh()

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
            failed_candidates = [candidate for candidate, _ in failed]
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
                playlist = self.playlist_management_service.create_playlist(
                    dialog.playlist_name
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
            self.statusBar().showMessage("Playlist imported without its cover image.")
            return

        self._load_playlists()

    @staticmethod
    def _track_has_loudness_analysis(track: Track) -> bool:
        return (
            track.loudness_lufs is not None
            and track.loudness_true_peak_db is not None
            and track.loudness_gain_db is not None
            and track.loudness_analysis_version == LOUDNESS_ANALYSIS_VERSION
        )

    def _analyze_missing_loudness(self) -> None:
        """Queue loudness analysis for local tracks that have no measurement."""

        if self._is_shutting_down:
            return
        if self._loudness_pending_track_ids:
            self.statusBar().showMessage("Loudness analysis is already running")
            return

        tracks = [
            track
            for track in self.store.list_tracks()
            if (
                track.local_path
                and Path(track.local_path).is_file()
                and not self._track_has_loudness_analysis(track)
            )
        ]
        if not tracks:
            self.statusBar().showMessage(
                "The library has no unanalyzed local loudness tracks."
            )
            return

        for track in tracks:
            self._enqueue_loudness_analysis(track)

        self.statusBar().showMessage(
            f"Loudness analysis queued: {len(tracks)} track(s)"
        )

    def _enqueue_loudness_analysis(self, track: Track) -> None:
        if self._is_shutting_down:
            return

        stored_track = self.store.get_track(track.id)
        if stored_track is not None:
            track = stored_track

        if (
            not track.local_path
            or not Path(track.local_path).is_file()
            or self._track_has_loudness_analysis(track)
            or track.id in self._loudness_pending_track_ids
        ):
            return

        if not self._loudness_pending_track_ids:
            self._loudness_analysis_total = 0
            self._loudness_analysis_completed = 0
            self._loudness_analysis_failed = 0

        self._loudness_pending_track_ids.add(track.id)
        self._loudness_analysis_total += 1
        task = LoudnessAnalysisTask(
            track_id=track.id,
            audio_path=Path(track.local_path),
        )
        task.signals.result_ready.connect(self._handle_loudness_analysis_result)
        task.signals.error_occurred.connect(self._handle_loudness_analysis_error)
        task.signals.finished.connect(self._handle_loudness_analysis_finished)
        task.signals.finished.connect(
            lambda _track_id, task=task: self._forget_loudness_analysis_task(task)
        )
        self._loudness_analysis_tasks.add(task)
        self._loudness_analysis_pool.start(task)

    def _forget_loudness_analysis_task(
        self,
        task: LoudnessAnalysisTask,
    ) -> None:
        self._loudness_analysis_tasks.discard(task)

    def _handle_loudness_analysis_result(
        self,
        track_id: str,
        analysis_result: object,
    ) -> None:
        if track_id not in self._loudness_pending_track_ids:
            return
        if not isinstance(analysis_result, LoudnessAnalysis):
            self._handle_loudness_analysis_error(
                track_id,
                "Loudness analysis returned an invalid result.",
            )
            return

        try:
            updated_track = self.track_management_service.update_loudness(
                track_id=track_id,
                loudness_lufs=analysis_result.integrated_lufs,
                loudness_true_peak_db=analysis_result.true_peak_db,
                loudness_gain_db=analysis_result.gain_db,
                loudness_analysis_version=LOUDNESS_ANALYSIS_VERSION,
            )
        except (OSError, RuntimeError, ValueError) as error:
            self._handle_loudness_analysis_error(track_id, str(error))
            return

        self._update_library_track_row(updated_track)
        if self.current_track_id == track_id:
            self._apply_track_loudness_gain(updated_track)

    def _handle_loudness_analysis_error(
        self,
        track_id: str,
        message: str,
    ) -> None:
        if track_id not in self._loudness_pending_track_ids:
            return
        self._loudness_analysis_failed += 1
        self.statusBar().showMessage(
            f"Loudness analysis failed for {track_id}: {message}"
        )

    def _handle_loudness_analysis_finished(self, track_id: str) -> None:
        if track_id not in self._loudness_pending_track_ids:
            return

        self._loudness_pending_track_ids.remove(track_id)
        self._loudness_analysis_completed += 1
        if self._loudness_pending_track_ids:
            self.statusBar().showMessage(
                "Loudness analysis progress: "
                f"{self._loudness_analysis_completed}/"
                f"{self._loudness_analysis_total}"
            )
            return

        analyzed_count = (
            self._loudness_analysis_total - self._loudness_analysis_failed
        )
        self.statusBar().showMessage(
            "Loudness analysis completed: "
            f"{analyzed_count}/{self._loudness_analysis_total} tracks"
        )

    def _cancel_loudness_analysis(self) -> None:
        for task in tuple(self._loudness_analysis_tasks):
            task.cancel()
        self._loudness_analysis_pool.clear()
        self._loudness_analysis_tasks.clear()
        self._loudness_pending_track_ids.clear()

    def _enqueue_genre_analysis(
        self,
        track: Track,
        *,
        force: bool = False,
    ) -> None:
        if self._is_shutting_down:
            return

        stored_track = self.store.get_track(track.id)
        if stored_track is not None:
            track = stored_track

        if not track.local_path:
            self._genre_statuses[track.id] = "No local file"
            self._set_genre_status(track.id, "No local file")
            return

        if not Path(track.local_path).is_file():
            self._genre_statuses[track.id] = "No local file"
            self._set_genre_status(track.id, "No local file")
            return

        if track.id in self._analysis_pending_track_ids:
            return

        if not force and self._track_has_analysis(track):
            self._genre_statuses[track.id] = "Completed"
            self._set_genre_status(track.id, "Completed")
            return

        self._genre_model_release_requested = False
        self._genre_model_release_timer.stop()

        if not self._analysis_pending_track_ids:
            self._analysis_total = 0
            self._analysis_completed = 0

        self._analysis_pending_track_ids.add(track.id)
        self._analysis_total += 1
        self._genre_statuses[track.id] = "Queued"
        self._set_genre_status(track.id, "Queued")
        if self.selected_track_id == track.id:
            self.analyze_genres_button.setEnabled(False)

        analysis_service = self._get_genre_analysis_service()
        task = GenreAnalysisTask(
            service=analysis_service,
            track_id=track.id,
            audio_path=Path(track.local_path),
        )
        task.signals.result_ready.connect(self._handle_genre_analysis_result)
        task.signals.error_occurred.connect(self._handle_genre_analysis_error)
        task.signals.finished.connect(
            lambda task=task: self._forget_genre_analysis_task(task)
        )

        self._genre_analysis_tasks.add(task)
        self._genre_analysis_pool.start(task)
        self._show_analysis_progress()
        self._update_analysis_progress()
        self.statusBar().showMessage(f"Track analysis queued: {track.title}")

    def _get_genre_analysis_service(self) -> LazyGenreAnalysisService:
        return self._genre_analysis_service

    @staticmethod
    def _create_genre_analysis_service(
        *,
        gpu_optimized: bool = False,
    ) -> "GenreAnalysisService":
        """Import ML dependencies only when the worker starts analysis."""

        from app.ml.genre_analysis import GenreAnalysisService

        return GenreAnalysisService(
            top_k=10,
            min_score=0.1,
            gpu_optimized=gpu_optimized,
        )

    def _forget_genre_analysis_task(
        self,
        task: GenreAnalysisTask,
    ) -> None:
        self._genre_analysis_tasks.discard(task)

    def _show_analysis_progress(self) -> None:
        """Open the modeless analysis window used as a restorable top tab."""

        if self._analysis_progress_dialog is not None:
            return

        dialog = AnalysisProgressDialog(self)
        dialog.cancel_requested.connect(self._cancel_all_genre_analysis)
        dialog.closed.connect(self._cancel_all_genre_analysis)
        dialog.finished.connect(
            lambda _result, target=dialog: self._handle_analysis_progress_finished(
                target
            )
        )
        self._analysis_progress_dialog = dialog
        self._show_auxiliary_dialog(dialog)

    def _handle_analysis_progress_finished(
        self,
        dialog: AnalysisProgressDialog,
    ) -> None:
        if self._analysis_progress_dialog is dialog:
            self._analysis_progress_dialog = None

    def _update_analysis_progress(self) -> None:
        dialog = self._analysis_progress_dialog
        if dialog is None:
            return
        dialog.update_progress(
            self._analysis_completed,
            self._analysis_total,
            len(self._analysis_pending_track_ids),
        )
        if self._auxiliary_dialogs is not None:
            self._auxiliary_dialogs.refresh(dialog)

    def _finish_analysis_item(self, track_id: str) -> bool:
        """Mark one analysis task complete and close the progress window last."""

        if track_id not in self._analysis_pending_track_ids:
            return False

        self._analysis_pending_track_ids.remove(track_id)
        self._analysis_completed += 1
        self._update_analysis_progress()
        if not self._analysis_pending_track_ids:
            dialog = self._analysis_progress_dialog
            if dialog is not None:
                dialog.accept()
            self._analysis_total = 0
            self._analysis_completed = 0
        return True

    def _cancel_all_genre_analysis(self) -> None:
        """Cancel queued analysis and ignore results already running."""

        cancelled_ids = set(self._analysis_pending_track_ids)
        if (
            not cancelled_ids
            and not self._genre_batch_track_ids
            and not self._genre_analysis_tasks
        ):
            return

        self._cancel_genre_analysis_tasks()
        self._analysis_pending_track_ids.clear()
        self._genre_batch_track_ids.clear()
        self._genre_batch_completed = 0
        self._genre_batch_total = 0
        self._analysis_total = 0
        self._analysis_completed = 0
        self.reanalyze_genres_button.setEnabled(True)

        for track_id in cancelled_ids:
            self._genre_statuses[track_id] = "Cancelled"
            self._set_genre_status(track_id, "Cancelled")
            if self.selected_track_id == track_id:
                self.analyze_genres_button.setEnabled(True)

        if self._is_shutting_down:
            return

        dialog = self._analysis_progress_dialog
        if dialog is not None:
            dialog.reject()

        self._maybe_refresh_recommendations()
        self.statusBar().showMessage(
            f"Track analysis cancelled: {len(cancelled_ids)} task(s)"
        )

    def _cancel_genre_analysis_tasks(self) -> None:
        self._genre_model_release_requested = True
        for task in tuple(self._genre_analysis_tasks):
            task.cancel()

        self._genre_analysis_pool.clear()
        self._genre_analysis_tasks.clear()
        self._release_cancelled_genre_models()

    def _release_cancelled_genre_models(self) -> None:
        """Unload models once every cancelled inference has actually stopped."""

        if not self._genre_model_release_requested:
            return

        if (
            self._genre_analysis_pool.activeThreadCount() != 0
            or self._genre_analysis_tasks
        ):
            if not self._is_shutting_down:
                self._genre_model_release_timer.start()
            return

        self._genre_model_release_requested = False
        self._genre_model_release_timer.stop()
        self._genre_analysis_service.unload()

    def _analyze_selected_track(self) -> None:
        if self.selected_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        track = self.store.get_track(self.selected_track_id)

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
            if track.local_path and Path(track.local_path).exists()
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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._genre_batch_track_ids = {track.id for track in local_tracks}
        self._genre_batch_completed = 0
        self._genre_batch_total = len(local_tracks)
        self.reanalyze_genres_button.setEnabled(False)

        for track in local_tracks:
            self._enqueue_genre_analysis(track, force=True)

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
                f"Genre reanalysis completed: {self._genre_batch_total} tracks"
            )

        return True

    def _set_genre_status(
        self,
        track_id: str,
        status: str,
    ) -> None:
        self._genre_statuses[track_id] = status
        for row_index, track in enumerate(self._visible_tracks):
            if track.id == track_id:
                self.track_table.update_row(
                    row_index,
                    track,
                )

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
        from app.ml.genre_analysis import TrackAnalysisResult
        from app.ml.maest import GenrePrediction

        if track_id not in self._analysis_pending_track_ids:
            return

        if not isinstance(analysis_result, TrackAnalysisResult):
            self._handle_genre_analysis_error(
                track_id,
                "Track analysis returned an invalid result.",
            )
            return

        predictions = list(analysis_result.genre_result.genres)

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
            updated_track = self.track_management_service.update_detected_genres(
                track_id=track_id,
                detected_genres=detected_genres,
                track_embedding=tuple(
                    float(value)
                    for value in analysis_result.genre_result.track_embedding
                ),
                mood=analysis_result.mood_result.mood,
                mood_tags=tuple(
                    (
                        str(tag),
                        float(score),
                    )
                    for tag, score in analysis_result.mood_result.tags
                ),
                mood_profiles=tuple(
                    (
                        prediction.profile,
                        float(prediction.score),
                    )
                    for prediction in analysis_result.mood_result.profiles
                ),
                mood_analysis_version=(analysis_result.mood_result.analysis_version),
            )
            self.recommendation_service.update_track(updated_track)
        except (OSError, RuntimeError, ValueError) as error:
            self._handle_genre_analysis_error(
                track_id,
                str(error),
            )
            return

        self._genre_statuses[track_id] = "Completed"
        self._genre_predictions[track_id] = analysis_result
        self._update_library_track_row(updated_track)
        self._refresh_music_map()
        if self.selected_track_id == track_id:
            self.analyze_genres_button.setEnabled(True)

        self._finish_analysis_item(track_id)
        is_batch_item = self._finish_genre_batch_item(track_id)
        self._maybe_refresh_recommendations()

        if is_batch_item:
            return

        track = self.store.get_track(track_id)
        track_name = track.title if track is not None else track_id

        self.statusBar().showMessage(f"Track analysis completed: {track_name}")

    def _unload_idle_models(self) -> None:
        if self._genre_analysis_pool.activeThreadCount() != 0:
            return

        if self._genre_analysis_service is not None:
            self._genre_analysis_service.unload_idle_models()

    def _handle_genre_analysis_error(
        self,
        track_id: str,
        message: str,
    ) -> None:
        if track_id not in self._analysis_pending_track_ids:
            return

        self._genre_statuses[track_id] = "Failed"
        track = self.store.get_track(track_id)
        if track is not None:
            self._update_library_track_row(track)
        else:
            self._set_genre_status(track_id, "Failed")
        if self.selected_track_id == track_id:
            self.analyze_genres_button.setEnabled(True)
        self._finish_analysis_item(track_id)
        is_batch_item = self._finish_genre_batch_item(track_id)
        self._maybe_refresh_recommendations()
        if is_batch_item:
            return
        self.statusBar().showMessage(f"Track analysis failed: {message}")

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
        self._schedule_library_refresh()
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

        track = self.store.get_track(self.selected_track_id)

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

        if metadata_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        title, artist = metadata_dialog.get_values()

        if self.current_track_id == track.id:
            # Stopping playback is not enough on Windows: QMediaPlayer can
            # keep the current source open until it is explicitly unloaded.
            self.media_player.stop()
            self.media_player.setSource(QUrl())

        try:
            updated_track = self.track_management_service.update_metadata(
                track_id=track.id,
                title=title,
                artist=artist,
                genres=track.genres,
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
            (f"Updated:\n{updated_track.artist} — {updated_track.title}"),
        )

    def _delete_selected_track(self) -> None:
        if self.selected_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        track = self.store.get_track(self.selected_track_id)

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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        if self.current_track_id == track.id:
            # Unload the source before deleting the file.  Otherwise the
            # media backend may still hold a Windows file lock after stop().
            self.media_player.stop()
            self.media_player.setSource(QUrl())

        try:
            self.track_management_service.delete_track(self.selected_track_id)
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
            item for item in self._library_tracks if item.id != track.id
        ]
        if self.selected_playlist_id is not None:
            self._load_selected_playlist_tracks()
        self._refresh_music_map()
        self.selected_track_id = None
        if self.current_track_id == track.id:
            self.current_track_id = None
            self.playback_queue_service.clear()
            self._playback_state_settings.remove("playback/last_track_id")
        self._load_queue()
        self._load_recommendations()
        self.statusBar().showMessage(f"Deleted: {track.artist} — {track.title}")

    def _play_selected_track(self) -> None:
        if self.selected_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        self._start_library_queue(
            self.selected_track_id,
            preserve_manual_queue=False,
        )

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
        queue = self.playback_queue_service.queue
        if queue is None:
            self.statusBar().showMessage("No next track")
            return

        if (
            queue.current_track_id is not None
            and queue.mode in {QueueMode.RECOMMENDATIONS, QueueMode.SESSION}
            and self._get_active_recommendation_context() is not None
        ):
            self._record_interaction(InteractionType.RECOMMENDATION_SKIP)
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
        self._update_queue_source_label()

        if queue is None or queue.current_track_id is None:
            self._play_next_from_queue()
            return

        self._play_track(queue.current_track_id)

    def _play_next_from_queue(self) -> None:
        queue = self.playback_queue_service.queue
        if (
            queue is not None
            and queue.mode == QueueMode.SESSION
            and queue.current_track_id is not None
            and (
                self.session_mood_name is not None
                or self.session_genre_name is not None
            )
            and not self.playback_queue_service.upcoming_track_ids()
        ):
            # Mood sessions are replenished asynchronously.  Keep the
            # current track alive until the next batch arrives instead of
            # advancing into an empty queue.
            self._mood_wait_track_id = queue.current_track_id
            self._replenish_mood_session()
            self._wait_for_mood_track()
            return

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
            elif queue.mode == QueueMode.SESSION:
                self._replenish_mood_session()
                self._load_queue()

            if queue.current_track_id is not None and self._play_track(
                queue.current_track_id
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
            self.statusBar().showMessage("No more recommendations available")
            return

        self._radio_wait_attempts += 1
        self._replenish_recommendation_queue(force=True)
        self.statusBar().showMessage("Finding the next recommendation…")
        QTimer.singleShot(250, self._wait_for_radio_track)

    def _wait_for_mood_track(self) -> None:
        queue = self.playback_queue_service.queue
        if (
            queue is None
            or queue.mode != QueueMode.SESSION
            or queue.current_track_id != self._mood_wait_track_id
        ):
            self._mood_wait_attempts = 0
            self._mood_wait_track_id = None
            return

        if self.playback_queue_service.upcoming_track_ids():
            self._mood_wait_attempts = 0
            self._mood_wait_track_id = None
            self._play_next_from_queue()
            return

        if self._mood_refill_exhausted:
            self._mood_wait_attempts = 0
            self._mood_wait_track_id = None
            self.statusBar().showMessage("No more tracks available for this Wave")
            return

        if self._mood_wait_attempts >= MOOD_SESSION_WAIT_ATTEMPTS:
            self._mood_wait_attempts = 0
            self._mood_wait_track_id = None
            self._mood_refill_exhausted = True
            self.statusBar().showMessage("No more tracks available for this Wave")
            return

        self._mood_wait_attempts += 1
        self._replenish_mood_session()
        self.statusBar().showMessage("Finding the next Wave track…")
        QTimer.singleShot(250, self._wait_for_mood_track)

    def _play_track(
        self,
        track_id: str,
        *,
        autoplay: bool = True,
    ) -> bool:
        track = self.store.get_track(track_id)

        if track is None or not track.local_path:
            self.statusBar().showMessage(f"Skipped unavailable track: {track_id}")
            return False

        audio_path = Path(track.local_path)

        if not audio_path.exists():
            self.statusBar().showMessage(f"Skipped missing file: {audio_path}")
            return False

        source_url = QUrl.fromLocalFile(str(audio_path.resolve()))
        self.current_track_id = track.id
        active_queue = self.playback_queue_service.queue
        if active_queue is not None:
            if active_queue.mode == QueueMode.RECOMMENDATIONS:
                self._radio_session_seen_track_ids.add(track.id)
            elif active_queue.mode == QueueMode.SESSION:
                self._mood_session_seen_track_ids.add(track.id)
        self._apply_track_loudness_gain(track)
        # A stale EndOfMedia event from the previous source can arrive while
        # Qt is switching to this one. Do not let it advance the new queue
        # item before the new source has reached a loaded state.
        self._last_end_of_media_track_id = None
        self._media_ready_for_end_of_media = False
        self._player_duration_ms = max(int(track.duration_ms or 0), 0)
        self.player_position_label.setText("0:00")
        self.player_duration_label.setText(
            self._format_duration(self._player_duration_ms)
        )
        self.player_progress_slider.setValue(0)
        self._current_track_played_ms = 0
        self._current_track_last_position_ms = None
        self._current_track_played_30s_recorded = False
        self._current_track_listen_recorded = False
        self._current_track_early_exit_recorded = False
        self._current_track_seeked_to_completion = False
        self.media_player.setSource(source_url)
        if autoplay:
            self.media_player.play()
        self._playback_state_settings.setValue(
            "playback/last_track_id",
            track.id,
        )
        self._radio_wait_attempts = 0
        self._radio_wait_seed_track_id = None
        self.player_title_label.setText(track.title)
        self.player_title_label.setToolTip(f"{track.title}\nClick for track actions")
        self.player_artist_label.setText(track.artist)
        self.player_artist_label.setToolTip(track.artist)
        self.player_cover.setText("")
        self.player_cover.setPixmap(
            track_cover_pixmap(track.title, track.cover_path, 46)
        )
        self._update_like_button()

        if autoplay:
            self._record_playback_signal(InteractionType.PLAY_START)

        self._load_history()
        self._load_queue()
        self._load_recommendations()
        self.statusBar().showMessage(
            f"{'Playing' if autoplay else 'Paused'}: {track.artist} — {track.title}"
        )
        return True

    def _stop_playback(self) -> None:
        self._record_early_exit_if_needed()
        self.media_player.stop()
        self.statusBar().showMessage("Playback stopped")

    def _skip_current_track(self) -> None:
        interaction_type = InteractionType.SKIP
        if self._player_duration_ms > 0 and self._current_track_played_ms < 30_000:
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

        self.like_button.set_svg(HEART_LIKED_ICON if is_liked else HEART_ICON)
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
                    mood_context=self._get_active_recommendation_context(),
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

        self.statusBar().showMessage(f"Playback error: {message}")

    def _handle_media_status_changed(
        self,
        status: QMediaPlayer.MediaStatus,
    ) -> None:
        if status in {
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        }:
            self._media_ready_for_end_of_media = True
            return

        if status != QMediaPlayer.MediaStatus.EndOfMedia:
            return

        current_track_id = self.current_track_id
        if (
            self._is_shutting_down
            or current_track_id is None
            or not self._media_ready_for_end_of_media
            or self._last_end_of_media_track_id == current_track_id
        ):
            return

        self._last_end_of_media_track_id = current_track_id

        if self._repeat_mode == RepeatMode.TRACK:
            self._current_track_listen_recorded = False
            self._current_track_played_30s_recorded = False
            self._current_track_played_ms = 0
            self._current_track_last_position_ms = 0
            self._current_track_seeked_to_completion = False
            self._last_end_of_media_track_id = None
            self.media_player.setPosition(0)
            self.media_player.play()
            self._record_playback_signal(InteractionType.REPEAT)
            self._record_playback_signal(InteractionType.PLAY_START)
            return

        if self._repeat_mode == RepeatMode.QUEUE:
            queue = self.playback_queue_service.restart_cycle()
            if queue is not None:
                if queue.mode == QueueMode.RECOMMENDATIONS:
                    self._replenish_recommendation_queue(force=True)
                self._load_queue()
                self._play_current_queue_track()
                return

        self._replenish_mood_session()
        self._play_next_from_queue()

    def _handle_volume_changed(
        self,
        value: int,
    ) -> None:
        self._apply_audio_output_volume(value)

        self.statusBar().showMessage(f"Volume: {value}%")

    def _set_loudness_normalization_enabled(self, enabled: bool) -> None:
        self._loudness_normalization_enabled = bool(enabled)
        self._volume_settings.setValue(
            "playback/loudness_normalization",
            self._loudness_normalization_enabled,
        )
        self._apply_audio_output_volume()
        self.statusBar().showMessage(
            "Loudness normalization "
            f"{'enabled' if self._loudness_normalization_enabled else 'disabled'}"
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
            self._apply_audio_output_volume(self.volume_slider.value())

    def _update_master_volume_label(self) -> None:
        if hasattr(self, "master_volume_label"):
            self.master_volume_label.setText(
                f"Master volume: {self._master_volume_percent}%"
            )

    @staticmethod
    def _clamp_master_volume_percent(value: int) -> int:
        return max(0, min(int(value), 100))

    def _apply_track_loudness_gain(self, track: Track) -> None:
        self._current_track_loudness_gain_db = (
            track.loudness_gain_db
            if self._track_has_loudness_analysis(track)
            else 0.0
        )
        self._apply_audio_output_volume()

    def _apply_audio_output_volume(self, value: int | None = None) -> None:
        if value is None:
            value = (
                self.volume_slider.value()
                if hasattr(self, "volume_slider")
                else DEFAULT_VOLUME_PERCENT
            )
        gain_db = (
            self._current_track_loudness_gain_db
            if self._loudness_normalization_enabled
            else 0.0
        )
        self.audio_output.setVolume(
            self._output_volume(
                value,
                self._master_volume_percent,
                gain_db,
            )
        )

    @staticmethod
    def _output_volume(
        value: int,
        master_volume: int = 100,
        track_gain_db: float = 0.0,
    ) -> float:
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
        normalization_gain = 10 ** (track_gain_db / 20)
        return min(
            1.0,
            response * MAX_AUDIO_GAIN * master_gain * normalization_gain,
        )

    def _get_active_recommendation_context(self) -> str | None:
        queue = self.playback_queue_service.queue

        if queue is None:
            return None

        if queue.source_playlist_id is not None:
            return f"playlist:{queue.source_playlist_id.casefold()}"

        if (
            queue.mode == QueueMode.RECOMMENDATIONS
            and self._radio_anchor_track_id is not None
        ):
            return f"track_radio:{self._radio_anchor_track_id.casefold()}"

        if queue.mode != QueueMode.SESSION:
            return None

        if self.session_genre_name is not None:
            return f"genre:{self.session_genre_name.casefold()}"
        return self.session_mood_name

    def _get_active_recommendation_session_id(self) -> str | None:
        queue = self.playback_queue_service.queue
        if queue is None:
            return None
        if queue.mode == QueueMode.RECOMMENDATIONS:
            return self._radio_impression_session_id
        if queue.mode == QueueMode.SESSION:
            return self._mood_session_impression_session_id
        return None

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
            InteractionType.RECOMMENDATION_SKIP,
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
                InteractionType.RECOMMENDATION_SKIP,
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
                mood_context=self._get_active_recommendation_context(),
                recommendation_session_id=(
                    self._get_active_recommendation_session_id()
                    if track_id == self.current_track_id
                    else None
                ),
            )
        except ValueError as error:
            self.statusBar().showMessage(f"Feedback failed: {error}")
            return

        self._load_recommendations()
        if advance and track_id == self.current_track_id:
            self._play_next_from_queue()

        status = "recorded" if result.created else "already recorded"
        self.statusBar().showMessage(f"Feedback {status}: {interaction_type.value}")

    def _refresh_content(self) -> None:
        self.recommendation_service.refresh()
        self._load_library()
        self._load_recommendations()

    def _restart_application(self) -> None:
        """Restart this process so edited Python modules are re-imported."""

        self._save_playback_state()
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
