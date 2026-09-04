import base64
import hashlib
import json
import os
import secrets
import time
import webbrowser
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from app.storage.paths import DATA_DIR

SUPPORTED_SPOTIFY_HOSTS = {
    "open.spotify.com",
    "play.spotify.com",
    "spotify.link",
}
DEFAULT_SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
DEFAULT_SPOTIFY_TOKEN_PATH = DATA_DIR / "spotify_token.json"
SPOTIFY_OAUTH_SCOPES = (
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-library-read",
)
SPOTIFY_ANONYMOUS_TOKEN_ENDPOINT = (
    "https://open.spotify.com/get_access_token?"
    "reason=transport&productType=web_player"
)
SPOTIFY_PARTNER_PLAYLIST_QUERIES = (
    (
        "https://api-partner.spotify.com/pathfinder/v2/query",
        "bb67e0af06e8d6f52b531f97468ee4acd44cd0f82b988e15c2ea47b1148efc77",
    ),
    (
        "https://api-partner.spotify.com/pathfinder/v1/query",
        "91d4c2bc3e0cd1bc672281c4f1f59f43ff55ba726ca04a45810d99bd091f3f0e",
    ),
)
SPOTIFY_PARTNER_ALBUM_ENDPOINT = (
    "https://api-partner.spotify.com/pathfinder/v2/query"
)
SPOTIFY_PARTNER_ALBUM_QUERY_HASH = (
    "b9bfabef66ed756e5e13f68a942deb60bd4125ec1f1be8cc42769dc0259b4b10"
)
SPOTIFY_PARTNER_PAGE_SIZE = 100


@dataclass(frozen=True)
class SpotifyTrack:
    title: str
    artist: str | None
    spotify_id: str | None = None
    album: str | None = None
    duration_ms: int | None = None
    added_at: str | None = None
    isrc: str | None = None

    @property
    def search_query(self) -> str:
        if self.artist:
            return f"{self.artist} - {self.title}"

        return self.title


@dataclass(frozen=True)
class SpotifyPlaylist:
    name: str
    tracks: tuple[SpotifyTrack, ...]


