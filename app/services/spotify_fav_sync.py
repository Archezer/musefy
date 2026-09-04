from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.sources.spotify import SpotifyMetadataProvider, SpotifyTrack
from app.storage.paths import DATA_DIR

DEFAULT_STATE_PATH = DATA_DIR / "spotify_fav_sync.json"


@dataclass(frozen=True)
class SpotifyFavSyncResult:
    """Tracks discovered since the previous successful synchronization."""

    new_tracks: tuple[SpotifyTrack, ...]
    synced_at: str


class SpotifyFavSyncService:
    """Persist and incrementally scan Spotify's saved-track library.

    Enabling the feature creates a local high-water mark. Existing Spotify
    favorites therefore stay untouched. After the first successful scan, the
    persisted ``last_sync_at`` cursor is used so a restart can continue from
    the last synchronization instead of replaying the whole saved library.
    """

    def __init__(
        self,
        provider: SpotifyMetadataProvider,
        *,
        state_path: Path | None = None,
    ) -> None:
        self.provider = provider
        self.state_path = state_path or DEFAULT_STATE_PATH

    def is_enabled(self) -> bool:
        return bool(self._load_state().get("enabled", False))

    def set_enabled(self, enabled: bool) -> None:
        state = self._load_state()
        was_enabled = bool(state.get("enabled", False))

        if enabled and not was_enabled:
            state = {
                "enabled": True,
                "tracking_since": _now_iso(),
                "last_sync_at": None,
                "seen_track_ids": [],
            }
        elif not enabled:
            state["enabled"] = False

        self._save_state(state)

    def sync_new_saved_tracks(self) -> SpotifyFavSyncResult:
        state = self._load_state()
        synced_at = _now_iso()
        if not state.get("enabled", False):
            return SpotifyFavSyncResult((), synced_at)

        tracking_since = _parse_timestamp(state.get("tracking_since"))
        # ``tracking_since`` is the initial baseline created when the feature
        # is enabled.  Once a scan has completed, ``last_sync_at`` becomes the
        # durable cursor used across app restarts.  Keep the fallback for
        # state files written by older versions.
        last_sync_at = _parse_timestamp(state.get("last_sync_at"))
        sync_cursors = [
            timestamp
            for timestamp in (tracking_since, last_sync_at)
            if timestamp is not None
        ]
        sync_cursor = max(sync_cursors) if sync_cursors else None
        seen_track_ids = {
            str(track_id)
            for track_id in state.get("seen_track_ids", [])
            if track_id
        }
        new_tracks: list[SpotifyTrack] = []

        for track in self.provider.get_saved_tracks():
            if not track.spotify_id or not track.added_at:
                continue

            added_at = _parse_timestamp(track.added_at)
            if added_at is None or (
                sync_cursor is not None and added_at <= sync_cursor
            ):
                continue
            if track.spotify_id in seen_track_ids:
                continue

            seen_track_ids.add(track.spotify_id)
            new_tracks.append(track)

        state["last_sync_at"] = synced_at
        state["seen_track_ids"] = sorted(seen_track_ids)
        self._save_state(state)

        return SpotifyFavSyncResult(tuple(new_tracks), synced_at)

    def sync_all_saved_tracks(self) -> SpotifyFavSyncResult:
        """Read the complete saved-track library for an explicit sync-all."""

        synced_at = _now_iso()
        tracks = self.provider.get_saved_tracks()
        state = self._load_state()
        state["last_sync_at"] = synced_at
        state["seen_track_ids"] = sorted(
            {
                track.spotify_id
                for track in tracks
                if track.spotify_id
            }
        )
        self._save_state(state)
        return SpotifyFavSyncResult(tracks, synced_at)

    def _load_state(self) -> dict[str, object]:
        try:
            payload = json.loads(
                self.state_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return {}

        return payload if isinstance(payload, dict) else {}

    def _save_state(self, state: dict[str, object]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, self.state_path)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
