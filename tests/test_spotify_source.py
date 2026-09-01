import io
import json

import pytest

import app.sources.spotify as spotify_source
from app.sources.spotify import SpotifyMetadataProvider


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_spotify_track_metadata_builds_youtube_query(monkeypatch) -> None:
    response = FakeResponse(
        json.dumps(
            {
                "title": "Antarctica",
                "author_name": "$uicideboy$",
            }
        ).encode()
    )

    def fake_urlopen(request, timeout):
        assert "open.spotify.com%2Ftrack" in request.full_url
        assert timeout == 10
        return response

    monkeypatch.setattr(
        spotify_source,
        "urlopen",
        fake_urlopen,
    )

    track = SpotifyMetadataProvider().get_track(
        "https://open.spotify.com/track/track-1"
    )

    assert track.title == "Antarctica"
    assert track.artist == "$uicideboy$"
    assert track.search_query == "$uicideboy$ - Antarctica"


def test_spotify_provider_rejects_non_track_url() -> None:
    with pytest.raises(ValueError, match="Spotify track"):
        SpotifyMetadataProvider().get_track(
            "https://open.spotify.com/playlist/playlist-1"
        )


def test_spotify_provider_detects_track_and_playlist_urls() -> None:
    provider = SpotifyMetadataProvider()

    assert provider.get_resource_type(
        "https://open.spotify.com/track/track-1"
    ) == "track"
    assert provider.get_resource_type(
        "https://open.spotify.com/playlist/playlist-1"
    ) == "playlist"


def test_spotify_playlist_reads_tracks_with_client_credentials(
    monkeypatch,
) -> None:
    responses = [
        FakeResponse(
            json.dumps(
                {
                    "access_token": "access-token",
                    "expires_in": 3600,
                }
            ).encode()
        ),
        FakeResponse(json.dumps({"name": "Night drive"}).encode()),
        FakeResponse(
            json.dumps(
                {
                    "items": [
                        {
                            "is_local": False,
                            "track": {
                                "type": "track",
                                "name": "First track",
                                "artists": [{"name": "Artist One"}],
                            },
                        },
                        {
                            "is_local": True,
                            "track": {
                                "type": "track",
                                "name": "Local track",
                                "artists": [{"name": "Local artist"}],
                            },
                        },
                    ],
                    "next": None,
                    "total": 2,
                }
            ).encode()
        ),
    ]

    def fake_urlopen(request, timeout):
        assert timeout == 10.0
        return responses.pop(0)

    monkeypatch.setattr(spotify_source, "urlopen", fake_urlopen)

    playlist = SpotifyMetadataProvider(
        client_id="client-id",
        client_secret="client-secret",
    ).get_playlist(
        "https://open.spotify.com/playlist/playlist-1"
    )

    assert playlist.name == "Night drive"
    assert playlist.tracks == (
        spotify_source.SpotifyTrack(
            title="First track",
            artist="Artist One",
        ),
    )
    assert responses == []
