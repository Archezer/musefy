"""Import Spotify saved-track metadata without downloading audio."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.domain.models import SpotifyFavorite, Track
from app.services.youtube_import import OperationCancelled
from app.sources.spotify import SpotifyMetadataProvider, SpotifyTrack
from app.storage.protocols import MusicStore

SPOTIFY_FAVORITE_SOURCE = "spotify_favorite"


@dataclass(frozen=True)
class SpotifyFavoritesImportResult:
    fetched: int
    imported_tracks: int
    updated_tracks: int
    active_preferences: int
    deactivated_preferences: int
    skipped_tracks: int
    imported_at: datetime


class SpotifyFavoritesImportService:
    """Persist Spotify favorites as metadata and user-specific preferences."""

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
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("User ID must not be empty")
        if self.store.get_user(normalized_user_id) is None:
            raise ValueError(f"User does not exist: {normalized_user_id}")

        spotify_tracks = self.provider.get_saved_tracks()
        imported_at = datetime.now(UTC)
        current_spotify_ids: set[str] = set()
        imported_tracks = 0
        updated_tracks = 0
        active_preferences = 0
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

            spotify_id = spotify_track.spotify_id.strip()
            current_spotify_ids.add(spotify_id)
            track, created, changed = self._upsert_track(
                spotify_track,
                imported_at=imported_at,
            )
            if created:
                imported_tracks += 1
            elif changed:
                updated_tracks += 1

            self.store.upsert_spotify_favorite(
                SpotifyFavorite(
                    user_id=normalized_user_id,
                    track_id=track.id,
                    spotify_id=spotify_id,
                    added_at=_parse_timestamp(spotify_track.added_at),
                    imported_at=imported_at,
                    album=spotify_track.album,
                    isrc=spotify_track.isrc,
                    active=True,
                )
            )
            active_preferences += 1
            self._report_progress(
                on_progress,
                index,
                len(spotify_tracks),
                spotify_track.title,
            )

        deactivated_preferences = 0
        for favorite in self.store.list_spotify_favorites(
            normalized_user_id,
            active_only=True,
        ):
            if favorite.spotify_id in current_spotify_ids:
                continue
            self.store.upsert_spotify_favorite(
                replace(
                    favorite,
                    imported_at=imported_at,
                    active=False,
                )
            )
            deactivated_preferences += 1

        return SpotifyFavoritesImportResult(
            fetched=len(spotify_tracks),
            imported_tracks=imported_tracks,
            updated_tracks=updated_tracks,
            active_preferences=active_preferences,
            deactivated_preferences=deactivated_preferences,
            skipped_tracks=skipped_tracks,
            imported_at=imported_at,
        )

    def _upsert_track(
        self,
        spotify_track: SpotifyTrack,
        *,
        imported_at: datetime,
    ) -> tuple[Track, bool, bool]:
        assert spotify_track.spotify_id is not None
        spotify_id = spotify_track.spotify_id.strip()
        title = spotify_track.title.strip()
        artist = (spotify_track.artist or "Unknown Artist").strip()
        source_url = f"https://open.spotify.com/track/{spotify_id}"
        existing = self.store.get_track_by_source(
            SPOTIFY_FAVORITE_SOURCE,
            spotify_id,
        )
        if existing is None:
            existing = self._find_matching_local_track(
                title=title,
                artist=artist,
                duration_ms=spotify_track.duration_ms,
            )

        if existing is not None:
            updated = replace(
                existing,
                title=title,
                artist=artist,
                duration_ms=(
                    spotify_track.duration_ms
                    if spotify_track.duration_ms is not None
                    else existing.duration_ms
                ),
                source_url=existing.source_url or source_url,
            )
            if updated != existing:
                self.store.update_track(updated)
            return updated, False, updated != existing

        created_at = _parse_timestamp(spotify_track.added_at) or imported_at
        track = Track(
            id=f"spotify-{spotify_id}",
            title=title,
            artist=artist,
            created_at=created_at,
            duration_ms=spotify_track.duration_ms,
            source=SPOTIFY_FAVORITE_SOURCE,
            source_id=spotify_id,
            source_url=source_url,
        )
        self.store.add_track(track)
        return track, True, True

    def _find_matching_local_track(
        self,
        *,
        title: str,
        artist: str,
        duration_ms: int | None,
    ) -> Track | None:
        normalized_title = _normalize_text(title)
        normalized_artist = _normalize_text(artist)
        for track in self.store.list_tracks():
            if track.source not in {"spotify_favorite", "youtube"}:
                continue
            if (
                _normalize_text(track.title) != normalized_title
                or _normalize_text(track.artist) != normalized_artist
            ):
                continue
            if (
                duration_ms is not None
                and track.duration_ms is not None
                and abs(duration_ms - track.duration_ms) > 2_000
            ):
                continue
            return track
        return None

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


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


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
