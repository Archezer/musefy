from collections.abc import Iterable
from typing import Protocol

from app.domain.models import (
    Interaction,
    Playlist,
    PlaylistEntry,
    RecommendationImpression,
    SpotifyFavorite,
    SpotifyListeningStats,
    SpotifyTrackMetadata,
    Track,
    User,
)


class MusicStore(Protocol):

    def add_user(self, user: User) -> None:
        ...

    def get_user(self, user_id: str) -> User | None:
        ...

    def list_users(self) -> Iterable[User]:
        ...

    def upsert_spotify_favorite(
        self,
        favorite: SpotifyFavorite,
    ) -> None:
        ...

    def list_spotify_favorites(
        self,
        user_id: str,
        *,
        active_only: bool = False,
    ) -> Iterable[SpotifyFavorite]:
        ...

    def get_spotify_track_metadata(
        self,
        spotify_id: str,
    ) -> SpotifyTrackMetadata | None:
        ...

    def upsert_spotify_track_metadata(
        self,
        metadata: SpotifyTrackMetadata,
    ) -> None:
        ...

    def list_spotify_track_metadata(self) -> Iterable[SpotifyTrackMetadata]:
        ...

    def get_spotify_listening_stats(
        self,
        spotify_id: str,
    ) -> SpotifyListeningStats | None:
        ...

    def upsert_spotify_listening_stats(
        self,
        stats: SpotifyListeningStats,
    ) -> None:
        ...

    def list_spotify_listening_stats(self) -> Iterable[SpotifyListeningStats]:
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

    def delete_interactions(
        self,
        user_id: str,
        track_id: str,
        interaction_type: str,
    ) -> int:
        ...

    def compact_preference_interactions(self) -> int:
        """Remove obsolete duplicate like/dislike records."""
        ...

    def list_tracks(self) -> Iterable[Track]:
        ...

    def list_interactions(
        self,
        user_id: str | None = None,
    ) -> Iterable[Interaction]:
        ...

    def add_recommendation_impression(
        self,
        impression: RecommendationImpression,
    ) -> None:
        ...

    def list_recommendation_impressions(
        self,
        user_id: str | None = None,
    ) -> Iterable[RecommendationImpression]:
        ...
