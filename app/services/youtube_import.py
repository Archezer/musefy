from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from tempfile import TemporaryDirectory

from app.domain.models import Track
from app.ingestion.audio import AudioIngestionService
from app.sources.spotify import (
    SpotifyMetadataProvider,
    SpotifyTrack,
)
from app.sources.youtube import (
    YouTubeCandidate,
    YouTubeSearchProvider,
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
    ) -> SpotifySearchResult | SpotifyPlaylistSearchResult:
        if self.spotify_provider.get_resource_type(url) == "playlist":
            return self.search_playlist_from_spotify(url)

        spotify_track = self.spotify_provider.get_track(url)
        candidates = self.provider.search(
            spotify_track.search_query,
            max_results=5,
        )

        return SpotifySearchResult(
            query=spotify_track.search_query,
            candidates=tuple(candidates),
        )

    def search_playlist_from_spotify(
        self,
        url: str,
    ) -> SpotifyPlaylistSearchResult:
        playlist = self.spotify_provider.get_playlist(url)
        candidates = []
        failed = []

        for position, spotify_track in enumerate(playlist.tracks):
            try:
                matches = self.provider.search(
                    spotify_track.search_query,
                    max_results=5,
                )
            except (OSError, RuntimeError, ValueError) as error:
                failed.append((spotify_track, str(error)))
                continue

            if not matches:
                failed.append(
                    (spotify_track, "No YouTube match found.")
                )
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
            playlist_name=playlist.name,
            candidates=tuple(candidates),
            failed=tuple(failed),
        )

    def download_and_import(
        self,
        candidate: YouTubeCandidate,
    ) -> Track:
        with TemporaryDirectory(
            prefix="music-recommendation-youtube-"
        ) as temporary_directory:
            downloaded_path = self.provider.download(
                candidate,
                Path(temporary_directory),
            )

            return self.ingestion_service.ingest(
                downloaded_path,
                title=candidate.requested_title or candidate.title,
                artist=(
                    candidate.requested_artist
                    or candidate.channel_title
                ),
                source="youtube",
                source_url=candidate.url,
            )

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
