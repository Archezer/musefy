from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from app.domain.models import Track
from app.ingestion.audio import AudioIngestionService
from app.services.parallel_playlist import parallel_playlist_import

SUPPORTED_MP3PARTY_HOSTS = {
    "mp3party.net",
    "www.mp3party.net",
}
MP3PARTY_BASE_URL = "https://mp3party.net"
MP3PARTY_USER_AGENT = "Mozilla/5.0 (compatible; Musefy/0.1)"
MP3PARTY_MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024


@dataclass(frozen=True)
class Mp3PartyCandidate:
    """One MP3Party track returned by search or a direct track page."""

    track_id: str
    title: str
    artist: str
    duration_ms: int | None
    url: str
    audio_url: str
    cover_url: str | None = None
    # MP3Party exposes a dedicated download endpoint in addition to the
    # player stream URL.  Prefer it when present because it is the URL used
    # by the site's own download button.
    download_url: str | None = None
    # Position in the source playlist, when the candidate was found as part
    # of a playlist retry search.  Direct searches leave it unset.
    playlist_position: int | None = None


@dataclass(frozen=True)
class Mp3PartyPlaylistImportResult:
    """Per-track results from importing an MP3Party playlist selection."""

    imported: tuple[Track, ...]
    failed: tuple[tuple[Mp3PartyCandidate, str], ...]
    imported_candidates: tuple[tuple[Mp3PartyCandidate, Track], ...] = ()


