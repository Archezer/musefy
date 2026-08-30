from dataclasses import dataclass, field

from app.domain.models import Interaction, Track, User


@dataclass
class InMemoryMusicStore:
    tracks: dict[str, Track] = field(default_factory=dict)
    interactions: list[Interaction] = field(default_factory=list)
    users: dict[str, User] = field(default_factory=dict)

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
