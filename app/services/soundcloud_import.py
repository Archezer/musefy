from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

import yt_dlp
from dotenv import load_dotenv
from yt_dlp.utils import DownloadError

from app.domain.models import Track
from app.ingestion.audio import (
    SUPPORTED_AUDIO_EXTENSIONS,
    AudioIngestionService,
)
from app.services.parallel_playlist import parallel_playlist_import

SUPPORTED_SOUNDCLOUD_HOSTS = {
    "soundcloud.com",
    "www.soundcloud.com",
    "m.soundcloud.com",
    "on.soundcloud.com",
}

SOUNDCLOUD_AUDIO_FORMAT = (
    # ``download`` is the original uploaded file when SoundCloud exposes it
    # to the current account.  Streaming formats are the safe fallback.
    "download/"
    "bestaudio[vcodec=none][format_id!*=preview]"
)
SOUNDCLOUD_FULL_TRACK_ERROR = (
    "SoundCloud provided no full-length audio stream. "
    "Only a preview may be available, or the track may require "
    "an authorized SoundCloud session."
)


@dataclass(frozen=True)
class SoundCloudCandidate:
    """One public SoundCloud track returned by the search endpoint."""

    track_id: str
    title: str
    artist: str
    duration_ms: int | None
    playback_count: int | None
    url: str
    playlist_position: int | None = None


@dataclass(frozen=True)
class SoundCloudPlaylist:
    """A SoundCloud set and its resolved track candidates."""

    name: str
    candidates: tuple[SoundCloudCandidate, ...]
    cover_url: str | None = None


@dataclass(frozen=True)
class SoundCloudPlaylistImportResult:
    """Per-track results from importing a SoundCloud set."""

    imported: tuple[Track, ...]
    failed: tuple[tuple[SoundCloudCandidate, str], ...]
    imported_candidates: tuple[tuple[SoundCloudCandidate, Track], ...] = ()