class SpotifyOAuthClient:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        redirect_uri: str | None = None,
        token_path: Path | None = None,
        timeout: float = 10.0,
        callback_timeout: float = 300.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Spotify timeout must be positive.")
        if callback_timeout <= 0:
            raise ValueError(
                "Spotify callback timeout must be positive."
            )

        load_dotenv()
        self.client_id = client_id or os.getenv("SPOTIFY_CLIENT_ID")
        self.redirect_uri = (
            redirect_uri
            or os.getenv("SPOTIFY_REDIRECT_URI")
            or DEFAULT_SPOTIFY_REDIRECT_URI
        )
        self.token_path = token_path or Path(
            os.getenv(
                "SPOTIFY_TOKEN_PATH",
                str(DEFAULT_SPOTIFY_TOKEN_PATH),
            )
        )
        self.timeout = timeout
        self.callback_timeout = callback_timeout

    def get_access_token(self) -> str:
        token = self._load_token()
        if token is not None:
            access_token = str(token.get("access_token") or "")
            expires_at = float(token.get("expires_at") or 0.0)
            if access_token and expires_at > time.time() + 60:
                return access_token

            refresh_token = str(token.get("refresh_token") or "")
            if refresh_token:
                payload = self._request_token(
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": self._require_client_id(),
                    }
                )
                return self._save_token(payload, refresh_token)

        return self._authorize()

    def reauthorize(self) -> str:
        """Run OAuth again so newly requested scopes are granted."""

        return self._authorize()

    def has_saved_credentials(self) -> bool:
        token = self._load_token()
        if token is None:
            return False

        access_token = str(token.get("access_token") or "")
        expires_at = float(token.get("expires_at") or 0.0)
        refresh_token = str(token.get("refresh_token") or "")

        return bool(
            refresh_token
            or (
                access_token
                and expires_at > time.time() + 60
            )
        )

    def get_json(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict:
        token = self.get_access_token()
        query = urlencode(params or {})
        endpoint = f"https://api.spotify.com{path}"
        if query:
            endpoint = f"{endpoint}?{query}"

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
                f"Spotify API request failed: "
                f"{details or error.reason}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Could not connect to the Spotify Web API."
            ) from error

        if not isinstance(payload, dict):
            raise TypeError("Spotify API returned an invalid response.")

        return payload

    def _authorize(self) -> str:
        client_id = self._require_client_id()
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        state = secrets.token_urlsafe(32)
        authorization_url = (
            "https://accounts.spotify.com/authorize?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": client_id,
                    "scope": " ".join(SPOTIFY_OAUTH_SCOPES),
                    "redirect_uri": self.redirect_uri,
                    "state": state,
                    "code_challenge_method": "S256",
                    "code_challenge": code_challenge,
                }
            )
        )

        callback_host, callback_port = self._callback_address()
        server = _SpotifyCallbackServer(
            (callback_host, callback_port),
            _SpotifyCallbackHandler,
        )
        server.timeout = self.callback_timeout

        try:
            if not webbrowser.open(authorization_url):
                raise RuntimeError(
                    "Could not open the Spotify authorization page."
                )
            server.handle_request()
        finally:
            server.server_close()

        if server.authorization_error:
            raise RuntimeError(
                "Spotify authorization was denied: "
                f"{server.authorization_error}"
            )
        if not server.authorization_code:
            raise RuntimeError(
                "Spotify authorization timed out."
            )
        if server.authorization_state != state:
            raise RuntimeError(
                "Spotify authorization state verification failed."
            )

        payload = self._request_token(
            {
                "grant_type": "authorization_code",
                "code": server.authorization_code,
                "redirect_uri": self.redirect_uri,
                "client_id": client_id,
                "code_verifier": code_verifier,
            }
        )
        return self._save_token(payload, None)

    def _request_token(self, data: dict[str, str]) -> dict:
        request = Request(
            "https://accounts.spotify.com/api/token",
            data=urlencode(data).encode("utf-8"),
            headers={
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
                "Spotify token request failed: "
                f"{details or error.reason}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Could not connect to Spotify authentication."
            ) from error

        if not isinstance(payload, dict):
            raise TypeError("Spotify token response was invalid.")

        return payload

    def _load_token(self) -> dict | None:
        try:
            payload = json.loads(
                self.token_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return None

        return payload if isinstance(payload, dict) else None

    def _save_token(
        self,
        payload: dict,
        previous_refresh_token: str | None,
    ) -> str:
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise RuntimeError(
                "Spotify token response contained no access token."
            )

        refresh_token = str(
            payload.get("refresh_token") or previous_refresh_token or ""
        )
        expires_in = float(payload.get("expires_in") or 3600.0)
        token = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": time.time() + max(30.0, expires_in - 30.0),
        }

        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.token_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(token),
            encoding="utf-8",
        )
        os.replace(temporary_path, self.token_path)
        try:
            os.chmod(self.token_path, 0o600)
        except OSError:
            pass

        return access_token

    def _require_client_id(self) -> str:
        client_id = str(self.client_id or "").strip()
        if not client_id:
            raise RuntimeError(
                "Spotify OAuth requires SPOTIFY_CLIENT_ID in .env."
            )

        return client_id

    def _callback_address(self) -> tuple[str, int]:
        parsed_url = urlparse(self.redirect_uri)
        if (
            parsed_url.scheme != "http"
            or parsed_url.hostname not in {"127.0.0.1", "localhost"}
            or parsed_url.path != "/callback"
        ):
            raise ValueError(
                "Spotify redirect URI must be an HTTP loopback "
                "address ending with /callback."
            )

        return "127.0.0.1", parsed_url.port or 80


class _SpotifyCallbackServer(HTTPServer):
    authorization_code: str | None = None
    authorization_state: str | None = None
    authorization_error: str | None = None


