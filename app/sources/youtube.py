import json
import os
import shutil
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import yt_dlp
from yt_dlp.utils import DownloadError

from app.storage.paths import DATA_DIR

SUPPORTED_DOWNLOAD_EXTENSIONS = {
    ".flac",
    ".m4a",
    ".mp3",
    # Some videos only expose progressive MP4 with AAC audio.
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
}

DEFAULT_COOKIES_FILE = DATA_DIR / "youtube_cookies.txt"
SUPPORTED_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}


@dataclass(frozen=True)
class YouTubeCandidate:
    video_id: str
    title: str
    channel_title: str
    duration_ms: int | None
    view_count: int | None
    url: str
    requested_title: str | None = None
    requested_artist: str | None = None
    playlist_position: int | None = None


class YouTubeSearchProvider:
    def search(
        self,
        query: str,
        *,
        max_results: int = 10,
    ) -> list[YouTubeCandidate]:
        normalized_query = query.strip()

        if not normalized_query:
            raise ValueError(
                "YouTube search query must not be empty"
            )

        if not 1 <= max_results <= 50:
            raise ValueError(
                "max_results must be between 1 and 50"
            )

        search_query = (
            f"ytsearch{max_results}:"
            f"{normalized_query}"
        )

        auth_sources = _authentication_sources()
        last_error: DownloadError | None = None

        for auth_source in auth_sources:
            options = _youtube_options(auth_source=auth_source)
            options.update(
                {
                    "quiet": True,
                    "no_warnings": True,
                    "skip_download": True,
                    "extract_flat": True,
                }
            )

            try:
                with _dns_fallback(), yt_dlp.YoutubeDL(
                    options
                ) as downloader:
                    result = downloader.extract_info(
                        search_query,
                        download=False,
                    )
                break
            except DownloadError as error:
                last_error = error
                if (
                    auth_source != auth_sources[-1]
                    and _is_authentication_error(str(error))
                ):
                    continue

                if _is_authentication_error(str(error)):
                    raise RuntimeError(
                        _youtube_authentication_message()
                    ) from error

                raise RuntimeError(
                    "YouTube search failed"
                ) from error
        else:
            assert last_error is not None
            raise RuntimeError(
                _youtube_authentication_message()
            ) from last_error

        candidates = []

        for entry in result.get("entries", []):
            if not entry:
                continue

            video_id = entry.get("id")

            if not video_id:
                continue

            duration = entry.get("duration")

            candidates.append(
                YouTubeCandidate(
                    video_id=video_id,
                    title=entry.get(
                        "title",
                        "Unknown title",
                    ),
                    channel_title=entry.get(
                        "channel"
                    )
                    or entry.get(
                        "uploader",
                        "Unknown channel",
                    ),
                    duration_ms=(
                        round(duration * 1000)
                        if duration is not None
                        else None
                    ),
                    view_count=entry.get("view_count"),
                    url=(
                        "https://www.youtube.com/watch?v="
                        f"{video_id}"
                    ),
                )
            )

        return candidates

    def playlist(
        self,
        url: str,
    ) -> list[YouTubeCandidate]:
        normalized_url = url.strip()
        _validate_youtube_playlist_url(normalized_url)

        auth_sources = _authentication_sources()
        clients = _youtube_clients(auth_sources)
        result = None
        last_error: DownloadError | None = None

        for auth_source in auth_sources:
            for client in clients:
                options = _youtube_options(
                    client=client,
                    auth_source=auth_source,
                )
                options.update(
                    {
                        "quiet": True,
                        "no_warnings": True,
                        "skip_download": True,
                        "extract_flat": "in_playlist",
                        "noplaylist": False,
                    }
                )

                try:
                    with _dns_fallback(), yt_dlp.YoutubeDL(
                        options
                    ) as downloader:
                        result = downloader.extract_info(
                            normalized_url,
                            download=False,
                        )
                    break
                except DownloadError as error:
                    last_error = error

                    if (
                        client != clients[-1]
                        or auth_source != auth_sources[-1]
                    ):
                        continue

                    if _is_authentication_error(str(error)):
                        break

                    raise RuntimeError(
                        "YouTube playlist extraction failed"
                    ) from error

            if result is not None:
                break

        if result is None:
            assert last_error is not None
            raise RuntimeError(
                _youtube_authentication_message()
            ) from last_error

        candidates = []

        for entry in result.get("entries", []):
            if not entry:
                continue

            video_id = entry.get("id")

            if not video_id:
                continue

            duration = entry.get("duration")
            candidates.append(
                YouTubeCandidate(
                    video_id=video_id,
                    title=entry.get(
                        "title",
                        f"YouTube video {video_id}",
                    ),
                    channel_title=(
                        entry.get("channel")
                        or entry.get(
                            "uploader",
                            "Unknown channel",
                        )
                    ),
                    duration_ms=(
                        round(duration * 1000)
                        if duration is not None
                        else None
                    ),
                    view_count=entry.get("view_count"),
                    url=(
                        "https://www.youtube.com/watch?v="
                        f"{video_id}"
                    ),
                )
            )

        return candidates

    def candidate_from_url(
        self,
        url: str,
    ) -> YouTubeCandidate:
        normalized_url = url.strip()
        _validate_youtube_url(normalized_url)

        auth_sources = _authentication_sources()
        clients = _youtube_clients(auth_sources)

        result = None
        last_error: DownloadError | None = None

        for auth_source in auth_sources:
            for client in clients:
                options = _youtube_options(
                    client=client,
                    auth_source=auth_source,
                )
                options.update(
                    {
                        "quiet": True,
                        "no_warnings": True,
                        "skip_download": True,
                        "noplaylist": True,
                    }
                )

                try:
                    with _dns_fallback(), yt_dlp.YoutubeDL(
                        options
                    ) as downloader:
                        result = downloader.extract_info(
                            normalized_url,
                            download=False,
                        )
                    break
                except DownloadError as error:
                    last_error = error

                    if (
                        client != clients[-1]
                        or auth_source != auth_sources[-1]
                    ):
                        continue

                    if _is_authentication_error(str(error)):
                        break

                    raise RuntimeError(
                        "YouTube URL extraction failed"
                    ) from error

            if result is not None:
                break

        if result is None:
            video_id = extract_youtube_video_id(normalized_url)

            if video_id is not None:
                return YouTubeCandidate(
                    video_id=video_id,
                    title=f"YouTube video {video_id}",
                    channel_title="Unknown channel",
                    duration_ms=None,
                    view_count=None,
                    url=normalized_url,
                )

            assert last_error is not None
            raise RuntimeError(
                _youtube_authentication_message()
            ) from last_error

        video_id = result.get("id")

        if not video_id:
            raise RuntimeError(
                "The YouTube URL did not contain a video."
            )

        duration = result.get("duration")

        return YouTubeCandidate(
            video_id=video_id,
            title=result.get("title", "Unknown title"),
            channel_title=(
                result.get("channel")
                or result.get(
                    "uploader",
                    "Unknown channel",
                )
            ),
            duration_ms=(
                round(duration * 1000)
                if duration is not None
                else None
            ),
            view_count=result.get("view_count"),
            url=normalized_url,
        )

    def get_resource_type(self, url: str) -> str:
        normalized_url = url.strip()
        _validate_youtube_url(normalized_url)
        parsed_url = urlparse(normalized_url)

        if extract_youtube_video_id(normalized_url) is not None:
            return "track"

        if parse_qs(parsed_url.query).get("list"):
            return "playlist"

        raise ValueError(
            "URL must point to a YouTube track or playlist."
        )

    def download(
        self,
        candidate: YouTubeCandidate,
        output_dir: Path,
    ) -> Path:
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        base_options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio[ext=m4a]/bestaudio[acodec*=mp4a]",
            "outtmpl": str(
                output_dir
                / f"{candidate.video_id}.%(ext)s"
            ),
            "overwrites": False,
        }

        auth_sources = _authentication_sources()
        clients = _youtube_clients(auth_sources)

        last_error: DownloadError | None = None
        download_succeeded = False

        for auth_source in auth_sources:
            for client in clients:
                options = _youtube_options(
                    client=client,
                    auth_source=auth_source,
                )
                options.update(base_options)

                try:
                    with _dns_fallback(), yt_dlp.YoutubeDL(
                        options
                    ) as downloader:
                        downloader.download(
                            [candidate.url]
                        )
                    download_succeeded = True
                    break
                except PermissionError:
                    raise
                except DownloadError as error:
                    last_error = error

                    if (
                        client != clients[-1]
                        or auth_source != auth_sources[-1]
                    ):
                        continue

                    if _is_authentication_error(str(error)):
                        break

                    raise RuntimeError(
                        "YouTube download failed"
                    ) from error

            if download_succeeded:
                break
        else:
            assert last_error is not None
            raise RuntimeError(
                _youtube_authentication_message()
            ) from last_error

        downloaded_files = [
            path
            for path in output_dir.glob(
                f"{candidate.video_id}.*"
            )
            if (
                path.is_file()
                and path.suffix.lower()
                in SUPPORTED_DOWNLOAD_EXTENSIONS
            )
        ]

        if not downloaded_files:
            raise RuntimeError(
                "Downloaded format is not supported."
            )

        return downloaded_files[0]


