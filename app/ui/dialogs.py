from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ingestion.metadata import AudioMetadata
from app.sources.youtube import YouTubeCandidate


class TrackMetadataDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget | None,
        file_path: Path | None = None,
        metadata: AudioMetadata | None = None,
        title: str | None = None,
        artist: str | None = None,
        genres: tuple[str, ...] = (),
    ) -> None:
        super().__init__(parent)

        self.setWindowTitle("Track metadata")

        initial_title = (
            title
            or (metadata.title if metadata else None)
            or (file_path.stem if file_path else "")
        )
        initial_artist = (
            artist
            or (metadata.artist if metadata else None)
            or "Unknown Artist"
        )

        self.title_edit = QLineEdit(
            initial_title
        )
        self.artist_edit = QLineEdit(
            initial_artist
        )
        self.genres_edit = QLineEdit(
            ", ".join(genres)
        )

        self.genres_edit.setPlaceholderText(
            "electronic, trip-hop"
        )

        form_layout = QFormLayout(self)
        form_layout.addRow(
            "Title:",
            self.title_edit,
        )
        form_layout.addRow(
            "Artist:",
            self.artist_edit,
        )
        form_layout.addRow(
            "Genres:",
            self.genres_edit,
        )

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        form_layout.addRow(button_box)

    def get_values(
        self,
    ) -> tuple[str, str, tuple[str, ...]]:
        genres = tuple(
            genre.strip().lower()
            for genre in self.genres_edit.text().split(",")
            if genre.strip()
        )

        return (
            self.title_edit.text().strip(),
            self.artist_edit.text().strip(),
            genres,
        )

    def accept(self) -> None:
        title, artist, _ = self.get_values()

        if not title:
            QMessageBox.warning(
                self,
                "Invalid metadata",
                "Title must not be empty.",
            )
            return

        if not artist:
            QMessageBox.warning(
                self,
                "Invalid metadata",
                "Artist must not be empty.",
            )
            return

        super().accept()


class YouTubeSearchDialog(QDialog):
    search_requested = Signal(str)
    import_requested = Signal(object, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._busy = False

        self.setWindowTitle("Add track from YouTube")
        self.resize(760, 520)

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText(
            "Artist and track title"
        )
        form_layout.addRow("Search:", self.query_edit)

        self.channel_id_edit = QLineEdit()
        self.channel_id_edit.setPlaceholderText(
            "UC..."
        )
        form_layout.addRow(
            "Allowed channel ID:",
            self.channel_id_edit,
        )

        layout.addLayout(form_layout)
        layout.addWidget(
            QLabel(
                "Only a selected video from this channel "
                "can be downloaded."
            )
        )

        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(
            self._request_search
        )

        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_button)
        search_layout.addStretch()
        layout.addLayout(search_layout)

        self.results_list = QListWidget()
        self.results_list.setWordWrap(True)
        self.results_list.itemSelectionChanged.connect(
            self._handle_selection_changed
        )
        layout.addWidget(self.results_list)

        self.status_label = QLabel(
            "Enter a query and press Search."
        )
        layout.addWidget(self.status_label)

        buttons_layout = QHBoxLayout()

        self.import_button = QPushButton(
            "Download selected"
        )
        self.import_button.setEnabled(False)
        self.import_button.clicked.connect(
            self._request_import
        )

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        buttons_layout.addWidget(self.import_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(cancel_button)
        layout.addLayout(buttons_layout)

        self._cancel_button = cancel_button

    def _request_search(self) -> None:
        query = self.query_edit.text().strip()

        if not query:
            QMessageBox.warning(
                self,
                "Search failed",
                "Search query must not be empty.",
            )
            return

        self.search_requested.emit(query)

    def _request_import(self) -> None:
        candidate = self.selected_candidate()
        channel_id = self.channel_id_edit.text().strip()

        if candidate is None:
            return

        if not channel_id:
            QMessageBox.warning(
                self,
                "Download failed",
                "Allowed channel ID must not be empty.",
            )
            return

        self.import_requested.emit(candidate, channel_id)

    def _handle_selection_changed(self) -> None:
        self.import_button.setEnabled(
            not self._busy
            and self.selected_candidate() is not None
        )

    def selected_candidate(
        self,
    ) -> YouTubeCandidate | None:
        item = self.results_list.currentItem()

        if item is None:
            return None

        candidate = item.data(Qt.ItemDataRole.UserRole)

        if isinstance(candidate, YouTubeCandidate):
            return candidate

        return None

    def set_candidates(
        self,
        candidates: list[YouTubeCandidate],
    ) -> None:
        self.results_list.clear()

        for index, candidate in enumerate(
            candidates,
            start=1,
        ):
            item = QListWidgetItem(
                self._format_candidate(index, candidate)
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                candidate,
            )
            self.results_list.addItem(item)

        self.status_label.setText(
            f"Found {len(candidates)} videos. "
            "Select one to download."
        )
        self._handle_selection_changed()

    def set_busy(
        self,
        busy: bool,
        message: str,
    ) -> None:
        self._busy = busy
        self.search_button.setEnabled(not busy)
        self.query_edit.setEnabled(not busy)
        self.channel_id_edit.setEnabled(not busy)
        self._cancel_button.setEnabled(not busy)
        self.status_label.setText(message)
        self._handle_selection_changed()

    def show_error(self, message: str) -> None:
        self.set_busy(False, "Operation failed.")
        QMessageBox.warning(
            self,
            "YouTube operation failed",
            message,
        )

    @staticmethod
    def _format_candidate(
        index: int,
        candidate: YouTubeCandidate,
    ) -> str:
        duration = YouTubeSearchDialog._format_duration(
            candidate.duration_ms
        )

        return (
            f"{index}. {candidate.title}\n"
            f"{candidate.channel_title} · {duration}"
        )

    @staticmethod
    def _format_duration(
        duration_ms: int | None,
    ) -> str:
        if duration_ms is None:
            return "Unknown duration"

        total_seconds = duration_ms // 1000
        minutes, seconds = divmod(total_seconds, 60)

        return f"{minutes}:{seconds:02d}"
