from app.services.spotify_fav_sync import SpotifyFavSyncService
from app.sources.spotify import SpotifyTrack


class FakeSpotifyProvider:
    def __init__(self, tracks: tuple[SpotifyTrack, ...]) -> None:
        self.tracks = tracks
        self.calls = 0

    def get_saved_tracks(self) -> tuple[SpotifyTrack, ...]:
        self.calls += 1
        return self.tracks


def test_favorite_sync_ignores_tracks_saved_before_enable(tmp_path) -> None:
    provider = FakeSpotifyProvider(
        (
            SpotifyTrack(
                "Old",
                "Artist",
                spotify_id="old",
                added_at="2026-09-03T10:00:00Z",
            ),
        )
    )
    service = SpotifyFavSyncService(
        provider,
        state_path=tmp_path / "spotify-sync.json",
    )

    service.set_enabled(True)
    result = service.sync_new_saved_tracks()

    assert result.new_tracks == ()
    assert provider.calls == 1


def test_favorite_sync_returns_each_new_track_once(tmp_path) -> None:
    provider = FakeSpotifyProvider(())
    service = SpotifyFavSyncService(
        provider,
        state_path=tmp_path / "spotify-sync.json",
    )
    service.set_enabled(True)

    provider.tracks = (
        SpotifyTrack(
            "New",
            "Artist",
            spotify_id="new",
            added_at="2999-01-01T00:00:00Z",
        ),
    )
    first = service.sync_new_saved_tracks()
    second = service.sync_new_saved_tracks()

    assert [track.spotify_id for track in first.new_tracks] == ["new"]
    assert second.new_tracks == ()


def test_sync_all_returns_every_saved_track(tmp_path) -> None:
    tracks = (
        SpotifyTrack("First", "Artist", spotify_id="first"),
        SpotifyTrack("Second", "Artist", spotify_id="second"),
    )
    provider = FakeSpotifyProvider(tracks)
    service = SpotifyFavSyncService(
        provider,
        state_path=tmp_path / "spotify-sync.json",
    )

    result = service.sync_all_saved_tracks()

    assert result.new_tracks == tracks
    assert provider.calls == 1
