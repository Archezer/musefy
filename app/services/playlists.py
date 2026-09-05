import shutil
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from app.domain.models import Playlist, PlaylistEntry, Track
from app.storage.paths import PLAYLIST_COVERS_DIR
from app.storage.protocols import MusicStore

SUPPORTED_COVER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_COVER_DOWNLOAD_BYTES = 8 * 1024 * 1024


class PlaylistManagementService:
    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def create_playlist(self, name: str) -> Playlist:
        normalized_name = name.strip()

        if not normalized_name:
            raise ValueError("Playlist name must not be empty")

        playlist = Playlist(
            id=str(uuid4()),
            name=normalized_name,
        )
        self.store.add_playlist(playlist)

        return playlist

    def rename_playlist(
        self,
        playlist_id: str,
        name: str,
    ) -> Playlist:
        playlist = self._get_playlist_or_raise(playlist_id)
        normalized_name = name.strip()

        if not normalized_name:
            raise ValueError("Playlist name must not be empty")

        updated_playlist = replace(
            playlist,
            name=normalized_name,
        )
        self.store.update_playlist(updated_playlist)

        return updated_playlist

    def delete_playlist(self, playlist_id: str) -> None:
        self._get_playlist_or_raise(playlist_id)
        self.store.delete_playlist(playlist_id)

    def set_cover(
        self,
        playlist_id: str,
        source_path: Path,
    ) -> Playlist:
        playlist = self._get_playlist_or_raise(playlist_id)

        if not source_path.is_file():
            raise FileNotFoundError(
                f"Playlist cover does not exist: {source_path}"
            )

        suffix = source_path.suffix.lower()
        if suffix not in SUPPORTED_COVER_EXTENSIONS:
            raise ValueError(
                f"Unsupported cover format: {source_path.suffix}"
            )

        PLAYLIST_COVERS_DIR.mkdir(parents=True, exist_ok=True)
        destination = PLAYLIST_COVERS_DIR / f"{playlist.id}{suffix}"
        shutil.copy2(source_path, destination)
        return self._update_cover_path(playlist, destination)

    def set_cover_from_url(
        self,
        playlist_id: str,
        cover_url: str,
    ) -> Playlist:
        playlist = self._get_playlist_or_raise(playlist_id)
        normalized_url = cover_url.strip()
        parsed_url = urlparse(normalized_url)

        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("Playlist cover URL must use HTTP or HTTPS.")

        request = Request(
            normalized_url,
            headers={"User-Agent": "MusicAtlas/1.0"},
        )
        with urlopen(request, timeout=12) as response:
            image_data = response.read(MAX_COVER_DOWNLOAD_BYTES + 1)
            content_type = response.headers.get_content_type()

        if not image_data or len(image_data) > MAX_COVER_DOWNLOAD_BYTES:
            raise ValueError("Playlist cover image is empty or too large.")

        suffix = self._remote_cover_suffix(
            normalized_url,
            content_type,
            image_data,
        )
        PLAYLIST_COVERS_DIR.mkdir(parents=True, exist_ok=True)
        destination = PLAYLIST_COVERS_DIR / f"{playlist.id}{suffix}"
        destination.write_bytes(image_data)
        return self._update_cover_path(playlist, destination)

    def ensure_generated_cover(
        self,
        playlist_id: str,
        artwork_factory: Callable[[], str],
    ) -> Playlist:
        """Return a playlist with a persisted fallback artwork.

        Generated artwork is only created when the playlist has no usable
        cover.  Keeping this decision in the management service means UI
        refreshes and application restarts reuse the same stored artwork.
        """

        playlist = self._get_playlist_or_raise(playlist_id)
        if playlist.cover_path and Path(playlist.cover_path).is_file():
            return playlist

        return self.set_generated_cover(
            playlist_id,
            artwork_factory(),
        )

    def set_generated_cover(
        self,
        playlist_id: str,
        svg: str,
    ) -> Playlist:
        """Persist generated SVG artwork and make it the playlist cover."""

        playlist = self._get_playlist_or_raise(playlist_id)
        normalized_svg = svg.strip()
        if not normalized_svg:
            raise ValueError("Generated playlist artwork must not be empty")

        PLAYLIST_COVERS_DIR.mkdir(parents=True, exist_ok=True)
        destination = PLAYLIST_COVERS_DIR / f"{playlist.id}.svg"
        destination.write_text(normalized_svg, encoding="utf-8")
        return self._update_cover_path(playlist, destination)

    def list_playlists(self) -> list[Playlist]:
        return list(self.store.list_playlists())

    def get_playlist_tracks(
        self,
        playlist_id: str,
    ) -> list[Track]:
        self._get_playlist_or_raise(playlist_id)
        entries = self.store.list_playlist_entries(playlist_id)
        tracks: list[Track] = []

        for entry in entries:
            track = self.store.get_track(entry.track_id)

            if track is not None:
                tracks.append(track)

        return tracks

    def add_track(
        self,
        playlist_id: str,
        track_id: str,
    ) -> list[Track]:
        self._get_playlist_or_raise(playlist_id)

        if self.store.get_track(track_id) is None:
            raise ValueError(
                f"Track does not exist: {track_id}"
            )

        entries = list(
            self.store.list_playlist_entries(playlist_id)
        )
        # Older databases (or a track deleted with database-level cascade)
        # can contain a gap in positions.  Reindex the existing entries before
        # appending so one stale position cannot block every future add.
        normalized_entries = [
            PlaylistEntry(
                playlist_id=playlist_id,
                track_id=entry.track_id,
                position=position,
            )
            for position, entry in enumerate(entries)
        ]
        normalized_entries.append(
            PlaylistEntry(
                playlist_id=playlist_id,
                track_id=track_id,
                position=len(normalized_entries),
            )
        )
        self.store.replace_playlist_entries(
            playlist_id,
            normalized_entries,
        )

        return self.get_playlist_tracks(playlist_id)

    def replace_tracks(
        self,
        playlist_id: str,
        track_ids: Iterable[str],
    ) -> list[Track]:
        self._get_playlist_or_raise(playlist_id)
        normalized_track_ids = tuple(track_ids)

        for track_id in normalized_track_ids:
            if self.store.get_track(track_id) is None:
                raise ValueError(
                    f"Track does not exist: {track_id}"
                )

        entries = tuple(
            PlaylistEntry(
                playlist_id=playlist_id,
                track_id=track_id,
                position=position,
            )
            for position, track_id in enumerate(normalized_track_ids)
        )
        self.store.replace_playlist_entries(
            playlist_id,
            entries,
        )

        return self.get_playlist_tracks(playlist_id)

    def merge_playlists(
        self,
        target_playlist_id: str,
        source_playlist_id: str,
        *,
        include_duplicates: bool = False,
    ) -> list[Track]:
        """Append one playlist to another while preserving track order."""

        if target_playlist_id == source_playlist_id:
            raise ValueError("A playlist cannot be merged with itself")

        target_tracks = self.get_playlist_tracks(target_playlist_id)
        source_tracks = self.get_playlist_tracks(source_playlist_id)
        if include_duplicates:
            appended_tracks = source_tracks
        else:
            seen_track_ids = {track.id for track in target_tracks}
            appended_tracks = []
            for track in source_tracks:
                if track.id in seen_track_ids:
                    continue
                seen_track_ids.add(track.id)
                appended_tracks.append(track)
        merged_track_ids = [
            track.id for track in (*target_tracks, *appended_tracks)
        ]
        return self.replace_tracks(
            target_playlist_id,
            merged_track_ids,
        )

    def remove_track_at(
        self,
        playlist_id: str,
        position: int,
    ) -> list[Track]:
        self._get_playlist_or_raise(playlist_id)
        entries = list(
            self.store.list_playlist_entries(playlist_id)
        )

        if position < 0 or position >= len(entries):
            raise ValueError(
                f"Playlist position does not exist: {position}"
            )

        del entries[position]

        normalized_entries = tuple(
            PlaylistEntry(
                playlist_id=playlist_id,
                track_id=entry.track_id,
                position=index,
            )
            for index, entry in enumerate(entries)
        )
        self.store.replace_playlist_entries(
            playlist_id,
            normalized_entries,
        )

        return self.get_playlist_tracks(playlist_id)

    def remove_track(
        self,
        playlist_id: str,
        track_id: str,
    ) -> list[Track]:
        """Remove the first occurrence of a track from a playlist."""

        self._get_playlist_or_raise(playlist_id)
        normalized_track_id = track_id.strip()
        entries = list(self.store.list_playlist_entries(playlist_id))
        position = next(
            (
                index
                for index, entry in enumerate(entries)
                if entry.track_id == normalized_track_id
            ),
            None,
        )
        if position is None:
            raise ValueError("Track is not in this playlist")
        return self.remove_track_at(playlist_id, position)

    def _get_playlist_or_raise(
        self,
        playlist_id: str,
    ) -> Playlist:
        playlist = self.store.get_playlist(playlist_id)

        if playlist is None:
            raise ValueError(
                f"Playlist does not exist: {playlist_id}"
            )

        return playlist

    def _update_cover_path(
        self,
        playlist: Playlist,
        destination: Path,
    ) -> Playlist:
        previous_cover = (
            Path(playlist.cover_path)
            if playlist.cover_path
            else None
        )
        updated_playlist = replace(
            playlist,
            cover_path=str(destination.resolve()),
        )
        self.store.update_playlist(updated_playlist)

        if (
            previous_cover is not None
            and previous_cover != destination
            and previous_cover.parent.resolve()
            == PLAYLIST_COVERS_DIR.resolve()
            and previous_cover.exists()
        ):
            previous_cover.unlink()

        return updated_playlist

    @staticmethod
    def _remote_cover_suffix(
        url: str,
        content_type: str,
        image_data: bytes,
    ) -> str:
        normalized_type = content_type.lower()
        if normalized_type == "image/png" or image_data.startswith(b"\x89PNG"):
            return ".png"
        if normalized_type == "image/webp" or image_data[:4] == b"RIFF":
            return ".webp"
        if normalized_type in {"image/jpeg", "image/jpg"} or image_data.startswith(b"\xff\xd8\xff"):
            return ".jpg"

        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in SUPPORTED_COVER_EXTENSIONS:
            return suffix

        raise ValueError("Playlist cover URL did not return an image.")
