from dataclasses import replace
from pathlib import Path

from app.domain.models import Track
from app.ingestion.filenames import (
    add_collision_suffix,
    build_library_filename,
)
from app.storage.paths import LIBRARY_DIR
from app.storage.protocols import MusicStore


class TrackManagementService:
    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def update_metadata(
        self,
        *,
        track_id: str,
        title: str,
        artist: str,
        genres: tuple[str, ...],
    ) -> Track:
        normalized_track_id = track_id.strip()
        normalized_title = title.strip()
        normalized_artist = artist.strip()

        if not normalized_track_id:
            raise ValueError(
                "Track ID must not be empty"
            )

        if not normalized_title:
            raise ValueError(
                "Track title must not be empty"
            )

        if not normalized_artist:
            raise ValueError(
                "Track artist must not be empty"
            )

        current_track = self.store.get_track(
            normalized_track_id
        )

        if current_track is None:
            raise ValueError(
                f"Track does not exist: "
                f"{normalized_track_id}"
            )

        normalized_genres = tuple(
            genre.strip().lower()
            for genre in genres
            if genre.strip()
        )

        old_path = self._get_managed_file_path(
            current_track
        )

        new_path = self._build_new_file_path(
            current_track=current_track,
            artist=normalized_artist,
            title=normalized_title,
        )

        if old_path is not None and new_path != old_path:
            old_path.rename(new_path)

        updated_track = replace(
            current_track,
            title=normalized_title,
            artist=normalized_artist,
            genres=normalized_genres,
            local_path=(
                str(new_path)
                if new_path is not None
                else None
            ),
        )

        try:
            self.store.update_track(updated_track)
        except Exception:
            if (
                old_path is not None
                and new_path != old_path
                and new_path is not None
                and new_path.exists()
            ):
                new_path.rename(old_path)

            raise

        return updated_track

    @staticmethod
    def _get_managed_file_path(
        track: Track,
    ) -> Path | None:
        if not track.local_path:
            return None

        file_path = Path(
            track.local_path
        ).resolve()

        if not file_path.exists():
            raise FileNotFoundError(
                f"Track file does not exist: "
                f"{file_path}"
            )

        library_root = LIBRARY_DIR.resolve()

        try:
            file_path.relative_to(library_root)
        except ValueError as error:
            raise ValueError(
                "Track file is outside the managed library"
            ) from error

        return file_path

    @staticmethod
    def _build_new_file_path(
        *,
        current_track: Track,
        artist: str,
        title: str,
    ) -> Path | None:
        if not current_track.local_path:
            return None

        old_path = Path(
            current_track.local_path
        ).resolve()

        new_name = build_library_filename(
            artist=artist,
            title=title,
            suffix=old_path.suffix,
            track_id=current_track.id,
        )

        new_path = (
            LIBRARY_DIR / new_name
        ).resolve()

        if (
            new_path != old_path
            and new_path.exists()
        ):
            new_path = add_collision_suffix(
                new_path,
                current_track.id,
            )

        return new_path
