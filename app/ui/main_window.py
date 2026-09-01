import random
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    QObject,
    QRunnable,
    Qt,
    QThread,
    QThreadPool,
    QUrl,
    Signal,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
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
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
from app.ingestion.audio import AudioIngestionService
from app.ingestion.metadata import read_audio_metadata
from app.ml.genre_analysis import GenreAnalysisService
from app.ml.maest import (
    GenrePrediction,
    MaestAnalysisResult,
)
from app.recommenders.similarity import TrackSimilarityIndex
from app.recommenders.smart_shuffle import SmartShuffleBuilder
from app.services.interactions import InteractionService
from app.services.playback_queue import PlaybackQueueService
from app.services.playlists import PlaylistManagementService
from app.services.recommendations import RecommendationService
from app.services.tracks import TrackManagementService
from app.services.youtube_import import YouTubeImportService
from app.sources.youtube import YouTubeCandidate
from app.storage.protocols import MusicStore
from app.ui.dialogs import (
    TrackMetadataDialog,
    YouTubeSearchDialog,
)


class YouTubeTaskThread(QThread):
    result_ready = Signal(object)
    error_occurred = Signal(str)

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
            analysis_result = self.service.analyze_result(
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
        self.current_track_id: str | None = None
        self._youtube_thread: YouTubeTaskThread | None = None
        self._genre_statuses: dict[str, str] = {}
        self._genre_predictions: dict[str, object] = {}
        self._genre_batch_track_ids: set[str] = set()
        self._genre_batch_completed = 0
        self._genre_batch_total = 0
        self._genre_analysis_service = (
            GenreAnalysisService(
                top_k=10,
                min_score=0.1,
            )
        )
        self._genre_analysis_pool = QThreadPool(self)
        self._genre_analysis_pool.setMaxThreadCount(1)

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.7)

        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.errorOccurred.connect(
            self._handle_player_error
        )
        self.media_player.mediaStatusChanged.connect(
            self._handle_media_status_changed
        )

        self.setWindowTitle("Music Recommendation System")
        self.resize(1100, 700)

        self._build_interface()
        self._load_playlists()
        self._load_library()
        self._load_recommendations()

    def _build_interface(self) -> None:
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)

        toolbar = QHBoxLayout()

        import_button = QPushButton("Import track")
        import_button.clicked.connect(self._import_track)

        youtube_button = QPushButton(
            "Add from YouTube"
        )
        youtube_button.clicked.connect(
            self._import_from_youtube
        )

        self.edit_button = QPushButton("Edit track")
        self.edit_button.clicked.connect(
            self._edit_selected_track
        )
        self.edit_button.setEnabled(False)

        self.delete_button = QPushButton("Delete track")
        self.delete_button.clicked.connect(
            self._delete_selected_track
        )
        self.delete_button.setEnabled(False)

        self.analyze_genres_button = QPushButton(
            "Analyze genres"
        )
        self.analyze_genres_button.clicked.connect(
            self._analyze_selected_track
        )
        self.analyze_genres_button.setEnabled(False)

        self.reanalyze_genres_button = QPushButton(
            "Reanalyze all genres"
        )
        self.reanalyze_genres_button.clicked.connect(
            self._reanalyze_all_genres
        )

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_content)

        toolbar.addWidget(import_button)
        toolbar.addWidget(youtube_button)
        toolbar.addWidget(self.edit_button)
        toolbar.addWidget(self.delete_button)
        toolbar.addWidget(self.analyze_genres_button)
        toolbar.addWidget(self.reanalyze_genres_button)
        toolbar.addWidget(refresh_button)
        toolbar.addStretch()

        main_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        library_widget = self._build_library_panel()
        right_tabs = QTabWidget()
        right_tabs.addTab(
            self._build_recommendations_panel(),
            "Discover",
        )
        right_tabs.addTab(
            self._build_playlists_panel(),
            "Playlists",
        )

        splitter.addWidget(library_widget)
        splitter.addWidget(right_tabs)
        splitter.setSizes([700, 400])

        main_layout.addWidget(splitter)

        actions_layout = QHBoxLayout()

        play_button = QPushButton("Play")
        play_button.clicked.connect(
            self._play_selected_track
        )

        stop_button = QPushButton("Stop")
        stop_button.clicked.connect(
            self._stop_playback
        )

        play_queue_button = QPushButton("Play queue")
        play_queue_button.clicked.connect(self._play_queue)

        like_button = QPushButton("Like")
        like_button.clicked.connect(
            lambda: self._record_interaction(
                InteractionType.LIKE
            )
        )

        skip_button = QPushButton("Skip")
        skip_button.clicked.connect(
            lambda: self._record_interaction(
                InteractionType.SKIP
            )
        )

        save_button = QPushButton("Save")
        save_button.clicked.connect(
            lambda: self._record_interaction(
                InteractionType.SAVE
            )
        )

        actions_layout.addWidget(play_button)
        actions_layout.addWidget(stop_button)
        actions_layout.addWidget(play_queue_button)
        actions_layout.addWidget(like_button)
        actions_layout.addWidget(skip_button)
        actions_layout.addWidget(save_button)
        actions_layout.addStretch()

        main_layout.addLayout(actions_layout)

        volume_layout = QHBoxLayout()

        volume_layout.addWidget(
            QLabel("Volume")
        )

        self.volume_slider = QSlider(
            Qt.Orientation.Horizontal
        )
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.valueChanged.connect(
            self._handle_volume_changed
        )

        volume_layout.addWidget(
            self.volume_slider
        )

        main_layout.addLayout(volume_layout)

        self.setCentralWidget(central_widget)
        self.statusBar().showMessage("Ready")

    def _build_library_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        layout.addWidget(QLabel("Music library"))

        self.track_table = QTableWidget()
        self.track_table.setColumnCount(5)
        self.track_table.setHorizontalHeaderLabels(
            [
                "Title",
                "Artist",
                "Duration",
                "Genres (top 2)",
                "Genre analysis",
            ]
        )
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

    def _build_recommendations_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        layout.addWidget(
            QLabel("Recommendations for current user")
        )

        self.recommendation_list = QListWidget()
        layout.addWidget(self.recommendation_list)

        layout.addWidget(QLabel("Up next"))
        self.queue_list = QListWidget()
        layout.addWidget(self.queue_list)

        return panel

    def _build_playlists_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        playlist_actions = QHBoxLayout()

        create_button = QPushButton("New")
        create_button.clicked.connect(self._create_playlist)

        rename_button = QPushButton("Rename")
        rename_button.clicked.connect(self._rename_playlist)

        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self._delete_playlist)

        playlist_actions.addWidget(create_button)
        playlist_actions.addWidget(rename_button)
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

        self.track_table.setRowCount(0)
        self.track_table.setRowCount(len(tracks))

        for row_index, track in enumerate(tracks):
            title_item = QTableWidgetItem(track.title)
            title_item.setData(
                Qt.ItemDataRole.UserRole,
                track.id,
            )

            self.track_table.setItem(
                row_index,
                0,
                title_item,
            )
            self.track_table.setItem(
                row_index,
                1,
                QTableWidgetItem(track.artist),
            )
            self.track_table.setItem(
                row_index,
                2,
                QTableWidgetItem(
                    self._format_duration(track.duration_ms)
                ),
            )
            self.track_table.setItem(
                row_index,
                3,
                QTableWidgetItem(
                    self._format_display_genres(track)
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

        self.track_table.resizeColumnsToContents()
        self._load_queue()
        self.statusBar().showMessage(
            f"Loaded {len(tracks)} tracks"
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
        recommendations = (
            self.recommendation_service.get_recommendations(
                user_id=self.user_id,
                limit=10,
            )
        )

        self.recommendation_list.clear()

        for recommendation in recommendations:
            track = recommendation.track

            text = (
                f"{track.artist} — {track.title} "
                f"(score: {recommendation.score:.1f})"
            )

            self.recommendation_list.addItem(text)

    def _load_queue(self) -> None:
        self.queue_list.clear()
        queue = self.playback_queue_service.queue

        if queue is None:
            self.queue_list.addItem("Queue is empty")
            return

        for prefix, track_ids in (
            ("Queued", queue.queued_track_ids),
            ("Planned", queue.remaining_track_ids),
        ):
            for track_id in track_ids:
                track = self.store.get_track(track_id)
                track_name = (
                    f"{track.artist} — {track.title}"
                    if track is not None
                    else "Missing track"
                )
                self.queue_list.addItem(
                    f"{prefix}: {track_name}"
                )

    def _show_track_context_menu(self, position: object) -> None:
        item = self.track_table.itemAt(position)

        if item is None:
            return

        title_item = self.track_table.item(item.row(), 0)

        if title_item is None:
            return

        track_id = title_item.data(Qt.ItemDataRole.UserRole)

        if not isinstance(track_id, str):
            return

        menu = QMenu(self)
        add_to_queue_action = menu.addAction("Add to queue")
        add_to_queue_action.triggered.connect(
            lambda checked=False, selected_track_id=track_id: (
                self._enqueue_track(selected_track_id)
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

        menu.exec(
            self.track_table.viewport().mapToGlobal(position)
        )

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

    def _handle_playlist_selection(self) -> None:
        selected_items = self.playlist_list.selectedItems()

        if not selected_items:
            self.selected_playlist_id = None
            self.playlist_track_list.clear()
            return

        playlist_id = selected_items[0].data(
            Qt.ItemDataRole.UserRole
        )

        if not isinstance(playlist_id, str):
            return

        self.selected_playlist_id = playlist_id
        self._load_selected_playlist_tracks()

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
            self.analyze_genres_button.setEnabled(False)
            return

        title_item = selected_items[0]

        self.selected_track_id = title_item.data(
            Qt.ItemDataRole.UserRole
        )
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.analyze_genres_button.setEnabled(
            self._genre_statuses.get(
                self.selected_track_id,
                "Not analyzed",
            )
            != "Queued"
        )

        self.statusBar().showMessage(
            f"Selected track: {title_item.text()}"
        )

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

        self._enqueue_genre_analysis(track)
        self._load_library()
        self._load_recommendations()

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
        dialog.import_requested.connect(
            lambda candidate: (
                self._start_youtube_import(
                    dialog,
                    candidate,
                )
            )
        )
        dialog.url_import_requested.connect(
            lambda url: self._start_youtube_url_import(
                dialog,
                url,
            )
        )

        dialog.exec()

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

    def _start_youtube_url_import(
        self,
        dialog: YouTubeSearchDialog,
        url: str,
    ) -> None:
        if self._youtube_thread is not None:
            return

        dialog.set_busy(True, "Downloading YouTube URL...")

        thread = YouTubeTaskThread(
            lambda: (
                self.youtube_import_service
                .download_and_import_url(url)
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
        self._enqueue_genre_analysis(track)
        self._load_library()
        self._load_recommendations()

        QMessageBox.information(
            self,
            "YouTube import completed",
            (
                f"Added to Library:\n"
                f"{track.artist} — {track.title}"
            ),
        )

    def _enqueue_genre_analysis(
        self,
        track: Track,
    ) -> None:
        if not track.local_path:
            self._genre_statuses[track.id] = (
                "No local file"
            )
            return

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
            f"Genre analysis queued: {track.title}"
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
            "Reanalyze all genres",
            (
                f"Analyze genres for {len(local_tracks)} local tracks?\n"
                "The current detected genres will be replaced."
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

    def _handle_genre_analysis_result(
        self,
        track_id: str,
        analysis_result: object,
    ) -> None:
        if not isinstance(
            analysis_result,
            MaestAnalysisResult,
        ):
            self._handle_genre_analysis_error(
                track_id,
                "Genre analysis returned an invalid result.",
            )
            return

        predictions = list(
            analysis_result.genres
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
            self.track_management_service.update_detected_genres(
                track_id=track_id,
                detected_genres=detected_genres,
                track_embedding=tuple(
                    float(value)
                    for value in analysis_result.track_embedding
                ),
            )
        except (OSError, RuntimeError, ValueError) as error:
            self._handle_genre_analysis_error(
                track_id,
                str(error),
            )
            return

        self._genre_statuses[track_id] = "Completed"
        self._genre_predictions[track_id] = (
            analysis_result
        )
        self._set_genre_status(track_id, "Completed")
        if self.selected_track_id == track_id:
            self.analyze_genres_button.setEnabled(True)

        self._load_library()
        self._load_recommendations()

        if self._finish_genre_batch_item(track_id):
            return

        track = self.store.get_track(track_id)
        track_name = (
            track.title
            if track is not None
            else track_id
        )

        self.statusBar().showMessage(
            f"Genre analysis completed: {track_name}"
        )

    def _handle_genre_analysis_error(
        self,
        track_id: str,
        message: str,
    ) -> None:
        self._genre_statuses[track_id] = "Failed"
        self._set_genre_status(track_id, "Failed")
        if self.selected_track_id == track_id:
            self.analyze_genres_button.setEnabled(True)
        if self._finish_genre_batch_item(track_id):
            return
        self.statusBar().showMessage(
            f"Genre analysis failed: {message}"
        )

    @staticmethod
    def _handle_youtube_error(
        dialog: YouTubeSearchDialog,
        message: str,
    ) -> None:
        dialog.show_error(message)

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

        self._load_library()
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

        self.selected_track_id = None
        if self.current_track_id == track.id:
            self.current_track_id = None
            self.playback_queue_service.clear()
        self._load_library()
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
        self.media_player.setSource(source_url)
        self.media_player.play()
        self.current_track_id = track.id

        try:
            self.interaction_service.record(
                user_id=self.user_id,
                track_id=track.id,
                interaction_type=InteractionType.PLAY,
            )
        except ValueError as error:
            self.statusBar().showMessage(
                f"Interaction failed: {error}"
            )

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
            self._play_next_from_queue()

    def _handle_volume_changed(
        self,
        value: int,
    ) -> None:
        self.audio_output.setVolume(
            value / 100
        )

        self.statusBar().showMessage(
            f"Volume: {value}%"
        )

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
