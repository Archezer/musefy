import base64
import json
import os
import time
from dataclasses import dataclass
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

SUPPORTED_SPOTIFY_HOSTS = {
    "open.spotify.com",
    "play.spotify.com",
    "spotify.link",
}


@dataclass(frozen=True)
class SpotifyTrack:
    title: str
    artist: str | None

    @property
    def search_query(self) -> str:
        if self.artist:
            return f"{self.artist} - {self.title}"

        return self.title


@dataclass(frozen=True)
class SpotifyPlaylist:
    name: str
    tracks: tuple[SpotifyTrack, ...]


class SpotifyMetadataProvider:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Spotify timeout must be positive.")

        self.client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = (
            client_secret or os.getenv("SPOTIFY_CLIENT_SECRET")
        )
        self.timeout = timeout
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    def get_track(self, url: str) -> SpotifyTrack:
        normalized_url = url.strip()
        _validate_spotify_url(normalized_url, expected_type="track")

        endpoint = (
            "https://open.spotify.com/oembed?"
            f"{urlencode({'url': normalized_url})}"
        )
        request = Request(
            endpoint,
            headers={"User-Agent": "music-recommendation-system/1.0"},
        )

        with urlopen(request, timeout=10) as response:
            payload = json.load(response)

        title = str(payload.get("title") or "").strip()
        artist = str(payload.get("author_name") or "").strip()

        if not title:
            raise RuntimeError(
                "Spotify did not return track metadata."
            )

        return SpotifyTrack(
            title=title,
            artist=artist or None,
        )

    def get_resource_type(self, url: str) -> str:
        normalized_url = self._canonical_url(url)
        parsed_url = urlparse(normalized_url)
        parts = _path_parts(parsed_url)

        if len(parts) < 2:
            raise ValueError(
                "URL must point to a Spotify track or playlist."
            )

        resource_type = parts[0].casefold()
        if resource_type not in {"track", "playlist"}:
            raise ValueError(
                "URL must point to a Spotify track or playlist."
            )

        _validate_spotify_url(
            normalized_url,
            expected_type=resource_type,
        )
        return resource_type

    def get_playlist(self, url: str) -> SpotifyPlaylist:
        normalized_url = self._canonical_url(url)
        _validate_spotify_url(
            normalized_url,
            expected_type="playlist",
        )
        playlist_id = _resource_id(normalized_url, "playlist")
        encoded_playlist_id = quote(playlist_id, safe="")

        playlist_payload = self._api_get(
            f"/v1/playlists/{encoded_playlist_id}",
            {"fields": "name"},
        )
        playlist_name = str(
            playlist_payload.get("name") or "Spotify playlist"
        ).strip()

        tracks: list[SpotifyTrack] = []
        offset = 0
        while True:
            payload = self._api_get(
                f"/v1/playlists/{encoded_playlist_id}/tracks",
                {
                    "limit": "100",
                    "offset": str(offset),
                    "fields": (
                        "items(is_local,track(name,artists(name),type)),"
                        "next,total"
                    ),
                },
            )
            items = payload.get("items") or []

            for item in items:
                spotify_track = _parse_playlist_track(item)
                if spotify_track is not None:
                    tracks.append(spotify_track)

            next_url = payload.get("next")
            if not next_url or not items:
                break

            offset += len(items)

        return SpotifyPlaylist(
            name=playlist_name,
            tracks=tuple(tracks),
        )

    def _canonical_url(self, url: str) -> str:
        normalized_url = url.strip()
        parsed_url = urlparse(normalized_url)
        hostname = (parsed_url.hostname or "").casefold()

        if hostname != "spotify.link":
            return normalized_url

        request = Request(
            normalized_url,
            headers={"User-Agent": "music-recommendation-system/1.0"},
        )
        with urlopen(request, timeout=self.timeout) as response:
            return response.geturl()

    def _api_get(
        self,
        path: str,
        params: dict[str, str],
    ) -> dict:
        token = self._get_access_token()
        query = urlencode(params)
        endpoint = f"https://api.spotify.com{path}?{query}"
        request = Request(
            endpoint,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "music-recommendation-system/1.0",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Spotify API request failed: {details or error.reason}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Could not connect to the Spotify Web API."
            ) from error

        if not isinstance(payload, dict):
            raise TypeError("Spotify API returned an invalid response.")

        return payload

    def _get_access_token(self) -> str:
        now = time.monotonic()
        if (
            self._access_token is not None
            and now < self._token_expires_at
        ):
            return self._access_token

        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "Spotify playlist import requires "
                "SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET."
            )

        credentials = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        request = Request(
            "https://accounts.spotify.com/api/token",
            data=urlencode(
                {"grant_type": "client_credentials"}
            ).encode(),
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "music-recommendation-system/1.0",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Spotify authentication failed: "
                f"{details or error.reason}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Could not connect to Spotify authentication."
            ) from error

        token = str(payload.get("access_token") or "").strip()
        if not token:
            raise RuntimeError(
                "Spotify authentication returned no access token."
            )

        expires_in = float(payload.get("expires_in") or 3600.0)
        self._access_token = token
        self._token_expires_at = now + max(30.0, expires_in - 30.0)
        return token


def _validate_spotify_url(url: str, *, expected_type: str) -> None:
    parsed_url = urlparse(url)
    hostname = (parsed_url.hostname or "").lower()

    if (
        parsed_url.scheme not in {"http", "https"}
        or hostname not in SUPPORTED_SPOTIFY_HOSTS
    ):
        raise ValueError(
            "URL must be a valid Spotify track or playlist URL."
        )

    if hostname == "spotify.link":
        return

    path_parts = _path_parts(parsed_url)
    if len(path_parts) < 2 or path_parts[0].casefold() != expected_type:
        raise ValueError(
            f"URL must point to a Spotify {expected_type}."
        )


def _path_parts(parsed_url) -> list[str]:
    return [part for part in parsed_url.path.split("/") if part]


def _resource_id(url: str, expected_type: str) -> str:
    parsed_url = urlparse(url)
    parts = _path_parts(parsed_url)
    if len(parts) < 2 or parts[0].casefold() != expected_type:
        raise ValueError(
            f"URL must point to a Spotify {expected_type}."
        )

    return parts[1]


def _parse_playlist_track(payload: object) -> SpotifyTrack | None:
    if not isinstance(payload, dict):
        return None

    if payload.get("is_local"):
        return None

    track = payload.get("track") or payload
    if not isinstance(track, dict):
        return None

    if track.get("type") not in {
        None,
        "track",
    }:
        return None

    title = str(track.get("name") or "").strip()
    artists = track.get("artists") or []
    artist_names = [
        str(artist.get("name") or "").strip()
        for artist in artists
        if isinstance(artist, dict) and artist.get("name")
    ]

    if not title:
        return None

    return SpotifyTrack(
        title=title,
        artist=", ".join(artist_names) or None,
    )
