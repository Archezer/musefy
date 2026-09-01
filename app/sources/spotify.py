import json
from dataclasses import dataclass
from urllib.parse import urlencode, urlparse
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


class SpotifyMetadataProvider:
    def get_track(self, url: str) -> SpotifyTrack:
        normalized_url = url.strip()
        _validate_spotify_track_url(normalized_url)

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


def _validate_spotify_track_url(url: str) -> None:
    parsed_url = urlparse(url)
    hostname = (parsed_url.hostname or "").lower()

    if (
        parsed_url.scheme not in {"http", "https"}
        or hostname not in SUPPORTED_SPOTIFY_HOSTS
    ):
        raise ValueError(
            "URL must be a valid Spotify track URL."
        )

    if hostname == "spotify.link":
        return

    path_parts = [
        part
        for part in parsed_url.path.split("/")
        if part
    ]

    if len(path_parts) < 2 or path_parts[0].lower() != "track":
        raise ValueError(
            "URL must point to a Spotify track."
        )
