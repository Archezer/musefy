import hashlib
from pathlib import Path

from app.domain.models import Track
from app.ingestion.metadata import read_audio_metadata
from app.storage.protocols import MusicStore


SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
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

        resolved_track_id = (
            track_id
            or self._build_track_id(file_path)
        )

        track = Track(
            id=resolved_track_id,
            title=resolved_title,
            artist=resolved_artist,
            genres=genres,
            duration_ms=metadata.duration_ms,
            source=source,
            source_url=source_url,
            local_path=str(file_path.resolve()),
        )

        self.store.add_track(track)

        return track

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