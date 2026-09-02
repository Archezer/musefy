import random
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QPropertyAnimation,
    QRunnable,
    QSize,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsBlurEffect,
    QGraphicsOpacityEffect,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSlider,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import (
    DetectedGenre,
    InteractionType,
    Playlist,
    QueueMode,
    Track,
)
from app.domain.mood import MOOD_PRESETS
from app.domain.recommendations import RecommendationContext
from app.ingestion.audio import AudioIngestionService
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
from app.services.playback_queue import PlaybackQueueService
from app.services.playlists import PlaylistManagementService
from app.services.recommendations import RecommendationService
from app.services.tracks import TrackManagementService
from app.services.youtube_import import (
    SpotifyPlaylistSearchResult,
    SpotifySearchResult,
    YouTubeImportService,
    YouTubePlaylistImportResult,
)
from app.sources.youtube import YouTubeCandidate
from app.storage.paths import PLAYLIST_EXPORTS_DIR
from app.storage.protocols import MusicStore
from app.ui.dialogs import (
    PlaylistImportResultDialog,
    TrackMetadataDialog,
    YouTubeSearchDialog,
)
from app.ui.components import (
    HEART_ICON,
    IMPORT_ICON,
    JSON_ICON,
    LIBRARY_ICON,
    LOCAL_FILE_ICON,
    MAP_ICON,
    NEXT_ICON,
    PAUSE_ICON,
    PLAY_ICON,
    PREVIOUS_ICON,
    QUEUE_ICON,
    SPOTIFY_ICON,
    VOLUME_ICON,
    YOUTUBE_ICON,
    MoodPlaylistCard,
    PlaylistCard,
    QueueDialog,
    SvgIconButton,
    TrackIdentityWidget,
    track_cover_pixmap,
    svg_icon,
)
from app.ui.music_map import MusicMapWidget
from app.ui.theme import DARK_THEME

MAX_AUDIO_GAIN = 0.15
DEFAULT_VOLUME_PERCENT = 50
MAP_MODES = ("background", "hidden")


