from dataclasses import dataclass, field

from app.domain.models import (
    Interaction,
    Playlist,
    PlaylistEntry,
    Track,
    User,
)


@dataclass
class InMemoryMusicStore:
    tracks: dict[str, Track] = field(default_factory=dict)
    interactions: list[Interaction] = field(default_factory=list)
    users: dict[str, User] = field(default_factory=dict)
    playlists: dict[str, Playlist] = field(default_factory=dict)
    playlist_entries: dict[str, list[PlaylistEntry]] = field(
        default_factory=dict
    )

    def add_user(self, user: User) -> None:
        if user.id in self.users:
            raise ValueError(
                f"User already exists: {user.id}"
            )
        self.users[user.id] = user


    def get_user(self, user_id: str) -> User | None:
        return self.users.get(user_id)

    def add_track(self, track: Track) -> None:
        if track.id in self.tracks:
            raise ValueError(f"Track with ID {track.id} already exists")
        
        self.tracks[track.id] = track

    def get_track(self, track_id: str) -> Track | None:
        return self.tracks.get(track_id)

    def update_track(self, track: Track) -> None:
        if track.id not in self.tracks:
            raise ValueError(
                f"Track does not exist: {track.id}"
            )

        self.tracks[track.id] = track

    def delete_track(self, track_id: str) -> None:
        if track_id not in self.tracks:
            raise ValueError(
                f"Track does not exist: {track_id}"
            )

        del self.tracks[track_id]
        self.interactions = [
            interaction
            for interaction in self.interactions
            if interaction.track_id != track_id
        ]
        for playlist_id, entries in self.playlist_entries.items():
            remaining_entries = [
                entry
                for entry in entries
                if entry.track_id != track_id
            ]
            self.playlist_entries[playlist_id] = [
                PlaylistEntry(
                    playlist_id=playlist_id,
                    track_id=entry.track_id,
                    position=position,
                )
                for position, entry in enumerate(remaining_entries)
            ]

    def add_playlist(self, playlist: Playlist) -> None:
        if playlist.id in self.playlists:
            raise ValueError(
                f"Playlist already exists: {playlist.id}"
            )

        self.playlists[playlist.id] = playlist
        self.playlist_entries[playlist.id] = []

    def get_playlist(self, playlist_id: str) -> Playlist | None:
        return self.playlists.get(playlist_id)

    def update_playlist(self, playlist: Playlist) -> None:
        if playlist.id not in self.playlists:
            raise ValueError(
                f"Playlist does not exist: {playlist.id}"
            )

        self.playlists[playlist.id] = playlist

    def delete_playlist(self, playlist_id: str) -> None:
        if playlist_id not in self.playlists:
            raise ValueError(
                f"Playlist does not exist: {playlist_id}"
            )

        del self.playlists[playlist_id]
        del self.playlist_entries[playlist_id]

    def list_playlists(self) -> list[Playlist]:
        return list(self.playlists.values())

    def list_playlist_entries(
        self,
        playlist_id: str,
    ) -> list[PlaylistEntry]:
        return list(self.playlist_entries.get(playlist_id, []))

    def replace_playlist_entries(
        self,
        playlist_id: str,
        entries: list[PlaylistEntry],
    ) -> None:
        if playlist_id not in self.playlists:
            raise ValueError(
                f"Playlist does not exist: {playlist_id}"
            )

        expected_positions = list(range(len(entries)))

        if [entry.position for entry in entries] != expected_positions:
            raise ValueError(
                "Playlist entry positions must be consecutive"
            )

        for entry in entries:
            if entry.playlist_id != playlist_id:
                raise ValueError(
                    "Playlist entries must belong to one playlist"
                )

            if entry.track_id not in self.tracks:
                raise ValueError(
                    "Playlist entries must reference existing tracks"
                )

        self.playlist_entries[playlist_id] = list(entries)

    def add_interaction(self, interaction: Interaction) -> None:
        if interaction.track_id not in self.tracks:
            raise ValueError(
                f"Cannot create interaction for unknown track: "
                f"{interaction.track_id}"
            )

        self.interactions.append(interaction)

    def list_tracks(self) -> list[Track]:
        return list(self.tracks.values())

    def list_interactions(self) -> list[Interaction]:
        return list(self.interactions)
