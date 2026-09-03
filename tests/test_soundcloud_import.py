from pathlib import Path
from subprocess import CompletedProcess

from app.domain.models import Track
from app.services import soundcloud_import
from app.services.soundcloud_import import SoundCloudImportService


class FakeIngestionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ingest(
        self,
        source_path: Path,
        *,
        fallback_title: str,
        source: str,
        source_url: str | None,
    ) -> Track:
        self.calls.append(
            {
                "source_path": source_path,
                "fallback_title": fallback_title,
                "source": source,
                "source_url": source_url,
            }
        )
        return Track(
            id="track-1",
            title=fallback_title,
            artist="Friend Artist",
            source=source,
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


def test_build_command_uses_search_or_url(tmp_path: Path) -> None:
    search_command = SoundCloudImportService._build_command(
        "Yeat 2TONE",
        tmp_path,
    )
    url_command = SoundCloudImportService._build_command(
        "https://soundcloud.com/lilyeat/2tone",
        tmp_path,
    )

    assert search_command[:5] == [
        soundcloud_import.sys.executable,
        "-m",
        "scdl.scdl",
        "-s",
        "Yeat 2TONE",
    ]
    assert url_command[:5] == [
        soundcloud_import.sys.executable,
        "-m",
        "scdl.scdl",
        "-l",
        "https://soundcloud.com/lilyeat/2tone",
    ]


def test_download_imports_the_audio_file(monkeypatch) -> None:
    ingestion_service = FakeIngestionService()

    def fake_run(command, **kwargs):
        output_directory = Path(
            command[command.index("--path") + 1]
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        (output_directory / "2tone.m4a").write_bytes(b"audio")
        assert kwargs["check"] is False
        assert kwargs["capture_output"] is True
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(soundcloud_import.subprocess, "run", fake_run)

    track = SoundCloudImportService(ingestion_service).download(
        "https://soundcloud.com/lilyeat/2tone"
    )

    assert track.source == "soundcloud_import"
    assert track.source_url == "https://soundcloud.com/lilyeat/2tone"
    assert ingestion_service.calls[0]["fallback_title"] == "2tone"


def test_download_reports_when_no_audio_is_produced(monkeypatch) -> None:
    def fake_run(command, **kwargs):
        return CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(soundcloud_import.subprocess, "run", fake_run)

    try:
        SoundCloudImportService(FakeIngestionService()).download(
            "Yeat 2TONE"
        )
    except RuntimeError as error:
        assert "did not provide an audio file" in str(error)
    else:
        raise AssertionError("Expected a missing audio file error")
