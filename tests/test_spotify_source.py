import io
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

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
    assert provider.get_resource_type(
        "https://open.spotify.com/album/album-1"
    ) == "album"


def test_public_spotify_playlist_is_paginated(monkeypatch) -> None:
    first_item = {
        "itemV2": {
            "data": {
                "__typename": "Track",
                "name": "Exorcism",
                "artists": {
                    "items": [
                        {
                            "profile": {
                                "name": "Sidewalks and Skeletons"
                            }
                        }
                    ]
                },
            }
        }
    }
    last_item = {
        "itemV2": {
            "data": {
                "__typename": "Track",
                "name": "Blood",
                "artists": {
                    "items": [{"profile": {"name": "SET"}}]
                },
            }
        }
    }
    responses = [
        {"accessToken": "anonymous-token"},
        {
            "data": {
                "playlistV2": {
                    "name": "Witch House",
                    "content": {
                        "totalCount": 101,
                        "items": [first_item] * 100,
                    },
                }
            }
        },
        {
            "data": {
                "playlistV2": {
                    "name": "Witch House",
                    "content": {
                        "totalCount": 101,
                        "items": [last_item],
                    },
                }
            }
        },
    ]
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        assert timeout == 10.0
        return FakeResponse(json.dumps(responses.pop(0)).encode())

    monkeypatch.setattr(spotify_source, "urlopen", fake_urlopen)

    playlist = SpotifyMetadataProvider().get_playlist(
        "https://open.spotify.com/playlist/playlist-1"
    )

    assert playlist.name == "Witch House"
    assert len(playlist.tracks) == 101
    assert playlist.tracks[0].search_query == (
        "Sidewalks and Skeletons - Exorcism"
    )
    assert playlist.tracks[-1].search_query == "SET - Blood"
    assert "get_access_token" in calls[0].full_url
    assert "/pathfinder/v2/query" in calls[1].full_url
    first_query = parse_qs(urlparse(calls[1].full_url).query)
    second_query = parse_qs(urlparse(calls[2].full_url).query)
    assert json.loads(first_query["variables"][0])["offset"] == 0
    assert json.loads(second_query["variables"][0])["offset"] == 100


def test_public_spotify_album_is_paginated(monkeypatch) -> None:
    first_track = {
        "track": {
            "type": "track",
            "name": "First track",
            "artists": [{"name": "Artist One"}],
        }
    }
    second_track = {
        "track": {
            "type": "track",
            "name": "Second track",
            "artists": [{"name": "Artist Two"}],
        }
    }
    responses = [
        {"accessToken": "anonymous-token"},
        {
            "data": {
                "albumUnion": {
                    "name": "Long album",
                    "tracksV2": {
                        "totalCount": 101,
                        "items": [first_track] * 100,
                    },
                }
            }
        },
        {
            "data": {
                "albumUnion": {
                    "name": "Long album",
                    "tracksV2": {
                        "totalCount": 101,
                        "items": [second_track],
                    },
                }
            }
        },
    ]
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request)
        assert timeout == 10.0
        return FakeResponse(json.dumps(responses.pop(0)).encode())

    monkeypatch.setattr(spotify_source, "urlopen", fake_urlopen)

    album = SpotifyMetadataProvider().get_album(
        "https://open.spotify.com/album/album-1"
    )

    assert album.name == "Long album"
    assert len(album.tracks) == 101
    assert album.tracks[0].search_query == "Artist One - First track"
    assert album.tracks[-1].search_query == "Artist Two - Second track"
    assert "/pathfinder/v2/query" in calls[1].full_url
    assert "getAlbum" in calls[1].full_url
    first_query = parse_qs(urlparse(calls[1].full_url).query)
    second_query = parse_qs(urlparse(calls[2].full_url).query)
    assert json.loads(first_query["variables"][0])["offset"] == 0
    assert json.loads(second_query["variables"][0])["offset"] == 100


class FakeSpotifyOAuthClient:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, dict[str, str]]] = []

    def get_json(
        self,
        path: str,
        params: dict[str, str],
    ) -> dict:
        self.requests.append((path, params))
        return self.responses.pop(0)


def test_authenticated_spotify_playlist_is_paginated() -> None:
    oauth_client = FakeSpotifyOAuthClient(
        [
            {"name": "Long playlist"},
            {
                "items": [
                    {
                        "is_local": False,
                        "item": {
                            "type": "track",
                            "name": "First track",
                            "artists": [{"name": "Artist One"}],
                        },
                    }
                ],
                "next": "https://api.spotify.com/next",
            },
            {
                "items": [
                    {
                        "is_local": False,
                        "item": {
                            "type": "track",
                            "name": "Second track",
                            "artists": [{"name": "Artist Two"}],
                        },
                    }
                ],
                "next": None,
            },
        ]
    )

    playlist = SpotifyMetadataProvider(
        oauth_client=oauth_client,
    ).get_authenticated_playlist(
        "https://open.spotify.com/playlist/playlist-1"
    )

    assert playlist.name == "Long playlist"
    assert [track.search_query for track in playlist.tracks] == [
        "Artist One - First track",
        "Artist Two - Second track",
    ]
    assert oauth_client.requests[1][1]["offset"] == "0"
    assert oauth_client.requests[2][1]["offset"] == "1"


def test_saved_spotify_tracks_keep_identity_and_added_at() -> None:
    oauth_client = FakeSpotifyOAuthClient(
        [
            {
                "items": [
                    {
                        "added_at": "2026-09-04T10:00:00Z",
                        "track": {
                            "id": "track-1",
                            "type": "track",
                            "name": "Antarctica",
                            "artists": [{"name": "$uicideboy$"}],
                            "album": {"name": "I Want to Die in New Orleans"},
                            "duration_ms": 123000,
                            "external_ids": {"isrc": "US-AAA-1"},
                        },
                    }
                ],
                "next": None,
            }
        ]
    )

    tracks = SpotifyMetadataProvider(
        oauth_client=oauth_client,
    ).get_saved_tracks()

    assert len(tracks) == 1
    assert tracks[0].spotify_id == "track-1"
    assert tracks[0].added_at == "2026-09-04T10:00:00Z"
    assert tracks[0].album == "I Want to Die in New Orleans"
    assert tracks[0].duration_ms == 123000
    assert tracks[0].isrc == "US-AAA-1"
    assert oauth_client.requests[0][0] == "/v1/me/tracks"
    assert oauth_client.requests[0][1]["limit"] == "50"


def test_saved_spotify_tracks_stop_paging_at_incremental_cursor() -> None:
    oauth_client = FakeSpotifyOAuthClient(
        [
            {
                "items": [
                    {
                        "added_at": "2026-09-04T12:00:00Z",
                        "track": {
                            "id": "new-track",
                            "type": "track",
                            "name": "New track",
                            "artists": [{"name": "Artist"}],
                        },
                    },
                    {
                        "added_at": "2026-09-04T10:00:00Z",
                        "track": {
                            "id": "old-track",
                            "type": "track",
                            "name": "Old track",
                            "artists": [{"name": "Artist"}],
                        },
                    },
                ],
                "next": "https://api.spotify.com/next",
            },
            {
                "items": [],
                "next": None,
            },
        ]
    )

    tracks = SpotifyMetadataProvider(
        oauth_client=oauth_client,
    ).get_saved_tracks_since(
        datetime(2026, 9, 4, 11, tzinfo=UTC),
    )

    assert [track.spotify_id for track in tracks] == ["new-track"]
    assert len(oauth_client.requests) == 1
