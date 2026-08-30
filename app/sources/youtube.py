import json
import os
import shutil
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

import yt_dlp
from yt_dlp.utils import DownloadError

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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COOKIES_FILE = PROJECT_ROOT / "data" / "youtube_cookies.txt"


@dataclass(frozen=True)
class YouTubeCandidate:
    video_id: str
    title: str
    channel_title: str
    duration_ms: int | None
    view_count: int | None
    url: str


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

        options = _youtube_options()
        options.update(
            {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
            }
        )

        search_query = (
            f"ytsearch{max_results}:"
            f"{normalized_query}"
        )

        try:
            with _dns_fallback(), yt_dlp.YoutubeDL(
                options
            ) as downloader:
                result = downloader.extract_info(
                    search_query,
                    download=False,
                )
        except DownloadError as error:
            error_text = str(error).lower()

            if (
                "sign in to confirm" in error_text
                or "not a bot" in error_text
            ):
                raise RuntimeError(
                    "YouTube requires authentication. Export fresh "
                    "YouTube cookies to "
                    f"{DEFAULT_COOKIES_FILE} and try again."
                ) from error

            raise RuntimeError(
                "YouTube search failed"
            ) from error

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
            "format": (
                "bestaudio[ext=m4a]"
                "/bestaudio[ext=opus]"
                "/bestaudio"
                "/best[acodec!=none]"
            ),
            "outtmpl": str(
                output_dir
                / f"{candidate.video_id}.%(ext)s"
            ),
            "overwrites": False,
        }

        cookie_file = _find_cookie_file()
        clients = ["web_embedded"]

        if cookie_file is not None:
            # A cookie file allows the regular web client to access videos
            # that are not available through the embedded client.
            clients = ["web", "web_embedded"]

        last_error: DownloadError | None = None

        for client in clients:
            options = _youtube_options(client=client)
            options.update(base_options)

            try:
                with _dns_fallback(), yt_dlp.YoutubeDL(
                    options
                ) as downloader:
                    downloader.download(
                        [candidate.url]
                    )
                break
            except PermissionError:
                raise
            except DownloadError as error:
                last_error = error
                error_text = str(error).lower()

                if (
                    "sign in to confirm" in error_text
                    or "not a bot" in error_text
                    or "login_required" in error_text
                ):
                    continue

                raise RuntimeError(
                    "YouTube download failed"
                ) from error
        else:
            assert last_error is not None
            cookie_hint = (
                " Export fresh YouTube cookies to "
                f"{DEFAULT_COOKIES_FILE} and try again."
            )
            raise RuntimeError(
                "YouTube requires a browser session for this video."
                + cookie_hint
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


def _youtube_options(*, client: str = "web_embedded") -> dict:
    options = {
        "extractor_args": {
            "youtube": {
                "player_client": [client],
            },
        },
    }

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