class _SpotifyCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        query = parse_qs(urlparse(self.path).query)
        server = self.server
        if isinstance(server, _SpotifyCallbackServer):
            server.authorization_code = _first_query_value(
                query,
                "code",
            )
            server.authorization_state = _first_query_value(
                query,
                "state",
            )
            server.authorization_error = _first_query_value(
                query,
                "error",
            )

        body = (
            b"<html><body>Spotify authorization completed. "
            b"You can close this window.</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return None


def _first_query_value(
    query: dict[str, list[str]],
    key: str,
) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


class SpotifyMetadataProvider:
    def __init__(
        self,
        *,
        oauth_client: SpotifyOAuthClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if timeout <= 0:
            raise ValueError("Spotify timeout must be positive.")

        self.timeout = timeout
        self.oauth_client = oauth_client or SpotifyOAuthClient(
            timeout=timeout,
        )

    def authenticate(self) -> None:
        self.oauth_client.get_access_token()

    def reauthorize(self) -> None:
        self.oauth_client.reauthorize()

    def has_saved_credentials(self) -> bool:
        return self.oauth_client.has_saved_credentials()

    def get_saved_tracks(self) -> tuple[SpotifyTrack, ...]:
        """Return the current user's saved tracks through the Web API."""

        tracks: list[SpotifyTrack] = []
        offset = 0

        while True:
            payload = self.oauth_client.get_json(
                "/v1/me/tracks",
                {
                    "limit": "50",
                    "offset": str(offset),
                },
            )
            items = payload.get("items") or []
            for item in items:
                track = _parse_saved_track(item)
                if track is not None:
                    tracks.append(track)

            if not items or not payload.get("next"):
                break
            offset += len(items)

        return tuple(tracks)

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

        with urlopen(request, timeout=self.timeout) as response:
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
                "URL must point to a Spotify track, album, or playlist."
            )

        resource_type = parts[0].casefold()
        if resource_type not in {"track", "album", "playlist"}:
            raise ValueError(
                "URL must point to a Spotify track, album, or playlist."
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
        try:
            return self._get_playlist_from_partner_api(playlist_id)
        except (OSError, RuntimeError, TypeError, ValueError):
            return self._get_playlist_from_public_page(playlist_id)

    def get_authenticated_playlist(self, url: str) -> SpotifyPlaylist:
        normalized_url = self._canonical_url(url)
        _validate_spotify_url(
            normalized_url,
            expected_type="playlist",
        )
        playlist_id = _resource_id(normalized_url, "playlist")
        return self._get_playlist_from_authorized_api(playlist_id)

    def get_album(self, url: str) -> SpotifyPlaylist:
        normalized_url = self._canonical_url(url)
        _validate_spotify_url(
            normalized_url,
            expected_type="album",
        )
        album_id = _resource_id(normalized_url, "album")
        return self._get_album_from_partner_api(album_id)

    def get_authenticated_album(self, url: str) -> SpotifyPlaylist:
        normalized_url = self._canonical_url(url)
        _validate_spotify_url(
            normalized_url,
            expected_type="album",
        )
        album_id = _resource_id(normalized_url, "album")
        return self._get_album_from_authorized_api(album_id)

    def _get_playlist_from_authorized_api(
        self,
        playlist_id: str,
    ) -> SpotifyPlaylist:
        encoded_playlist_id = quote(playlist_id, safe="")
        playlist_payload = self.oauth_client.get_json(
            f"/v1/playlists/{encoded_playlist_id}",
            {"fields": "name"},
        )
        playlist_name = str(
            playlist_payload.get("name") or "Spotify playlist"
        ).strip()

        tracks: list[SpotifyTrack] = []
        offset = 0
        while True:
            payload = self.oauth_client.get_json(
                f"/v1/playlists/{encoded_playlist_id}/items",
                {
                    "limit": "100",
                    "offset": str(offset),
                    "fields": (
                        "items(is_local,item(name,artists(name),type)),"
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

    def _get_album_from_authorized_api(
        self,
        album_id: str,
    ) -> SpotifyPlaylist:
        encoded_album_id = quote(album_id, safe="")
        album_payload = self.oauth_client.get_json(
            f"/v1/albums/{encoded_album_id}",
            {"fields": "name"},
        )
        album_name = str(
            album_payload.get("name") or "Spotify album"
        ).strip()
        tracks: list[SpotifyTrack] = []
        offset = 0
        while True:
            payload = self.oauth_client.get_json(
                f"/v1/albums/{encoded_album_id}/tracks",
                {"limit": "50", "offset": str(offset)},
            )
            items = payload.get("items") or []
            tracks.extend(
                spotify_track
                for item in items
                if (spotify_track := _parse_playlist_track(item)) is not None
            )
            if not items:
                break
            offset += len(items)
            if not payload.get("next"):
                break

        if not tracks:
            raise RuntimeError(
                "Spotify API did not expose album track metadata."
            )

        return SpotifyPlaylist(
            name=album_name or "Spotify album",
            tracks=tuple(tracks),
        )

    def _get_playlist_from_public_page(
        self,
        playlist_id: str,
    ) -> SpotifyPlaylist:
        encoded_playlist_id = quote(playlist_id, safe="")
        endpoint = (
            "https://open.spotify.com/embed/playlist/"
            f"{encoded_playlist_id}"
        )
        request = Request(
            endpoint,
            headers={"User-Agent": "music-recommendation-system/1.0"},
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                html = response.read().decode("utf-8", errors="replace")
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "Spotify public playlist page request failed: "
                f"{details or error.reason}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Could not connect to the Spotify public playlist page."
            ) from error

        payload = _parse_next_data(html)
        entity = _get_embed_entity(payload)
        playlist_name = str(
            entity.get("name") or entity.get("title") or "Spotify playlist"
        ).strip()

        tracks: list[SpotifyTrack] = []
        for item in entity.get("trackList") or []:
            spotify_track = _parse_embed_track(item)
            if spotify_track is not None:
                tracks.append(spotify_track)

        if not tracks:
            raise RuntimeError(
                "Spotify public playlist page did not expose track metadata."
            )

        return SpotifyPlaylist(
            name=playlist_name,
            tracks=tuple(tracks),
        )

    def _get_playlist_from_partner_api(
        self,
        playlist_id: str,
    ) -> SpotifyPlaylist:
        """Read every public playlist page exposed by Spotify Web Player.

        This is intentionally a best-effort integration with Spotify's
        undocumented Web Player endpoint. It is used only for public
        playlists; OAuth remains available for private playlists.
        """
        access_token = self._get_anonymous_access_token()
        errors: list[str] = []

        for endpoint, query_hash in SPOTIFY_PARTNER_PLAYLIST_QUERIES:
            try:
                return self._get_partner_playlist_pages(
                    playlist_id,
                    access_token=access_token,
                    endpoint=endpoint,
                    query_hash=query_hash,
                )
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                errors.append(str(error))

        details = "; ".join(error for error in errors if error)
        raise RuntimeError(
            "Spotify Web Player did not expose the public playlist."
            + (f" {details}" if details else "")
        )

    def _get_album_from_partner_api(
        self,
        album_id: str,
    ) -> SpotifyPlaylist:
        access_token = self._get_anonymous_access_token()
        tracks: list[SpotifyTrack] = []
        offset = 0
        album_name = "Spotify album"
        total_count: int | None = None

        while True:
            payload = self._get_partner_album_page(
                album_id,
                access_token=access_token,
                offset=offset,
            )
            album = _get_partner_album(payload)
            album_name = str(album.get("name") or album_name).strip()
            tracks_data = album.get("tracksV2") or {}
            if not isinstance(tracks_data, dict):
                raise TypeError(
                    "Spotify Web Player returned invalid album tracks."
                )
            raw_items = tracks_data.get("items") or []
            if not isinstance(raw_items, list):
                raise TypeError(
                    "Spotify Web Player returned invalid album items."
                )
            total_value = tracks_data.get("totalCount")
            if isinstance(total_value, int) and total_value >= 0:
                total_count = total_value

            tracks.extend(
                spotify_track
                for item in raw_items
                if (spotify_track := _parse_partner_album_track(item))
                is not None
            )

            item_count = len(raw_items)
            offset += item_count
            if (
                not raw_items
                or item_count < SPOTIFY_PARTNER_PAGE_SIZE
                or (total_count is not None and offset >= total_count)
            ):
                break

        if not tracks:
            raise RuntimeError(
                "Spotify Web Player did not expose album track metadata."
            )

        return SpotifyPlaylist(
            name=album_name or "Spotify album",
            tracks=tuple(tracks),
        )

    def _get_partner_album_page(
        self,
        album_id: str,
        *,
        access_token: str,
        offset: int,
    ) -> dict:
        query = urlencode(
            {
                "operationName": "getAlbum",
                "variables": json.dumps(
                    {
                        "uri": f"spotify:album:{album_id}",
                        "offset": offset,
                        "limit": SPOTIFY_PARTNER_PAGE_SIZE,
                    },
                    separators=(",", ":"),
                ),
                "extensions": json.dumps(
                    {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": SPOTIFY_PARTNER_ALBUM_QUERY_HASH,
                        }
                    },
                    separators=(",", ":"),
                ),
            }
        )
        request = Request(
            f"{SPOTIFY_PARTNER_ALBUM_ENDPOINT}?{query}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Origin": "https://open.spotify.com",
                "Referer": "https://open.spotify.com/",
                "User-Agent": "Mozilla/5.0",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "Spotify Web Player album request failed: "
                f"{details or error.reason}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Could not connect to Spotify Web Player album data."
            ) from error

        if not isinstance(payload, dict):
            raise TypeError(
                "Spotify Web Player album response was invalid."
            )
        if payload.get("errors"):
            raise RuntimeError(
                "Spotify Web Player rejected the album request."
            )

        return payload

    def _get_anonymous_access_token(self) -> str:
        request = Request(
            SPOTIFY_ANONYMOUS_TOKEN_ENDPOINT,
            headers={
                "Origin": "https://open.spotify.com",
                "Referer": "https://open.spotify.com/",
                "User-Agent": "Mozilla/5.0",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "Spotify Web Player token request failed: "
                f"{details or error.reason}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Could not connect to Spotify Web Player."
            ) from error

        if not isinstance(payload, dict):
            raise TypeError("Spotify Web Player token was invalid.")

        token = str(payload.get("accessToken") or "").strip()
        if not token:
            raise RuntimeError(
                "Spotify Web Player did not return an anonymous token."
            )

        return token

    def _get_partner_playlist_pages(
        self,
        playlist_id: str,
        *,
        access_token: str,
        endpoint: str,
        query_hash: str,
    ) -> SpotifyPlaylist:
        playlist_name = "Spotify playlist"
        tracks: list[SpotifyTrack] = []
        offset = 0
        total_count: int | None = None

        while True:
            payload = self._get_partner_playlist_page(
                playlist_id,
                access_token=access_token,
                endpoint=endpoint,
                query_hash=query_hash,
                offset=offset,
            )
            playlist = _get_partner_playlist(payload)
            playlist_name = str(
                playlist.get("name") or playlist_name
            ).strip()
            content = playlist.get("content") or {}
            if not isinstance(content, dict):
                raise TypeError(
                    "Spotify Web Player returned invalid playlist content."
                )

            raw_items = content.get("items") or []
            if not isinstance(raw_items, list):
                raise TypeError(
                    "Spotify Web Player returned invalid playlist items."
                )

            total_value = content.get("totalCount")
            if isinstance(total_value, int) and total_value >= 0:
                total_count = total_value

            for item in raw_items:
                spotify_track = _parse_partner_playlist_track(item)
                if spotify_track is not None:
                    tracks.append(spotify_track)

            item_count = len(raw_items)
            offset += item_count
            if (
                not raw_items
                or item_count < SPOTIFY_PARTNER_PAGE_SIZE
                or (total_count is not None and offset >= total_count)
            ):
                break

        if not tracks:
            raise RuntimeError(
                "Spotify Web Player did not expose track metadata."
            )

        return SpotifyPlaylist(
            name=playlist_name or "Spotify playlist",
            tracks=tuple(tracks),
        )

    def _get_partner_playlist_page(
        self,
        playlist_id: str,
        *,
        access_token: str,
        endpoint: str,
        query_hash: str,
        offset: int,
    ) -> dict:
        query = urlencode(
            {
                "operationName": "fetchPlaylist",
                "variables": json.dumps(
                    {
                        "uri": f"spotify:playlist:{playlist_id}",
                        "offset": offset,
                        "limit": SPOTIFY_PARTNER_PAGE_SIZE,
                    },
                    separators=(",", ":"),
                ),
                "extensions": json.dumps(
                    {
                        "persistedQuery": {
                            "version": 1,
                            "sha256Hash": query_hash,
                        }
                    },
                    separators=(",", ":"),
                ),
            }
        )
        request = Request(
            f"{endpoint}?{query}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Origin": "https://open.spotify.com",
                "Referer": "https://open.spotify.com/",
                "User-Agent": "Mozilla/5.0",
            },
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "Spotify Web Player playlist request failed: "
                f"{details or error.reason}"
            ) from error
        except OSError as error:
            raise RuntimeError(
                "Could not connect to Spotify Web Player playlist data."
            ) from error

        if not isinstance(payload, dict):
            raise TypeError(
                "Spotify Web Player playlist response was invalid."
            )
        if payload.get("errors"):
            raise RuntimeError(
                "Spotify Web Player rejected the playlist request."
            )

        return payload

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

    track = payload.get("track") or payload.get("item") or payload
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


def _parse_saved_track(payload: object) -> SpotifyTrack | None:
    """Parse a saved-track item while retaining its Spotify identity."""

    if not isinstance(payload, dict):
        return None

    track_payload = payload.get("track")
    track = _parse_playlist_track(payload)
    if track is None or not isinstance(track_payload, dict):
        return None

    spotify_id = str(track_payload.get("id") or "").strip()
    if not spotify_id:
        return None

    album_payload = track_payload.get("album")
    album = (
        str(album_payload.get("name") or "").strip()
        if isinstance(album_payload, dict)
        else ""
    )
    duration_value = track_payload.get("duration_ms")
    try:
        duration_ms = int(duration_value) if duration_value is not None else None
    except (TypeError, ValueError):
        duration_ms = None

    external_ids = track_payload.get("external_ids")
    isrc = (
        str(external_ids.get("isrc") or "").strip()
        if isinstance(external_ids, dict)
        else ""
    )

    return replace(
        track,
        spotify_id=spotify_id,
        album=album or None,
        duration_ms=duration_ms,
        added_at=str(payload.get("added_at") or "").strip() or None,
        isrc=isrc or None,
    )


def _parse_next_data(html: str) -> dict:
    marker = '<script id="__NEXT_DATA__" type="application/json">'
    start = html.find(marker)
    if start < 0:
        raise RuntimeError(
            "Spotify public playlist page did not contain page data."
        )

    start += len(marker)
    end = html.find("</script>", start)
    if end < 0:
        raise RuntimeError(
            "Spotify public playlist page contained incomplete page data."
        )

    try:
        payload = json.loads(html[start:end])
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Spotify public playlist page returned invalid page data."
        ) from error

    if not isinstance(payload, dict):
        raise TypeError("Spotify public playlist page returned invalid data.")

    return payload


def _get_embed_entity(payload: dict) -> dict:
    current: object = payload
    for key in ("props", "pageProps", "state", "data", "entity"):
        if not isinstance(current, dict):
            break
        current = current.get(key)

    if not isinstance(current, dict) or current.get("type") != "playlist":
        raise RuntimeError(
            "Spotify public page did not contain playlist metadata."
        )

    return current


def _get_partner_playlist(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TypeError(
            "Spotify Web Player response did not contain playlist data."
        )

    playlist = data.get("playlistV2")
    if not isinstance(playlist, dict):
        raise TypeError(
            "Spotify Web Player response did not contain a playlist."
        )

    return playlist


def _get_partner_album(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise TypeError(
            "Spotify Web Player response did not contain album data."
        )

    album = data.get("albumUnion")
    if not isinstance(album, dict):
        raise TypeError(
            "Spotify Web Player response did not contain an album."
        )

    return album


def _parse_partner_playlist_track(payload: object) -> SpotifyTrack | None:
    if not isinstance(payload, dict):
        return None

    item = payload.get("itemV2") or payload.get("item") or payload
    if not isinstance(item, dict):
        return None

    track = item.get("data") or item.get("track") or item
    if not isinstance(track, dict):
        return None
    if track.get("__typename") not in {None, "Track"}:
        return None

    title = str(track.get("name") or "").strip()
    if not title:
        return None

    artists = track.get("artists") or {}
    artist_items = (
        artists.get("items") or []
        if isinstance(artists, dict)
        else artists
    )
    artist_names = [
        _partner_artist_name(artist)
        for artist in artist_items
        if isinstance(artist, dict)
    ]

    return SpotifyTrack(
        title=title,
        artist=", ".join(name for name in artist_names if name) or None,
    )


def _parse_partner_album_track(payload: object) -> SpotifyTrack | None:
    if not isinstance(payload, dict):
        return None

    track = payload.get("track") or payload.get("itemV2") or payload
    return _parse_partner_playlist_track(track)


def _partner_artist_name(payload: dict) -> str:
    profile = payload.get("profile") or {}
    if isinstance(profile, dict):
        name = str(profile.get("name") or "").strip()
        if name:
            return name

    data = payload.get("data") or {}
    if isinstance(data, dict) and data:
        return _partner_artist_name(data)

    return str(payload.get("name") or "").strip()


def _parse_embed_track(payload: object) -> SpotifyTrack | None:
    if not isinstance(payload, dict):
        return None

    if payload.get("entityType") not in {None, "track"}:
        return None

    title = str(payload.get("title") or "").strip()
    artist = str(payload.get("subtitle") or "").strip()
    if not title:
        return None

    return SpotifyTrack(
        title=title,
        artist=artist or None,
    )