class YouTubeTaskThread(QThread):
    result_ready = Signal(object)
    error_occurred = Signal(str)
    progress_updated = Signal(int, int)
    track_imported = Signal(object, object)

    def __init__(
        self,
        task: Callable[[], object],
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self.task = task

    def run(self) -> None:
        try:
            result = self.task()
        except (OSError, RuntimeError, ValueError) as error:
            message = str(error) or error.__class__.__name__
            self.error_occurred.emit(message)
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


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: MusicStore,
        ingestion_service: AudioIngestionService,
        interaction_service: InteractionService,
        recommendation_service: RecommendationService,
        track_management_service: TrackManagementService,
        youtube_import_service: YouTubeImportService,
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
        self._youtube_thread: YouTubeTaskThread | None = None
        self._genre_statuses: dict[str, str] = {}
        self._genre_predictions: dict[str, object] = {}
        self._genre_batch_track_ids: set[str] = set()
        self._genre_batch_completed = 0
        self._genre_batch_total = 0
        self._analysis_pending_track_ids: set[str] = set()
        self._playlist_import_active = False
        self._music_map_mode = "background"
        self._player_duration_ms = 0
        self._genre_analysis_service = (
            GenreAnalysisService(
                top_k=10,
                min_score=0.1,
            )
        )
        self._genre_analysis_pool = QThreadPool(self)
        self._genre_analysis_pool.setMaxThreadCount(1)
        self._model_idle_timer = QTimer(self)
        self._model_idle_timer.setInterval(60_000)
        self._model_idle_timer.timeout.connect(
            self._unload_idle_models
        )
        self._model_idle_timer.start()

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(
            self._output_volume(DEFAULT_VOLUME_PERCENT)
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

        self.setWindowTitle("Music Recommendation System")
        self.resize(1240, 800)
        self.setStyleSheet(DARK_THEME)

        self._build_interface()
        self._load_playlists()
        self._load_library()
        self._load_recommendations()

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
        map_blur = QGraphicsBlurEffect(self.music_map)
        map_blur.setBlurRadius(2.4)
        self.music_map.setGraphicsEffect(map_blur)
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
        content_layout.setContentsMargins(12, 10, 12, 8)
        content_layout.setSpacing(8)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(9)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(142)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.setSpacing(6)

        import_button = QToolButton()
        import_button.setIcon(svg_icon(IMPORT_ICON, 19))
        import_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        import_button.setToolTip("Import music")
        import_button.setFixedSize(34, 32)
        import_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        import_menu = QMenu(import_button)
        local_action = import_menu.addAction("Local audio file", self._import_track)
        local_action.setIcon(svg_icon(LOCAL_FILE_ICON))
        youtube_action = import_menu.addAction("YouTube", self._import_from_youtube)
        youtube_action.setIcon(svg_icon(YOUTUBE_ICON))
        spotify_action = import_menu.addAction("Spotify", self._import_from_youtube)
        spotify_action.setIcon(svg_icon(SPOTIFY_ICON))
        exported_action = import_menu.addAction("Playlist JSON", self._import_exported_playlist)
        exported_action.setIcon(svg_icon(JSON_ICON))
        import_button.setMenu(import_menu)
        sidebar_layout.addWidget(import_button, 0, Qt.AlignmentFlag.AlignLeft)

        library_button = QToolButton()
        library_button.setIcon(svg_icon(LIBRARY_ICON, 19))
        library_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        library_button.setToolTip("Library actions")
        library_button.setFixedSize(34, 32)
        library_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        library_menu = QMenu(library_button)
        self.edit_button = library_menu.addAction(
            "Edit selected",
            self._edit_selected_track,
        )
        self.edit_button.setEnabled(False)
        self.delete_button = library_menu.addAction(
            "Delete selected",
            self._delete_selected_track,
        )
        self.delete_button.setEnabled(False)
        self.queue_selected_button = library_menu.addAction(
            "Add selected to queue",
            self._enqueue_selected_track,
        )
        self.queue_selected_button.setEnabled(False)
        library_menu.addSeparator()
        self.analyze_genres_button = library_menu.addAction(
            "Analyze selected",
            self._analyze_selected_track
        )
        self.analyze_genres_button.setEnabled(False)
        self.reanalyze_genres_button = library_menu.addAction(
            "Reanalyze library",
            self._reanalyze_all_genres
        )
        library_menu.addSeparator()
        library_menu.addAction("Refresh", self._refresh_content)
        library_button.setMenu(library_menu)
        sidebar_layout.addWidget(library_button, 0, Qt.AlignmentFlag.AlignLeft)

        self.map_cycle_button = QToolButton()
        self.map_cycle_button.setObjectName("mapCycleButton")
        self.map_cycle_button.setIcon(svg_icon(MAP_ICON, 19))
        self.map_cycle_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.map_cycle_button.setFixedSize(34, 32)
        self.map_cycle_button.setToolTip("Toggle the music graph background")
        self.map_cycle_button.clicked.connect(self._toggle_music_map)
        sidebar_layout.addWidget(self.map_cycle_button, 0, Qt.AlignmentFlag.AlignLeft)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setObjectName("sidebarSeparator")
        sidebar_layout.addWidget(separator)

        history_label = QLabel("History")
        history_label.setObjectName("sectionCaption")
        sidebar_layout.addWidget(history_label)
        self.history_list = QListWidget()
        self.history_list.setObjectName("historyList")
        self.history_list.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.history_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.history_list.itemDoubleClicked.connect(self._play_history_item)
        sidebar_layout.addWidget(self.history_list, 1)
        body_layout.addWidget(sidebar)

        main_column = QWidget()
        main_layout = QVBoxLayout(main_column)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(8)

        playlist_strip = QFrame()
        playlist_strip.setObjectName("playlistStrip")
        playlist_strip_layout = QVBoxLayout(playlist_strip)
        playlist_strip_layout.setContentsMargins(9, 5, 9, 5)
        playlist_strip_layout.setSpacing(3)
        playlist_label = QLabel("Playlists")
        playlist_label.setObjectName("sectionCaption")
        playlist_strip_layout.addWidget(playlist_label)

        self.playlist_scroll = QScrollArea()
        self.playlist_scroll.setWidgetResizable(True)
        self.playlist_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.playlist_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.playlist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.playlist_scroll.viewport().setAutoFillBackground(False)
        self.playlist_carousel = QWidget()
        self.playlist_carousel.setAutoFillBackground(False)
        self.playlist_carousel.setAttribute(
            Qt.WidgetAttribute.WA_TranslucentBackground
        )
        self.playlist_carousel_layout = QHBoxLayout(self.playlist_carousel)
        self.playlist_carousel_layout.setContentsMargins(0, 0, 0, 0)
        self.playlist_carousel_layout.setSpacing(9)
        self.playlist_carousel_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft
        )
        self.playlist_scroll.setWidget(self.playlist_carousel)
        playlist_strip_layout.addWidget(self.playlist_scroll)
        # Leave enough vertical room for the cover and its caption; the old
        # viewport was a few pixels shorter than the card itself.
        playlist_strip.setFixedHeight(116)
        main_layout.addWidget(playlist_strip)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        library_widget = self._build_library_panel()
        playlists_panel = self._build_playlists_panel()

        splitter.addWidget(library_widget)
        splitter.addWidget(playlists_panel)
        splitter.setSizes([760, 410])
        main_layout.addWidget(splitter, 1)
        body_layout.addWidget(main_column, 1)
        content_layout.addWidget(body, 1)

        content_layout.addWidget(self._build_player_bar())
        self.queue_dialog = QueueDialog(self)

        self.setCentralWidget(app_root)
        self.statusBar().showMessage("Ready")
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
        metadata_layout.setSpacing(1)
        self.player_title_label = QLabel("Nothing playing")
        self.player_title_label.setObjectName("playerTitle")
        self.player_artist_label = QLabel("Choose a track or playlist")
        self.player_artist_label.setObjectName("playerArtist")
        metadata_layout.addWidget(self.player_title_label)
        metadata_layout.addWidget(self.player_artist_label)
        layout.addLayout(metadata_layout, 2)

        center_layout = QVBoxLayout()
        center_layout.setSpacing(1)
        control_layout = QHBoxLayout()
        control_layout.setSpacing(4)
        control_layout.addStretch()

        previous_button = SvgIconButton(
            PREVIOUS_ICON,
            tooltip="Previous track",
            diameter=30,
            parent=player_bar,
        )
        previous_button.clicked.connect(self._go_previous)
        control_layout.addWidget(previous_button)

        self.player_play_button = SvgIconButton(
            PLAY_ICON,
            tooltip="Play or pause",
            diameter=34,
            parent=player_bar,
        )
        self.player_play_button.clicked.connect(self._toggle_playback)
        control_layout.addWidget(self.player_play_button)

        next_button = SvgIconButton(
            NEXT_ICON,
            tooltip="Next track",
            diameter=30,
            parent=player_bar,
        )
        next_button.clicked.connect(self._go_next)
        control_layout.addWidget(next_button)
        control_layout.addStretch()
        center_layout.addLayout(control_layout)

        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(6)
        self.player_position_label = QLabel("0:00")
        self.player_duration_label = QLabel("0:00")
        self.player_progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.player_progress_slider.setRange(0, 1000)
        self.player_progress_slider.sliderReleased.connect(self._seek_player)
        progress_layout.addWidget(self.player_position_label)
        progress_layout.addWidget(self.player_progress_slider, 1)
        progress_layout.addWidget(self.player_duration_label)
        center_layout.addLayout(progress_layout)
        layout.addLayout(center_layout, 5)

        next_track_layout = QVBoxLayout()
        next_track_layout.setSpacing(0)
        next_caption = QLabel("Next")
        next_caption.setObjectName("nextTrackCaption")
        self.next_track_title_label = QLabel("Nothing next")
        self.next_track_title_label.setObjectName("nextTrackTitle")
        self.next_track_artist_label = QLabel("")
        self.next_track_artist_label.setObjectName("nextTrackArtist")
        next_track_layout.addWidget(next_caption)
        next_track_layout.addWidget(self.next_track_title_label)
        next_track_layout.addWidget(self.next_track_artist_label)
        layout.addLayout(next_track_layout, 1)

        like_button = SvgIconButton(
            HEART_ICON,
            tooltip="Like current track",
            diameter=30,
            parent=player_bar,
        )
        like_button.clicked.connect(
            lambda: self._record_interaction(InteractionType.LIKE)
        )
        layout.addWidget(like_button)

        queue_button = SvgIconButton(
            QUEUE_ICON,
            tooltip="Show queue",
            diameter=30,
            parent=player_bar,
        )
        queue_button.clicked.connect(self._show_queue)
        layout.addWidget(queue_button)

        player_menu_button = QToolButton()
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
        player_menu.addAction("Stop playback", self._stop_playback)
        player_menu.addAction("Save current track", self._save_current_track)
        player_menu_button.setMenu(player_menu)
        layout.addWidget(player_menu_button)

        volume_button = SvgIconButton(
            VOLUME_ICON,
            tooltip="Volume",
            diameter=30,
            parent=player_bar,
        )
        volume_button.setEnabled(False)
        layout.addWidget(volume_button)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setFixedWidth(96)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(DEFAULT_VOLUME_PERCENT)
        self.volume_slider.valueChanged.connect(self._handle_volume_changed)
        layout.addWidget(self.volume_slider)

        player_bar.setFixedHeight(62)
        return player_bar

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "content_overlay"):
            return

        root_rect = self.centralWidget().rect()
        self.map_layer.setGeometry(root_rect)
        self.content_overlay.setGeometry(root_rect)

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
            "Hide music graph background"
            if mode == "background"
            else "Show music graph background"
        )

        target_opacity = 0.38 if mode == "background" else 0.0
        if not animated:
            self._map_opacity.setOpacity(target_opacity)
            self.map_layer.setVisible(mode == "background")
            return

        self.map_layer.show()
        self._map_opacity_animation.stop()
        self._map_opacity_animation.setStartValue(
            self._map_opacity.opacity()
        )
        self._map_opacity_animation.setEndValue(target_opacity)
        self._map_opacity_animation.start()

    def _toggle_music_map(self) -> None:
        self._set_music_map_mode(
            "hidden"
            if self._music_map_mode == "background"
            else "background"
        )

    def _refresh_music_map(self) -> None:
        self.music_map.set_tracks(list(self.store.list_tracks()))

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
        panel = QFrame()
        panel.setObjectName("glassPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Music library"))

        self.track_table = QTableWidget()
        self.track_table.setColumnCount(5)
        self.track_table.setHorizontalHeaderLabels(
            [
                "#",
                "Title",
                "Genres",
                "Duration",
                "Analysis",
            ]
        )
        self.track_table.verticalHeader().setVisible(False)
        self.track_table.verticalHeader().setDefaultSectionSize(52)
        header = self.track_table.horizontalHeader()
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
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.track_table.setColumnHidden(4, True)
        self.track_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.track_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.track_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.track_table.itemSelectionChanged.connect(
            self._handle_track_selection
        )
        self.track_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.track_table.customContextMenuRequested.connect(
            self._show_track_context_menu
        )

        layout.addWidget(self.track_table)

        return panel

    def _build_playlists_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("glassPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        playlist_actions = QHBoxLayout()

        create_button = QPushButton("New")
        create_button.clicked.connect(self._create_playlist)

        rename_button = QPushButton("Rename")
        rename_button.clicked.connect(self._rename_playlist)

        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete_playlist)

        cover_button = QPushButton("Artwork")
        cover_button.clicked.connect(self._set_playlist_cover)

        playlist_actions.addWidget(create_button)
        playlist_actions.addWidget(rename_button)
        playlist_actions.addWidget(cover_button)
        playlist_actions.addWidget(delete_button)
        playlist_actions.addStretch()

        layout.addLayout(playlist_actions)
        layout.addWidget(QLabel("Your playlists"))

        self.playlist_list = QListWidget()
        self.playlist_list.itemSelectionChanged.connect(
            self._handle_playlist_selection
        )
        layout.addWidget(self.playlist_list)

        track_actions = QHBoxLayout()

        add_track_button = QPushButton("Add selected track")
        add_track_button.clicked.connect(
            self._add_selected_track_to_playlist
        )

        remove_track_button = QPushButton("Remove track")
        remove_track_button.clicked.connect(
            self._remove_selected_playlist_track
        )

        track_actions.addWidget(add_track_button)
        track_actions.addWidget(remove_track_button)
        track_actions.addStretch()

        layout.addLayout(track_actions)
        layout.addWidget(QLabel("Playlist tracks"))

        self.playlist_track_list = QListWidget()
        layout.addWidget(self.playlist_track_list)

        playback_actions = QHBoxLayout()

        play_button = QPushButton("Play playlist")
        play_button.clicked.connect(self._play_playlist)

        shuffle_button = QPushButton("Shuffle playlist")
        shuffle_button.clicked.connect(self._shuffle_playlist)

        smart_shuffle_button = QPushButton("Smart shuffle")
        smart_shuffle_button.clicked.connect(
            self._smart_shuffle_playlist
        )

        playback_actions.addWidget(play_button)
        playback_actions.addWidget(shuffle_button)
        playback_actions.addWidget(smart_shuffle_button)
        playback_actions.addStretch()

        layout.addLayout(playback_actions)

        return panel

    def _load_library(self) -> None:
        tracks = list(self.store.list_tracks())
        self.recommendation_service.refresh()

        self.track_table.setRowCount(0)
        self.track_table.setRowCount(len(tracks))

        for row_index, track in enumerate(tracks):
            self._populate_track_row(row_index, track)

        self._load_queue()
        self._load_history()
        self._refresh_music_map()
        self.statusBar().showMessage(
            f"Loaded {len(tracks)} tracks"
        )

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
                and interaction.interaction_type == InteractionType.PLAY
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
        number_item = QTableWidgetItem(str(row_index + 1))
        number_item.setTextAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        number_item.setData(
            Qt.ItemDataRole.UserRole,
            track.id,
        )

        self.track_table.setItem(
            row_index,
            0,
            number_item,
        )
        track_identity = TrackIdentityWidget(
            track.title,
            track.artist,
            cover_path=track.cover_path,
        )
        track_identity.play_requested.connect(
            lambda track_id=track.id: self._play_track_now(track_id)
        )
        self.track_table.setCellWidget(
            row_index,
            1,
            track_identity,
        )
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
            QTableWidgetItem(
                self._format_duration(track.duration_ms)
            ),
        )
        self.track_table.setItem(
            row_index,
            4,
            QTableWidgetItem(
                self._genre_statuses.get(
                    track.id,
                    "Not analyzed",
                )
            ),
        )

    def _append_library_track(self, track: Track) -> None:
        for row_index in range(self.track_table.rowCount()):
            title_item = self.track_table.item(row_index, 0)
            if title_item is None:
                continue
            if title_item.data(Qt.ItemDataRole.UserRole) != track.id:
                continue

            self._populate_track_row(row_index, track)
            return

        row_index = self.track_table.rowCount()
        self.track_table.insertRow(row_index)
        self._populate_track_row(row_index, track)

    def _update_library_track_row(self, track: Track) -> None:
        for row_index in range(self.track_table.rowCount()):
            title_item = self.track_table.item(row_index, 0)
            if title_item is None:
                continue
            if title_item.data(Qt.ItemDataRole.UserRole) != track.id:
                continue

            self._populate_track_row(row_index, track)
            return

    def _remove_library_track_row(self, track_id: str) -> None:
        for row_index in range(self.track_table.rowCount()):
            title_item = self.track_table.item(row_index, 0)
            if title_item is None:
                continue
            if title_item.data(Qt.ItemDataRole.UserRole) != track_id:
                continue

            self.track_table.removeRow(row_index)
            return

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

        if self.selected_mood_name is not None:
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

        recommendations = self.recommendation_service.get_recommendations(
            user_id=self.user_id,
            limit=10,
            context=context,
        )

        self.recommendation_list.clear()

        for recommendation in recommendations:
            track = recommendation.track

            text = (
                f"{track.artist} — {track.title} "
                f"(match: {recommendation.match_score:.2f})"
            )

            self.recommendation_list.addItem(text)

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
        self.selected_mood_name = mood_name
        self._start_mood_session()

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

        target_mood = MOOD_PRESETS[self.session_mood_name]
        recommendations = self.recommendation_service.get_recommendations(
            user_id=self.user_id,
            limit=10,
            context=RecommendationContext.mood(
                target_mood,
                mood_name=self.session_mood_name,
            ),
        )
        existing_ids = {
            queue.current_track_id,
            *self.playback_queue_service.upcoming_track_ids(),
        }

        for recommendation in recommendations:
            track = recommendation.track
            if track.id in existing_ids:
                continue
            if track.mood is None:
                continue
            if not track.local_path or not Path(track.local_path).exists():
                continue

            self.playback_queue_service.enqueue(track.id)
            existing_ids.add(track.id)

    def _load_queue(self) -> None:
        queue = self.playback_queue_service.queue
        track_ids = (
            self.playback_queue_service.upcoming_track_ids()
            if queue is not None
            else ()
        )
        tracks = [
            track
            for track_id in track_ids
            if (track := self.store.get_track(track_id)) is not None
        ]

        if tracks:
            next_track = tracks[0]
            self.next_track_title_label.setText(next_track.title)
            self.next_track_artist_label.setText(next_track.artist)
        else:
            self.next_track_title_label.setText("Nothing next")
            self.next_track_artist_label.setText("")

        self.queue_dialog.set_tracks(
            [(track.title, track.artist) for track in tracks]
        )

    def _show_queue(self) -> None:
        self._load_queue()
        self.queue_dialog.show()
        self.queue_dialog.raise_()
        self.queue_dialog.activateWindow()

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

        self.playback_queue_service.start((track_id,))
        self._play_current_queue_track()

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

    def _load_playlists(self) -> None:
        playlists = self.playlist_management_service.list_playlists()
        selected_playlist_id = self.selected_playlist_id

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

        self._populate_playlist_carousel(playlists)

    def _populate_playlist_carousel(
        self,
        playlists: list[Playlist],
    ) -> None:
        while self.playlist_carousel_layout.count():
            item = self.playlist_carousel_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        mood_card = MoodPlaylistCard(tuple(MOOD_PRESETS))
        mood_card.mood_selected.connect(self._start_mood_session_from_card)
        self.playlist_carousel_layout.addWidget(mood_card)

        if not playlists:
            empty_label = QLabel(
                "Create a playlist to keep favourite moments together."
            )
            empty_label.setObjectName("appSubtitle")
            self.playlist_carousel_layout.addWidget(empty_label)
            self.playlist_carousel_layout.addStretch()
            return

        for playlist in playlists:
            card = PlaylistCard(
                playlist_id=playlist.id,
                name=playlist.name,
                cover_path=playlist.cover_path,
            )
            card.set_selected(playlist.id == self.selected_playlist_id)
            card.activated.connect(self._select_playlist_from_carousel)
            self.playlist_carousel_layout.addWidget(card)

        self.playlist_carousel_layout.addStretch()

    def _select_playlist_from_carousel(self, playlist_id: str) -> None:
        for index in range(self.playlist_list.count()):
            item = self.playlist_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == playlist_id:
                self.playlist_list.setCurrentItem(item)
                return

    def _set_playlist_cover(self) -> None:
        playlist = self._get_selected_playlist()
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
            self.selected_playlist_id = None
            self.playlist_track_list.clear()
            self._populate_playlist_carousel(
                self.playlist_management_service.list_playlists()
            )
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

        tracks = self.playlist_management_service.get_playlist_tracks(
            self.selected_playlist_id
        )

        for position, track in enumerate(tracks):
            item = QListWidgetItem(
                f"{track.artist} — {track.title}"
            )
            item.setData(Qt.ItemDataRole.UserRole, position)
            self.playlist_track_list.addItem(item)

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
        self._load_playlists()

    def _rename_playlist(self) -> None:
        playlist = self._get_selected_playlist()

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

    def _delete_playlist(self) -> None:
        playlist = self._get_selected_playlist()

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

        self.playlist_management_service.delete_playlist(playlist.id)
        self.selected_playlist_id = None
        self._load_playlists()

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

        item = self.playlist_track_list.currentItem()

        if item is None:
            QMessageBox.warning(
                self,
                "No playlist track selected",
                "Select a playlist track first.",
            )
            return

        position = item.data(Qt.ItemDataRole.UserRole)

        if not isinstance(position, int):
            return

        self.playlist_management_service.remove_track_at(
            self.selected_playlist_id,
            position,
        )
        self._load_selected_playlist_tracks()

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
    ) -> None:
        playlist = self._get_selected_playlist()

        if playlist is None:
            return

        tracks = self.playlist_management_service.get_playlist_tracks(
            playlist.id
        )

        if not tracks:
            QMessageBox.information(
                self,
                "Playlist is empty",
                "Add at least one track before playback.",
            )
            return

        track_ids = [track.id for track in tracks]

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
            random.shuffle(track_ids)

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

    def _handle_track_selection(self) -> None:
        selected_items = self.track_table.selectedItems()

        if not selected_items:
            self.selected_track_id = None
            self.edit_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            self.queue_selected_button.setEnabled(False)
            self.analyze_genres_button.setEnabled(False)
            self._load_recommendations()
            return

        title_item = selected_items[0]

        self.selected_track_id = title_item.data(
            Qt.ItemDataRole.UserRole
        )
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
        if (
            self._player_duration_ms <= 0
            or self.player_progress_slider.isSliderDown()
        ):
            return

        self.player_progress_slider.setValue(
            round(position_ms * 1000 / self._player_duration_ms)
        )

    def _seek_player(self) -> None:
        if self._player_duration_ms <= 0:
            return

        position_ms = round(
            self.player_progress_slider.value()
            * self._player_duration_ms
            / self.player_progress_slider.maximum()
        )
        self.media_player.setPosition(position_ms)

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

    def _import_from_youtube(self) -> None:
        dialog = YouTubeSearchDialog(self)
        dialog.search_requested.connect(
            lambda query: self._start_youtube_search(
                dialog,
                query,
            )
        )
        dialog.authenticate_requested.connect(
            lambda url: self._start_url_authentication(
                dialog,
                url,
            )
        )
        dialog.url_load_requested.connect(
            lambda url: self._start_url_load(
                dialog,
                url,
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
            lambda candidates: self._start_youtube_playlist_import(
                dialog,
                candidates,
            )
        )

        dialog.exec()

    def _import_exported_playlist(self) -> None:
        export_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open exported playlist",
            str(PLAYLIST_EXPORTS_DIR),
            "Playlist exports (*.json)",
        )

        if not export_path:
            return

        dialog = YouTubeSearchDialog(self)
        dialog.set_busy(True, "Reading exported playlist...")
        dialog.playlist_import_requested.connect(
            lambda candidates: self._start_youtube_playlist_import(
                dialog,
                candidates,
            )
        )

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.search_playlist_export(
                Path(export_path)
            ),
            self,
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
        dialog.exec()

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

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.search(query),
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

        dialog.set_busy(True, "Authenticating URL source...")

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

        dialog.set_busy(True, "Detecting and loading URL...")

        thread = YouTubeTaskThread(
            lambda: self.youtube_import_service.load_url(url),
            self,
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

        def import_playlist() -> YouTubePlaylistImportResult:
            return self.youtube_import_service.download_and_import_playlist(
                selected_candidates,
                on_progress=thread.progress_updated.emit,
                on_track_imported=thread.track_imported.emit,
            )

        thread = YouTubeTaskThread(import_playlist, self)
        thread.track_imported.connect(
            lambda candidate, track: (
                self._handle_youtube_playlist_track_imported(
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

    def _start_youtube_thread(
        self,
        thread: YouTubeTaskThread,
        dialog: YouTubeSearchDialog,
    ) -> None:
        self._youtube_thread = thread
        thread.finished.connect(
            lambda: self._finish_youtube_thread(dialog)
        )
        thread.start()

    def _finish_youtube_thread(
        self,
        dialog: YouTubeSearchDialog,
    ) -> None:
        if self._youtube_thread is not None:
            self._youtube_thread.deleteLater()
            self._youtube_thread = None

        if dialog.isVisible():
            dialog.set_busy(False, dialog.status_label.text())

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

        dialog.set_busy(False, result)
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
                "YouTube import returned an invalid result.",
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
            "YouTube import completed",
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
        if result.failed or unmatched:
            failed_candidates = [
                candidate for candidate, _ in result.failed
            ]
            dialog.set_candidates(
                failed_candidates,
                playlist=True,
                playlist_name=dialog.playlist_name,
                playlist_cover_url=dialog.playlist_cover_url,
                unmatched=unmatched,
            )
            dialog.set_busy(
                False,
                (
                    f"{len(failed_candidates) + len(unmatched)} "
                    "tracks failed or were not found."
                ),
            )

            result_dialog = PlaylistImportResultDialog(
                len(result.imported),
                result.failed,
                dialog,
                unmatched=unmatched,
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
            if not result.failed:
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

    def _handle_youtube_playlist_track_imported(
        self,
        dialog: YouTubeSearchDialog,
        candidate: YouTubeCandidate,
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

        self.playback_queue_service.start(
            (self.selected_track_id,)
        )
        self._play_current_queue_track()

    def _go_previous(self) -> None:
        if self.media_player.position() > 0:
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
        while True:
            queue = self.playback_queue_service.advance()

            if queue is None:
                self.current_track_id = None
                self.media_player.stop()
                self._load_queue()
                self.statusBar().showMessage("Queue finished")
                return

            if (
                queue.current_track_id is not None
                and self._play_track(queue.current_track_id)
            ):
                return

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
        self.media_player.setSource(source_url)
        self.media_player.play()
        self.current_track_id = track.id
        self.player_title_label.setText(track.title)
        self.player_artist_label.setText(track.artist)
        self.player_cover.setText("")
        self.player_cover.setPixmap(
            track_cover_pixmap(track.title, track.cover_path, 46)
        )

        try:
            self.interaction_service.record(
                user_id=self.user_id,
                track_id=track.id,
                interaction_type=InteractionType.PLAY,
                mood_context=self._get_active_mood_context(),
            )
        except ValueError as error:
            self.statusBar().showMessage(
                f"Interaction failed: {error}"
            )

        self._load_history()
        self._load_queue()
        self._load_recommendations()
        self.statusBar().showMessage(
            f"Playing: {track.artist} — {track.title}"
        )
        return True

    def _stop_playback(self) -> None:
        self.media_player.stop()
        self.statusBar().showMessage(
            "Playback stopped"
        )

    def _skip_current_track(self) -> None:
        self._record_interaction(InteractionType.SKIP)

    def _save_current_track(self) -> None:
        self._record_interaction(InteractionType.SAVE)

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
            self._replenish_mood_session()
            self._play_next_from_queue()

    def _handle_volume_changed(
        self,
        value: int,
    ) -> None:
        self.audio_output.setVolume(
            self._output_volume(value)
        )

        self.statusBar().showMessage(
            f"Volume: {value}%"
        )

    @staticmethod
    def _output_volume(value: int) -> float:
        return max(0, min(value, 100)) / 100 * MAX_AUDIO_GAIN

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

        try:
            result = self.interaction_service.record(
                user_id=self.user_id,
                track_id=self.current_track_id,
                interaction_type=interaction_type,
                mood_context=self._get_active_mood_context(),
            )
        except ValueError as error:
            QMessageBox.warning(
                self,
                "Interaction failed",
                str(error),
            )
            return

        self._load_recommendations()

        if interaction_type == InteractionType.SKIP:
            self._play_next_from_queue()

        if result.created:
            message = (
                f"Interaction recorded: "
                f"{interaction_type.value}"
            )
        else:
            message = (
                f"Interaction already exists: "
                f"{interaction_type.value}"
            )

        self.statusBar().showMessage(message)

    def _refresh_content(self) -> None:
        self._load_library()
        self._load_recommendations()

    @staticmethod
    def _format_duration(
        duration_ms: int | None,
    ) -> str:
        if duration_ms is None:
            return "Unknown"

        total_seconds = duration_ms // 1000
        minutes, seconds = divmod(total_seconds, 60)

        return f"{minutes}:{seconds:02d}"
