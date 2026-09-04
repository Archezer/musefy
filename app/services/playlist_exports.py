from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXPORT_SOURCES = frozenset({"vk", "spotify", "yandex"})
SUPPORTED_EXPORT_FORMAT = "music-recommendation-system."


@dataclass(frozen=True)
class ExportedPlaylistTrack:
    position: int
    artist: str
    title: str
    duration_seconds: int | None = None


@dataclass(frozen=True)
class ExportedPlaylist:
    source: str
    title: str
    url: str
    cover_url: str | None
    tracks: tuple[ExportedPlaylistTrack, ...]


def read_playlist_export(path: Path) -> ExportedPlaylist:
    if not path.exists():
        raise FileNotFoundError(f"Playlist export does not exist: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read playlist export: {path}") from error

    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004 - malformed JSON is a validation error
            "Playlist export must contain a JSON object."
        )

    export_format = payload.get("format")
    if not (
        isinstance(export_format, str)
        and export_format.startswith(SUPPORTED_EXPORT_FORMAT)
        and export_format.endswith("-playlist")
    ):
        raise ValueError("Unsupported playlist export format.")

    playlist = payload.get("playlist")
    raw_tracks = payload.get("tracks")

    if not isinstance(playlist, dict):
        raise ValueError(  # noqa: TRY004 - malformed JSON is a validation error
            "Playlist export does not contain playlist metadata."
        )

    if not isinstance(raw_tracks, list):
        raise ValueError(  # noqa: TRY004 - malformed JSON is a validation error
            "Playlist export does not contain a tracks list."
        )

    source = _required_text(playlist.get("source"), "playlist source").lower()
    if source not in SUPPORTED_EXPORT_SOURCES:
        raise ValueError(f"Unsupported playlist source: {source}")

    title = _required_text(playlist.get("title"), "playlist title")
    url = str(playlist.get("url") or "").strip()
    cover_url = _optional_cover_url(playlist.get("cover_url"))
    tracks = tuple(
        _parse_track(raw_track, fallback_position=index + 1)
        for index, raw_track in enumerate(raw_tracks)
    )

    if not tracks:
        raise ValueError("Playlist export does not contain any tracks.")

    return ExportedPlaylist(
        source=source,
        title=title,
        url=url,
        cover_url=cover_url,
        tracks=tracks,
    )


def _parse_track(
    payload: object,
    *,
    fallback_position: int,
) -> ExportedPlaylistTrack:
    if not isinstance(payload, dict):
        raise ValueError(  # noqa: TRY004 - malformed JSON is a validation error
            "Playlist export contains an invalid track."
        )

    artist = _required_text(payload.get("artist"), "track artist")
    title = _required_text(payload.get("title"), "track title")
    raw_position = payload.get("position", fallback_position)

    if isinstance(raw_position, bool):
        position = fallback_position
    else:
        try:
            position = int(raw_position)
        except (TypeError, ValueError) as error:
            raise ValueError("Track position must be an integer.") from error

    if position < 1:
        raise ValueError("Track position must be positive.")

    raw_duration = payload.get("duration_seconds")
    duration_seconds = None
    if raw_duration is not None:
        try:
            duration_seconds = int(raw_duration)
        except (TypeError, ValueError) as error:
            raise ValueError("Track duration must be an integer.") from error

        if duration_seconds < 0:
            raise ValueError("Track duration must not be negative.")

    return ExportedPlaylistTrack(
        position=position,
        artist=artist,
        title=title,
        duration_seconds=duration_seconds,
    )


def _required_text(value: object, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Playlist export is missing {field_name}.")

    return text


def _optional_cover_url(value: object) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None

    if not url.lower().startswith(("https://", "http://")):
        return None

    return url
