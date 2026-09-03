from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from app.domain.models import Track
from app.ingestion.audio import (
    SUPPORTED_AUDIO_EXTENSIONS,
    AudioIngestionService,
)

SUPPORTED_SOUNDCLOUD_HOSTS = {
    "soundcloud.com",
    "www.soundcloud.com",
    "m.soundcloud.com",
    "on.soundcloud.com",
}


class SoundCloudImportService:
    """Download an authorized SoundCloud track through the scdl package."""

    def __init__(
        self,
        ingestion_service: AudioIngestionService,
        *,
        timeout_seconds: int = 900,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("SoundCloud timeout must be positive.")

        self.ingestion_service = ingestion_service
        self.timeout_seconds = timeout_seconds

    def download(self, source: str) -> Track:
        """Search or load a SoundCloud URL, then import the downloaded file."""

        normalized_source = source.strip()
        if not normalized_source:
            raise ValueError("SoundCloud search or URL must not be empty.")

        with TemporaryDirectory(
            prefix="music-recommendation-soundcloud-"
        ) as directory:
            output_directory = Path(directory)
            command = self._build_command(
                normalized_source,
                output_directory,
            )
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=self.timeout_seconds,
                )
            except FileNotFoundError as error:
                raise RuntimeError(
                    "SoundCloud downloader is not installed. "
                    "Install the project dependencies and try again."
                ) from error
            except subprocess.TimeoutExpired as error:
                raise RuntimeError(
                    "SoundCloud download timed out."
                ) from error

            if completed.returncode != 0:
                detail = (
                    completed.stderr.strip()
                    or completed.stdout.strip()
                    or "scdl returned an unknown error."
                )
                raise RuntimeError(
                    f"SoundCloud download failed: {detail[-600:]}"
                )

            downloaded_file = self._find_downloaded_file(output_directory)
            if downloaded_file is None:
                raise RuntimeError(
                    "SoundCloud did not provide an audio file. "
                    "The result may be a playlist, unavailable, or have "
                    "downloads disabled."
                )

            source_url = (
                normalized_source
                if self.is_supported_url(normalized_source)
                else None
            )
            return self.ingestion_service.ingest(
                downloaded_file,
                fallback_title=downloaded_file.stem,
                source="soundcloud_import",
                source_url=source_url,
            )

    @staticmethod
    def is_supported_url(value: str) -> bool:
        parsed_url = urlparse(value.strip())
        hostname = (parsed_url.hostname or "").casefold()
        return (
            parsed_url.scheme in {"http", "https"}
            and hostname in SUPPORTED_SOUNDCLOUD_HOSTS
        )

    @classmethod
    def _build_command(
        cls,
        source: str,
        output_directory: Path,
    ) -> list[str]:
        source_option = "-l" if cls.is_supported_url(source) else "-s"
        return [
            sys.executable,
            "-m",
            "scdl.scdl",
            source_option,
            source,
            "--path",
            str(output_directory),
            "--no-playlist",
            "--hide-progress",
        ]

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
