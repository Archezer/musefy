from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
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
from app.services.mp3party_import import Mp3PartyCandidate
from app.services.soundcloud_import import SoundCloudCandidate
from app.sources.spotify import SpotifyTrack
from app.sources.youtube import YouTubeCandidate

SearchCandidate = (
    YouTubeCandidate
    | SoundCloudCandidate
    | Mp3PartyCandidate
)


class TrackMetadataDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget | None,
        file_path: Path | None = None,
        metadata: AudioMetadata | None = None,
        title: str | None = None,
        artist: str | None = None,
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

        form_layout = QFormLayout(self)
        form_layout.addRow(
            "Title:",
            self.title_edit,
        )
        form_layout.addRow(
            "Artist:",
            self.artist_edit,
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
    ) -> tuple[str, str]:
        return (
            self.title_edit.text().strip(),
            self.artist_edit.text().strip(),
        )

    def accept(self) -> None:
        title, artist = self.get_values()

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
    source_requested = Signal(str)
    # Kept under the old name for compatibility with existing integrations.
    soundcloud_download_requested = Signal(str)
    soundcloud_import_requested = Signal(object)
    mp3party_download_requested = Signal(str)
    mp3party_import_requested = Signal(object)
    # Compatibility signals for integrations that still use the old API.
    search_requested = Signal(str)
    authenticate_requested = Signal(str)
    url_load_requested = Signal(str)
    import_requested = Signal(object)
    playlist_import_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._busy = False
        self._playlist_mode = False
        self._playlist_name: str | None = None
        self._playlist_cover_url: str | None = None
        self._unmatched_playlist_tracks: tuple[
            tuple[SpotifyTrack, str], ...
        ] = ()
        self._local_playlist_id: str | None = None
        self._imported_playlist_tracks: dict[int, str] = {}

        self.setWindowTitle(
            "Add from YouTube, Spotify, SoundCloud or MP3Party"
        )
        self.resize(760, 520)

        layout = QVBoxLayout(self)

        form_layout = QFormLayout()

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText(
            "Artist/title or a YouTube, Spotify, SoundCloud or MP3Party URL"
        )
        form_layout.addRow("Search or URL:", self.source_edit)

        # Keep the old attribute names as aliases for host integrations.
        self.query_edit = self.source_edit
        self.url_edit = self.source_edit

        layout.addLayout(form_layout)

        search_layout = QHBoxLayout()
        self.source_button = QPushButton("Search / Load")
        self.source_button.setToolTip(
            "Search YouTube, or load a YouTube/Spotify/SoundCloud/MP3Party link."
        )
        self.source_button.clicked.connect(self._request_source)
        search_layout.addWidget(self.source_button)

        # Compatibility aliases; only one visible action is shown.
        self.search_button = self.source_button
        self.load_button = self.source_button

        self.soundcloud_button = QPushButton(
            "Search SoundCloud"
        )
        self.soundcloud_button.setToolTip(
            "Search SoundCloud or load a track/set URL. "
            "Use only tracks you are authorized to download."
        )
        self.soundcloud_button.clicked.connect(
            self._request_soundcloud_download
        )
        search_layout.addWidget(self.soundcloud_button)

        self.mp3party_button = QPushButton("Find with MP3Party")
        self.mp3party_button.setToolTip(
            "Search MP3Party or load a direct track URL. "
            "Use only tracks you are authorized to download."
        )
        self.mp3party_button.clicked.connect(
            self._request_mp3party_download
        )
        search_layout.addWidget(self.mp3party_button)

        self.authenticate_button = QPushButton("Authenticate Spotify")
        self.authenticate_button.setToolTip(
            "Authorize Spotify for private or collaborative playlists."
        )
        self.authenticate_button.clicked.connect(
            self._request_authenticate
        )
        search_layout.addWidget(self.authenticate_button)

        search_layout.addStretch()
        layout.addLayout(search_layout)

        self.results_list = QListWidget()
        self.results_list.setWordWrap(True)
        self.results_list.itemSelectionChanged.connect(
            self._handle_selection_changed
        )
        self.results_list.itemChanged.connect(
            self._handle_selection_changed
        )
        layout.addWidget(self.results_list)

        self.status_label = QLabel(
            "Search YouTube or paste a YouTube, Spotify, SoundCloud or MP3Party URL."
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

    def _request_source(self) -> None:
        source = self.source_edit.text().strip()

        if not source:
            QMessageBox.warning(
                self,
                "Search or load failed",
                "Enter a search query or paste a supported URL.",
            )
            return

        self.source_requested.emit(source)

    def _request_soundcloud_download(self) -> None:
        source = self.source_edit.text().strip()

        if not source:
            QMessageBox.warning(
                self,
                "SoundCloud search failed",
                "Enter a SoundCloud search query or URL.",
            )
            return

        self.soundcloud_download_requested.emit(source)

    def _request_mp3party_download(self) -> None:
        source = self.source_edit.text().strip()

        if not source:
            QMessageBox.warning(
                self,
                "MP3Party search failed",
                "Enter a track search query or MP3Party URL.",
            )
            return

        self.mp3party_download_requested.emit(source)

    def _request_search(self) -> None:
        """Legacy search signal entry point."""

        query = self.source_edit.text().strip()

        if not query:
            QMessageBox.warning(
                self,
                "Search failed",
                "Search query must not be empty.",
            )
            return

        self.search_requested.emit(query)

    def _request_authenticate(self) -> None:
        url = self.source_edit.text().strip()

        if not url:
            QMessageBox.warning(
                self,
                "Authentication failed",
                "Paste a YouTube or Spotify URL first.",
            )
            return

        self.authenticate_requested.emit(url)

    def _request_import(self) -> None:
        candidates = self.selected_candidates()

        if not candidates:
            return

        if self._playlist_mode:
            self.playlist_import_requested.emit(candidates)
        else:
            if isinstance(candidates[0], SoundCloudCandidate):
                self.soundcloud_import_requested.emit(candidates[0])
            elif isinstance(candidates[0], Mp3PartyCandidate):
                self.mp3party_import_requested.emit(candidates[0])
            else:
                self.import_requested.emit(candidates[0])

    def _request_url_load(self) -> None:
        """Legacy URL-load signal entry point."""

        url = self.source_edit.text().strip()

        if not url:
            QMessageBox.warning(
                self,
                "Load failed",
                "URL must not be empty.",
            )
            return

        self.url_load_requested.emit(url)

    def _handle_selection_changed(self) -> None:
        selected_count = len(self.selected_candidates())
        self.import_button.setEnabled(
            not self._busy
            and selected_count > 0
        )

        if self._playlist_mode:
            self.import_button.setText(
                f"Download selected ({selected_count})"
            )
        else:
            self.import_button.setText("Download selected")

    def selected_candidate(
        self,
    ) -> SearchCandidate | None:
        item = self.results_list.currentItem()

        if item is None:
            return None

        candidate = item.data(Qt.ItemDataRole.UserRole)

        if isinstance(
            candidate,
            (YouTubeCandidate, SoundCloudCandidate, Mp3PartyCandidate),
        ):
            return candidate

        return None

    def selected_candidates(self) -> list[SearchCandidate]:
        if self._playlist_mode:
            candidates = []

            for index in range(self.results_list.count()):
                item = self.results_list.item(index)

                if item.checkState() != Qt.CheckState.Checked:
                    continue

                candidate = item.data(Qt.ItemDataRole.UserRole)

                if isinstance(
                    candidate,
                    (
                        YouTubeCandidate,
                        SoundCloudCandidate,
                        Mp3PartyCandidate,
                    ),
                ):
                    candidates.append(candidate)

            return candidates

        candidate = self.selected_candidate()
        return [candidate] if candidate is not None else []

    def set_candidates(
        self,
        candidates: list[SearchCandidate],
        *,
        playlist: bool = False,
        playlist_name: str | None = None,
        playlist_cover_url: str | None = None,
        unmatched: tuple[tuple[SpotifyTrack, str], ...] = (),
        source_label: str = "videos",
    ) -> None:
        self._playlist_mode = playlist
        self._playlist_name = playlist_name if playlist else None
        self._playlist_cover_url = (
            playlist_cover_url if playlist else None
        )
        self._unmatched_playlist_tracks = (
            unmatched if playlist else ()
        )
        self.results_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
            if playlist
            else QAbstractItemView.SelectionMode.SingleSelection
        )
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
            if playlist:
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                )
                item.setCheckState(Qt.CheckState.Checked)
            self.results_list.addItem(item)

        if playlist:
            message = (
                f"Matched {len(candidates)} playlist tracks. "
                "Uncheck anything you do not want to download."
            )
            if unmatched:
                message += (
                    f" {len(unmatched)} tracks were not found."
                )
        else:
            message = (
                f"Found {len(candidates)} {source_label}. "
                "Select one to download."
            )

        self.status_label.setText(message)
        self._handle_selection_changed()

    @property
    def playlist_name(self) -> str | None:
        return self._playlist_name

    @property
    def playlist_cover_url(self) -> str | None:
        return self._playlist_cover_url

    @property
    def unmatched_playlist_tracks(
        self,
    ) -> tuple[tuple[SpotifyTrack, str], ...]:
        return self._unmatched_playlist_tracks

    @property
    def local_playlist_id(self) -> str | None:
        return self._local_playlist_id

    def set_local_playlist_id(self, playlist_id: str) -> None:
        self._local_playlist_id = playlist_id

    def remember_imported_playlist_track(
        self,
        position: int,
        track_id: str,
    ) -> None:
        self._imported_playlist_tracks[position] = track_id

    def imported_playlist_track_ids(self) -> tuple[str, ...]:
        return tuple(
            track_id
            for _, track_id in sorted(
                self._imported_playlist_tracks.items()
            )
        )

    def set_search_query(self, query: str) -> None:
        self.source_edit.setText(query)

    def set_busy(
        self,
        busy: bool,
        message: str,
    ) -> None:
        self._busy = busy
        self.source_button.setEnabled(not busy)
        self.soundcloud_button.setEnabled(not busy)
        self.mp3party_button.setEnabled(not busy)
        self.authenticate_button.setEnabled(not busy)
        self.source_edit.setEnabled(not busy)
        self._cancel_button.setEnabled(not busy)
        self.status_label.setText(message)
        self._handle_selection_changed()

    def update_playlist_download_progress(
        self,
        completed: int,
        total: int,
    ) -> None:
        if not self._playlist_mode:
            return

        self.status_label.setText(
            f"Downloading playlist: {completed}/{total}..."
        )

    def show_error(self, message: str) -> None:
        self.set_busy(False, "Operation failed.")
        QMessageBox.warning(
            self,
            "Import operation failed",
            message,
        )

    @staticmethod
    def _format_candidate(
        index: int,
        candidate: SearchCandidate,
    ) -> str:
        if isinstance(candidate, SoundCloudCandidate):
            duration = YouTubeSearchDialog._format_duration(
                candidate.duration_ms
            )
            plays = YouTubeSearchDialog._format_views(
                candidate.playback_count,
                noun="plays",
            )
            return (
                f"{index}. {candidate.artist} — {candidate.title}\n"
                f"SoundCloud · {duration} · {plays}"
            )

        if isinstance(candidate, Mp3PartyCandidate):
            duration = YouTubeSearchDialog._format_duration(
                candidate.duration_ms
            )
            return (
                f"{index}. {candidate.artist} — {candidate.title}\n"
                f"MP3Party · {duration} · MP3"
            )

        duration = YouTubeSearchDialog._format_duration(
            candidate.duration_ms
        )
        views = YouTubeSearchDialog._format_views(
            candidate.view_count
        )

        if candidate.requested_title:
            requested_artist = (
                candidate.requested_artist or "Unknown artist"
            )
            return (
                f"{index}. {requested_artist} — "
                f"{candidate.requested_title}\n"
                f"YouTube: {candidate.title}\n"
                f"{candidate.channel_title} · {duration} · {views}"
            )

        return (
            f"{index}. {candidate.title}\n"
            f"{candidate.channel_title} · {duration} · {views}"
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

    @staticmethod
    def _format_views(
        view_count: int | None,
        *,
        noun: str = "views",
    ) -> str:
        if view_count is None:
            return f"Unknown {noun}"

        return f"{view_count:,} {noun}"


class PlaylistImportResultDialog(QDialog):
    retry_requested = Signal(object)

    def __init__(
        self,
        imported_count: int,
        failed: tuple[
            tuple[YouTubeCandidate | SoundCloudCandidate, str],
            ...,
        ],
        parent: QWidget | None = None,
        *,
        unmatched: tuple[tuple[SpotifyTrack, str], ...] = (),
    ) -> None:
        super().__init__(parent)

        self.failed = failed
        self.setWindowTitle("Playlist import completed")
        self.resize(640, 440)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"Imported {imported_count} playlist tracks.\n"
                f"Skipped {len(failed) + len(unmatched)} tracks."
            )
        )

        layout.addWidget(QLabel("Not imported:"))
        failed_tracks = QListWidget()

        for candidate, error in failed:
            failed_tracks.addItem(
                f"{candidate.title}\n{error}"
            )

        for track, error in unmatched:
            artist = track.artist or "Unknown artist"
            failed_tracks.addItem(
                f"{artist} — {track.title}\n{error}"
            )

        layout.addWidget(failed_tracks)

        buttons_layout = QHBoxLayout()
        retry_button = QPushButton(
            f"Try failed downloads again ({len(failed)})"
        )
        retry_button.setEnabled(bool(failed))
        retry_button.clicked.connect(self._request_retry)
        buttons_layout.addWidget(retry_button)
        buttons_layout.addStretch()

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons_layout.addWidget(close_button)
        layout.addLayout(buttons_layout)

    def _request_retry(self) -> None:
        self.retry_requested.emit(
            [candidate for candidate, _ in self.failed]
        )
        self.accept()
