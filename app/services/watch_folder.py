"""Incremental synchronization for a user-selected local audio folder."""

from __future__ import annotations

import filecmp
import json
from dataclasses import dataclass
from pathlib import Path

from app.domain.models import Track
from app.ingestion.audio import SUPPORTED_AUDIO_EXTENSIONS, AudioIngestionService
from app.ingestion.metadata import read_audio_metadata
from app.services.tracks import TrackManagementService
from app.storage.paths import DATA_DIR, ensure_storage_directories
from app.storage.protocols import MusicStore

WATCH_SOURCE = "watch_folder"
WATCH_SOURCE_PREFIX = "watch_folder:"
WATCH_CONFIG_PATH = DATA_DIR / "watch-folder.json"


@dataclass(frozen=True)
class WatchFolderConfig:
    folder: Path | None = None
    enabled: bool = False
    update_metadata: bool = False


@dataclass(frozen=True)
class WatchFolderReport:
    folder: Path | None
    imported: tuple[Track, ...] = ()
    updated: tuple[Track, ...] = ()
    removed_files: tuple[Path, ...] = ()
    removed_tracks: tuple[Track, ...] = ()
    errors: tuple[str, ...] = ()
    skipped: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.imported
            or self.updated
            or self.removed_files
            or self.removed_tracks
        )


