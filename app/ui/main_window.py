from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSlider,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import InteractionType
from app.ingestion.audio import AudioIngestionService
from app.ingestion.metadata import read_audio_metadata
from app.services.interactions import InteractionService
from app.services.recommendations import RecommendationService
from app.services.tracks import TrackManagementService
from app.storage.protocols import MusicStore
from app.ui.dialogs import TrackMetadataDialog


class MainWindow(QMainWindow):
    def __init__(
        self,
        store: MusicStore,
        ingestion_service: AudioIngestionService,
        interaction_service: InteractionService,
        recommendation_service: RecommendationService,
        track_management_service: TrackManagementService,
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
        self.user_id = user_id
        self.current_track_id: str | None = None

        self.audio_output = QAudioOutput(self)
        self.audio_output.setVolume(0.7)

        self.media_player = QMediaPlayer(self)
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.errorOccurred.connect(
            self._handle_player_error
        )

        self.setWindowTitle("Music Recommendation System")
        self.resize(1100, 700)

        self._build_interface()
        self._load_library()
        self._load_recommendations()

    def _build_interface(self) -> None:
        central_widget = QWidget()
        main_layout = QVBoxLayout(central_widget)

        toolbar = QHBoxLayout()

        import_button = QPushButton("Import track")
        import_button.clicked.connect(self._import_track)

        self.edit_button = QPushButton("Edit track")
        self.edit_button.clicked.connect(
            self._edit_selected_track
        )
        self.edit_button.setEnabled(False)

        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self._refresh_content)

        toolbar.addWidget(import_button)
        toolbar.addWidget(self.edit_button)
        toolbar.addWidget(refresh_button)
        toolbar.addStretch()

        main_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        library_widget = self._build_library_panel()
        recommendations_widget = self._build_recommendations_panel()

        splitter.addWidget(library_widget)
        splitter.addWidget(recommendations_widget)
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
        self.track_table.setColumnCount(4)
        self.track_table.setHorizontalHeaderLabels(
            [
                "Title",
                "Artist",
                "Duration",
                "Genres",
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
                    ", ".join(track.genres)
                ),
            )

        self.track_table.resizeColumnsToContents()
        self.statusBar().showMessage(
            f"Loaded {len(tracks)} tracks"
        )

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

    def _handle_track_selection(self) -> None:
        selected_items = self.track_table.selectedItems()

        if not selected_items:
            self.current_track_id = None
            self.edit_button.setEnabled(False)
            return

        title_item = selected_items[0]

        self.current_track_id = title_item.data(
            Qt.ItemDataRole.UserRole
        )
        self.edit_button.setEnabled(True)

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
                "(*.mp3 *.wav *.flac *.m4a *.ogg *.opus)"
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

        title, artist, genres = (
            metadata_dialog.get_values()
        )

        try:
            track = self.ingestion_service.ingest(
                source_path,
                title=title,
                artist=artist,
                genres=genres,
                source="windows_import",
            )
        except (FileNotFoundError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Import failed",
                str(error),
            )
            return

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

    def _edit_selected_track(self) -> None:
        if self.current_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        track = self.store.get_track(
            self.current_track_id
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
            genres=track.genres,
        )

        if (
            metadata_dialog.exec()
            != QDialog.DialogCode.Accepted
        ):
            return

        title, artist, genres = (
            metadata_dialog.get_values()
        )

        if (
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
                    genres=genres,
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

    def _play_selected_track(self) -> None:
        if self.current_track_id is None:
            QMessageBox.warning(
                self,
                "No track selected",
                "Select a track first.",
            )
            return

        track = self.store.get_track(
            self.current_track_id
        )

        if track is None:
            QMessageBox.warning(
                self,
                "Playback failed",
                "Track was not found.",
            )
            return

        if not track.local_path:
            QMessageBox.warning(
                self,
                "Playback unavailable",
                "This track does not have a local file.",
            )
            return

        audio_path = Path(track.local_path)

        if not audio_path.exists():
            QMessageBox.warning(
                self,
                "Playback failed",
                f"File not found:\n{audio_path}",
            )
            return

        source_url = QUrl.fromLocalFile(
            str(audio_path.resolve())
        )

        self.media_player.setSource(source_url)
        self.media_player.play()

        try:
            self.interaction_service.record(
                user_id=self.user_id,
                track_id=track.id,
                interaction_type=InteractionType.PLAY,
            )
        except ValueError as error:
            QMessageBox.warning(
                self,
                "Interaction failed",
                str(error),
            )
            return

        self._load_recommendations()

        self.statusBar().showMessage(
            f"Playing: {track.artist} — {track.title}"
        )

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
