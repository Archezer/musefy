import json

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


def test_favorite_sync_state_survives_service_restart(tmp_path) -> None:
    track = SpotifyTrack(
        "New",
        "Artist",
        spotify_id="new",
        added_at="2999-01-01T00:00:00Z",
    )
    provider = FakeSpotifyProvider((track,))
    state_path = tmp_path / "spotify-sync.json"

    first_service = SpotifyFavSyncService(
        provider,
        state_path=state_path,
    )
    first_service.set_enabled(True)
    first = first_service.sync_new_saved_tracks()

    restarted_service = SpotifyFavSyncService(
        provider,
        state_path=state_path,
    )
    assert restarted_service.is_enabled()
    assert restarted_service.sync_new_saved_tracks().new_tracks == ()
    assert first.new_tracks == (track,)


def test_favorite_sync_uses_last_sync_cursor_after_restart(tmp_path) -> None:
    state_path = tmp_path / "spotify-sync.json"
    state_path.write_text(
        json.dumps(
            {
                "enabled": True,
                "tracking_since": "2999-01-01T00:00:00Z",
                "last_sync_at": "2999-01-02T00:00:00Z",
                "seen_track_ids": [],
            }
        ),
        encoding="utf-8",
    )
    provider = FakeSpotifyProvider(
        (
            SpotifyTrack(
                "Before cursor",
                "Artist",
                spotify_id="before",
                added_at="2999-01-01T12:00:00Z",
            ),
            SpotifyTrack(
                "After cursor",
                "Artist",
                spotify_id="after",
                added_at="2999-01-02T12:00:00Z",
            ),
        )
    )

    result = SpotifyFavSyncService(
        provider,
        state_path=state_path,
    ).sync_new_saved_tracks()

    assert [track.spotify_id for track in result.new_tracks] == ["after"]


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