class WatchFolderService:
    """Persist one watch-folder configuration and synchronize it safely."""

    def __init__(self, store: MusicStore) -> None:
        self.store = store
        self._config = self._read_config()
        self._state = self._read_state()

    @property
    def config(self) -> WatchFolderConfig:
        return self._config

    def configure(
        self,
        folder: Path,
        *,
        update_metadata: bool = False,
    ) -> WatchFolderConfig:
        folder = folder.expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f"Watch folder does not exist: {folder}")

        if self._config.folder != folder:
            self._state = {}
        self._config = WatchFolderConfig(
            folder=folder,
            enabled=True,
            update_metadata=bool(update_metadata),
        )
        self._write_config()
        self._write_state()
        return self._config

    def set_update_metadata(self, enabled: bool) -> WatchFolderConfig:
        self._config = WatchFolderConfig(
            folder=self._config.folder,
            enabled=self._config.enabled,
            update_metadata=bool(enabled),
        )
        self._write_config()
        return self._config

    def disable(self) -> WatchFolderConfig:
        self._config = WatchFolderConfig(
            folder=self._config.folder,
            enabled=False,
            update_metadata=self._config.update_metadata,
        )
        self._write_config()
        return self._config

    def sync(
        self,
        ingestion_service: AudioIngestionService,
        track_management_service: TrackManagementService,
    ) -> WatchFolderReport:
        config = self._config
        if not config.enabled or config.folder is None:
            return WatchFolderReport(folder=config.folder)

        folder = config.folder
        try:
            source_files = {
                path.resolve(): self._file_signature(path)
                for path in folder.rglob("*")
                if path.is_file()
                and path.suffix.casefold() in SUPPORTED_AUDIO_EXTENSIONS
            }
        except OSError as error:
            return WatchFolderReport(folder=folder, errors=(str(error),))

        tracks_by_source_id = {
            track.source_id: track
            for track in self.store.list_tracks()
            if track.source == WATCH_SOURCE and track.source_id
        }
        imported: list[Track] = []
        updated: list[Track] = []
        removed_files = [
            Path(path)
            for path in self._state
            if Path(path).resolve() not in source_files
        ]
        errors: list[str] = []
        skipped = 0
        next_state: dict[str, dict[str, object]] = {}

        for path, signature in source_files.items():
            path_key = str(path)
            source_id = self._source_id(folder, path)
            prior = self._state.get(path_key)
            track = tracks_by_source_id.get(source_id)
            is_unchanged = (
                prior is not None
                and prior.get("size") == signature[0]
                and prior.get("mtime_ns") == signature[1]
                and track is not None
            )
            if is_unchanged:
                next_state[path_key] = {
                    "size": signature[0],
                    "mtime_ns": signature[1],
                    "track_id": track.id,
                }
                skipped += 1
                continue

            try:
                if track is None:
                    track = ingestion_service.ingest(
                        path,
                        source=WATCH_SOURCE,
                        source_id=source_id,
                    )
                    imported.append(track)
                else:
                    source_content_changed = self._content_changed(path, track)
                    metadata = (
                        read_audio_metadata(path)
                        if config.update_metadata or source_content_changed
                        else None
                    )
                    title = (
                        metadata.title
                        if metadata is not None and metadata.title
                        and config.update_metadata
                        else track.title
                    )
                    artist = (
                        metadata.artist
                        if metadata is not None and metadata.artist
                        and config.update_metadata
                        else track.artist
                    )
                    if source_content_changed:
                        track = ingestion_service.restore_missing_track(
                            existing_track=track,
                            file_path=path,
                            title=title,
                            artist=artist,
                            source=WATCH_SOURCE,
                            source_id=source_id,
                            source_url=track.source_url,
                        )
                        updated.append(track)
                    elif config.update_metadata and (
                        title != track.title or artist != track.artist
                    ):
                        track = track_management_service.update_metadata(
                            track_id=track.id,
                            title=title,
                            artist=artist,
                            genres=track.genres,
                        )
                        updated.append(track)
            except (OSError, RuntimeError, ValueError) as error:
                errors.append(f"{path.name}: {error}")
                # Keep a prior record so a transiently locked file is retried
                # on the next polling pass instead of being treated as gone.
                if prior is not None:
                    next_state[path_key] = dict(prior)
                continue

            if track is not None:
                next_state[path_key] = {
                    "size": signature[0],
                    "mtime_ns": signature[1],
                    "track_id": track.id,
                }

        removed_tracks = [
            track
            for track in tracks_by_source_id.values()
            if self._source_key(folder, track.source_id) in self._state
            if not self._source_path_exists(folder, track.source_id, source_files)
        ]
        self._state = next_state
        self._write_state()
        return WatchFolderReport(
            folder=folder,
            imported=tuple(imported),
            updated=tuple(updated),
            removed_files=tuple(removed_files),
            removed_tracks=tuple(removed_tracks),
            errors=tuple(errors),
            skipped=skipped,
        )

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns

    @staticmethod
    def _source_id(folder: Path, path: Path) -> str:
        relative = path.relative_to(folder).as_posix()
        return f"{WATCH_SOURCE_PREFIX}{relative}"

    @staticmethod
    def _source_path_exists(
        folder: Path,
        source_id: str | None,
        source_files: dict[Path, tuple[int, int]],
    ) -> bool:
        if not source_id or not source_id.startswith(WATCH_SOURCE_PREFIX):
            return True
        relative = source_id.removeprefix(WATCH_SOURCE_PREFIX)
        candidate = (folder / relative).resolve()
        return candidate in source_files

    @staticmethod
    def _source_key(folder: Path, source_id: str | None) -> str:
        if not source_id or not source_id.startswith(WATCH_SOURCE_PREFIX):
            return ""
        relative = source_id.removeprefix(WATCH_SOURCE_PREFIX)
        return str((folder / relative).resolve())

    @staticmethod
    def _content_changed(path: Path, track: Track) -> bool:
        if not track.local_path:
            return True
        managed_path = Path(track.local_path)
        if not managed_path.is_file():
            return True
        try:
            return not filecmp.cmp(path, managed_path, shallow=False)
        except OSError:
            return True

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _read_config(self) -> WatchFolderConfig:
        payload = self._read_json(WATCH_CONFIG_PATH)
        folder_value = payload.get("folder")
        folder = Path(folder_value).expanduser() if isinstance(folder_value, str) else None
        if folder is not None:
            folder = folder.resolve()
        return WatchFolderConfig(
            folder=folder,
            enabled=bool(payload.get("enabled", False)) and folder is not None,
            update_metadata=bool(payload.get("update_metadata", False)),
        )

    def _read_state(self) -> dict[str, dict[str, object]]:
        state_value = self._read_json(WATCH_CONFIG_PATH.with_name("watch-folder-state.json"))
        files = state_value.get("files")
        if not isinstance(files, dict):
            return {}
        return {
            str(path): value
            for path, value in files.items()
            if isinstance(value, dict)
        }

    def _write_config(self) -> None:
        ensure_storage_directories()
        WATCH_CONFIG_PATH.write_text(
            json.dumps(
                {
                    "folder": str(self._config.folder) if self._config.folder else None,
                    "enabled": self._config.enabled,
                    "update_metadata": self._config.update_metadata,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_state(self) -> None:
        state_path = WATCH_CONFIG_PATH.with_name("watch-folder-state.json")
        ensure_storage_directories()
        state_path.write_text(
            json.dumps({"files": self._state}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
