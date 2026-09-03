from pathlib import Path

from app.domain.models import Track
from app.services import soundcloud_import
from app.services.soundcloud_import import (
    SOUNDCLOUD_AUDIO_FORMAT,
    SoundCloudCandidate,
    SoundCloudImportService,
    SoundCloudPlaylist,
)


class FakeIngestionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ingest(
        self,
        source_path: Path,
        *,
        title: str | None = None,
        artist: str | None = None,
        fallback_title: str | None = None,
        source: str = "local_upload",
        source_id: str | None = None,
        source_url: str | None = None,
    ) -> Track:
        self.calls.append(
            {
                "source_path": source_path,
                "title": title,
                "artist": artist,
                "fallback_title": fallback_title,
                "source": source,
                "source_id": source_id,
                "source_url": source_url,
            }
        )
        return Track(
            id="track-1",
            title=title or fallback_title or "Unknown title",
            artist=artist or "Friend Artist",
            source=source,
            source_id=source_id,
            source_url=source_url,
            local_path=str(source_path),
        )


def test_soundcloud_url_detection() -> None:
    assert SoundCloudImportService.is_supported_url(
        "https://soundcloud.com/lilyeat/2tone"
    )
    assert SoundCloudImportService.is_supported_url(
        "https://m.soundcloud.com/artist/track"
    )
    assert SoundCloudImportService.is_supported_url(
        "https://on.soundcloud.com/track-token"
    )
    assert not SoundCloudImportService.is_supported_url(
        "https://example.com/track"
    )
    assert SoundCloudImportService.is_playlist_url(
        "https://soundcloud.com/trendalert/sets/2tone-yeat-don-toliver"
    )
    assert not SoundCloudImportService.is_playlist_url(
        "https://soundcloud.com/lilyeat/2tone"
    )


def test_soundcloud_authentication_options_use_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "SOUNDCLOUD_COOKIES_FILE",
        r"C:\private\soundcloud_cookies.txt",
    )
    monkeypatch.setenv("SOUNDCLOUD_OAUTH_TOKEN", "private-token")

    assert SoundCloudImportService._authentication_options() == {
        "cookiefile": r"C:\private\soundcloud_cookies.txt",
        "username": "oauth",
        "password": "private-token",
    }


