from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from app.domain.models import Track
from app.ingestion.audio import AudioIngestionService
from app.services.parallel_playlist import (
    DEFAULT_PLAYLIST_IMPORT_WORKERS,
    parallel_playlist_import,
)
from app.services.playlist_exports import read_playlist_export
from app.sources.spotify import (
    SUPPORTED_SPOTIFY_HOSTS,
    SpotifyMetadataProvider,
    SpotifyTrack,
)
from app.sources.youtube import (
    SUPPORTED_YOUTUBE_HOSTS,
    YouTubeCandidate,
    YouTubeSearchProvider,
    extract_youtube_video_id,
)

DEFAULT_SEARCH_WORKERS = 6


class OperationCancelled(RuntimeError):
    """Raised when a background import/search is cancelled by the user."""


@dataclass(frozen=True)
class YouTubePlaylistImportResult:
    imported: tuple[Track, ...]
    failed: tuple[tuple[YouTubeCandidate, str], ...]
    imported_candidates: tuple[tuple[YouTubeCandidate, Track], ...] = ()


@dataclass(frozen=True)
class SpotifySearchResult:
    query: str
    candidates: tuple[YouTubeCandidate, ...]


@dataclass(frozen=True)
class SpotifyPlaylistSearchResult:
    playlist_name: str
    candidates: tuple[YouTubeCandidate, ...]
    failed: tuple[tuple[SpotifyTrack, str], ...]
    cover_url: str | None = None
    # Positions line up with ``failed`` and let the UI put a retried match
    # back into the original playlist order.
    failed_positions: tuple[int, ...] = ()


