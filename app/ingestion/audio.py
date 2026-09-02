import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

from app.domain.models import Track
from app.ingestion.filenames import (
    add_collision_suffix,
    build_library_filename,
)
from app.ingestion.metadata import read_audio_metadata
from app.storage.paths import (
    LIBRARY_DIR,
    ensure_storage_directories,
)
from app.storage.protocols import MusicStore

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".mp4",
    ".ogg",
    ".opus",
}


class AudioIngestionService:
    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def ingest(
        self,
        file_path: Path,
        *,
        title: str | None = None,
        artist: str | None = None,
        fallback_title: str | None = None,
        track_id: str | None = None,
        genres: tuple[str, ...] = (),
        source: str = "local_upload",
        source_id: str | None = None,
        source_url: str | None = None,
    ) -> Track:
        self._validate_file(file_path)

        metadata = read_audio_metadata(file_path)

        resolved_title = (
            title
            or metadata.title
            or fallback_title
            or file_path.stem
        )

        resolved_artist = (
            artist
            or metadata.artist
            or "Unknown Artist"
        )

        content_id = self._build_track_id(file_path)

        resolved_track_id = (
            track_id
            or content_id
        )

        internal_path = self._copy_to_library(
            file_path=file_path,
            content_id=content_id,
            artist=resolved_artist,
            title=resolved_title,
        )

        track = Track(
            id=resolved_track_id,
            title=resolved_title,
            artist=resolved_artist,
            genres=genres,
            duration_ms=metadata.duration_ms,
            source=source,
            source_id=source_id,
            source_url=source_url,
            local_path=str(internal_path),
        )

        self.store.add_track(track)

        return track

    def restore_missing_track(
        self,
        existing_track: Track,
        file_path: Path,
        *,
        title: str,
        artist: str,
        source: str,
        source_id: str | None,
        source_url: str | None,
    ) -> Track:
        self._validate_file(file_path)

        metadata = read_audio_metadata(file_path)
        content_id = self._build_track_id(file_path)
        internal_path = self._copy_to_library(
            file_path=file_path,
            content_id=content_id,
            artist=artist,
            title=title,
        )

        restored_track = replace(
            existing_track,
            title=title,
            artist=artist,
            duration_ms=metadata.duration_ms,
            source=source,
            source_id=source_id,
            source_url=source_url,
            local_path=str(internal_path),
        )
        self.store.update_track(restored_track)

        return restored_track

    @staticmethod
    def _copy_to_library(
        file_path: Path,
        content_id: str,
        artist: str,
        title: str,
    ) -> Path:
        ensure_storage_directories()

        source_path = file_path.resolve()

        file_name = build_library_filename(
            artist=artist,
            title=title,
            suffix=file_path.suffix,
            track_id=content_id,
        )

        destination_path = (
            LIBRARY_DIR / file_name
        ).resolve()

        if destination_path.exists():
            destination_path = (
                add_collision_suffix(
                    destination_path,
                    content_id,
                )
            )

        if (
            source_path != destination_path
            and not destination_path.exists()
        ):
            shutil.copy2(
                source_path,
                destination_path,
            )

        return destination_path

    @staticmethod
    def _validate_file(file_path: Path) -> None:
        if not file_path.exists():
            raise FileNotFoundError(
                f"Audio file does not exist: {file_path}"
            )

        if not file_path.is_file():
            raise ValueError(
                f"Audio path is not a file: {file_path}"
            )

        if file_path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            raise ValueError(
                f"Unsupported audio format: {file_path.suffix}"
            )

    @staticmethod
    def _build_track_id(file_path: Path) -> str:
        hasher = hashlib.sha256()

        with file_path.open("rb") as audio_stream:
            while chunk := audio_stream.read(1024 * 1024):
                hasher.update(chunk)

        return f"local-{hasher.hexdigest()[:16]}"
