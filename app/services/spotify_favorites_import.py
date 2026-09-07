"""Import Spotify saved-track metadata without creating library tracks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.domain.models import SpotifyTrackMetadata
from app.services.youtube_import import OperationCancelled
from app.sources.spotify import SpotifyMetadataProvider, SpotifyTrack
from app.storage.protocols import MusicStore


@dataclass(frozen=True)
class SpotifyFavoritesImportResult:
    fetched: int
    imported_metadata: int
    updated_metadata: int
    skipped_tracks: int
    imported_at: datetime


class SpotifyFavoritesImportService:
    """Persist Spotify metadata only; audio sync remains a separate flow."""

    def __init__(
        self,
        store: MusicStore,
        provider: SpotifyMetadataProvider,
    ) -> None:
        self.store = store
        self.provider = provider

    def import_all(
        self,
        user_id: str,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> SpotifyFavoritesImportResult:
        """Import the current Spotify saved-track catalog.

        ``user_id`` is retained for CLI/UI compatibility and validation. It is
        intentionally not persisted: this first stage stores one external
        Spotify metadata catalog without a user-to-track relation.
        """

        if not user_id.strip():
            raise ValueError("User ID must not be empty")

        spotify_tracks = self.provider.get_saved_tracks()
        imported_at = datetime.now(UTC)
        imported_metadata = 0
        updated_metadata = 0
        skipped_tracks = 0

        for index, spotify_track in enumerate(spotify_tracks, start=1):
            self._check_cancelled(should_cancel)
            if not self._is_valid_track(spotify_track):
                skipped_tracks += 1
                self._report_progress(
                    on_progress,
                    index,
                    len(spotify_tracks),
                    spotify_track.title,
                )
                continue

            metadata = self._to_metadata(
                spotify_track,
                imported_at=imported_at,
            )
            existing = self.store.get_spotify_track_metadata(
                metadata.spotify_id
            )
            if existing is None:
                imported_metadata += 1
            elif self._metadata_changed(existing, metadata):
                updated_metadata += 1

            self.store.upsert_spotify_track_metadata(metadata)
            self._report_progress(
                on_progress,
                index,
                len(spotify_tracks),
                spotify_track.title,
            )

        return SpotifyFavoritesImportResult(
            fetched=len(spotify_tracks),
            imported_metadata=imported_metadata,
            updated_metadata=updated_metadata,
            skipped_tracks=skipped_tracks,
            imported_at=imported_at,
        )

    @staticmethod
    def _to_metadata(
        spotify_track: SpotifyTrack,
        *,
        imported_at: datetime,
    ) -> SpotifyTrackMetadata:
        assert spotify_track.spotify_id is not None
        return SpotifyTrackMetadata(
            spotify_id=spotify_track.spotify_id.strip(),
            title=spotify_track.title.strip(),
            artist=(spotify_track.artist or "Unknown Artist").strip(),
            album=spotify_track.album,
            duration_ms=spotify_track.duration_ms,
            added_at=_parse_timestamp(spotify_track.added_at),
            isrc=spotify_track.isrc,
            imported_at=imported_at,
        )

    @staticmethod
    def _metadata_changed(
        existing: SpotifyTrackMetadata,
        current: SpotifyTrackMetadata,
    ) -> bool:
        return replace(existing, imported_at=current.imported_at) != current

    @staticmethod
    def _is_valid_track(track: SpotifyTrack) -> bool:
        return bool(
            track.spotify_id
            and track.spotify_id.strip()
            and track.title.strip()
        )

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
        title: str,
    ) -> None:
        if callback is not None:
            callback(completed, total, title)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        timestamp = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)
