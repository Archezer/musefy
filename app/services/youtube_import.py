from pathlib import Path
from tempfile import TemporaryDirectory

from app.domain.models import Track
from app.ingestion.audio import AudioIngestionService
from app.sources.youtube import (
    YouTubeCandidate,
    YouTubeSearchProvider,
)


class YouTubeImportService:
    def __init__(
        self,
        ingestion_service: AudioIngestionService,
        provider: YouTubeSearchProvider | None = None,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.provider = provider or YouTubeSearchProvider()

    def search(
        self,
        query: str,
    ) -> list[YouTubeCandidate]:
        return self.provider.search(
            query,
            max_results=5,
        )

    def download_and_import(
        self,
        candidate: YouTubeCandidate,
        *,
        allowed_channel_id: str,
    ) -> Track:
        normalized_channel_id = (
            allowed_channel_id.strip()
        )

        if not normalized_channel_id:
            raise ValueError(
                "Allowed channel ID must not be empty"
            )

        with TemporaryDirectory(
            prefix="music-recommendation-youtube-"
        ) as temporary_directory:
            downloaded_path = self.provider.download(
                candidate,
                Path(temporary_directory),
                allowed_channel_id=normalized_channel_id,
            )

            return self.ingestion_service.ingest(
                downloaded_path,
                title=candidate.title,
                artist=candidate.channel_title,
                source="youtube",
                source_url=candidate.url,
            )
