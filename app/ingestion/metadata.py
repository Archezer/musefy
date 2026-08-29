from dataclasses import dataclass
from pathlib import Path

from mutagen import File, MutagenError


@dataclass(frozen=True)
class AudioMetadata:
    title: str | None
    artist: str | None
    duration_ms: int


def read_audio_metadata(file_path: Path) -> AudioMetadata:
    try:
        audio_file = File(file_path, easy=True)
    except MutagenError as error:
        raise ValueError(
            f"Could not read audio metadata: {file_path}"
        ) from error

    if audio_file is None or audio_file.info is None:
        raise ValueError(
            f"Unsupported or unreadable audio file: {file_path}"
        )

    title = _read_first_tag(audio_file.tags, "title")
    artist = _read_first_tag(audio_file.tags, "artist")
    duration_ms = round(audio_file.info.length * 1000)

    return AudioMetadata(
        title=title,
        artist=artist,
        duration_ms=duration_ms,
    )


def _read_first_tag(
    tags: dict[str, list[str]] | None,
    key: str,
) -> str | None:
    if not tags:
        return None

    values = tags.get(key)

    if not values:
        return None

    value = values[0].strip()

    return value or None
