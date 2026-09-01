from pathlib import Path
from typing import Self

import app.sources.youtube as youtube_source
from app.domain.models import Track
from app.services.youtube_import import (
    SpotifyPlaylistSearchResult,
    YouTubeImportService,
)
from app.sources.spotify import SpotifyPlaylist, SpotifyTrack
from app.sources.youtube import YouTubeCandidate, YouTubeSearchProvider


class FakeYoutubeDownloader:
    def __init__(self, result: dict) -> None:
        self.result = result

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def extract_info(
        self,
        url: str,
        download: bool,
    ) -> dict:
        assert "list=playlist-1" in url
        assert download is False
        return self.result


def test_playlist_extracts_video_candidates(monkeypatch) -> None:
    result = {
        "entries": [
            {
                "id": "video-1",
                "title": "First track",
                "channel": "Artist One",
                "duration": 125,
                "view_count": 42,
            },
            None,
            {
                "id": "video-2",
                "title": "Second track",
                "uploader": "Artist Two",
            },
        ]
    }

    monkeypatch.setattr(
        youtube_source.yt_dlp,
        "YoutubeDL",
        lambda options: FakeYoutubeDownloader(result),
    )
    monkeypatch.setattr(
        youtube_source,
        "_authentication_sources",
        lambda: ("none",),
    )

    candidates = YouTubeSearchProvider().playlist(
        "https://www.youtube.com/playlist?list=playlist-1"
    )

    assert [candidate.video_id for candidate in candidates] == [
        "video-1",
        "video-2",
    ]
    assert candidates[0].duration_ms == 125_000
    assert candidates[1].channel_title == "Artist Two"


class FakeIngestionService:
    def ingest(
        self,
        source_path: Path,
        *,
        title: str,
        artist: str,
        source: str,
        source_url: str,
    ) -> Track:
        if title == "Broken track":
            raise ValueError("duplicate track")

        return Track(
            id=title,
            title=title,
            artist=artist,
            source=source,
            source_url=source_url,
            local_path=str(source_path),
        )


class FakeDownloadProvider:
    def download(
        self,
        candidate: YouTubeCandidate,
        output_dir: Path,
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{candidate.video_id}.mp3"
        path.touch()
        return path


class FakeYoutubeDownloadWriter:
    def __init__(self, options: dict) -> None:
        self.options = options

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def download(self, urls: list[str]) -> None:
        output_path = Path(
            self.options["outtmpl"].replace("%(ext)s", "m4a")
        )
        output_path.touch()


def test_download_prefers_m4a_audio(monkeypatch, tmp_path) -> None:
    captured_options: list[dict] = []

    def create_downloader(options: dict) -> FakeYoutubeDownloadWriter:
        captured_options.append(options)
        return FakeYoutubeDownloadWriter(options)

    monkeypatch.setattr(
        youtube_source.yt_dlp,
        "YoutubeDL",
        create_downloader,
    )
    monkeypatch.setattr(
        youtube_source,
        "_authentication_sources",
        lambda: ("none",),
    )

    candidate = YouTubeCandidate(
        video_id="video-1",
        title="First track",
        channel_title="Artist One",
        duration_ms=None,
        view_count=None,
        url="https://www.youtube.com/watch?v=video-1",
    )

    downloaded_path = YouTubeSearchProvider().download(
        candidate,
        tmp_path,
    )

    assert downloaded_path.suffix == ".m4a"
    assert captured_options[0]["format"] == (
        "bestaudio[ext=m4a]/bestaudio[acodec*=mp4a]"
    )


def test_playlist_import_keeps_successes_when_one_track_fails() -> None:
    candidates = [
        YouTubeCandidate(
            video_id="ok",
            title="Working track",
            channel_title="Artist",
            duration_ms=None,
            view_count=None,
            url="https://www.youtube.com/watch?v=ok",
        ),
        YouTubeCandidate(
            video_id="broken",
            title="Broken track",
            channel_title="Artist",
            duration_ms=None,
            view_count=None,
            url="https://www.youtube.com/watch?v=broken",
        ),
    ]
    service = YouTubeImportService(
        FakeIngestionService(),
        FakeDownloadProvider(),
    )

    progress: list[tuple[int, int]] = []

    result = service.download_and_import_playlist(
        candidates,
        on_progress=lambda completed, total: progress.append(
            (completed, total)
        ),
    )

    assert [track.title for track in result.imported] == [
        "Working track"
    ]
    assert [candidate.title for candidate, _ in result.failed] == [
        "Broken track"
    ]
    assert progress == [(1, 2), (2, 2)]


class FakeSpotifyProvider:
    def get_resource_type(self, url: str) -> str:
        assert url == "spotify-playlist"
        return "playlist"

    def get_playlist(self, url: str) -> SpotifyPlaylist:
        return SpotifyPlaylist(
            name="Imported playlist",
            tracks=(
                SpotifyTrack("First track", "Artist One"),
                SpotifyTrack("Second track", "Artist Two"),
            ),
        )


class FakeSpotifyYoutubeProvider:
    def search(
        self,
        query: str,
        *,
        max_results: int,
    ) -> list[YouTubeCandidate]:
        return [
            YouTubeCandidate(
                video_id=query,
                title=f"YouTube {query}",
                channel_title="YouTube channel",
                duration_ms=None,
                view_count=None,
                url=f"https://youtube.test/{query}",
            )
        ]


def test_spotify_playlist_search_keeps_order_and_metadata() -> None:
    service = YouTubeImportService(
        FakeIngestionService(),
        FakeSpotifyYoutubeProvider(),
        FakeSpotifyProvider(),
    )

    result = service.search_from_spotify("spotify-playlist")

    assert isinstance(result, SpotifyPlaylistSearchResult)
    assert result.playlist_name == "Imported playlist"
    assert [candidate.requested_title for candidate in result.candidates] == [
        "First track",
        "Second track",
    ]
    assert [candidate.playlist_position for candidate in result.candidates] == [
        0,
        1,
    ]
