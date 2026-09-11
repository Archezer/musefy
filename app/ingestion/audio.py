import hashlib
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import Track
from app.ingestion.artwork import (
    save_embedded_artwork,
    save_remote_artwork,
)
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

    def ensure_cover(
        self,
        track: Track,
        *,
        cover_url: str | None,
        replace_existing: bool = False,
    ) -> Track:
        """Persist a remote cover, optionally refreshing the stored artwork."""

        if (
            track.cover_path
            and Path(track.cover_path).is_file()
            and not replace_existing
        ) or not cover_url:
            return track

        cover_path = save_remote_artwork(cover_url, track.id)
        if cover_path is None:
            return track

        updated_track = replace(track, cover_path=cover_path)
        self.store.update_track(updated_track)
        return updated_track

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
        created_at: datetime | None = None,
        cover_url: str | None = None,
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

        existing_track = self.store.get_track(resolved_track_id)
        if existing_track is not None:
            if (
                existing_track.local_path
                and Path(existing_track.local_path).is_file()
            ):
                # The content hash is the track ID, so importing the same
                # audio from another source must reuse the existing record.
                if (
                    cover_url
                    and (
                        not existing_track.cover_path
                        or not Path(existing_track.cover_path).is_file()
                    )
                ):
                    downloaded_cover = save_remote_artwork(
                        cover_url,
                        existing_track.id,
                    )
                    if downloaded_cover is not None:
                        updated_track = replace(
                            existing_track,
                            cover_path=downloaded_cover,
                        )
                        self.store.update_track(updated_track)
                        return updated_track
                return existing_track

            return self.restore_missing_track(
                existing_track=existing_track,
                file_path=file_path,
                title=resolved_title,
                artist=resolved_artist,
                source=source,
                source_id=source_id,
                source_url=source_url,
                created_at=created_at,
                cover_url=cover_url,
            )

        internal_path = self._copy_to_library(
            file_path=file_path,
            content_id=content_id,
            artist=resolved_artist,
            title=resolved_title,
        )
        cover_path = save_embedded_artwork(
            file_path,
            resolved_track_id,
        )
        if cover_path is None and cover_url:
            cover_path = save_remote_artwork(
                cover_url,
                resolved_track_id,
            )

        track = Track(
            id=resolved_track_id,
            title=resolved_title,
            artist=resolved_artist,
            created_at=(
                created_at
                if created_at is not None
                else datetime.now(UTC)
            ),
            genres=genres,
            duration_ms=metadata.duration_ms,
            source=source,
            source_id=source_id,
            source_url=source_url,
            local_path=str(internal_path),
            cover_path=cover_path,
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
        created_at: datetime | None = None,
        cover_url: str | None = None,
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
        cover_path = save_embedded_artwork(
            file_path,
            existing_track.id,
        )
        if cover_path is None and cover_url:
            cover_path = save_remote_artwork(
                cover_url,
                existing_track.id,
            )

        restored_track = replace(
            existing_track,
            title=title,
            artist=artist,
            created_at=(
                created_at
                if created_at is not None
                else existing_track.created_at
            ),
            duration_ms=metadata.duration_ms,
            source=source,
            source_id=source_id,
            source_url=source_url,
            local_path=str(internal_path),
            cover_path=cover_path or existing_track.cover_path,
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