class _Mp3PartyHTMLParser(HTMLParser):
    """Extract the public track data embedded in MP3Party HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[dict[str, object]] = []
        self._stack: list[tuple[str, set[str]]] = []
        self._current: dict[str, object] | None = None
        self._info_values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        self._stack.append((tag, classes))

        if self._current is None and "track__user-panel" in classes:
            self._current = {
                "track_id": attributes.get("data-js-id"),
                "title": attributes.get("data-js-song-title"),
                "artist": attributes.get("data-js-artist-name"),
                "audio_url": attributes.get("data-js-url"),
                "cover_url": attributes.get("data-js-image"),
                "download_url": None,
            }
            self._info_values = []
            return

        if "js-download" in classes or "js-dw-btn" in classes:
            download_url = attributes.get("data-download-url")
            if not download_url and "js-dw-btn" in classes:
                download_url = attributes.get("href")
            if not download_url:
                return

            if self._current is not None:
                self._current["download_url"] = download_url
                return

            track_id = attributes.get("data-track-id")
            if not track_id:
                return

            for entry in reversed(self.entries):
                if str(entry.get("track_id") or "") == track_id:
                    entry["download_url"] = download_url
                    break

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        if any("track__info" in classes for _, classes in self._stack):
            self._info_values.append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return

        _, classes = self._stack.pop()
        if self._current is None:
            return

        if "track__user-panel" in classes:
            self._current["duration_ms"] = _parse_duration_ms(
                self._info_values
            )
            self.entries.append(self._current)
            self._current = None
            self._info_values = []


class Mp3PartyImportService:
    """Search and import authorized MP3Party tracks as MP3 audio."""

    DEFAULT_SEARCH_RESULTS = 5

    def __init__(
        self,
        ingestion_service: AudioIngestionService,
        *,
        timeout_seconds: int = 120,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("MP3Party timeout must be positive.")

        self.ingestion_service = ingestion_service
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        query: str,
        *,
        max_results: int = DEFAULT_SEARCH_RESULTS,
    ) -> list[Mp3PartyCandidate]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("MP3Party search query must not be empty.")
        if not 1 <= max_results <= 50:
            raise ValueError(
                "MP3Party max_results must be between 1 and 50."
            )

        search_url = f"{MP3PARTY_BASE_URL}/search?{urlencode({'q': normalized_query})}"
        entries = self._read_entries(search_url)
        candidates = self._build_candidates(entries)
        return candidates[:max_results]

    def candidate_from_url(self, url: str) -> Mp3PartyCandidate:
        normalized_url = url.strip()
        if not self.is_supported_url(normalized_url):
            raise ValueError("MP3Party URL must point to a music track.")

        entries = self._read_entries(normalized_url)
        candidates = self._build_candidates(entries)
        requested_track_id = urlparse(normalized_url).path.rstrip("/").split("/")[-1]
        for candidate in candidates:
            if candidate.track_id == requested_track_id:
                return candidate

        if not candidates:
            raise RuntimeError("MP3Party page did not expose track metadata.")

        raise RuntimeError(
            "MP3Party page did not expose metadata for the requested track."
        )

    def download(self, source: str | Mp3PartyCandidate) -> Track:
        """Download one MP3Party MP3 and import it into the local library."""

        candidate = (
            source
            if isinstance(source, Mp3PartyCandidate)
            else self.candidate_from_url(source)
        )

        with TemporaryDirectory(prefix="music-recommendation-mp3party-") as directory:
            output_path = Path(directory) / f"{candidate.track_id}.mp3"
            self._download_audio(
                candidate.download_url or candidate.audio_url,
                output_path,
            )
            return self.ingestion_service.ingest(
                output_path,
                title=candidate.title,
                artist=candidate.artist,
                fallback_title=output_path.stem,
                source="mp3party",
                source_id=candidate.track_id,
                source_url=candidate.url,
            )

    def download_and_import_playlist(
        self,
        candidates: list[Mp3PartyCandidate],
        *,
        on_progress: Callable[[int, int], None] | None = None,
        on_track_imported: Callable[[Mp3PartyCandidate, Track], None]
        | None = None,
    ) -> Mp3PartyPlaylistImportResult:
        """Download selected MP3Party tracks concurrently.

        A single unavailable item must not discard successful downloads from
        the same selection, so the result keeps per-track failures just like
        the YouTube and SoundCloud playlist import flows.
        """

        imported, failed, imported_candidates = parallel_playlist_import(
            candidates,
            self.download,
            on_progress=on_progress,
            on_track_imported=on_track_imported,
        )

        return Mp3PartyPlaylistImportResult(
            imported=imported,
            failed=failed,
            imported_candidates=imported_candidates,
        )

    @staticmethod
    def is_supported_url(value: str) -> bool:
        parsed_url = urlparse(value.strip())
        path_parts = tuple(
            part for part in parsed_url.path.split("/") if part
        )
        return (
            parsed_url.scheme in {"http", "https"}
            and (parsed_url.hostname or "").casefold()
            in SUPPORTED_MP3PARTY_HOSTS
            and len(path_parts) == 2
            and path_parts[0].casefold() == "music"
            and path_parts[1].isdigit()
        )

    def _read_entries(self, url: str) -> list[dict[str, object]]:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru,en;q=0.8",
                "User-Agent": MP3PARTY_USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                html = response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            if error.code == 451:
                raise RuntimeError(
                    "MP3Party denied access from this region."
                ) from error
            raise RuntimeError(
                f"MP3Party page request failed ({error.code})."
            ) from error
        except (OSError, URLError, TimeoutError) as error:
            raise RuntimeError("Could not connect to MP3Party.") from error

        parser = _Mp3PartyHTMLParser()
        parser.feed(html)
        return parser.entries

    @classmethod
    def _build_candidates(
        cls,
        entries: list[dict[str, object]],
    ) -> list[Mp3PartyCandidate]:
        candidates: list[Mp3PartyCandidate] = []
        seen_ids: set[str] = set()
        for entry in entries:
            track_id = str(entry.get("track_id") or "").strip()
            title = str(entry.get("title") or "").strip()
            artist = str(entry.get("artist") or "").strip()
            audio_url = str(entry.get("audio_url") or "").strip()
            download_url = str(entry.get("download_url") or "").strip()
            if (
                not track_id.isdigit()
                or track_id in seen_ids
                or not title
                or not artist
                or not audio_url
            ):
                continue

            page_url = f"{MP3PARTY_BASE_URL}/music/{track_id}"
            cover_url_value = str(entry.get("cover_url") or "").strip()
            candidates.append(
                Mp3PartyCandidate(
                    track_id=track_id,
                    title=title,
                    artist=artist,
                    duration_ms=(
                        int(entry["duration_ms"])
                        if entry.get("duration_ms") is not None
                        else None
                    ),
                    url=page_url,
                    audio_url=urljoin(MP3PARTY_BASE_URL, audio_url),
                    cover_url=(
                        urljoin(MP3PARTY_BASE_URL, cover_url_value)
                        if cover_url_value
                        else None
                    ),
                    download_url=(
                        urljoin(MP3PARTY_BASE_URL, download_url)
                        if download_url
                        else None
                    ),
                )
            )
            seen_ids.add(track_id)

        return candidates

    def _download_audio(self, audio_url: str, output_path: Path) -> None:
        request = Request(
            audio_url,
            headers={
                "Accept": "audio/mpeg,audio/*;q=0.9,*/*;q=0.1",
                "User-Agent": MP3PARTY_USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > MP3PARTY_MAX_DOWNLOAD_BYTES:
                    raise RuntimeError("MP3Party audio file is too large.")

                output_path.parent.mkdir(parents=True, exist_ok=True)
                total_bytes = 0
                with output_path.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        total_bytes += len(chunk)
                        if total_bytes > MP3PARTY_MAX_DOWNLOAD_BYTES:
                            raise RuntimeError("MP3Party audio file is too large.")
                        output.write(chunk)
        except RuntimeError:
            raise
        except HTTPError as error:
            raise RuntimeError(
                f"MP3Party audio download failed ({error.code})."
            ) from error
        except (OSError, URLError, TimeoutError) as error:
            raise RuntimeError("Could not download audio from MP3Party.") from error


def _parse_duration_ms(values: list[str]) -> int | None:
    for value in values:
        match = re.fullmatch(r"(\d{1,3}):(\d{2})", value)
        if match is None:
            continue
        minutes, seconds = (int(part) for part in match.groups())
        return (minutes * 60 + seconds) * 1000
    return None