@contextmanager
def _dns_fallback():
    original_getaddrinfo = socket.getaddrinfo
    resolved_hosts: dict[str, str] = {}

    def getaddrinfo(
        host,
        port,
        family=0,
        type=0,
        proto=0,
        flags=0,
    ):
        try:
            return original_getaddrinfo(
                host,
                port,
                family,
                type,
                proto,
                flags,
            )
        except socket.gaierror:
            if not host or host == "dns.google":
                raise

            ip_address = resolved_hosts.get(host)

            if ip_address is None:
                with urlopen(
                    "https://dns.google/resolve?"
                    f"name={host}&type=A",
                    timeout=5,
                ) as response:
                    dns_result = json.load(response)

                answers = dns_result.get("Answer", [])
                ip_address = next(
                    (
                        answer["data"]
                        for answer in answers
                        if answer.get("type") == 1
                    ),
                    None,
                )

                if ip_address is None:
                    raise

                resolved_hosts[host] = ip_address

            return original_getaddrinfo(
                ip_address,
                port,
                family,
                type,
                proto,
                flags,
            )

    socket.getaddrinfo = getaddrinfo

    try:
        yield
    finally:
        socket.getaddrinfo = original_getaddrinfo


def _youtube_options(
    *,
    client: str = "web_embedded",
    auth_source: str = "auto",
) -> dict:
    options = {
        "extractor_args": {
            "youtube": {
                "player_client": [client],
            },
        },
    }

    if auth_source == "auto":
        auth_source = _authentication_sources()[0]

    if auth_source == "browser":
        options["cookiesfrombrowser"] = ("firefox",)
    elif auth_source == "file":
        cookie_file = _find_cookie_file()

        if cookie_file is not None:
            options["cookiefile"] = str(cookie_file)

    node_path = os.environ.get("YTDLP_NODE_PATH")
    node_path = node_path or shutil.which("node")

    if not node_path:
        bundled_node_path = (
            Path.home()
            / ".cache"
            / "codex-runtimes"
            / "codex-primary-runtime"
            / "dependencies"
            / "node"
            / "bin"
            / "node.exe"
        )

        if bundled_node_path.is_file():
            node_path = str(bundled_node_path)

    if node_path:
        options["js_runtimes"] = {
            "node": {"path": node_path},
        }

    return options


