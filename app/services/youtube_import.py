from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from app.domain.models import Track
from app.ingestion.audio import AudioIngestionService
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
    ) -> None:
        self.ingestion_service = ingestion_service
        self.provider = provider or YouTubeSearchProvider()
        self.spotify_provider = (
            spotify_provider or SpotifyMetadataProvider()
        )

    def search(
        self,
        query: str,
    ) -> list[YouTubeCandidate]:
        return self.provider.search(
            query,
            max_results=5,
        )

    def search_from_spotify(
        self,
        url: str,
        *,
        use_oauth: bool = False,
    ) -> SpotifySearchResult | SpotifyPlaylistSearchResult:
        resource_type = self.spotify_provider.get_resource_type(url)
        if resource_type == "playlist":
            return self.search_playlist_from_spotify(
                url,
                use_oauth=use_oauth,
            )
        if resource_type == "album":
            return self.search_album_from_spotify(
                url,
                use_oauth=use_oauth,
            )

        spotify_track = self.spotify_provider.get_track(url)
        candidates = self.provider.search(
            spotify_track.search_query,
            max_results=5,
        )

        return SpotifySearchResult(
            query=spotify_track.search_query,
            candidates=tuple(candidates),
        )

    def load_url(
        self,
        url: str,
    ) -> (
        Track
        | list[YouTubeCandidate]
        | SpotifySearchResult
        | SpotifyPlaylistSearchResult
    ):
        normalized_url = url.strip()
        source = self._get_url_source(normalized_url)

        if source == "youtube":
            resource_type = self.provider.get_resource_type(
                normalized_url
            )
            if resource_type == "track":
                return self.download_and_import_url(normalized_url)

            return self.get_playlist(normalized_url)

        return self.search_from_spotify(
            normalized_url,
            use_oauth=(
                self.spotify_provider.has_saved_credentials()
            ),
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
        )

    def search_playlist_export(
        self,
        path: Path,
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
        )

    def _search_playlist_tracks(
        self,
        playlist_name: str,
        tracks: tuple[SpotifyTrack, ...],
        *,
        cover_url: str | None = None,
        positions: tuple[int, ...] | None = None,
    ) -> SpotifyPlaylistSearchResult:
        if positions is None:
            positions = tuple(range(len(tracks)))
        elif len(positions) != len(tracks):
            raise ValueError(
                "Playlist track positions must match the track count."
            )

        candidates = []
        failed = []
        failed_positions = []

        for position, spotify_track in zip(positions, tracks):
            try:
                matches = self.provider.search(
                    spotify_track.search_query,
                    max_results=5,
                )
            except (OSError, RuntimeError, ValueError) as error:
                failed.append((spotify_track, str(error)))
                failed_positions.append(position)
                continue

            if not matches:
                failed.append(
                    (spotify_track, "No YouTube match found.")
                )
                failed_positions.append(position)
                continue

            candidates.append(
                replace(
                    matches[0],
                    requested_title=spotify_track.title,
                    requested_artist=spotify_track.artist,
                    playlist_position=position,
                )
            )

        if not candidates and failed:
            raise RuntimeError(
                "No Spotify playlist tracks could be matched on YouTube."
            )

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
        )

    def search_album_from_spotify(
        self,
        url: str,
        *,
        use_oauth: bool = False,
    ) -> SpotifyPlaylistSearchResult:
        if use_oauth:
            album = self.spotify_provider.get_authenticated_album(url)
        else:
            album = self.spotify_provider.get_album(url)

        return self._search_spotify_collection(album)

    def _search_spotify_collection(
        self,
        collection,
    ) -> SpotifyPlaylistSearchResult:
        candidates = []
        failed = []
        failed_positions = []

        for position, spotify_track in enumerate(collection.tracks):
            try:
                matches = self.provider.search(
                    spotify_track.search_query,
                    max_results=5,
                )
            except (OSError, RuntimeError, ValueError) as error:
                failed.append((spotify_track, str(error)))
                failed_positions.append(position)
                continue

            if not matches:
                failed.append(
                    (spotify_track, "No YouTube match found.")
                )
                failed_positions.append(position)
                continue

            candidates.append(
                replace(
                    matches[0],
                    requested_title=spotify_track.title,
                    requested_artist=spotify_track.artist,
                    playlist_position=position,
                )
            )

        if not candidates and failed:
            raise RuntimeError(
                "No Spotify collection tracks could be matched on YouTube."
            )

        return SpotifyPlaylistSearchResult(
            playlist_name=collection.name,
            candidates=tuple(candidates),
            failed=tuple(failed),
            failed_positions=tuple(failed_positions),
        )

    def download_and_import(
        self,
        candidate: YouTubeCandidate,
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
                    source="youtube",
                    source_id=candidate.video_id,
                    source_url=candidate.url,
                )

            return self.ingestion_service.ingest(
                downloaded_path,
                title=title,
                artist=artist,
                track_id=f"youtube-{candidate.video_id}",
                source="youtube",
                source_id=candidate.video_id,
                source_url=candidate.url,
            )

    def _find_existing_youtube_track(
        self,
        video_id: str,
    ) -> Track | None:
        existing_track = self.ingestion_service.store.get_track_by_source(
            "youtube",
            video_id,
        )
        if existing_track is not None:
            return existing_track

        # Migrate old YouTube records that only stored source_url.
        for track in self.ingestion_service.store.list_tracks():
            if track.source != "youtube" or not track.source_url:
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
        on_progress: Callable[[int, int], None] | None = None,
        on_track_imported: Callable[[YouTubeCandidate, Track], None]
        | None = None,
    ) -> YouTubePlaylistImportResult:
        imported = []
        failed = []
        imported_candidates = []
        total = len(candidates)

        for completed, candidate in enumerate(candidates, start=1):
            try:
                track = self.download_and_import(candidate)
                imported.append(track)
                imported_candidates.append((candidate, track))
                if on_track_imported is not None:
                    on_track_imported(candidate, track)
            except (OSError, RuntimeError, ValueError) as error:
                failed.append(
                    (candidate, str(error))
                )
            finally:
                if on_progress is not None:
                    on_progress(completed, total)

        return YouTubePlaylistImportResult(
            imported=tuple(imported),
            failed=tuple(failed),
            imported_candidates=tuple(imported_candidates),
        )
