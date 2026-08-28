from collections.abc import Iterable
from typing import Protocol

from app.domain.models import Interaction, Track


class MusicStore(Protocol):
    def add_track(self, track: Track) -> None:
        ...

    def get_track(self, track_id: str) -> Track | None:
        ...

    def add_interaction(self, interaction: Interaction) -> None:
        ...

    def list_tracks(self) -> Iterable[Track]:
        ...

    def list_interactions(self) -> Iterable[Interaction]:
        ...
