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
