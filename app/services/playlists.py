from collections.abc import Iterable
from dataclasses import replace
from uuid import uuid4

from app.domain.models import Playlist, PlaylistEntry, Track
from app.storage.protocols import MusicStore


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
        entries.append(
            PlaylistEntry(
                playlist_id=playlist_id,
                track_id=track_id,
                position=len(entries),
            )
        )
        self.store.replace_playlist_entries(
            playlist_id,
            entries,
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
