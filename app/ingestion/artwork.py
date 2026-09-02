from __future__ import annotations

import base64
from pathlib import Path

from mutagen import File, MutagenError
from mutagen.flac import Picture

from app.storage.paths import TRACK_COVERS_DIR, ensure_storage_directories

MAX_ARTWORK_BYTES = 12 * 1024 * 1024


def save_embedded_artwork(
    audio_path: Path,
    track_id: str,
) -> str | None:
    """Extract embedded album art and return the persisted local path.

    Unsupported tags and invalid artwork deliberately return ``None``: the UI
    then renders its dark fallback tile instead of failing the audio import.
    """

    artwork = extract_embedded_artwork(audio_path)
    if artwork is None:
        return None

    image_data, mime_type = artwork
    if not image_data or len(image_data) > MAX_ARTWORK_BYTES:
        return None

    ensure_storage_directories()
    destination = TRACK_COVERS_DIR / (
        f"{track_id}{_image_suffix(image_data, mime_type)}"
    )

    try:
        destination.write_bytes(image_data)
    except OSError:
        return None

    return str(destination.resolve())


def extract_embedded_artwork(
    audio_path: Path,
) -> tuple[bytes, str | None] | None:
    """Read common MP3, M4A/MP4, FLAC and Vorbis artwork containers."""

    try:
        audio_file = File(audio_path)
    except (MutagenError, OSError):
        return None

    if audio_file is None:
        return None

    tags = audio_file.tags
    if tags is not None:
        pictures = getattr(tags, "getall", lambda _key: [])("APIC")
        for picture in pictures:
            data = getattr(picture, "data", None)
            if isinstance(data, bytes):
                return data, getattr(picture, "mime", None)

        cover_values = getattr(tags, "get", lambda _key, _default: [])(
            "covr",
            [],
        )
        for cover in cover_values:
            if isinstance(cover, bytes):
                return bytes(cover), _mp4_cover_mime(cover)

        encoded_pictures = getattr(tags, "get", lambda _key, _default: [])(
            "metadata_block_picture",
            [],
        )
        for encoded_picture in encoded_pictures:
            try:
                picture = Picture(base64.b64decode(encoded_picture))
            except (TypeError, ValueError):
                continue
            if picture.data:
                return picture.data, picture.mime or None

    for picture in getattr(audio_file, "pictures", []):
        data = getattr(picture, "data", None)
        if isinstance(data, bytes):
            return data, getattr(picture, "mime", None)

    return None


def _mp4_cover_mime(cover: object) -> str | None:
    image_format = getattr(cover, "imageformat", None)
    name = getattr(image_format, "name", "").lower()
    if "png" in name:
        return "image/png"
    if "jpeg" in name or "jpg" in name:
        return "image/jpeg"
    return None


def _image_suffix(image_data: bytes, mime_type: str | None) -> str:
    normalized_mime = (mime_type or "").lower()
    if "png" in normalized_mime or image_data.startswith(b"\x89PNG"):
        return ".png"
    if "webp" in normalized_mime or image_data[:4] == b"RIFF":
        return ".webp"
    if "gif" in normalized_mime or image_data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    return ".jpg"
