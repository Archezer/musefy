from datetime import UTC, datetime

from app.domain.models import User
from app.services.spotify_favorites_import import (
    SpotifyFavoritesImportService,
)
from app.sources.spotify import SpotifyTrack
from app.storage.memory import InMemoryMusicStore


class FakeSpotifyMetadataProvider:
    def __init__(self, tracks: tuple[SpotifyTrack, ...]) -> None:
        self.tracks = tracks

    def get_saved_tracks(self) -> tuple[SpotifyTrack, ...]:
        return self.tracks


def make_service(
    tracks: tuple[SpotifyTrack, ...],
) -> tuple[InMemoryMusicStore, SpotifyFavoritesImportService]:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test user"))
    return store, SpotifyFavoritesImportService(
        store,
        FakeSpotifyMetadataProvider(tracks),
    )


def test_import_favorites_stores_metadata_without_interactions() -> None:
    tracks = (
        SpotifyTrack(
            "First",
            "Artist",
            spotify_id="spotify-1",
            album="Album",
            duration_ms=123_000,
            added_at="2026-09-01T10:00:00Z",
            isrc="US-AAA-26-00001",
        ),
        SpotifyTrack(
            "Second",
            "Other Artist",
            spotify_id="spotify-2",
            duration_ms=180_000,
        ),
    )
    store, service = make_service(tracks)

    result = service.import_all("user-1")

    assert result.fetched == 2
    assert result.imported_tracks == 2
    assert result.updated_tracks == 0
    assert result.active_preferences == 2
    assert result.deactivated_preferences == 0
    assert store.list_interactions() == []

    imported_tracks = store.list_tracks()
    assert {track.source_id for track in imported_tracks} == {
        "spotify-1",
        "spotify-2",
    }
    assert all(track.source == "spotify_favorite" for track in imported_tracks)
    assert all(track.local_path is None for track in imported_tracks)

    favorites = store.list_spotify_favorites("user-1", active_only=True)
    assert len(favorites) == 2
    assert favorites[0].spotify_id == "spotify-1"
    assert favorites[0].album == "Album"
    assert favorites[0].isrc == "US-AAA-26-00001"
    assert favorites[0].added_at == datetime(
        2026,
        9,
        1,
        10,
        tzinfo=UTC,
    )


def test_import_favorites_is_idempotent_and_tracks_removals() -> None:
    initial_tracks = (
        SpotifyTrack("First", "Artist", spotify_id="spotify-1"),
        SpotifyTrack("Second", "Artist", spotify_id="spotify-2"),
    )
    store, service = make_service(initial_tracks)

    first = service.import_all("user-1")
    second = service.import_all("user-1")

    assert first.imported_tracks == 2
    assert second.imported_tracks == 0
    assert second.updated_tracks == 0
    assert len(store.list_tracks()) == 2
    assert len(store.list_spotify_favorites("user-1", active_only=True)) == 2

    service.provider.tracks = (initial_tracks[0],)
    third = service.import_all("user-1")

    assert third.deactivated_preferences == 1
    assert [
        favorite.spotify_id
        for favorite in store.list_spotify_favorites(
            "user-1",
            active_only=True,
        )
    ] == ["spotify-1"]
    assert {
        favorite.spotify_id
        for favorite in store.list_spotify_favorites("user-1")
    } == {"spotify-1", "spotify-2"}
