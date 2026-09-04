from collections import Counter
from math import cos, pi, sin, sqrt
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import (
    QElapsedTimer,
    QEvent,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import Track
from app.ingestion.metadata import AudioMetadata
from app.services.library_maintenance import LibraryHealthReport
from app.services.mp3party_import import Mp3PartyCandidate
from app.services.soundcloud_import import SoundCloudCandidate
from app.services.statistics import ListeningStatistics
from app.services.watch_folder import WatchFolderConfig, WatchFolderReport
from app.sources.spotify import SpotifyTrack
from app.sources.youtube import YouTubeCandidate
from app.ui.dialog_style import prepare_dialog

SearchCandidate = (
    YouTubeCandidate
    | SoundCloudCandidate
    | Mp3PartyCandidate
)


def _format_elapsed(milliseconds: int) -> str:
    """Format an operation duration compactly for the dialog header."""

    total_seconds = max(milliseconds, 0) // 1000
    minutes, seconds = divmod(total_seconds, 60)
    if minutes < 60:
        return f"{minutes:02d}:{seconds:02d}"

    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class SpotifySyncRow(QFrame):
    """A compact clickable row for the Spotify favorite-sync setting."""

    settings_requested = Signal()
    sync_toggled = Signal(bool)

    def __init__(
        self,
        *,
        authenticated: bool = False,
        sync_enabled: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("spotifySyncRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(60)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(9)

        self.sync_checkbox = QCheckBox()
        self.sync_checkbox.setObjectName("spotifyFavSyncCheck")
        self.sync_checkbox.setToolTip(
            "Watch for newly saved Spotify tracks every five minutes."
        )
        self.sync_checkbox.toggled.connect(self.sync_toggled)
        layout.addWidget(self.sync_checkbox, 0, Qt.AlignmentFlag.AlignVCenter)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(1)

        self.title_label = QLabel("Spotify fav sync")
        self.title_label.setObjectName("spotifySyncTitle")
        self.subtitle_label = QLabel(
            "Watch new saved tracks every 5 minutes"
        )
        self.subtitle_label.setObjectName("spotifySyncSubtitle")
        text_layout.addWidget(self.title_label)
        text_layout.addWidget(self.subtitle_label)
        layout.addLayout(text_layout, 1)

        self.auth_status_label = QLabel()
        self.auth_status_label.setObjectName("spotifyAuthStatus")
        self.auth_status_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self.auth_status_label)

        self.arrow_label = QLabel("›")
        self.arrow_label.setObjectName("spotifySyncArrow")
        self.arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.arrow_label)

        for child in (
            self.title_label,
            self.subtitle_label,
            self.auth_status_label,
            self.arrow_label,
        ):
            child.installEventFilter(self)

        self.set_sync_enabled(sync_enabled)
        self.set_authenticated(authenticated)

    def eventFilter(self, watched: object, event: object) -> bool:
        clickable_children = (
            self.title_label,
            self.subtitle_label,
            self.auth_status_label,
            self.arrow_label,
        )
        if (
            watched in clickable_children
            and isinstance(event, QEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
        ):
            self.settings_requested.emit()
            return True

        return super().eventFilter(watched, event)

    def mouseReleaseEvent(self, event: object) -> None:
        if (
            isinstance(event, QEvent)
            and event.type() == QEvent.Type.MouseButtonRelease
        ):
            self.settings_requested.emit()
            return
        super().mouseReleaseEvent(event)

    def set_authenticated(self, authenticated: bool) -> None:
        # Keep the checkbox clickable even before OAuth.  The host window can
        # then offer to open Spotify settings instead of silently ignoring the
        # user's click.
        self.sync_checkbox.setEnabled(True)
        self.sync_checkbox.setToolTip(
            "Watch new saved Spotify tracks every five minutes."
            if authenticated
            else "Connect Spotify with OAuth to enable fav sync."
        )
        self.auth_status_label.setProperty("connected", authenticated)
        self.auth_status_label.setText(
            "✓ Connected" if authenticated else "Connect in settings"
        )
        self.auth_status_label.style().unpolish(self.auth_status_label)
        self.auth_status_label.style().polish(self.auth_status_label)

    def set_sync_enabled(self, enabled: bool) -> None:
        signals_blocked = self.sync_checkbox.blockSignals(True)
        self.sync_checkbox.setChecked(enabled)
        self.sync_checkbox.blockSignals(signals_blocked)


class SpotifySettingsDialog(QDialog):
    """Settings and connection status for Spotify integrations."""

    closed = Signal()
    authenticate_requested = Signal()
    sync_toggled = Signal(bool)
    sync_requested = Signal()

    def __init__(
        self,
        *,
        authenticated: bool = False,
        sync_enabled: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        prepare_dialog(self)
        self._close_notified = False
        self.setObjectName("spotifySettingsDialog")
        self.setWindowTitle("Spotify settings")
        self.resize(500, 300)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Spotify integration")
        title.setObjectName("spotifySettingsTitle")
        layout.addWidget(title)

        description = QLabel(
            "Connect Spotify to read saved-track metadata and watch for "
            "new favorites."
        )
        description.setWordWrap(True)
        description.setObjectName("spotifySettingsDescription")
        layout.addWidget(description)

        auth_frame = QFrame()
        auth_frame.setObjectName("spotifySettingsSection")
        auth_layout = QHBoxLayout(auth_frame)
        auth_layout.setContentsMargins(12, 10, 12, 10)
        auth_layout.setSpacing(10)

        self.auth_status_label = QLabel()
        self.auth_status_label.setObjectName("spotifySettingsAuthStatus")
        auth_layout.addWidget(self.auth_status_label, 1)

        self.authenticate_button = QPushButton("Connect Spotify (OAuth)")
        self.authenticate_button.setObjectName("spotifyOAuthButton")
        self.authenticate_button.setToolTip(
            "Authorize Musefy to read your saved Spotify tracks."
        )
        self.authenticate_button.clicked.connect(self.authenticate_requested)
        auth_layout.addWidget(self.authenticate_button)
        layout.addWidget(auth_frame)

        sync_frame = QFrame()
        sync_frame.setObjectName("spotifySettingsSection")
        sync_layout = QVBoxLayout(sync_frame)
        sync_layout.setContentsMargins(12, 10, 12, 10)
        sync_layout.setSpacing(5)

        self.sync_checkbox = QCheckBox("Spotify fav sync")
        self.sync_checkbox.setObjectName("spotifyFavSyncCheck")
        self.sync_checkbox.setToolTip(
            "Check Spotify for newly saved tracks every five minutes."
        )
        self.sync_checkbox.toggled.connect(self.sync_toggled)
        sync_layout.addWidget(self.sync_checkbox)

        sync_description = QLabel(
            "Only tracks saved after enabling this option are reported by "
            "automatic sync."
        )
        sync_description.setObjectName("spotifySettingsDescription")
        sync_description.setWordWrap(True)
        sync_layout.addWidget(sync_description)

        self.sync_now_button = QPushButton("Sync All")
        self.sync_now_button.setObjectName("spotifySyncAllButton")
        self.sync_now_button.setToolTip(
            "Read all saved Spotify tracks now."
        )
        self.sync_now_button.clicked.connect(self.sync_requested)
        sync_layout.addWidget(
            self.sync_now_button,
            0,
            Qt.AlignmentFlag.AlignLeft,
        )
        layout.addWidget(sync_frame)

        self.status_label = QLabel()
        self.status_label.setObjectName("spotifySettingsStatus")
        self.status_label.setWordWrap(True)
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(self.status_label, 1)

        self.elapsed_label = QLabel("00:00")
        self.elapsed_label.setObjectName("searchElapsedTime")
        self.elapsed_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.elapsed_label.hide()
        status_layout.addWidget(self.elapsed_label)
        layout.addLayout(status_layout)

        self._progress_clock = QElapsedTimer()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._refresh_elapsed_time)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("searchProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.reject)
        buttons_layout.addWidget(close_button)
        layout.addLayout(buttons_layout)

        self.set_authenticated(authenticated)
        self.set_sync_enabled(sync_enabled)
        self.set_busy(False, "")

    def set_authenticated(self, authenticated: bool) -> None:
        self.auth_status_label.setProperty("connected", authenticated)
        self.auth_status_label.setText(
            "✓ Spotify OAuth connected"
            if authenticated
            else "Spotify OAuth is not connected"
        )
        self.authenticate_button.setText(
            "Reconnect Spotify (OAuth)"
            if authenticated
            else "Connect Spotify (OAuth)"
        )
        self.sync_checkbox.setEnabled(authenticated)
        self.sync_now_button.setEnabled(authenticated)
        self.auth_status_label.style().unpolish(self.auth_status_label)
        self.auth_status_label.style().polish(self.auth_status_label)

    def set_sync_enabled(self, enabled: bool) -> None:
        signals_blocked = self.sync_checkbox.blockSignals(True)
        self.sync_checkbox.setChecked(enabled)
        self.sync_checkbox.blockSignals(signals_blocked)

    def set_busy(self, busy: bool, message: str) -> None:
        self.authenticate_button.setEnabled(not busy)
        self.sync_checkbox.setEnabled(
            not busy and self._is_authenticated()
        )
        self.sync_now_button.setEnabled(
            not busy and self._is_authenticated()
        )
        if message:
            self.status_label.setText(message)

    def _notify_closed(self) -> None:
        if not self._close_notified:
            self._close_notified = True
            self.closed.emit()

    def reject(self) -> None:
        self._notify_closed()
        super().reject()

    def closeEvent(self, event: object) -> None:
        self._notify_closed()
        super().closeEvent(event)

    def start_progress(
        self,
        message: str,
        *,
        total: int | None = None,
    ) -> None:
        """Show a compact progress indicator for a background operation."""

        if total is None or total <= 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)
        self._progress_clock.start()
        self._progress_timer.start()
        self.elapsed_label.setText("00:00")
        self.elapsed_label.show()
        self.progress_bar.show()
        self.status_label.setText(message)

    def update_search_progress(
        self,
        completed: int,
        total: int,
        found: int,
        failed: int,
        current: str = "",
    ) -> None:
        """Update Spotify/playlist search progress and its micro-log line."""

        total = max(total, 0)
        if total:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(max(completed, 0), total))
        else:
            self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

        parts = [
            f"Searching: {completed}/{total}",
            f"found {found}",
        ]
        if failed:
            parts.append(f"failed {failed}")
        if current:
            current = " ".join(current.split())
            if len(current) > 52:
                current = f"{current[:51].rstrip()}…"
            parts.append(current)
        self.status_label.setText(" · ".join(parts))

    def finish_progress(self, message: str) -> None:
        """Complete the visual indicator while retaining the final summary."""

        if self._progress_timer.isActive():
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self._refresh_elapsed_time()
            self._progress_timer.stop()
        self.status_label.setText(message)

    def hide_progress(self) -> None:
        self.progress_bar.hide()
        self.elapsed_label.hide()
        self._progress_timer.stop()

    def _refresh_elapsed_time(self) -> None:
        if self._progress_clock.isValid():
            self.elapsed_label.setText(
                _format_elapsed(self._progress_clock.elapsed())
            )

    def _is_authenticated(self) -> bool:
        return bool(self.auth_status_label.property("connected"))


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
        prepare_dialog(self)

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
    closed = Signal()
    source_requested = Signal(str)
    # Kept under the old name for compatibility with existing integrations.
    soundcloud_download_requested = Signal(str)
    soundcloud_import_requested = Signal(object)
    mp3party_download_requested = Signal(str)
    mp3party_import_requested = Signal(object)
    # Compatibility signals for integrations that still use the old API.
    search_requested = Signal(str)
    authenticate_requested = Signal(str)
    spotify_settings_requested = Signal()
    spotify_sync_toggled = Signal(bool)
    url_load_requested = Signal(str)
    import_requested = Signal(object)
    playlist_import_requested = Signal(object)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        spotify_authenticated: bool = False,
        spotify_sync_enabled: bool = False,
    ) -> None:
        super().__init__(parent)
        prepare_dialog(self)
        self._close_notified = False

        self._busy = False
        self._playlist_mode = False
        # Provenance used when the dialog downloads YouTube candidates.  The
        # regular search flow stays labelled as YouTube, while Spotify
        # favourite sync can opt into its own import-log method.
        self._import_source = "youtube"
        self._playlist_name: str | None = None
        self._playlist_cover_url: str | None = None
        self._unmatched_playlist_tracks: tuple[
            tuple[SpotifyTrack, str], ...
        ] = ()
        self._unmatched_playlist_positions: tuple[int, ...] = ()
        self._local_playlist_id: str | None = None
        self._imported_playlist_tracks: dict[int, str] = {}
        self._skipped_playlist_candidates: tuple[
            tuple[SearchCandidate, str],
        ] = ()

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

        self.mp3party_button = QPushButton("Search MP3Party")
        self.mp3party_button.setToolTip(
            "Search MP3Party or load a direct track URL. "
            "Use only tracks you are authorized to download."
        )
        self.mp3party_button.clicked.connect(
            self._request_mp3party_download
        )
        search_layout.addWidget(self.mp3party_button)

        self.spotify_auth_status_label = QLabel()
        self.spotify_auth_status_label.setObjectName("spotifyAuthStatus")
        # OAuth state is already shown in the Spotify fav sync row below;
        # keeping a second "Connected" badge in the search-actions row adds
        # noise without providing another action.
        self.spotify_auth_status_label.hide()
        search_layout.addWidget(self.spotify_auth_status_label)

        search_layout.addStretch()
        layout.addLayout(search_layout)

        self.spotify_sync_row = SpotifySyncRow(
            authenticated=spotify_authenticated,
            sync_enabled=spotify_sync_enabled,
            parent=self,
        )
        self.spotify_sync_row.settings_requested.connect(
            self.spotify_settings_requested
        )
        self.spotify_sync_row.sync_toggled.connect(
            self.spotify_sync_toggled
        )
        layout.addWidget(self.spotify_sync_row)

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
        status_layout = QHBoxLayout()
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(self.status_label, 1)

        self.elapsed_label = QLabel("00:00")
        self.elapsed_label.setObjectName("searchElapsedTime")
        self.elapsed_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.elapsed_label.hide()
        status_layout.addWidget(self.elapsed_label)
        layout.addLayout(status_layout)

        self._progress_clock = QElapsedTimer()
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self._refresh_elapsed_time)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("searchProgressBar")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

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
        self.set_spotify_authenticated(spotify_authenticated)

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

        if not url or not url.casefold().startswith(
            ("http://", "https://")
        ):
            self.spotify_settings_requested.emit()
            return

        self.authenticate_requested.emit(url)

    def set_spotify_authenticated(self, authenticated: bool) -> None:
        self.spotify_auth_status_label.setProperty(
            "connected",
            authenticated,
        )
        self.spotify_auth_status_label.setText(
            "✓ Connected" if authenticated else "Not connected"
        )
        self.spotify_auth_status_label.style().unpolish(
            self.spotify_auth_status_label
        )
        self.spotify_auth_status_label.style().polish(
            self.spotify_auth_status_label
        )
        self.spotify_sync_row.set_authenticated(authenticated)

    def set_spotify_sync_enabled(self, enabled: bool) -> None:
        self.spotify_sync_row.set_sync_enabled(enabled)

    @property
    def import_source(self) -> str:
        return self._import_source

    def set_import_source(self, source: str) -> None:
        self._import_source = source.strip() or "youtube"

    def _request_import(self) -> None:
        candidates = self.selected_candidates()

        if not candidates and not self._playlist_mode:
            return

        if self._playlist_mode:
            skipped: list[tuple[SearchCandidate, str]] = []
            for index in range(self.results_list.count()):
                item = self.results_list.item(index)
                if item.checkState() == Qt.CheckState.Checked:
                    continue

                candidate = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(
                    candidate,
                    (YouTubeCandidate, SoundCloudCandidate, Mp3PartyCandidate),
                ):
                    skipped.append((candidate, "Skipped by user."))

            self._skipped_playlist_candidates = tuple(skipped)
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
        can_review_playlist = (
            self._playlist_mode
            and (
                self.results_list.count() > 0
                or bool(self._unmatched_playlist_tracks)
            )
        )
        self.import_button.setEnabled(
            not self._busy
            and (selected_count > 0 or can_review_playlist)
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
        unmatched_positions: tuple[int, ...] = (),
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
        self._unmatched_playlist_positions = (
            unmatched_positions if playlist else ()
        )
        self._skipped_playlist_candidates = ()
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

        self.finish_progress(message)
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
    def unmatched_playlist_positions(self) -> tuple[int, ...]:
        return self._unmatched_playlist_positions

    @property
    def skipped_playlist_candidates(
        self,
    ) -> tuple[tuple[SearchCandidate, str], ...]:
        return self._skipped_playlist_candidates

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
        self.spotify_sync_row.setEnabled(not busy)
        self.source_edit.setEnabled(not busy)
        self._cancel_button.setEnabled(not busy)
        self.status_label.setText(message)
        self._handle_selection_changed()

    def _notify_closed(self) -> None:
        if not self._close_notified:
            self._close_notified = True
            self.closed.emit()

    def reject(self) -> None:
        self._notify_closed()
        super().reject()

    def closeEvent(self, event: object) -> None:
        self._notify_closed()
        super().closeEvent(event)

    def update_playlist_download_progress(
        self,
        completed: int,
        total: int,
    ) -> None:
        if not self._playlist_mode:
            return

        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(min(max(completed, 0), max(total, 1)))
        self.progress_bar.show()
        self.status_label.setText(
            f"Downloading playlist: {completed}/{total}..."
        )

    def start_progress(
        self,
        message: str,
        *,
        total: int | None = None,
    ) -> None:
        """Show a compact determinate or indeterminate progress indicator."""

        if total is None or total <= 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)
        self._progress_clock.start()
        self._progress_timer.start()
        self.elapsed_label.setText("00:00")
        self.elapsed_label.show()
        self.progress_bar.show()
        self.status_label.setText(message)

    def resume_progress(
        self,
        message: str,
        *,
        total: int | None = None,
    ) -> None:
        """Continue the elapsed clock when an operation changes phase."""

        if not self._progress_clock.isValid():
            self._progress_clock.start()
            self.elapsed_label.setText("00:00")
        self._progress_timer.start()
        self._refresh_elapsed_time()
        self.elapsed_label.show()
        if total is None or total <= 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.status_label.setText(message)

    def update_search_progress(
        self,
        completed: int,
        total: int,
        found: int,
        failed: int,
        current: str = "",
    ) -> None:
        """Render live search counts and the currently processed track."""

        total = max(total, 0)
        if total:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(max(completed, 0), total))
        else:
            self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

        parts = [
            f"Searching: {completed}/{total}",
            f"found {found}",
        ]
        if failed:
            parts.append(f"failed {failed}")
        if current:
            current = " ".join(current.split())
            if len(current) > 52:
                current = f"{current[:51].rstrip()}…"
            parts.append(current)
        self.status_label.setText(" · ".join(parts))

    def finish_progress(self, message: str) -> None:
        """Keep the completed bar visible beside the final summary."""

        if self._progress_timer.isActive():
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(100)
            self._refresh_elapsed_time()
            self._progress_timer.stop()
        self.status_label.setText(message)

    def hide_progress(self) -> None:
        self.progress_bar.hide()
        self.elapsed_label.hide()
        self._progress_timer.stop()

    def _refresh_elapsed_time(self) -> None:
        if self._progress_clock.isValid():
            self.elapsed_label.setText(
                _format_elapsed(self._progress_clock.elapsed())
            )

    def show_error(self, message: str) -> None:
        self.set_busy(False, "Operation failed.")
        self.finish_progress("Operation failed.")
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
    """Show per-track failures and offer alternate source searches."""

    retry_requested = Signal(object)
    youtube_search_requested = Signal()
    soundcloud_search_requested = Signal()
    mp3party_search_requested = Signal()
    # Compatibility signal retained for integrations using the old dialog
    # API.  It is emitted together with ``youtube_search_requested``.
    search_requested = Signal()

    def __init__(
        self,
        imported_count: int,
        failed: tuple[
            tuple[
                YouTubeCandidate | SoundCloudCandidate | Mp3PartyCandidate,
                str,
            ],
            ...,
        ],
        parent: QWidget | None = None,
        *,
        unmatched: tuple[tuple[SpotifyTrack, str], ...] = (),
        unmatched_positions: tuple[int, ...] = (),
        allow_search: bool = True,
    ) -> None:
        super().__init__(parent)
        prepare_dialog(self)
        # Kept for backwards compatibility; alternate-source actions are now
        # always shown together.
        _ = allow_search

        self.failed = failed
        self.unmatched = unmatched
        self.unmatched_positions = unmatched_positions
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
        failed_tracks.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )

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

        failed_count = len(failed) + len(unmatched)
        # Keep the labels short and consistent: each action starts with a
        # capital letter and names the source it will search.
        youtube_button = QPushButton("Try YouTube Again")
        youtube_button.setToolTip(
            f"Search YouTube again for {failed_count} failed track(s)."
        )
        youtube_button.setEnabled(bool(failed_count))
        youtube_button.clicked.connect(self._request_youtube_search)
        buttons_layout.addWidget(youtube_button)

        soundcloud_button = QPushButton("Try SoundCloud")
        soundcloud_button.setToolTip(
            f"Search SoundCloud for {failed_count} failed track(s)."
        )
        soundcloud_button.setEnabled(bool(failed_count))
        soundcloud_button.clicked.connect(self._request_soundcloud_search)
        buttons_layout.addWidget(soundcloud_button)

        mp3party_button = QPushButton("Try MP3Party")
        mp3party_button.setToolTip(
            f"Search MP3Party for {failed_count} failed track(s)."
        )
        mp3party_button.setEnabled(bool(failed_count))
        mp3party_button.clicked.connect(self._request_mp3party_search)
        buttons_layout.addWidget(mp3party_button)
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

    def _request_search(self) -> None:
        self._request_youtube_search()

    def _request_youtube_search(self) -> None:
        self.youtube_search_requested.emit()
        self.search_requested.emit()
        self.accept()

    def _request_soundcloud_search(self) -> None:
        self.soundcloud_search_requested.emit()
        self.accept()

    def _request_mp3party_search(self) -> None:
        self.mp3party_search_requested.emit()
        self.accept()


