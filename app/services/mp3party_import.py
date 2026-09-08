from __future__ import annotations

import re
import unicodedata
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
        self.artist_urls: list[str] = []
        self.page_urls: list[str] = []
        self._stack: list[tuple[str, set[str]]] = []
        self._current: dict[str, object] | None = None
        self._info_values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        self._stack.append((tag, classes))

        href = attributes.get("href")
        if tag == "a" and href:
            link = urljoin(MP3PARTY_BASE_URL, href)
            parsed_link = urlparse(link)
            if parsed_link.path.rstrip("/").startswith("/artist/"):
                if link not in self.artist_urls:
                    self.artist_urls.append(link)
                if "page=" in parsed_link.query and link not in self.page_urls:
                    self.page_urls.append(link)

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

        candidates: list[Mp3PartyCandidate] = []
        seen_ids: set[str] = set()
        artist_title = _split_artist_title(normalized_query)
        for search_query in _search_query_variants(normalized_query):
            search_url = (
                f"{MP3PARTY_BASE_URL}/search?"
                f"{urlencode({'q': search_query})}"
            )
            entries, _, _ = self._read_page(search_url)
            for candidate in self._build_candidates(entries):
                if candidate.track_id in seen_ids:
                    continue
                seen_ids.add(candidate.track_id)
                candidates.append(candidate)

            if artist_title is not None:
                direct_matches = [
                    candidate
                    for candidate in candidates
                    if _candidate_matches_artist_title(
                        candidate,
                        artist_name=artist_title[0],
                        title=artist_title[1],
                    )
                ]
                if direct_matches:
                    return direct_matches[:max_results]
            elif len(candidates) >= max_results:
                return candidates[:max_results]

        if artist_title is not None:
            artist_name, title = artist_title
            direct_matches = [
                candidate
                for candidate in candidates
                if _candidate_matches_artist_title(
                    candidate,
                    artist_name=artist_name,
                    title=title,
                )
            ]
            if direct_matches:
                return direct_matches[:max_results]

            catalog_matches = self._search_artist_catalog(
                artist_name,
                title,
                max_results=max_results,
            )
            if catalog_matches:
                return catalog_matches

        return candidates[:max_results]

    def candidate_from_url(self, url: str) -> Mp3PartyCandidate:
        normalized_url = url.strip()
        if not self.is_supported_url(normalized_url):
            raise ValueError("MP3Party URL must point to a music track.")

        entries, _, _ = self._read_page(normalized_url)
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
            download_urls = tuple(
                dict.fromkeys(
                    url
                    for url in (candidate.download_url, candidate.audio_url)
                    if url
                )
            )
            last_error: Exception | None = None

            for attempt, audio_url in enumerate(download_urls):
                output_path = Path(directory) / (
                    f"{candidate.track_id}-{attempt}.mp3"
                )
                try:
                    self._download_audio(
                        audio_url,
                        output_path,
                        referer=candidate.url,
                    )
                    return self.ingestion_service.ingest(
                        output_path,
                        title=candidate.title,
                        artist=candidate.artist,
                        fallback_title=output_path.stem,
                        source="mp3party",
                        source_id=candidate.track_id,
                        source_url=candidate.url,
                        cover_url=candidate.cover_url,
                    )
                except (OSError, RuntimeError, ValueError) as error:
                    last_error = error

            if last_error is not None:
                raise last_error

            raise RuntimeError("MP3Party did not expose an audio URL.")

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
        entries, _, _ = self._read_page(url)
        return entries

    def _read_page(
        self,
        url: str,
    ) -> tuple[list[dict[str, object]], tuple[str, ...], tuple[str, ...]]:
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
        return (
            parser.entries,
            tuple(parser.artist_urls),
            tuple(parser.page_urls),
        )

    def _search_artist_catalog(
        self,
        artist_name: str,
        title: str,
        *,
        max_results: int,
    ) -> list[Mp3PartyCandidate]:
        """Find an explicit artist-title query in the artist catalog.

        MP3Party's public search endpoint frequently omits tracks that are
        present on the artist page.  Use the artist search only to discover
        the canonical artist URL, then follow the pagination links exposed by
        that page and apply the same normalized title matching locally.
        """

        search_url = (
            f"{MP3PARTY_BASE_URL}/search?"
            f"{urlencode({'q': artist_name})}"
        )
        _, artist_urls, _ = self._read_page(search_url)
        pending_urls = list(artist_urls)
        visited_urls: set[str] = set()
        matches: list[Mp3PartyCandidate] = []
        seen_ids: set[str] = set()

        while pending_urls and len(visited_urls) < 32:
            page_url = pending_urls.pop(0)
            if page_url in visited_urls:
                continue
            visited_urls.add(page_url)

            entries, _, page_urls = self._read_page(page_url)
            for candidate in self._build_candidates(entries):
                if candidate.track_id in seen_ids:
                    continue
                if not _candidate_matches_artist_title(
                    candidate,
                    artist_name=artist_name,
                    title=title,
                ):
                    continue
                seen_ids.add(candidate.track_id)
                matches.append(candidate)
                if len(matches) >= max_results:
                    return matches

            for next_url in page_urls:
                if next_url not in visited_urls and next_url not in pending_urls:
                    pending_urls.append(next_url)

        return matches

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

            artist, title = _normalize_mp3party_artists(artist, title)
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

    def _download_audio(
        self,
        audio_url: str,
        output_path: Path,
        *,
        referer: str | None = None,
    ) -> None:
        headers = {
            "Accept": "audio/mpeg,audio/*;q=0.9,*/*;q=0.1",
            "User-Agent": MP3PARTY_USER_AGENT,
        }
        if referer:
            headers["Referer"] = referer

        request = Request(
            audio_url,
            headers=headers,
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                content_type = str(
                    response.headers.get("Content-Type") or ""
                ).casefold()
                if content_type.startswith(("text/", "application/json")):
                    raise RuntimeError(
                        "MP3Party returned a web page instead of audio."
                    )

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
                if total_bytes == 0:
                    raise RuntimeError("MP3Party returned an empty audio file.")
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


def _search_query_variants(query: str) -> tuple[str, ...]:
    """Return conservative fallbacks for MP3Party's inconsistent search."""

    variants: list[str] = []

    def add(value: str) -> None:
        normalized = " ".join(value.split())
        if normalized and normalized not in variants:
            variants.append(normalized)

    add(query)

    without_diacritics = "".join(
        character
        for character in unicodedata.normalize("NFKD", query)
        if not unicodedata.combining(character)
    )
    add(without_diacritics)

    # A hyphen between artist and title can be treated as punctuation or as a
    # search operator by the site. Keep the user's preferred query first, then
    # retry without that separator if the first request returns nothing.
    add(re.sub(r"\s*[-–—]\s*", " ", without_diacritics))

    return tuple(variants)


def _split_artist_title(query: str) -> tuple[str, str] | None:
    """Split the common ``artist - title`` form, with a compact fallback.

    MP3Party also accepts the same input without the separator.  In that
    form the first word is the most useful artist hint for the catalog
    fallback; the regular site search still gets the original query first.
    """

    explicit_match = re.match(r"^\s*(.+?)\s*[-–—]\s*(.+?)\s*$", query)
    if explicit_match is not None:
        return (
            explicit_match.group(1).strip(),
            explicit_match.group(2).strip(),
        )

    artist_name, separator, title = query.partition(" ")
    if not separator or not artist_name.strip() or not title.strip():
        return None
    return artist_name.strip(), title.strip()


def _candidate_matches_artist_title(
    candidate: Mp3PartyCandidate,
    *,
    artist_name: str,
    title: str,
) -> bool:
    normalized_artist = _normalize_match_text(candidate.artist)
    expected_artist = _normalize_match_text(artist_name)
    if not (
        normalized_artist == expected_artist
        or normalized_artist.startswith(f"{expected_artist} ")
    ):
        return False

    normalized_title = _normalize_match_text(candidate.title)
    expected_title = _normalize_match_text(title)
    if normalized_title == expected_title:
        return True

    # MP3Party commonly appends featured artists in parentheses to the title.
    title_without_parenthetical = _normalize_match_text(
        re.sub(r"\s*\([^)]*\)", "", candidate.title)
    )
    return (
        title_without_parenthetical == expected_title
        or normalized_title.startswith(f"{expected_title} ")
    )


def _normalize_match_text(value: str) -> str:
    without_diacritics = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return " ".join(
        re.findall(r"[^\W_]+", without_diacritics, flags=re.UNICODE)
    )


def _normalize_mp3party_artists(
    artist: str,
    title: str,
) -> tuple[str, str]:
    """Keep the first performer as artist and move the rest into ``Feat.``."""

    parts = [part.strip() for part in re.split(
        r"\s*(?:,|;|&|\+|\bx\b|\bfeat(?:uring)?\.?|\bft\.?)\s*",
        artist,
        flags=re.IGNORECASE,
    ) if part.strip()]
    if len(parts) <= 1:
        return artist, title

    primary_artist = parts[0]
    featured_artists = ", ".join(parts[1:])
    if re.search(r"\(\s*(?:feat(?:uring)?|ft)\.?\b", title, re.IGNORECASE):
        return primary_artist, title

    return primary_artist, f"{title} (Feat. {featured_artists})"
