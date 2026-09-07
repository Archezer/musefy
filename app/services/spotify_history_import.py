"""Import Spotify Extended Streaming History as aggregate listening stats."""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from app.domain.models import SpotifyListeningStats
from app.services.youtube_import import OperationCancelled
from app.storage.protocols import MusicStore


@dataclass(frozen=True)
class SpotifyListeningHistoryImportResult:
    source_files: int
    total_entries: int
    imported_stats: int
    updated_stats: int
    skipped_entries: int
    imported_at: datetime


@dataclass
class _StatsAccumulator:
    play_count: int = 0
    total_ms_played: int = 0
    first_played_at: datetime | None = None
    last_played_at: datetime | None = None
    completion_count: int = 0
    skip_count: int = 0

    def add(
        self,
        *,
        ms_played: int,
        played_at: datetime | None,
        completed: bool,
        skipped: bool,
    ) -> None:
        self.play_count += 1
        self.total_ms_played += ms_played
        if played_at is not None:
            if (
                self.first_played_at is None
                or played_at < self.first_played_at
            ):
                self.first_played_at = played_at
            if (
                self.last_played_at is None
                or played_at > self.last_played_at
            ):
                self.last_played_at = played_at
        if completed:
            self.completion_count += 1
        if skipped:
            self.skip_count += 1


class SpotifyListeningHistoryImportService:
    """Import history without creating library tracks or interactions."""

    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def import_path(
        self,
        path: Path,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifyListeningHistoryImportResult:
        entries, source_files = _read_history_entries(path)
        imported_at = datetime.now(UTC)
        accumulators: dict[str, _StatsAccumulator] = {}
        skipped_entries = 0

        for index, entry in enumerate(entries, start=1):
            self._check_cancelled(should_cancel)
            parsed = self._parse_entry(entry)
            if parsed is None:
                skipped_entries += 1
                self._report_progress(
                    on_progress,
                    index,
                    len(entries),
                    "Skipped entry",
                )
                continue

            spotify_id, ms_played, played_at, completed, skipped = parsed
            accumulator = accumulators.setdefault(
                spotify_id,
                _StatsAccumulator(),
            )
            accumulator.add(
                ms_played=ms_played,
                played_at=played_at,
                completed=completed,
                skipped=skipped,
            )
            self._report_progress(
                on_progress,
                index,
                len(entries),
                spotify_id,
            )

        imported_stats = 0
        updated_stats = 0
        for spotify_id, accumulator in sorted(accumulators.items()):
            stats = SpotifyListeningStats(
                spotify_id=spotify_id,
                play_count=accumulator.play_count,
                total_ms_played=accumulator.total_ms_played,
                first_played_at=accumulator.first_played_at,
                last_played_at=accumulator.last_played_at,
                completion_count=accumulator.completion_count,
                skip_count=accumulator.skip_count,
                imported_at=imported_at,
            )
            existing = self.store.get_spotify_listening_stats(spotify_id)
            if existing is None:
                imported_stats += 1
            elif replace(existing, imported_at=imported_at) != stats:
                updated_stats += 1
            self.store.upsert_spotify_listening_stats(stats)

        return SpotifyListeningHistoryImportResult(
            source_files=source_files,
            total_entries=len(entries),
            imported_stats=imported_stats,
            updated_stats=updated_stats,
            skipped_entries=skipped_entries,
            imported_at=imported_at,
        )

    def _parse_entry(
        self,
        entry: object,
    ) -> tuple[str, int, datetime | None, bool, bool] | None:
        if not isinstance(entry, dict):
            return None

        spotify_id = _spotify_track_id(
            entry.get("spotify_track_uri") or entry.get("track_uri")
        )
        if spotify_id is None:
            return None

        ms_played = _nonnegative_int(entry.get("ms_played"))
        played_at = _parse_timestamp(
            entry.get("ts")
            or entry.get("timestamp")
            or entry.get("played_at")
        )
        reason_end = str(entry.get("reason_end") or "").casefold()
        skipped = _as_bool(entry.get("skipped")) or reason_end in {
            "fwdbtn",
            "backbtn",
        }

        metadata = self.store.get_spotify_track_metadata(spotify_id)
        duration_ms = metadata.duration_ms if metadata is not None else None
        completed = not skipped and (
            reason_end == "trackdone"
            or (
                duration_ms is not None
                and duration_ms > 0
                and ms_played >= round(duration_ms * 0.8)
            )
        )
        return spotify_id, ms_played, played_at, completed, skipped

    @staticmethod
    def _check_cancelled(
        should_cancel: Callable[[], bool] | None,
    ) -> None:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled()

    @staticmethod
    def _report_progress(
        callback: Callable[[int, int, str], None] | None,
        completed: int,
        total: int,
        current: str,
    ) -> None:
        if callback is not None:
            callback(completed, total, current)


def _read_history_entries(path: Path) -> tuple[list[object], int]:
    normalized_path = Path(path)
    if not normalized_path.is_file():
        raise ValueError(f"Spotify history file does not exist: {path}")

    suffix = normalized_path.suffix.casefold()
    if suffix == ".zip":
        return _read_zip_entries(normalized_path)
    if suffix == ".json":
        return _read_json_entries(normalized_path), 1
    raise ValueError("Spotify history must be a .json or .zip file.")


def _read_zip_entries(path: Path) -> tuple[list[object], int]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError(f"Could not read Spotify history ZIP: {path}") from error

    with archive:
        json_names = [
            name
            for name in archive.namelist()
            if name.casefold().endswith(".json")
        ]
        history_names = [
            name
            for name in json_names
            if "streaming_history" in name.casefold()
            or "streaming history" in name.casefold()
        ]
        selected_names = history_names or json_names
        entries: list[object] = []
        for name in selected_names:
            try:
                payload = json.loads(
                    archive.read(name).decode("utf-8-sig")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(
                    f"Could not parse Spotify history file in ZIP: {name}"
                ) from error
            entries.extend(_extract_entries(payload))
        return entries, len(selected_names)


def _read_json_entries(path: Path) -> list[object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not parse Spotify history JSON: {path}") from error
    return _extract_entries(payload)


def _extract_entries(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("items", "entries", "streaming_history"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("Spotify history JSON must contain a list of entries.")


def _spotify_track_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if normalized.startswith("spotify:track:"):
        spotify_id = normalized.removeprefix("spotify:track:").split("?", 1)[0]
        return spotify_id or None

    parsed = urlparse(normalized)
    if parsed.hostname not in {"open.spotify.com", "play.spotify.com"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "track":
        return None
    return parts[1] or None


def _nonnegative_int(value: object) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return bool(value)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)