class SoundCloudImportService:
    """Search and download authorized SoundCloud tracks through yt-dlp."""

    DEFAULT_SEARCH_RESULTS = 5

    def __init__(
        self,
        ingestion_service: AudioIngestionService,
        *,
        timeout_seconds: int = 900,
        search_timeout_seconds: int = 60,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("SoundCloud timeout must be positive.")
        if search_timeout_seconds <= 0:
            raise ValueError("SoundCloud search timeout must be positive.")

        self.ingestion_service = ingestion_service
        self.timeout_seconds = timeout_seconds
        self.search_timeout_seconds = search_timeout_seconds

    def search(
        self,
        query: str,
        *,
        max_results: int = DEFAULT_SEARCH_RESULTS,
    ) -> list[SoundCloudCandidate]:
        """Return the first SoundCloud tracks matching ``query``."""

        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("SoundCloud search query must not be empty.")
        if not 1 <= max_results <= 50:
            raise ValueError(
                "SoundCloud max_results must be between 1 and 50."
            )

        options = {
            "quiet": True,
            "no_warnings": True,
            # A search result may point to a DRM-protected track.  Keep the
            # other results instead of failing the whole search.
            "ignoreerrors": True,
            "skip_download": True,
            # Resolve each result so the dialog receives the track's full
            # metadata instead of the short preview metadata.
            "extract_flat": False,
            "noplaylist": False,
            "socket_timeout": self.search_timeout_seconds,
        }
        options.update(self._authentication_options())

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                result = downloader.extract_info(
                    f"scsearch{max_results}:{normalized_query}",
                    download=False,
                )
        except DownloadError as error:
            raise RuntimeError("SoundCloud search failed.") from error

        return self._candidates_from_entries(
            result.get("entries", []) if result else [],
            with_positions=False,
        )

    def playlist(self, url: str) -> SoundCloudPlaylist:
        """Resolve one SoundCloud set into individually downloadable tracks."""

        normalized_url = url.strip()
        if not self.is_playlist_url(normalized_url):
            raise ValueError("SoundCloud playlist URL must point to a set.")

        options = {
            "quiet": True,
            "no_warnings": True,
            # A set can contain a mix of downloadable and DRM-protected
            # tracks.  Resolve the available entries and skip only failures.
            "ignoreerrors": True,
            "skip_download": True,
            "extract_flat": False,
            "noplaylist": False,
            "socket_timeout": self.search_timeout_seconds,
        }
        options.update(self._authentication_options())

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                result = downloader.extract_info(
                    normalized_url,
                    download=False,
                )
        except DownloadError as error:
            raise RuntimeError("SoundCloud playlist loading failed.") from error

        if not isinstance(result, dict):
            raise TypeError("SoundCloud playlist returned no tracks.")

        candidates = tuple(
            self._candidates_from_entries(
                result.get("entries", []),
                with_positions=True,
            )
        )
        if not candidates:
            raise RuntimeError("SoundCloud playlist returned no tracks.")

        thumbnail = result.get("thumbnail")
        return SoundCloudPlaylist(
            name=str(result.get("title") or "SoundCloud playlist"),
            candidates=candidates,
            cover_url=str(thumbnail) if thumbnail else None,
        )

    def download_and_import_playlist(
        self,
        candidates: list[SoundCloudCandidate],
        *,
        on_progress: Callable[[int, int], None] | None = None,
        on_track_imported: Callable[[SoundCloudCandidate, Track], None]
        | None = None,
    ) -> SoundCloudPlaylistImportResult:
        """Download selected set items concurrently and keep partial successes."""

        imported, failed, imported_candidates = parallel_playlist_import(
            candidates,
            self.download,
            on_progress=on_progress,
            on_track_imported=on_track_imported,
        )

        return SoundCloudPlaylistImportResult(
            imported=imported,
            failed=failed,
            imported_candidates=imported_candidates,
        )

    def download(self, source: str | SoundCloudCandidate) -> Track:
        """Download one selected SoundCloud track and import it."""

        candidate: SoundCloudCandidate | None = (
            source if isinstance(source, SoundCloudCandidate) else None
        )
        normalized_source = (
            candidate.url if candidate is not None else source.strip()
        )
        if not normalized_source:
            raise ValueError("SoundCloud URL must not be empty.")

        if not self.is_supported_url(normalized_source):
            raise ValueError(
                "SoundCloud download requires a track URL or a search result."
            )
        if self.is_playlist_url(normalized_source):
            raise ValueError(
                "SoundCloud set URLs must be loaded as a playlist first."
            )

        with TemporaryDirectory(
            prefix="music-recommendation-soundcloud-"
        ) as directory:
            output_directory = Path(directory)
            options = {
                "quiet": True,
                "no_warnings": True,
                "noplaylist": True,
                "format": SOUNDCLOUD_AUDIO_FORMAT,
                "outtmpl": str(output_directory / "%(id)s.%(ext)s"),
                "overwrites": False,
                "socket_timeout": self.timeout_seconds,
            }
            options.update(self._authentication_options())

            try:
                with yt_dlp.YoutubeDL(options) as downloader:
                    info = downloader.extract_info(
                        normalized_source,
                        download=False,
                    )
                    if self._has_explicit_formats(info) and not any(
                        self._is_full_length_audio_format(format_info)
                        for format_info in info["formats"]
                    ):
                        raise RuntimeError(SOUNDCLOUD_FULL_TRACK_ERROR)

                    downloader.download([normalized_source])
            except PermissionError:
                raise
            except RuntimeError:
                raise
            except DownloadError as error:
                if "requested format is not available" in str(error).casefold():
                    raise RuntimeError(SOUNDCLOUD_FULL_TRACK_ERROR) from error
                raise RuntimeError("SoundCloud download failed.") from error

            downloaded_file = self._find_downloaded_file(output_directory)
            if downloaded_file is None:
                raise RuntimeError(
                    SOUNDCLOUD_FULL_TRACK_ERROR
                )

            return self.ingestion_service.ingest(
                downloaded_file,
                title=candidate.title if candidate is not None else None,
                artist=candidate.artist if candidate is not None else None,
                fallback_title=downloaded_file.stem,
                source="soundcloud_import",
                source_id=candidate.track_id if candidate is not None else None,
                source_url=normalized_source,
            )

    @staticmethod
    def is_supported_url(value: str) -> bool:
        parsed_url = urlparse(value.strip())
        hostname = (parsed_url.hostname or "").casefold()
        return (
            parsed_url.scheme in {"http", "https"}
            and hostname in SUPPORTED_SOUNDCLOUD_HOSTS
        )

    @staticmethod
    def is_playlist_url(value: str) -> bool:
        """Return whether a SoundCloud URL points to a ``/sets/`` page."""

        parsed_url = urlparse(value.strip())
        path_parts = tuple(
            part.casefold()
            for part in parsed_url.path.split("/")
            if part
        )
        return (
            SoundCloudImportService.is_supported_url(value)
            and "sets" in path_parts
        )

    @staticmethod
    def _authentication_options() -> dict[str, str]:
        """Return optional, user-supplied SoundCloud credentials for yt-dlp."""

        load_dotenv()
        options: dict[str, str] = {}
        cookie_file = os.environ.get("SOUNDCLOUD_COOKIES_FILE", "").strip()
        oauth_token = os.environ.get("SOUNDCLOUD_OAUTH_TOKEN", "").strip()

        if cookie_file:
            options["cookiefile"] = cookie_file
        if oauth_token:
            # yt-dlp's SoundCloud extractor treats username=oauth as an OAuth
            # token login.  Do not log this options dict: it contains secrets.
            options["username"] = "oauth"
            options["password"] = oauth_token

        return options

    @staticmethod
    def _has_explicit_formats(info: object) -> bool:
        return isinstance(info, dict) and isinstance(info.get("formats"), list)

    @staticmethod
    def _is_full_length_audio_format(format_info: object) -> bool:
        if not isinstance(format_info, dict):
            return False
        if format_info.get("vcodec") != "none" or not format_info.get("url"):
            return False
        if format_info.get("is_preview"):
            return False

        format_id = str(format_info.get("format_id") or "").casefold()
        format_note = str(format_info.get("format_note") or "").casefold()
        stream_url = str(format_info.get("url") or "").casefold()
        return not (
            "preview" in format_id
            or "preview" in format_note
            or "/preview/" in stream_url
            or "/playlist/0/30/" in stream_url
        )

    @classmethod
    def _candidates_from_entries(
        cls,
        entries: object,
        *,
        with_positions: bool,
    ) -> list[SoundCloudCandidate]:
        if not isinstance(entries, (list, tuple)):
            return []

        candidates: list[SoundCloudCandidate] = []
        for position, entry in enumerate(entries):
            candidate = cls._candidate_from_entry(
                entry,
                position=position if with_positions else None,
            )
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    @classmethod
    def _candidate_from_entry(
        cls,
        entry: object,
        *,
        position: int | None,
    ) -> SoundCloudCandidate | None:
        if not isinstance(entry, dict):
            return None

        track_id = entry.get("id")
        url = entry.get("webpage_url") or entry.get("original_url")
        if not track_id or not url or not cls.is_supported_url(str(url)):
            return None

        duration = entry.get("duration")
        artists = entry.get("artists") or []
        artist = entry.get("uploader")
        if not artist and artists:
            first_artist = artists[0]
            artist = (
                first_artist.get("name")
                if isinstance(first_artist, dict)
                else first_artist
            )

        return SoundCloudCandidate(
            track_id=str(track_id),
            title=str(entry.get("title") or "Unknown title"),
            artist=str(artist or "Unknown artist"),
            duration_ms=(
                round(float(duration) * 1000)
                if duration is not None
                else None
            ),
            playback_count=entry.get("view_count"),
            url=str(url),
            playlist_position=position,
        )

    @staticmethod
    def _find_downloaded_file(directory: Path) -> Path | None:
        audio_files = sorted(
            (
                path
                for path in directory.rglob("*")
                if path.is_file()
                and path.suffix.casefold() in SUPPORTED_AUDIO_EXTENSIONS
            ),
            key=lambda path: str(path).casefold(),
        )
        return audio_files[0] if audio_files else None
