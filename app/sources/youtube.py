from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

SUPPORTED_DOWNLOAD_EXTENSIONS = {
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".opus",
    ".wav",
}


@dataclass(frozen=True)
class YouTubeCandidate:
    video_id: str
    title: str
    channel_id: str | None
    channel_title: str
    duration_ms: int | None
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

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": True,
        }

        search_query = (
            f"ytsearch{max_results}:"
            f"{normalized_query}"
        )

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                result = downloader.extract_info(
                    search_query,
                    download=False,
                )
        except DownloadError as error:
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
                    channel_id=entry.get(
                        "channel_id"
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
        *,
        allowed_channel_id: str,
    ) -> Path:
        normalized_channel_id = (
            allowed_channel_id.strip()
        )

        if not normalized_channel_id:
            raise ValueError(
                "Allowed channel ID must not be empty"
            )

        if candidate.channel_id != normalized_channel_id:
            raise PermissionError(
                "Selected video does not belong "
                "to the allowed channel"
            )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        options = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": (
                "bestaudio[ext=m4a]"
                "/bestaudio[ext=opus]"
                "/bestaudio"
            ),
            "outtmpl": str(
                output_dir
                / f"{candidate.video_id}.%(ext)s"
            ),
            "overwrites": False,
        }

        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                remote_info = downloader.extract_info(
                    candidate.url,
                    download=False,
                )

                actual_channel_id = (
                    remote_info.get("channel_id")
                )

                if (
                    actual_channel_id
                    != normalized_channel_id
                ):
                    raise PermissionError(
                        "YouTube channel verification failed"
                    )

                downloader.download(
                    [candidate.url]
                )
        except PermissionError:
            raise
        except DownloadError as error:
            raise RuntimeError(
                "YouTube download failed"
            ) from error

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
                "Downloaded format is not supported. "
                "The video may require FFmpeg conversion."
            )

        return downloaded_files[0]