class YouTubeImportService:
    def __init__(
        self,
        ingestion_service: AudioIngestionService,
        provider: YouTubeSearchProvider | None = None,
        spotify_provider: SpotifyMetadataProvider | None = None,
        *,
        search_workers: int = DEFAULT_SEARCH_WORKERS,
    ) -> None:
        if not 1 <= search_workers <= 16:
            raise ValueError("search_workers must be between 1 and 16")

        self.ingestion_service = ingestion_service
        self.provider = provider or YouTubeSearchProvider()
        self.spotify_provider = (
            spotify_provider or SpotifyMetadataProvider()
        )
        self.search_workers = search_workers

    def search(
        self,
        query: str,
        *,
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[YouTubeCandidate]:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        candidates = self.provider.search(
            query,
            max_results=5,
        )
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        return candidates

    def search_from_spotify(
        self,
        url: str,
        *,
        use_oauth: bool = False,
        on_progress: Callable[[int, int, int, int, str], None]
        | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifySearchResult | SpotifyPlaylistSearchResult:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        resource_type = self.spotify_provider.get_resource_type(url)
        if resource_type == "playlist":
            return self.search_playlist_from_spotify(
                url,
                use_oauth=use_oauth,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )
        if resource_type == "album":
            return self.search_album_from_spotify(
                url,
                use_oauth=use_oauth,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )

        spotify_track = self.spotify_provider.get_track(url)
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        if on_progress is not None:
            on_progress(0, 1, 0, 0, spotify_track.title)
        candidates = self.provider.search(
            spotify_track.search_query,
            max_results=5,
        )
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        if on_progress is not None:
            on_progress(
                1,
                1,
                len(candidates),
                0 if candidates else 1,
                spotify_track.title,
            )

        return SpotifySearchResult(
            query=spotify_track.search_query,
            candidates=tuple(candidates),
        )

    def load_url(
        self,
        url: str,
        *,
        on_progress: Callable[[int, int, int, int, str], None]
        | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> (
        Track
        | list[YouTubeCandidate]
        | SpotifySearchResult
        | SpotifyPlaylistSearchResult
    ):
        normalized_url = url.strip()
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        source = self._get_url_source(normalized_url)

        if source == "youtube":
            resource_type = self.provider.get_resource_type(
                normalized_url
            )
            if resource_type == "track":
                return self.download_and_import_url(normalized_url)

            result = self.get_playlist(normalized_url)
            if should_cancel is not None and should_cancel():
                raise OperationCancelled()
            return result

        return self.search_from_spotify(
            normalized_url,
            use_oauth=(
                self.spotify_provider.has_saved_credentials()
            ),
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

    def is_supported_url(self, value: str) -> bool:
        """Return whether an input should be treated as a source URL."""

        try:
            self._get_url_source(value.strip())
        except ValueError:
            return False
        return True

    def authenticate_url(self, url: str) -> str:
        source = self._get_url_source(url.strip())

        if source == "youtube":
            return (
                "YouTube uses browser cookies automatically; "
                "no separate sign-in is required."
            )

        self.spotify_provider.authenticate()
        return "Spotify authorization completed."

    def reauthorize_spotify(self) -> str:
        """Request Spotify OAuth again with the currently configured scopes."""

        self.spotify_provider.reauthorize()
        return "Spotify OAuth completed."

    @staticmethod
    def _get_url_source(url: str) -> str:
        parsed_url = urlparse(url)
        hostname = (parsed_url.hostname or "").casefold()

        if hostname in SUPPORTED_YOUTUBE_HOSTS:
            return "youtube"

        if hostname in SUPPORTED_SPOTIFY_HOSTS:
            return "spotify"

        raise ValueError(
            "URL must be a supported YouTube or Spotify link."
        )

    def search_playlist_from_spotify(
        self,
        url: str,
        *,
        use_oauth: bool = False,
        on_progress: Callable[[int, int, int, int, str], None]
        | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifyPlaylistSearchResult:
        if use_oauth:
            playlist = self.spotify_provider.get_authenticated_playlist(
                url
            )
        else:
            playlist = self.spotify_provider.get_playlist(url)
        return self._search_playlist_tracks(
            playlist.name,
            playlist.tracks,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

    def search_playlist_export(
        self,
        path: Path,
        *,
        on_progress: Callable[[int, int, int, int, str], None]
        | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifyPlaylistSearchResult:
        exported_playlist = read_playlist_export(path)
        tracks = tuple(
            SpotifyTrack(
                title=track.title,
                artist=track.artist,
            )
            for track in exported_playlist.tracks
        )

        return self._search_playlist_tracks(
            exported_playlist.title,
            tracks,
            cover_url=exported_playlist.cover_url,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

    def _search_playlist_tracks(
        self,
        playlist_name: str,
        tracks: tuple[SpotifyTrack, ...],
        *,
        cover_url: str | None = None,
        positions: tuple[int, ...] | None = None,
        on_progress: Callable[[int, int, int, int, str], None]
        | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifyPlaylistSearchResult:
        if positions is None:
            positions = tuple(range(len(tracks)))
        elif len(positions) != len(tracks):
            raise ValueError(
                "Playlist track positions must match the track count."
            )

        total = len(tracks)
        completed = 0
        candidates_by_index: dict[int, YouTubeCandidate] = {}
        failures_by_index: dict[int, tuple[SpotifyTrack, str]] = {}

        def report(track: SpotifyTrack) -> None:
            if on_progress is not None:
                on_progress(
                    completed,
                    total,
                    len(candidates_by_index),
                    len(failures_by_index),
                    track.title,
                )

        def search_one(
            index: int,
            position: int,
            spotify_track: SpotifyTrack,
        ) -> tuple[
            int,
            SpotifyTrack,
            YouTubeCandidate | None,
            str | None,
        ]:
            if should_cancel is not None and should_cancel():
                raise OperationCancelled()
            try:
                matches = self.provider.search(
                    spotify_track.search_query,
                    # Playlist rows use only the best match.  Avoid fetching
                    # four extra candidates for every track in a large list.
                    max_results=1,
                )
            except (OSError, RuntimeError, ValueError) as error:
                return index, spotify_track, None, str(error)

            if not matches:
                return (
                    index,
                    spotify_track,
                    None,
                    "No YouTube match found.",
                )

            return (
                index,
                spotify_track,
                replace(
                    matches[0],
                    requested_title=spotify_track.title,
                    requested_artist=spotify_track.artist,
                    playlist_position=position,
                ),
                None,
            )

        entries = tuple(zip(positions, tracks))
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()
        if on_progress is not None and entries:
            on_progress(
                0,
                total,
                0,
                0,
                f"Starting parallel search ({min(self.search_workers, total)} workers)",
            )

        with ThreadPoolExecutor(
            max_workers=min(self.search_workers, max(total, 1)),
            thread_name_prefix="musefy-search",
        ) as executor:
            futures = {
                executor.submit(search_one, index, position, track): index
                for index, (position, track) in enumerate(entries)
            }

            for future in as_completed(futures):
                if should_cancel is not None and should_cancel():
                    for pending in futures:
                        pending.cancel()
                    raise OperationCancelled()

                index, track, candidate, failure = future.result()
                completed += 1
                if candidate is not None:
                    candidates_by_index[index] = candidate
                else:
                    failures_by_index[index] = (
                        track,
                        failure or "Search failed.",
                    )
                report(track)

        candidates = [
            candidates_by_index[index]
            for index in range(total)
            if index in candidates_by_index
        ]
        failed = [
            failures_by_index[index]
            for index in range(total)
            if index in failures_by_index
        ]
        failed_positions = [
            positions[index]
            for index in range(total)
            if index in failures_by_index
        ]

        return SpotifyPlaylistSearchResult(
            playlist_name=playlist_name,
            candidates=tuple(candidates),
            failed=tuple(failed),
            cover_url=cover_url,
            failed_positions=tuple(failed_positions),
        )

    def search_playlist_tracks(
        self,
        tracks: list[tuple[int, SpotifyTrack]],
        *,
        playlist_name: str,
        cover_url: str | None = None,
        on_progress: Callable[[int, int, int, int, str], None]
        | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifyPlaylistSearchResult:
        """Search a selected set of playlist tracks again.

        ``position`` is supplied by the caller because retry searches only
        contain the tracks that failed previously.  Keeping it here prevents
        those tracks from being appended in a new, compact order.
        """

        return self._search_playlist_tracks(
            playlist_name,
            tuple(track for _, track in tracks),
            cover_url=cover_url,
            positions=tuple(position for position, _ in tracks),
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

    def search_album_from_spotify(
        self,
        url: str,
        *,
        use_oauth: bool = False,
        on_progress: Callable[[int, int, int, int, str], None]
        | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifyPlaylistSearchResult:
        if use_oauth:
            album = self.spotify_provider.get_authenticated_album(url)
        else:
            album = self.spotify_provider.get_album(url)

        return self._search_spotify_collection(
            album,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

    def _search_spotify_collection(
        self,
        collection,
        *,
        on_progress: Callable[[int, int, int, int, str], None]
        | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifyPlaylistSearchResult:
        result = self._search_playlist_tracks(
            collection.name,
            tuple(collection.tracks),
            on_progress=on_progress,
            should_cancel=should_cancel,
        )

        if not result.candidates and result.failed:
            raise RuntimeError(
                "No Spotify collection tracks could be matched on YouTube."
            )

        return result

    def download_and_import(
        self,
        candidate: YouTubeCandidate,
        *,
        source: str = "youtube",
    ) -> Track:
        existing_track = self._find_existing_youtube_track(
            candidate.video_id
        )

        with TemporaryDirectory(
            prefix="music-recommendation-youtube-"
        ) as temporary_directory:
            temporary_path = Path(temporary_directory)

            if (
                existing_track is not None
                and existing_track.local_path
                and Path(existing_track.local_path).is_file()
            ):
                return existing_track

            downloaded_path = self.provider.download(
                candidate,
                temporary_path,
            )

            title = candidate.requested_title or candidate.title
            artist = (
                candidate.requested_artist
                or candidate.channel_title
            )

            if existing_track is not None:
                return self.ingestion_service.restore_missing_track(
                    existing_track,
                    downloaded_path,
                    title=title,
                    artist=artist,
                    # A restore should retain the original provenance.  A
                    # missing file is not a new import, so re-downloading a
                    # Spotify favourite must not rewrite it as a YouTube
                    # import (or vice versa).
                    source=existing_track.source,
                    source_id=candidate.video_id,
                    source_url=candidate.url,
                )

            return self.ingestion_service.ingest(
                downloaded_path,
                title=title,
                artist=artist,
                track_id=f"youtube-{candidate.video_id}",
                source=source,
                source_id=candidate.video_id,
                source_url=candidate.url,
            )

    def _find_existing_youtube_track(
        self,
        video_id: str,
    ) -> Track | None:
        for source in ("youtube", "spotify_favorite"):
            existing_track = self.ingestion_service.store.get_track_by_source(
                source,
                video_id,
            )
            if existing_track is not None:
                return existing_track

        # Migrate older YouTube/Spotify records that only stored source_url.
        for track in self.ingestion_service.store.list_tracks():
            if (
                track.source not in {"youtube", "spotify_favorite"}
                or not track.source_url
            ):
                continue

            if extract_youtube_video_id(track.source_url) != video_id:
                continue

            migrated_track = replace(
                track,
                source_id=video_id,
            )
            self.ingestion_service.store.update_track(
                migrated_track
            )
            return migrated_track

        return None

    def download_and_import_url(
        self,
        url: str,
    ) -> Track:
        candidate = self.provider.candidate_from_url(url)
        return self.download_and_import(candidate)

    def get_playlist(
        self,
        url: str,
    ) -> list[YouTubeCandidate]:
        return self.provider.playlist(url)

    def download_and_import_playlist(
        self,
        candidates: list[YouTubeCandidate],
        *,
        source: str = "youtube",
        on_progress: Callable[[int, int], None] | None = None,
        on_track_imported: Callable[[YouTubeCandidate, Track], None]
        | None = None,
    ) -> YouTubePlaylistImportResult:
        imported, failed, imported_candidates = parallel_playlist_import(
            candidates,
            lambda candidate: self.download_and_import(
                candidate,
                source=source,
            ),
            max_workers=min(
                self.search_workers,
                DEFAULT_PLAYLIST_IMPORT_WORKERS,
            ),
            on_progress=on_progress,
            on_track_imported=on_track_imported,
        )

        return YouTubePlaylistImportResult(
            imported=imported,
            failed=failed,
            imported_candidates=imported_candidates,
        )