def test_search_returns_soundcloud_candidates(monkeypatch) -> None:
    entries = [
        {
            "id": "2139994098",
            "title": "2TONE",
            "uploader": "Yeat",
            "duration": 30.0,
            "view_count": 1217314,
            "webpage_url": "https://soundcloud.com/lilyeat/2tone",
        },
        {
            "id": "2140065534",
            "title": "Yeat - 2TONE (Slowed)",
            "uploader": "s2p (archive)",
            "duration": 255.644,
            "view_count": 53805,
            "webpage_url": (
                "https://soundcloud.com/user-256554434/yeat-2tone-9"
            ),
        },
    ]
    calls: list[tuple[str, bool]] = []

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            assert options["ignoreerrors"] is True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, query, *, download):
            calls.append((query, download))
            return {"entries": entries}

    monkeypatch.setattr(soundcloud_import.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    candidates = SoundCloudImportService(FakeIngestionService()).search(
        " Yeat 2TONE ",
        max_results=5,
    )

    assert calls == [("scsearch5:Yeat 2TONE", False)]
    assert [candidate.title for candidate in candidates] == [
        "2TONE",
        "Yeat - 2TONE (Slowed)",
    ]
    assert candidates[0].artist == "Yeat"
    assert candidates[0].duration_ms == 30_000
    assert candidates[1].playback_count == 53_805


def test_playlist_resolves_set_tracks_in_order(monkeypatch) -> None:
    set_url = (
        "https://soundcloud.com/trendalert/sets/2tone-yeat-don-toliver"
    )
    entries = [
        {
            "id": "track-1",
            "title": "2TONE",
            "uploader": "Yeat",
            "duration": 162.0,
            "webpage_url": "https://soundcloud.com/yeat/2tone",
        },
        {
            "id": "track-2",
            "title": "BAND4BAND",
            "uploader": "Central Cee",
            "duration": 140.0,
            "webpage_url": "https://soundcloud.com/centralcee/band4band",
        },
    ]

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options
            assert options["ignoreerrors"] is True

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, *, download):
            assert url == set_url
            assert download is False
            return {
                "title": "2TONE — Yeat / Don Toliver",
                "thumbnail": "https://cdn.example/set-cover.jpg",
                "entries": entries,
            }

    monkeypatch.setattr(soundcloud_import.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    result = SoundCloudImportService(FakeIngestionService()).playlist(set_url)

    assert isinstance(result, SoundCloudPlaylist)
    assert result.name == "2TONE — Yeat / Don Toliver"
    assert result.cover_url == "https://cdn.example/set-cover.jpg"
    assert [candidate.track_id for candidate in result.candidates] == [
        "track-1",
        "track-2",
    ]
    assert [candidate.playlist_position for candidate in result.candidates] == [
        0,
        1,
    ]


def test_search_rejects_invalid_query_or_limit() -> None:
    service = SoundCloudImportService(FakeIngestionService())

    for query in ("", "   "):
        try:
            service.search(query)
        except ValueError as error:
            assert "must not be empty" in str(error)
        else:
            raise AssertionError("Expected an empty-query error")

    try:
        service.search("Yeat", max_results=51)
    except ValueError as error:
        assert "between 1 and 50" in str(error)
    else:
        raise AssertionError("Expected a result-limit error")


def test_download_imports_selected_audio_file(monkeypatch) -> None:
    ingestion_service = FakeIngestionService()
    candidate = SoundCloudCandidate(
        track_id="2139994098",
        title="2TONE",
        artist="Yeat",
        duration_ms=30_000,
        playback_count=1_213_714,
        url="https://soundcloud.com/lilyeat/2tone",
    )

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, *, download):
            assert url == candidate.url
            assert download is False
            return {
                "formats": [
                    {
                        "format_id": "http_mp3_128",
                        "url": "https://cdn.example/audio.mp3",
                        "vcodec": "none",
                    }
                ]
            }

        def download(self, urls):
            assert urls == [candidate.url]
            output_path = Path(
                self.options["outtmpl"]
                .replace("%(id)s", candidate.track_id)
                .replace("%(ext)s", "mp3")
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"audio")

    monkeypatch.setattr(soundcloud_import.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    track = SoundCloudImportService(ingestion_service).download(candidate)

    assert track.source == "soundcloud_import"
    assert track.source_id == candidate.track_id
    assert track.source_url == candidate.url
    assert ingestion_service.calls[0]["title"] == "2TONE"
    assert ingestion_service.calls[0]["artist"] == "Yeat"


def test_download_excludes_soundcloud_preview_formats(monkeypatch) -> None:
    captured_options: list[dict] = []
    download_called = False

    class FakeYoutubeDL:
        def __init__(self, options):
            captured_options.append(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            assert download is False
            return {
                "formats": [
                    {
                        "format_id": "http_mp3_preview",
                        "url": "https://cdn.example/preview.mp3",
                        "vcodec": "none",
                    }
                ]
            }

        def download(self, _urls):
            nonlocal download_called
            download_called = True

    monkeypatch.setattr(soundcloud_import.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    try:
        SoundCloudImportService(FakeIngestionService()).download(
            "https://soundcloud.com/lilyeat/2tone"
        )
    except RuntimeError as error:
        assert "full-length audio stream" in str(error)
    else:
        raise AssertionError("Expected a missing full-length audio error")

    assert captured_options[0]["format"] == SOUNDCLOUD_AUDIO_FORMAT
    assert captured_options[0]["format"].startswith("download/")
    assert not download_called


def test_download_rejects_query_without_selected_result() -> None:
    try:
        SoundCloudImportService(FakeIngestionService()).download(
            "Yeat 2TONE"
        )
    except ValueError as error:
        assert "requires a track URL" in str(error)
    else:
        raise AssertionError("Expected a URL validation error")


def test_download_reports_when_no_audio_is_produced(monkeypatch) -> None:
    class FakeYoutubeDL:
        def __init__(self, _options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, *, download):
            assert download is False

        def download(self, _urls):
            return None

    monkeypatch.setattr(soundcloud_import.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    try:
        SoundCloudImportService(FakeIngestionService()).download(
            "https://soundcloud.com/lilyeat/2tone"
        )
    except RuntimeError as error:
        assert "full-length audio stream" in str(error)
    else:
        raise AssertionError("Expected a missing audio file error")
