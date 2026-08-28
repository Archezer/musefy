from dataclasses import dataclass, field

from app.domain.models import Interaction, Track


@dataclass
class InMemoryMusicStore:
    tracks: dict[str, Track] = field(default_factory=dict)
    interactions: list[Interaction] = field(default_factory=list)

    def add_track(self, track: Track) -> None:
        if track.id in self.tracks:
            raise ValueError(f"Track with ID {track.id} already exists")
        
        self.tracks[track.id] = track

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
