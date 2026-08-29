import re
from pathlib import Path

_INVALID_CHARACTERS = re.compile(
    r'[<>:"/\\|?*\x00-\x1F]'
)

_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "LPT1",
    "LPT2",
    "LPT3",
}


def build_library_filename(
    artist: str,
    title: str,
    suffix: str,
    track_id: str
) -> str:
    safe_artist = _sanitize_part(artist)
    safe_title = _sanitize_part(title)

    base_name = f"{safe_artist} — {safe_title}"

    if not safe_artist or not safe_title:
        base_name = f"track-{track_id}"

    if base_name.upper() in _RESERVED_NAMES:
        base_name = f"track-{track_id}"

    return f"{base_name}{suffix.lower()}"


def _sanitize_part(value: str) -> str:
    sanitized = _INVALID_CHARACTERS.sub(
        "_",
        value
    )

    sanitized = re.sub(
        r"\s+",
        " ",
        sanitized
    )

    return sanitized.strip(" .")


def add_collision_suffix(
    file_path: Path,
    track_id: str,
) -> Path:
    return file_path.with_name(
        f"{file_path.stem} "
        f"[{track_id[-8:]}]"
        f"{file_path.suffix}"
    )