class ListeningBarChart(QWidget):
    """Minimal native Qt bar chart with precise click targets."""

    period_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[object] = []
        self._selected_index = -1
        self._hover_index = -1
        self.setMinimumHeight(220)
        self.setMouseTracking(True)

    def set_items(self, items: tuple[object, ...] | list[object]) -> None:
        self._items = list(items)
        self._selected_index = len(self._items) - 1
        self._hover_index = -1
        self.update()

    def set_selected_index(self, index: int) -> None:
        if 0 <= index < len(self._items):
            self._selected_index = index
            self.update()

    def mousePressEvent(self, event: object) -> None:
        position = getattr(event, "position", lambda: None)()
        if position is None:
            return
        left, _top, width, _height = self._plot_rect()
        x = float(position.x())
        if x < left or x >= left + width or not self._items:
            return
        slot_width = width / len(self._items)
        index = int((x - left) / slot_width)
        if 0 <= index < len(self._items):
            self._selected_index = index
            self.period_clicked.emit(index)
            self.update()

    def mouseMoveEvent(self, event: object) -> None:
        position = getattr(event, "position", lambda: None)()
        if position is None or not self._items:
            return
        left, _top, width, _height = self._plot_rect()
        x = float(position.x())
        if left <= x < left + width:
            index = int((x - left) / (width / len(self._items)))
        else:
            index = -1
        if index != self._hover_index:
            self._hover_index = index
            if index >= 0:
                item = self._items[index]
                self.setToolTip(
                    f"{self._label(item)} · "
                    f"{self._track_count(item)} tracks listened"
                )
            else:
                self.setToolTip("")
            self.update()

    def leaveEvent(self, _event: object) -> None:
        self._hover_index = -1
        self.setToolTip("")
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 32), 1))
        left, top, width, height = self._plot_rect()
        baseline = top + height
        painter.drawLine(
            QRectF(left, baseline, width, 1).topLeft(),
            QRectF(left + width, baseline, width, 1).topLeft(),
        )
        if not self._items:
            painter.setPen(QColor(220, 225, 224, 150))
            painter.drawText(
                QRectF(left, top, width, height),
                Qt.AlignmentFlag.AlignCenter,
                "No listening data yet",
            )
            painter.end()
            return

        values = [self._track_count(item) for item in self._items]
        maximum = max(values, default=0)
        axis_maximum = max(maximum, 1)
        ticks = self._axis_ticks(axis_maximum)
        for tick in ticks:
            level = tick / axis_maximum
            y = baseline - height * level
            painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
            painter.drawLine(
                QRectF(left, y, width, 1).topLeft(),
                QRectF(left + width, y, width, 1).topLeft(),
            )
            painter.setPen(QColor(220, 225, 224, 170))
            painter.drawText(
                QRectF(0, y - 9, left - 7, 18),
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter,
                str(tick),
            )

        painter.save()
        painter.setPen(QColor(220, 225, 224, 150))
        painter.translate(9, top + height / 2)
        painter.rotate(-90)
        painter.drawText(
            QRectF(-height / 2, -12, height, 20),
            Qt.AlignmentFlag.AlignCenter,
            "Tracks",
        )
        painter.restore()

        slot_width = width / len(self._items)
        bar_width = max(3.0, slot_width - 4.0)
        for index, (item, track_count) in enumerate(
            zip(self._items, values, strict=True)
        ):
            bar_height = height * track_count / axis_maximum
            x = left + index * slot_width + (slot_width - bar_width) / 2
            y = baseline - bar_height
            color = QColor(
                "#14B893"
                if index == self._selected_index
                else "#54A995"
                if index == self._hover_index
                else "#2A756B"
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(x, y, bar_width, max(3.0, bar_height)), 4, 4)
            if index == self._selected_index or index == self._hover_index:
                painter.setPen(QPen(QColor("#B5FBE0"), 1))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(QRectF(x, y, bar_width, max(3.0, bar_height)), 4, 4)
            if len(self._items) <= 12 or index % 5 == 0 or index == self._selected_index:
                painter.setPen(QColor(220, 225, 224, 190))
                painter.drawText(
                    QRectF(x - slot_width, baseline + 7, slot_width * 3, 22),
                    Qt.AlignmentFlag.AlignCenter,
                    self._label(item),
                )
        painter.end()

    def _plot_rect(self) -> tuple[float, float, float, float]:
        return (
            48.0,
            12.0,
            max(1.0, self.width() - 60.0),
            max(1.0, self.height() - 48.0),
        )

    @staticmethod
    def _track_count(item: object) -> int:
        return max(0, int(getattr(item, "completed_listens", 0)))

    @staticmethod
    def _axis_ticks(axis_maximum: int) -> tuple[int, ...]:
        """Return readable ticks whose upper bound follows the data maximum."""

        if axis_maximum <= 1:
            return (0, 1)

        step = max(1, (axis_maximum + 3) // 4)
        ticks = list(range(0, axis_maximum, step))
        if ticks[-1] != axis_maximum:
            ticks.append(axis_maximum)
        return tuple(ticks)

    @staticmethod
    def _label(item: object) -> str:
        day = getattr(item, "day", None)
        if day is not None:
            return str(day.day)
        month = getattr(item, "month", None)
        return month.strftime("%b") if month is not None else ""


class ListeningGraph(QWidget):
    """Interactive listening network built from real track similarities."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tracks: tuple[
            tuple[
                str,
                str,
                int,
                tuple[float, ...] | None,
                tuple[str, ...],
            ],
            ...,
        ] = ()
        self._sphere_points: tuple[tuple[float, float, float], ...] = ()
        self._edge_pairs: tuple[tuple[int, int, float], ...] = ()
        self._cluster_groups: tuple[tuple[int, ...], ...] = ()
        self._hovered_index = -1
        self._rotation_x = -0.18
        self._rotation_y = 0.32
        self._zoom = 1.0
        self._last_pointer_position: QPointF | None = None
        self._is_rotating = False
        self.setMinimumHeight(174)
        self.setMouseTracking(True)

    def set_tracks(
        self,
        tracks: tuple[
            tuple[str, str, int, tuple[float, ...] | None, tuple[str, ...]],
            ...,
        ]
        | list[tuple[str, str, int, tuple[float, ...] | None, tuple[str, ...]]]
        | tuple[tuple[str, str, int, tuple[float, ...] | None], ...]
        | list[tuple[str, str, int, tuple[float, ...] | None]]
        | tuple[tuple[str, str, int], ...]
        | list[tuple[str, str, int]],
    ) -> None:
        normalized_tracks = []
        for track in tracks:
            title, artist, count = track[:3]
            embedding = track[3] if len(track) > 3 else None
            genres = track[4] if len(track) > 4 else ()
            normalized_tracks.append(
                (
                    str(title),
                    str(artist),
                    max(0, int(count)),
                    embedding,
                    tuple(
                        str(genre).strip().casefold()
                        for genre in genres
                        if str(genre).strip()
                    ),
                )
            )
        self._tracks = tuple(normalized_tracks)
        self._hovered_index = -1
        self._rotation_x = -0.18
        self._rotation_y = 0.32
        self._zoom = 1.0
        self._edge_pairs = self._build_edge_pairs(
            self._tracks,
        )
        self._cluster_groups = self._build_cluster_groups(
            self._tracks,
            self._edge_pairs,
        )
        self._sphere_points = self._build_layout_points(
            self._tracks,
            self._cluster_groups,
        )
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._tracks:
            painter.setPen(QColor(163, 163, 170, 145))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No tracks in this period yet",
            )
            painter.end()
            return

        projected = self._projected_positions()
        maximum = max(
            (
                count
                for _title, _artist, count, _embedding, _genres in self._tracks
            ),
            default=1,
        )
        # Paint the cluster atmosphere first.  It is deliberately very faint:
        # the links and nodes remain the primary signal, while the soft islands
        # make related tracks readable as groups even when their names are
        # hidden until hover.
        for group in self._cluster_groups:
            if len(group) < 2:
                continue
            group_positions = [projected[index][0] for index in group]
            center = QPointF(
                sum(position.x() for position in group_positions) / len(group),
                sum(position.y() for position in group_positions) / len(group),
            )
            radius_x = max(
                30.0,
                max(abs(position.x() - center.x()) for position in group_positions)
                + 22.0,
            )
            radius_y = max(
                22.0,
                max(abs(position.y() - center.y()) for position in group_positions)
                + 18.0,
            )
            painter.setPen(QPen(QColor(20, 184, 147, 20), 1.0))
            painter.setBrush(QColor(20, 184, 147, 7))
            painter.drawEllipse(center, radius_x, radius_y)

        for left_index, right_index, strength in self._edge_pairs:
            source = projected[left_index]
            target = projected[right_index]
            depth = (source[2] + target[2]) / 2
            alpha = int(24 + 82 * strength + 18 * ((depth + 1) / 2))
            width = 0.7 + 1.1 * strength
            painter.setPen(QPen(QColor(181, 251, 224, alpha), width))
            painter.drawLine(source[0], target[0])

        draw_order = sorted(
            range(len(self._tracks)),
            key=lambda index: projected[index][2],
        )
        for index in draw_order:
            title, artist, count, _embedding, _genres = self._tracks[index]
            position, depth, _scale = projected[index]
            front = (depth + 1) / 2
            strength = count / maximum if maximum else 0.0
            node_radius = (7.0 + 8.0 * strength) * (0.64 + 0.70 * front)
            if index == self._hovered_index:
                node_radius += 2.0
            # A small offset shadow and radial highlight give the node a clear
            # near/far reading without changing the dark, minimal visual style.
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, int(45 + 34 * front)))
            painter.drawEllipse(
                position + QPointF(1.5, 2.2),
                node_radius * 1.22,
                node_radius * 1.22,
            )
            painter.setBrush(QColor(20, 184, 147, int(12 + 44 * front)))
            painter.drawEllipse(position, node_radius * 1.9, node_radius * 1.9)
            base_color = self._node_color(index, front, index == 0)
            highlight = QColor(base_color)
            highlight.setAlpha(min(255, base_color.alpha() + 35))
            shade = QColor(base_color.darker(175))
            shade.setAlpha(base_color.alpha())
            gradient = QRadialGradient(
                position - QPointF(node_radius * 0.32, node_radius * 0.36),
                node_radius * 1.22,
            )
            gradient.setColorAt(0.0, highlight)
            gradient.setColorAt(0.56, base_color)
            gradient.setColorAt(1.0, shade)
            painter.setBrush(gradient)
            painter.drawEllipse(position, node_radius, node_radius)
            painter.setPen(QColor("#07100F"))
            painter.drawText(
                QRectF(
                    position.x() - node_radius,
                    position.y() - 9,
                    node_radius * 2,
                    18,
                ),
                Qt.AlignmentFlag.AlignCenter,
                str(count),
            )
            if index == self._hovered_index:
                self._paint_hover_label(painter, position, title, artist)
        painter.end()

    def mousePressEvent(self, event: object) -> None:
        position = getattr(event, "position", lambda: None)()
        if position is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._last_pointer_position = position
        self._is_rotating = True
        self._hovered_index = -1
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: object) -> None:
        position = getattr(event, "position", lambda: None)()
        if position is None or not self._tracks:
            return

        if self._is_rotating and self._last_pointer_position is not None:
            delta = position - self._last_pointer_position
            self._rotation_y += float(delta.x()) * 0.012
            self._rotation_x = max(
                -1.25,
                min(1.25, self._rotation_x + float(delta.y()) * 0.012),
            )
            self._last_pointer_position = position
            self.update()
            return

        projected = self._projected_positions()
        hovered = -1
        nearest_distance = 20.0
        for index, (node_position, _depth, _scale) in enumerate(projected):
            distance = sqrt(
                (position.x() - node_position.x()) ** 2
                + (position.y() - node_position.y()) ** 2
            )
            if distance < nearest_distance:
                hovered = index
                nearest_distance = distance
        if hovered != self._hovered_index:
            self._hovered_index = hovered
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if hovered >= 0
                else Qt.CursorShape.ArrowCursor
            )
            self.update()

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_rotating = False
            self._last_pointer_position = None
            self.unsetCursor()
            self.update()

    def wheelEvent(self, event: object) -> None:
        if not self._tracks:
            return
        direction = 1.12 if event.angleDelta().y() > 0 else 0.89
        self._zoom = max(0.72, min(1.55, self._zoom * direction))
        self.update()

    def leaveEvent(self, _event: object) -> None:
        if self._hovered_index != -1:
            self._hovered_index = -1
            self.unsetCursor()
            self.update()

    def _projected_positions(
        self,
    ) -> list[tuple[QPointF, float, float]]:
        center = QPointF(self.width() / 2, self.height() / 2 - 2)
        positions: list[tuple[QPointF, float, float]] = []
        orbit_x = max(42.0, min(self.width() * 0.41, 182.0)) * self._zoom
        orbit_y = max(34.0, min(self.height() * 0.36, 90.0)) * self._zoom
        cos_x = cos(self._rotation_x)
        sin_x = sin(self._rotation_x)
        cos_y = cos(self._rotation_y)
        sin_y = sin(self._rotation_y)
        for x3, y3, z3 in self._sphere_points:
            rotated_x = cos_y * x3 + sin_y * z3
            rotated_z = -sin_y * x3 + cos_y * z3
            rotated_y = cos_x * y3 - sin_x * rotated_z
            rotated_z = sin_x * y3 + cos_x * rotated_z
            perspective = 1.0 / max(0.46, 1.0 - rotated_z * 0.42)
            position = QPointF(
                center.x() + rotated_x * orbit_x * perspective,
                center.y() + rotated_y * orbit_y * perspective - rotated_z * 20.0,
            )
            positions.append((position, rotated_z, perspective))
        return positions

    @staticmethod
    def _build_cluster_groups(
        tracks: tuple[
            tuple[
                str,
                str,
                int,
                tuple[float, ...] | None,
                tuple[str, ...],
            ],
            ...,
        ],
        edges: tuple[tuple[int, int, float], ...],
    ) -> tuple[tuple[int, ...], ...]:
        """Return connected similarity communities for the visual layout."""

        count = len(tracks)
        if count <= 1:
            return tuple((index,) for index in range(count))

        parents = list(range(count))

        def find(index: int) -> int:
            while parents[index] != index:
                parents[index] = parents[parents[index]]
                index = parents[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        # Use the links shown on screen as the primary community definition.
        # Same-artist tracks are joined even when an embedding is unavailable.
        for left, right, strength in edges:
            if strength >= 0.48:
                union(left, right)
        for left_index, left in enumerate(tracks):
            for right_index in range(left_index + 1, count):
                right = tracks[right_index]
                left_artist = left[1].strip().casefold()
                right_artist = right[1].strip().casefold()
                same_artist = bool(left_artist and left_artist == right_artist)
                if same_artist:
                    union(left_index, right_index)

        groups: dict[int, list[int]] = {}
        for index in range(count):
            groups.setdefault(find(index), []).append(index)
        return tuple(
            tuple(members)
            for members in sorted(groups.values(), key=lambda values: values[0])
        )

    @staticmethod
    def _build_edge_pairs(
        tracks: tuple[
            tuple[
                str,
                str,
                int,
                tuple[float, ...] | None,
                tuple[str, ...],
            ],
            ...,
        ],
    ) -> tuple[tuple[int, int, float], ...]:
        """Connect only pairs with measurable genre/audio similarity."""

        pairs: set[tuple[int, int, float]] = set()
        for left_index, left_track in enumerate(tracks):
            neighbors = sorted(
                (
                    ListeningGraph._track_similarity(left_track, right_track),
                    right_index,
                )
                for right_index, right_track in enumerate(tracks)
                if right_index != left_index
            )
            for strength, right_index in neighbors[-3:]:
                if strength < 0.40:
                    continue
                first, second = sorted((left_index, right_index))
                pairs = {
                    pair
                    for pair in pairs
                    if pair[:2] != (first, second)
                }
                pairs.add((first, second, strength))
        return tuple(
            sorted(pairs, key=lambda pair: (pair[0], pair[1]))
        )

    @staticmethod
    def _track_similarity(
        left: tuple[
            str,
            str,
            int,
            tuple[float, ...] | None,
            tuple[str, ...],
        ],
        right: tuple[
            str,
            str,
            int,
            tuple[float, ...] | None,
            tuple[str, ...],
        ],
    ) -> float:
        embedding_score = ListeningGraph._cosine_similarity(
            left[3],
            right[3],
        )
        left_genres = set(left[4])
        right_genres = set(right[4])
        genre_score = (
            len(left_genres & right_genres) / len(left_genres | right_genres)
            if left_genres and right_genres
            else None
        )
        same_artist = left[1].strip().casefold() == right[1].strip().casefold()

        evidence = [score for score in (embedding_score, genre_score) if score is not None]
        if not evidence:
            return 0.78 if same_artist else 0.0
        if embedding_score is not None and genre_score is not None:
            score = embedding_score * 0.72 + genre_score * 0.28
        else:
            score = evidence[0]
        return max(score, 0.78) if same_artist else score

    @staticmethod
    def _cosine_similarity(
        left: tuple[float, ...] | None,
        right: tuple[float, ...] | None,
    ) -> float | None:
        if not left or not right:
            return None
        length = min(len(left), len(right))
        if not length:
            return None
        dot = sum(left[index] * right[index] for index in range(length))
        left_norm = sqrt(sum(value * value for value in left[:length]))
        right_norm = sqrt(sum(value * value for value in right[:length]))
        if left_norm <= 0 or right_norm <= 0:
            return None
        return max(0.0, min(1.0, dot / (left_norm * right_norm)))

    @classmethod
    def _build_layout_points(
        cls,
        tracks: tuple[
            tuple[
                str,
                str,
                int,
                tuple[float, ...] | None,
                tuple[str, ...],
            ],
            ...,
        ],
        cluster_groups: tuple[tuple[int, ...], ...] | None = None,
    ) -> tuple[tuple[float, float, float], ...]:
        """Place related tracks into readable, deterministic 3D communities.

        A pure force layout tends to collapse a small selected period into a
        line.  We therefore build a shallow spherical shell for every
        similarity community first.  The shell keeps the depth visible while
        the community anchors keep related tracks together.
        """

        count = len(tracks)
        if count <= 0:
            return ()
        if count == 1:
            return ((0.0, 0.0, 0.0),)

        groups = cluster_groups
        if not groups:
            groups = cls._build_cluster_groups(
                tracks,
                cls._build_edge_pairs(tracks),
            )

        group_count = len(groups)
        group_centers: dict[int, tuple[float, float, float]] = {}
        for group_index, members in enumerate(groups):
            if group_count == 1:
                center = (0.0, 0.0, 0.0)
            else:
                angle = (
                    2.0 * pi * group_index / group_count + 0.28
                    if group_count <= 4
                    else group_index * 2.399963 + 0.28
                )
                radius_x = min(0.68, 0.42 + 0.055 * sqrt(group_count))
                radius_y = min(0.50, 0.30 + 0.045 * sqrt(group_count))
                center = (
                    cos(angle) * radius_x,
                    sin(angle) * radius_y,
                    0.16 * sin(angle * 1.71),
                )
            for member in members:
                group_centers[member] = center

        points: list[tuple[float, float, float]] = [
            (0.0, 0.0, 0.0)
            for _ in tracks
        ]
        for group_index, members in enumerate(groups):
            center = group_centers[members[0]]
            member_count = len(members)
            local_scale = min(0.34, 0.145 + 0.046 * sqrt(member_count))
            phase = group_index * 1.17 + 0.4
            for local_index, member in enumerate(members):
                if member_count == 1:
                    local_x = local_y = local_z = 0.0
                else:
                    # Fibonacci-style points avoid a flat row when only a few
                    # tracks are selected and remain evenly spaced as a group
                    # grows.
                    latitude = 1.0 - 2.0 * (local_index + 0.5) / member_count
                    radial = sqrt(max(0.0, 1.0 - latitude * latitude))
                    angle = phase + local_index * 2.399963
                    local_x = cos(angle) * radial * local_scale
                    local_y = sin(angle) * radial * local_scale * 0.86
                    local_z = latitude * local_scale * 1.35
                points[member] = (
                    center[0] + local_x,
                    center[1] + local_y,
                    center[2] + local_z,
                )

        # A tiny deterministic jitter prevents exact projected overlaps after
        # a rotation, while keeping every community recognisably compact.
        return tuple(
            (
                max(-1.1, min(1.1, point[0] + 0.012 * cos(index * 2.41))),
                max(-1.0, min(1.0, point[1] + 0.012 * sin(index * 1.73))),
                max(-0.95, min(0.95, point[2] + 0.012 * sin(index * 2.07))),
            )
            for index, point in enumerate(points)
        )

    def _node_color(
        self,
        index: int,
        front: float,
        active: bool,
    ) -> QColor:
        palette = ("#14B893", "#8E7BC5", "#D08B55", "#4C9AA0", "#B36B8C")
        genres = self._tracks[index][4]
        key = genres[0] if genres else "unknown"
        color = QColor(palette[sum(ord(char) for char in key) % len(palette)])
        color.setAlpha(255 if active else int(130 + 105 * front))
        return color

    def _paint_hover_label(
        self,
        painter: QPainter,
        position: QPointF,
        title: str,
        artist: str,
    ) -> None:
        metrics = QFontMetrics(painter.font())
        available_width = max(170.0, self.width() - 12.0)
        bubble_width = min(
            available_width,
            max(
                170.0,
                float(
                    max(
                        metrics.horizontalAdvance(title),
                        metrics.horizontalAdvance(artist),
                    )
                    + 18
                ),
            ),
        )
        text_width = max(1, int(bubble_width - 18))

        def wrap(value: str) -> list[str]:
            if not value:
                return []
            words = value.split()
            lines: list[str] = []
            current = ""
            for word in words:
                candidate = f"{current} {word}".strip()
                if (
                    not current
                    or metrics.horizontalAdvance(candidate) <= text_width
                ):
                    current = candidate
                    continue
                lines.append(current)
                current = word
            if current:
                lines.append(current)
            return lines or [value]

        title_lines = wrap(title)
        artist_lines = wrap(artist)
        bubble_height = (
            10.0
            + max(1, len(title_lines)) * 17.0
            + (4.0 + len(artist_lines) * 15.0 if artist_lines else 0.0)
        )
        x = min(
            max(6.0, position.x() - bubble_width / 2),
            max(6.0, self.width() - bubble_width - 6.0),
        )
        y = position.y() - bubble_height - 18.0
        if y < 6.0:
            y = position.y() + 18.0
        bubble = QRectF(x, y, bubble_width, bubble_height)
        painter.setPen(QPen(QColor(181, 251, 224, 85), 1))
        painter.setBrush(QColor(7, 10, 12, 235))
        painter.drawRoundedRect(bubble, 7, 7)
        painter.setPen(QColor("#F1F9F5"))
        title_y = bubble.top() + 5.0
        for line in title_lines:
            painter.drawText(
                QRectF(bubble.left() + 9, title_y, bubble.width() - 18, 17),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                line,
            )
            title_y += 17.0
        if artist_lines:
            title_y += 4.0
            painter.setPen(QColor("#91A49E"))
            for line in artist_lines:
                painter.drawText(
                    QRectF(bubble.left() + 9, title_y, bubble.width() - 18, 15),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    line,
                )
                title_y += 15.0


class ListeningStatisticsDialog(QDialog):
    """Four-panel listening dashboard with a diagram and track graph."""

    def __init__(
        self,
        statistics: ListeningStatistics,
        parent: QWidget | None = None,
        *,
        track_catalog: tuple[Track, ...] | list[Track] = (),
    ) -> None:
        super().__init__(parent)
        prepare_dialog(self)
        self.setObjectName("listeningStatisticsDialog")
        self.setWindowTitle("Listening habits")
        self.resize(940, 700)
        self._statistics = statistics
        self._track_catalog = {
            (track.title.casefold(), track.artist.casefold()): track
            for track in track_catalog
        }
        # The diagram starts in the 30-day view.  The graph below it follows
        # whichever day or month is selected in that diagram.
        self._chart_mode = "day"
        self._chart_items = tuple(statistics.daily)
        self._selected_period_index: int | None = None
        self._daily_by_day = {
            item.day: item for item in statistics.daily
        }
        self._monthly_items = tuple(statistics.monthly)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 8, 20, 14)
        layout.setSpacing(8)

        period_text = (
            f"Last 30 days · {statistics.period_start.strftime('%d %b')} — "
            f"{statistics.period_end.strftime('%d %b %Y')}"
        )

        total_heading = QLabel("Total statistics")
        total_heading.setObjectName("listeningTotalHeading")
        layout.addWidget(total_heading)

        total_frame = QFrame()
        total_frame.setObjectName("listeningTotal")
        total_layout = QVBoxLayout(total_frame)
        total_layout.setContentsMargins(14, 6, 14, 7)
        total_layout.setSpacing(4)

        metric_row = QHBoxLayout()
        metric_row.setContentsMargins(0, 0, 0, 0)
        metric_row.setSpacing(8)
        metrics = (
            (self._format_minutes(statistics.listening_ms), "minutes listened"),
            (str(statistics.completed_listens), "completed listens"),
            (str(statistics.active_days), "active days"),
            (str(len(statistics.new_finds)), "new finds"),
            (str(statistics.skipped_count), "skips"),
            (str(statistics.liked_tracks), "liked tracks"),
        )
        for index, (value, label) in enumerate(metrics):
            self._add_metric(metric_row, value, label)
            if index < len(metrics) - 1:
                divider = QFrame()
                divider.setObjectName("listeningTotalDivider")
                divider.setFrameShape(QFrame.Shape.VLine)
                divider.setFixedWidth(1)
                metric_row.addWidget(divider)
        total_layout.addLayout(metric_row)
        layout.addWidget(total_frame)

        # Keep the date range with the chart it describes instead of spending
        # a separate row above the dashboard.
        period_label = QLabel(period_text)
        period_label.setObjectName("libraryMaintenanceDescription")

        content_grid = QGridLayout()
        content_grid.setHorizontalSpacing(12)
        content_grid.setVerticalSpacing(8)

        diagram_frame = QFrame()
        diagram_frame.setObjectName("listeningDiagramPanel")
        diagram_layout = QVBoxLayout(diagram_frame)
        diagram_layout.setContentsMargins(12, 10, 12, 10)
        diagram_header = QHBoxLayout()
        diagram_heading = QLabel("Diagram")
        diagram_heading.setObjectName("listeningPanelHeading")
        diagram_header.addWidget(diagram_heading)
        diagram_header.addStretch()
        self.chart_mode_combo = QComboBox()
        self.chart_mode_combo.addItems(("Days", "Months"))
        self.chart_mode_combo.currentIndexChanged.connect(
            self._change_chart_mode
        )
        diagram_header.addWidget(self.chart_mode_combo)
        diagram_layout.addLayout(diagram_header)
        self.bar_chart = ListeningBarChart()
        self.bar_chart.period_clicked.connect(self._show_chart_period)
        self.bar_chart.set_items(self._chart_items)
        diagram_layout.addWidget(self.bar_chart, 1)
        self.period_label = period_label
        diagram_layout.addWidget(period_label)
        content_grid.addWidget(diagram_frame, 0, 0)

        graph_frame = QFrame()
        graph_frame.setObjectName("listeningGraphPanel")
        graph_layout = QVBoxLayout(graph_frame)
        graph_layout.setContentsMargins(12, 10, 12, 10)
        graph_header = QHBoxLayout()
        graph_heading = QLabel("Graph")
        graph_heading.setObjectName("listeningPanelHeading")
        graph_header.addWidget(graph_heading)
        graph_header.addStretch()
        self.graph_period_label = QLabel("Selected period")
        self.graph_period_label.setObjectName("libraryMaintenanceDescription")
        graph_header.addWidget(self.graph_period_label)
        graph_layout.addLayout(graph_header)
        self.listening_graph = ListeningGraph()
        graph_layout.addWidget(self.listening_graph, 1)
        content_grid.addWidget(graph_frame, 1, 0)

        detail_frame = QFrame()
        detail_frame.setObjectName("listeningDetailPanel")
        detail_layout = QVBoxLayout(detail_frame)
        # Keep the metadata inset, while letting the table span the full
        # content width like the Highlights table below.
        # Let the table continue all the way to the panel's bottom edge.
        detail_layout.setContentsMargins(0, 10, 0, 0)
        detail_header = QWidget()
        detail_header_layout = QVBoxLayout(detail_header)
        detail_header_layout.setContentsMargins(12, 0, 12, 0)
        detail_header_layout.setSpacing(6)
        self.day_insight = QLabel("A quick read on this period.")
        self.day_insight.setObjectName("listeningDetailInsight")
        self.day_insight.setWordWrap(True)
        detail_header_layout.addWidget(self.day_insight)
        self.day_title = QLabel("Select a period")
        self.day_title.setObjectName("libraryMaintenanceTitle")
        detail_header_layout.addWidget(self.day_title)
        self.day_summary = QLabel(
            "Click a bar to inspect that period's pattern."
        )
        self.day_summary.setWordWrap(True)
        detail_header_layout.addWidget(self.day_summary)
        self.top_genre_label = QLabel("Top genre: —")
        detail_header_layout.addWidget(self.top_genre_label)
        detail_header_layout.addSpacing(3)
        self.top_tracks_heading = QLabel("Top tracks")
        self.top_tracks_heading.setObjectName("listeningPanelHeading")
        detail_header_layout.addWidget(self.top_tracks_heading)
        detail_layout.addWidget(detail_header)
        self.day_table = QTableWidget(0, 3)
        self.day_table.setObjectName("listeningPeriodTable")
        self.day_table.setHorizontalHeaderLabels(
            ("Track", "Artist", "Listens")
        )
        self.day_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.day_table.verticalHeader().setVisible(False)
        self.day_table.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.day_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.day_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.day_table.setShowGrid(False)
        self.day_table.setAlternatingRowColors(True)
        self.day_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.day_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.day_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.day_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.day_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        detail_layout.addWidget(self.day_table, 1)
        content_grid.addWidget(detail_frame, 0, 1)

        # Highlights belongs to the detail column: it stays aligned with the
        # selected-period table and no longer consumes a full-width row.
        insights = QWidget()
        insights.setObjectName("listeningHighlights")
        insights_layout = QVBoxLayout(insights)
        insights_layout.setContentsMargins(0, 0, 0, 0)
        insights_layout.setSpacing(4)
        highlights_heading = QLabel("Highlights")
        highlights_heading.setObjectName("listeningSectionHeading")
        insights_layout.addWidget(highlights_heading)
        self.highlights_table = QTableWidget(0, 3)
        self.highlights_table.setObjectName("listeningHighlightsTable")
        self.highlights_table.setHorizontalHeaderLabels(
            ("Category", "Favorite", "Count")
        )
        self.highlights_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.highlights_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.highlights_table.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )
        self.highlights_table.setShowGrid(False)
        self.highlights_table.setAlternatingRowColors(True)
        self.highlights_table.verticalHeader().setVisible(False)
        self.highlights_table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.highlights_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.highlights_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.highlights_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.highlights_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        insights_layout.addWidget(self.highlights_table)
        content_grid.addWidget(insights, 1, 1)
        content_grid.setColumnStretch(0, 3)
        content_grid.setColumnStretch(1, 2)
        content_grid.setRowStretch(0, 3)
        content_grid.setRowStretch(1, 2)
        layout.addLayout(content_grid, 1)
        self._populate_highlights()

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

        self._update_chart_period_label()
        if self._chart_items:
            self._show_chart_period(len(self._chart_items) - 1)

    def showEvent(self, event: object) -> None:
        super().showEvent(event)
        # Rebuild after the dialog receives its final size.  This also makes
        # reopening the modeless statistics window refresh the graph instead
        # of showing the previous paint pass.
        if self._chart_items:
            index = self._selected_period_index
            if index is None or index >= len(self._chart_items):
                index = len(self._chart_items) - 1
            QTimer.singleShot(0, lambda: self._show_chart_period(index))

    @staticmethod
    def _add_metric(layout: QHBoxLayout, value: str, label: str) -> None:
        metric = QWidget()
        metric_layout = QVBoxLayout(metric)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setSpacing(2)
        value_label = QLabel(value)
        value_label.setObjectName("listeningTotalValue")
        value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        metric_layout.addWidget(value_label)
        caption = QLabel(label)
        caption.setObjectName("listeningTotalCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setWordWrap(True)
        metric_layout.addWidget(caption)
        layout.addWidget(metric, 1)

    @staticmethod
    def _format_minutes(milliseconds: int) -> str:
        minutes = max(0, round(milliseconds / 60_000))
        hours, remainder = divmod(minutes, 60)
        return f"{hours}h {remainder:02d}m" if hours else f"{remainder}m"

    def _change_chart_mode(self, index: int) -> None:
        self._chart_mode = "month" if index == 1 else "day"
        self._chart_items = (
            self._monthly_items
            if self._chart_mode == "month"
            else tuple(self._statistics.daily)
        )
        self.bar_chart.set_items(self._chart_items)
        self._update_chart_period_label()
        if self._chart_items:
            self._show_chart_period(len(self._chart_items) - 1)
        else:
            self.listening_graph.set_tracks(())
            self.graph_period_label.setText("No selected period")

    def _show_chart_period(self, index: int) -> None:
        items = self._chart_items
        if not (0 <= index < len(items)):
            return
        item = items[index]
        self._selected_period_index = index
        self.bar_chart.set_selected_index(index)
        is_month = self._chart_mode == "month"
        period_date = item.month if is_month else item.day
        self.day_title.setText(
            period_date.strftime("%B %Y" if is_month else "%A, %d %B")
        )
        self.day_summary.setText(
            f"{self._format_minutes(item.listening_ms)} listened · "
            f"{item.completed_listens} completed · {item.skipped} skipped"
        )
        top_genre = (
            item.top_genre
            if is_month
            else (item.top_genres[0].label if item.top_genres else "")
        )
        self.top_genre_label.setText(f"Top genre: {top_genre or '—'}")
        # Keep this detail table intentionally compact.  The complete period
        # history is still fed to Graph below, while the table is a quick
        # top-five summary for the selected day/month.
        period_tracks = tuple(getattr(item, "top_tracks", ()))[:5]
        self.day_insight.setText(
            self._period_insight(item, period_tracks)
        )
        self.top_tracks_heading.setText("Top tracks")
        self.day_table.setRowCount(0)
        for stat in period_tracks:
            row = self.day_table.rowCount()
            self.day_table.insertRow(row)
            track_item = QTableWidgetItem(stat.label)
            track_item.setToolTip(stat.label)
            artist_item = QTableWidgetItem(stat.subtitle)
            artist_item.setToolTip(stat.subtitle)
            self.day_table.setItem(row, 0, track_item)
            self.day_table.setItem(row, 1, artist_item)
            self.day_table.setItem(row, 2, QTableWidgetItem(str(stat.count)))
        self.listening_graph.set_tracks(self._build_graph_tracks((item,)))
        self.graph_period_label.setText(
            f"Selected {period_date.strftime('%b %Y' if is_month else '%d %b')}"
        )

    @staticmethod
    def _period_insight(
        item: object,
        period_tracks: tuple[object, ...],
    ) -> str:
        """Return one compact, human-readable observation for the period."""

        completed = max(0, int(getattr(item, "completed_listens", 0)))
        skipped = max(0, int(getattr(item, "skipped", 0)))
        track_count = max(0, int(getattr(item, "track_count", 0)))
        if period_tracks and completed:
            leader = period_tracks[0]
            leader_title = str(getattr(leader, "label", "A track"))
            leader_count = max(0, int(getattr(leader, "count", 0)))
            share = round(leader_count / completed * 100)
            if track_count:
                return (
                    f"{leader_title} led this period with {leader_count} "
                    f"of {completed} listens · {track_count} unique tracks"
                )
            return (
                f"{leader_title} led this period with {share}% of your listens"
            )
        if skipped:
            return (
                f"A quieter period: {skipped} skipped track(s) and no "
                "completed listens yet"
            )
        return "No completed listens for this period yet"

    def _update_chart_period_label(self) -> None:
        if not self._chart_items:
            self.period_label.setText("No listening data yet")
            return

        is_month = self._chart_mode == "month"
        period_name = "Last 12 months" if is_month else "Last 30 days"
        start = self._chart_items[0].month if is_month else self._chart_items[0].day
        end = self._chart_items[-1].month if is_month else self._chart_items[-1].day
        date_format = "%b %Y" if is_month else "%d %b"
        self.period_label.setText(
            f"{period_name} · "
            f"{start.strftime(date_format)} — "
            f"{end.strftime('%b %Y' if is_month else '%d %b %Y')}"
        )

    def _build_graph_tracks(
        self,
        items: tuple[object, ...] | list[object],
    ) -> tuple[
        tuple[str, str, int, tuple[float, ...] | None, tuple[str, ...]],
        ...,
    ]:
        counts: Counter[tuple[str, str]] = Counter()
        for item in items:
            period_tracks = getattr(item, "all_tracks", ())
            if not period_tracks:
                period_tracks = getattr(item, "top_tracks", ())
            for stat in period_tracks:
                title = str(getattr(stat, "label", "")).strip()
                artist = str(getattr(stat, "subtitle", "")).strip()
                if title:
                    counts[(title, artist)] += max(
                        0,
                        int(getattr(stat, "count", 0)),
                    )
        rows = []
        for (title, artist), count in counts.most_common():
            if count <= 0:
                continue
            track = self._track_catalog.get(
                (title.casefold(), artist.casefold())
            )
            embedding = (
                tuple(float(value) for value in track.track_embedding)
                if track is not None and track.track_embedding
                else None
            )
            genres = ()
            if track is not None:
                detected_genres = tuple(
                    genre.parent_genre
                    for genre in track.detected_genres
                    if genre.parent_genre.strip()
                )
                genres = tuple(track.genres) + detected_genres
            rows.append((title, artist, count, embedding, genres))
        return tuple(rows)

    def _populate_highlights(self) -> None:
        groups = (
            ("Track", self._statistics.top_tracks),
            ("Artist", self._statistics.favorite_artists),
            ("Genre", self._statistics.favorite_genres),
            ("New find", self._statistics.new_finds),
            ("Skipped", self._statistics.skipped_tracks),
        )
        self.highlights_table.setRowCount(0)
        for category, stats in groups:
            if not stats:
                continue
            stat = stats[0]
            row = self.highlights_table.rowCount()
            self.highlights_table.insertRow(row)
            self.highlights_table.setItem(row, 0, QTableWidgetItem(category))
            favorite_item = QTableWidgetItem(stat.label)
            favorite_item.setToolTip(stat.label)
            self.highlights_table.setItem(row, 1, favorite_item)
            self.highlights_table.setItem(row, 2, QTableWidgetItem(str(stat.count)))

        self.highlights_table.resizeRowsToContents()
        header_height = self.highlights_table.horizontalHeader().sizeHint().height()
        rows_height = sum(
            self.highlights_table.rowHeight(row)
            for row in range(self.highlights_table.rowCount())
        )
        self.highlights_table.setFixedHeight(
            max(34, header_height + rows_height + 4)
        )


class LibraryMaintenanceDialog(QDialog):
    """One place for non-destructive library checks and data portability."""

    scan_requested = Signal()
    zip_backup_requested = Signal()
    json_export_requested = Signal()
    restore_requested = Signal()
    watch_folder_requested = Signal()
    watch_sync_requested = Signal()
    watch_disable_requested = Signal()
    watch_update_metadata_toggled = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        watch_config: WatchFolderConfig | None = None,
    ) -> None:
        super().__init__(parent)
        prepare_dialog(self)
        self.setObjectName("libraryMaintenanceDialog")
        self.setWindowTitle("Library health & backup")
        self.resize(780, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        title = QLabel("Library health & backup")
        title.setObjectName("libraryMaintenanceTitle")
        layout.addWidget(title)

        description = QLabel(
            "Check missing or unreadable audio and review duplicates. "
            "Acoustic matching compares decoded sound, so it can find the "
            "same recording saved in different codecs."
        )
        description.setObjectName("libraryMaintenanceDescription")
        description.setWordWrap(True)
        layout.addWidget(description)

        health_row = QHBoxLayout()
        self.health_status = QLabel("No scan has been run yet.")
        self.health_status.setObjectName("libraryMaintenanceStatus")
        health_row.addWidget(self.health_status, 1)
        self.scan_button = QPushButton("Check library")
        self.scan_button.clicked.connect(self.scan_requested)
        health_row.addWidget(self.scan_button)
        layout.addLayout(health_row)

        self.issues_table = QTableWidget(0, 3)
        self.issues_table.setHorizontalHeaderLabels(
            ("Check", "Track", "Details")
        )
        self.issues_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.issues_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.issues_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.issues_table.verticalHeader().setVisible(False)
        self.issues_table.setAlternatingRowColors(True)
        header = self.issues_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.issues_table, 1)

        watch_frame = QFrame()
        watch_frame.setObjectName("libraryMaintenanceBackup")
        watch_layout = QVBoxLayout(watch_frame)
        watch_layout.setContentsMargins(12, 9, 12, 9)
        watch_layout.setSpacing(5)
        watch_top_row = QHBoxLayout()
        self.watch_status = QLabel()
        self.watch_status.setObjectName("libraryMaintenanceStatus")
        watch_top_row.addWidget(self.watch_status, 1)
        self.watch_choose_button = QPushButton("Choose folder…")
        self.watch_choose_button.clicked.connect(self.watch_folder_requested)
        watch_top_row.addWidget(self.watch_choose_button)
        self.watch_sync_button = QPushButton("Sync now")
        self.watch_sync_button.clicked.connect(self.watch_sync_requested)
        watch_top_row.addWidget(self.watch_sync_button)
        self.watch_disable_button = QPushButton("Disable")
        self.watch_disable_button.clicked.connect(self.watch_disable_requested)
        watch_top_row.addWidget(self.watch_disable_button)
        watch_layout.addLayout(watch_top_row)
        self.watch_metadata_check = QCheckBox(
            "Update title and artist when a changed file has new tags"
        )
        self.watch_metadata_check.toggled.connect(
            self.watch_update_metadata_toggled
        )
        watch_layout.addWidget(self.watch_metadata_check)
        layout.addWidget(watch_frame)
        self.set_watch_config(watch_config or WatchFolderConfig())

        backup_frame = QFrame()
        backup_frame.setObjectName("libraryMaintenanceBackup")
        backup_layout = QVBoxLayout(backup_frame)
        backup_layout.setContentsMargins(12, 10, 12, 10)
        backup_layout.setSpacing(6)
        backup_label = QLabel(
            "Full ZIP includes the database, audio, covers and analysis. "
            "JSON is a portable catalog export without audio files."
        )
        backup_label.setWordWrap(True)
        backup_layout.addWidget(backup_label)
        backup_actions = QHBoxLayout()
        self.zip_backup_button = QPushButton("Create ZIP backup")
        self.zip_backup_button.clicked.connect(self.zip_backup_requested)
        backup_actions.addWidget(self.zip_backup_button)
        self.json_export_button = QPushButton("Export JSON")
        self.json_export_button.clicked.connect(self.json_export_requested)
        backup_actions.addWidget(self.json_export_button)
        backup_actions.addStretch()
        self.restore_button = QPushButton("Restore ZIP backup…")
        self.restore_button.clicked.connect(self.restore_requested)
        backup_actions.addWidget(self.restore_button)
        backup_layout.addLayout(backup_actions)
        layout.addWidget(backup_frame)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        close_row.addWidget(close_button)
        layout.addLayout(close_row)

    def set_scanning(self, active: bool) -> None:
        self.scan_button.setEnabled(not active)
        self.zip_backup_button.setEnabled(not active)
        self.json_export_button.setEnabled(not active)
        self.restore_button.setEnabled(not active)
        self.health_status.setText(
            "Checking files and acoustic fingerprints…" if active
            else self.health_status.text()
        )

    def show_report(self, report: LibraryHealthReport) -> None:
        self.set_scanning(False)
        rows: list[tuple[str, str, str]] = []
        rows.extend(
            ("Missing file", self._track_name(issue.track), issue.detail)
            for issue in report.missing_files
        )
        rows.extend(
            ("Unreadable audio", self._track_name(issue.track), issue.detail)
            for issue in report.broken_audio
        )
        rows.extend(
            (
                "Identical files",
                self._track_group_name(group.tracks),
                "The files have the same SHA-256 hash.",
            )
            for group in report.exact_duplicates
        )
        rows.extend(
            (
                "Acoustic match",
                self._track_group_name(group.tracks),
                f"Fingerprint similarity: {group.similarity:.1%}",
            )
            for group in report.acoustic_duplicates
        )
        rows.extend(
            ("Not fingerprinted", self._track_name(issue.track), issue.detail)
            for issue in report.fingerprint_unavailable
        )

        self.issues_table.setRowCount(0)
        for check, track_name, detail in rows:
            row = self.issues_table.rowCount()
            self.issues_table.insertRow(row)
            self.issues_table.setItem(row, 0, QTableWidgetItem(check))
            self.issues_table.setItem(row, 1, QTableWidgetItem(track_name))
            self.issues_table.setItem(row, 2, QTableWidgetItem(detail))

        found = len(rows)
        self.health_status.setText(
            f"Checked {report.checked_tracks} track(s): "
            f"{found} item(s) need review."
            if found
            else f"Checked {report.checked_tracks} track(s): library looks healthy."
        )

    def set_watch_config(self, config: WatchFolderConfig) -> None:
        if config.enabled and config.folder is not None:
            self.watch_status.setText(f"Watching: {config.folder}")
        elif config.folder is not None:
            self.watch_status.setText(f"Paused: {config.folder}")
        else:
            self.watch_status.setText("No watch folder selected.")
        self.watch_metadata_check.blockSignals(True)
        self.watch_metadata_check.setChecked(config.update_metadata)
        self.watch_metadata_check.blockSignals(False)

    def show_watch_report(self, report: WatchFolderReport) -> None:
        if report.folder is None:
            return
        parts = [
            f"Imported: {len(report.imported)}",
            f"Updated: {len(report.updated)}",
            f"Skipped unchanged: {report.skipped}",
            f"Removed from folder: {len(report.removed_files)}",
        ]
        if report.errors:
            parts.append(f"Errors: {len(report.errors)}")
        self.watch_status.setText(" · ".join(parts))

    def show_scan_error(self, message: str) -> None:
        self.set_scanning(False)
        self.health_status.setText(f"Check failed: {message}")

    @staticmethod
    def _track_name(track: Track) -> str:
        return f"{track.artist} — {track.title}"

    @classmethod
    def _track_group_name(cls, tracks: tuple[Track, ...]) -> str:
        return "  •  ".join(cls._track_name(track) for track in tracks)


class ImportLogDialog(QDialog):
    """Read-only history of tracks successfully added to the library."""

    _SOURCE_LABELS: ClassVar[dict[str, str]] = {
        "local_upload": "Local file",
        "windows_import": "Local file",
        "windows_folder_import": "Local folder",
        "youtube": "YouTube",
        "soundcloud_import": "SoundCloud",
        "mp3party": "MP3Party",
        "spotify": "Spotify",
        "spotify_favorite": "Spotify favorite sync",
        "watch_folder": "Watch folder",
    }

    def __init__(
        self,
        tracks: list[Track] | tuple[Track, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        prepare_dialog(self)

        self.setWindowTitle("Import log")
        self.resize(720, 460)

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"{len(tracks)} track(s) added to the library."
            )
        )

        self.log_table = QTableWidget(0, 3)
        self.log_table.setHorizontalHeaderLabels(
            ("Added", "Track", "Method")
        )
        self.log_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.log_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.log_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.log_table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.log_table.customContextMenuRequested.connect(
            self._show_track_context_menu
        )
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setAlternatingRowColors(True)
        header = self.log_table.horizontalHeader()
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

        ordered_tracks = sorted(
            tracks,
            key=lambda track: self._timestamp_sort_key(track.created_at),
            reverse=True,
        )
        for track in ordered_tracks:
            row = self.log_table.rowCount()
            self.log_table.insertRow(row)
            self.log_table.setItem(
                row,
                0,
                QTableWidgetItem(self._format_timestamp(track.created_at)),
            )
            track_item = QTableWidgetItem(
                f"{track.artist} — {track.title}"
            )
            if track.source_url:
                track_item.setToolTip(track.source_url)
                track_item.setData(
                    Qt.ItemDataRole.UserRole,
                    track.source_url,
                )
            self.log_table.setItem(row, 1, track_item)
            self.log_table.setItem(
                row,
                2,
                QTableWidgetItem(self._source_label(track.source)),
            )

        layout.addWidget(self.log_table, 1)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        buttons_layout.addWidget(close_button)
        layout.addLayout(buttons_layout)

    def _show_track_context_menu(self, position) -> None:
        index = self.log_table.indexAt(position)
        if not index.isValid():
            return

        self.log_table.selectRow(index.row())
        track_item = self.log_table.item(index.row(), 1)
        source_url = ""
        if track_item is not None:
            source_url = str(
                track_item.data(Qt.ItemDataRole.UserRole) or ""
            ).strip()

        menu = QMenu(self.log_table)
        copy_action = menu.addAction("Copy link")
        copy_action.setEnabled(bool(source_url))
        copy_action.triggered.connect(
            lambda _checked=False, url=source_url: (
                QGuiApplication.clipboard().setText(url)
                if url
                else None
            )
        )
        menu.exec(
            self.log_table.viewport().mapToGlobal(position)
        )

    @classmethod
    def _source_label(cls, source: str) -> str:
        return cls._SOURCE_LABELS.get(
            source,
            source.replace("_", " ").title() or "Unknown",
        )

    @staticmethod
    def _format_timestamp(value: object) -> str:
        if not hasattr(value, "strftime"):
            return str(value)
        if getattr(value, "tzinfo", None) is not None:
            value = value.astimezone()
        return value.strftime("%d %b %Y, %H:%M")

    @staticmethod
    def _timestamp_sort_key(value: object) -> float:
        timestamp = getattr(value, "timestamp", None)
        if not callable(timestamp):
            return 0.0
        try:
            return float(timestamp())
        except (OverflowError, OSError, ValueError):
            return 0.0
