from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from app.domain.models import Track
from app.ingestion.audio import AudioIngestionService
from app.sources.spotify import SpotifyMetadataProvider
from app.sources.youtube import (
    YouTubeCandidate,
    YouTubeSearchProvider,
)


@dataclass(frozen=True)
class YouTubePlaylistImportResult:
    imported: tuple[Track, ...]
    failed: tuple[tuple[YouTubeCandidate, str], ...]


@dataclass(frozen=True)
class SpotifySearchResult:
    query: str
    candidates: tuple[YouTubeCandidate, ...]


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
    ) -> SpotifySearchResult:
        spotify_track = self.spotify_provider.get_track(url)
        candidates = self.provider.search(
            spotify_track.search_query,
            max_results=5,
        )

        return SpotifySearchResult(
            query=spotify_track.search_query,
            candidates=tuple(candidates),
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
                title=candidate.title,
                artist=candidate.channel_title,
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
        total = len(candidates)

        for completed, candidate in enumerate(candidates, start=1):
            try:
                imported.append(
                    self.download_and_import(candidate)
                )
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
        )
