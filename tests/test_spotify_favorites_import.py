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
        self.search_calls = 0
        self.download_calls = 0

    def get_saved_tracks(self) -> tuple[SpotifyTrack, ...]:
        return self.tracks

    def search(self, *_args, **_kwargs):
        self.search_calls += 1
        raise AssertionError("Metadata import must not search for audio")

    def download(self, *_args, **_kwargs):
        self.download_calls += 1
        raise AssertionError("Metadata import must not download audio")


def make_service(
    tracks: tuple[SpotifyTrack, ...],
) -> tuple[
    InMemoryMusicStore,
    SpotifyFavoritesImportService,
    FakeSpotifyMetadataProvider,
]:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test user"))
    provider = FakeSpotifyMetadataProvider(tracks)
    return store, SpotifyFavoritesImportService(store, provider), provider


def test_import_favorites_stores_metadata_without_tracks_or_interactions() -> None:
    tracks = (
        SpotifyTrack(
            "First",
            "Artist",
            spotify_id="spotify-1",
            album="Album",
            duration_ms=123_000,
            added_at="2026-09-01T10:00:00Z",
            isrc="US-AAA-26-00001",
            cover_url="https://i.scdn.co/image/cover-1",
        ),
        SpotifyTrack(
            "Second",
            "Other Artist",
            spotify_id="spotify-2",
            duration_ms=180_000,
        ),
    )
    store, service, provider = make_service(tracks)

    result = service.import_all("user-1")

    assert result.fetched == 2
    assert result.imported_metadata == 2
    assert result.updated_metadata == 0
    assert result.skipped_tracks == 0
    assert store.list_tracks() == []
    assert store.list_interactions() == []
    assert store.list_spotify_favorites("user-1") == []
    assert provider.search_calls == 0
    assert provider.download_calls == 0

    metadata = store.list_spotify_track_metadata()
    assert [item.spotify_id for item in metadata] == [
        "spotify-1",
        "spotify-2",
    ]
    assert metadata[0].title == "First"
    assert metadata[0].artist == "Artist"
    assert metadata[0].album == "Album"
    assert metadata[0].duration_ms == 123_000
    assert metadata[0].isrc == "US-AAA-26-00001"
    assert metadata[0].cover_url == "https://i.scdn.co/image/cover-1"
    assert metadata[0].added_at == datetime(
        2026,
        9,
        1,
        10,
        tzinfo=UTC,
    )


def test_repeat_import_updates_metadata_without_duplicates() -> None:
    initial_tracks = (
        SpotifyTrack(
            "First",
            "Artist",
            spotify_id="spotify-1",
            album="Old album",
        ),
        SpotifyTrack("Second", "Artist", spotify_id="spotify-2"),
    )
    store, service, _provider = make_service(initial_tracks)

    first = service.import_all("user-1")
    second = service.import_all("user-1")

    assert first.imported_metadata == 2
    assert second.imported_metadata == 0
    assert second.updated_metadata == 0
    assert len(store.list_spotify_track_metadata()) == 2
    assert store.list_tracks() == []

    service.provider.tracks = (
        SpotifyTrack(
            "First",
            "Artist",
            spotify_id="spotify-1",
            album="New album",
        ),
        initial_tracks[1],
    )
    third = service.import_all("user-1")

    assert third.imported_metadata == 0
    assert third.updated_metadata == 1
    assert len(store.list_spotify_track_metadata()) == 2
    assert (
        store.get_spotify_track_metadata("spotify-1").album
        == "New album"
    )