def _authentication_sources() -> tuple[str, ...]:
    sources: list[str] = []

    if _firefox_profile_exists():
        sources.append("browser")

    if _find_cookie_file() is not None:
        sources.append("file")

    return tuple(sources) or ("none",)


def _youtube_clients(
    auth_sources: tuple[str, ...],
) -> list[str]:
    if auth_sources == ("none",):
        return ["web_embedded"]

    return ["web_embedded", "web"]


def _firefox_profile_exists() -> bool:
    app_data = os.environ.get("APPDATA")

    if not app_data:
        return False

    return (
        Path(app_data)
        / "Mozilla"
        / "Firefox"
        / "Profiles"
    ).is_dir()


def _is_authentication_error(error_text: str) -> bool:
    normalized_text = error_text.lower()

    markers = (
        "sign in to confirm",
        "not a bot",
        "login_required",
        "could not copy firefox cookie database",
        "failed to load cookies",
    )

    return any(marker in normalized_text for marker in markers)


def _youtube_authentication_message() -> str:
    if _firefox_profile_exists():
        return (
            "YouTube requires a Firefox session. Close Firefox completely "
            "and try again, or refresh the YouTube cookies file at "
            f"{DEFAULT_COOKIES_FILE}."
        )

    return (
        "YouTube requires authentication. Export fresh YouTube cookies "
        f"to {DEFAULT_COOKIES_FILE} and try again."
    )


def _find_cookie_file() -> Path | None:
    configured_path = os.environ.get("YTDLP_COOKIES_FILE")

    candidates = (
        Path(configured_path).expanduser()
        if configured_path
        else None,
        DEFAULT_COOKIES_FILE,
    )

    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return candidate

    return None


def _validate_youtube_url(url: str) -> None:
    parsed_url = urlparse(url)
    hostname = (parsed_url.hostname or "").lower()

    if (
        parsed_url.scheme not in {"http", "https"}
        or hostname not in SUPPORTED_YOUTUBE_HOSTS
    ):
        raise ValueError(
            "URL must be a valid YouTube video URL."
        )


def _validate_youtube_playlist_url(url: str) -> None:
    _validate_youtube_url(url)

    if not parse_qs(urlparse(url).query).get("list"):
        raise ValueError(
            "URL must contain a YouTube playlist."
        )


def extract_youtube_video_id(url: str) -> str | None:
    parsed_url = urlparse(url)
    hostname = (parsed_url.hostname or "").lower()

    if hostname == "youtu.be":
        video_id = parsed_url.path.strip("/").split("/")[0]
        return video_id or None

    query_video_id = parse_qs(
        parsed_url.query
    ).get("v", [None])[0]

    if query_video_id:
        return query_video_id

    path_parts = [
        part
        for part in parsed_url.path.split("/")
        if part
    ]

    for marker in ("shorts", "embed", "live"):
        if marker in path_parts:
            marker_index = path_parts.index(marker)

            if marker_index + 1 < len(path_parts):
                return path_parts[marker_index + 1]

    return None
