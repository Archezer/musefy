from collections.abc import Iterable
from typing import Protocol

from app.domain.models import (
    Interaction,
    Playlist,
    PlaylistEntry,
    Track,
    User,
)


class MusicStore(Protocol):

    def add_user(self, user: User) -> None:
        ...

    def get_user(self, user_id: str) -> User | None:
        ...

    def add_track(self, track: Track) -> None:
        ...

    def get_track(self, track_id: str) -> Track | None:
        ...

    def get_track_by_source(
        self,
        source: str,
        source_id: str,
    ) -> Track | None:
        ...

    def update_track(self, track: Track) -> None:
        ...

    def delete_track(self, track_id: str) -> None:
        ...

    def merge_track_references(
        self,
        duplicate_track_id: str,
        survivor_track_id: str,
    ) -> None:
        ...

    def add_playlist(self, playlist: Playlist) -> None:
        ...

    def get_playlist(self, playlist_id: str) -> Playlist | None:
        ...

    def update_playlist(self, playlist: Playlist) -> None:
        ...

    def delete_playlist(self, playlist_id: str) -> None:
        ...

    def list_playlists(self) -> Iterable[Playlist]:
        ...

    def list_playlist_entries(
        self,
        playlist_id: str,
    ) -> Iterable[PlaylistEntry]:
        ...

    def replace_playlist_entries(
        self,
        playlist_id: str,
        entries: Iterable[PlaylistEntry],
    ) -> None:
        ...

    def add_interaction(self, interaction: Interaction) -> None:
        ...

    def list_tracks(self) -> Iterable[Track]:
        ...

    def list_interactions(self) -> Iterable[Interaction]:
        ...
