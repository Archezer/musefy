from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.domain.models import (
    Interaction,
    InteractionType,
    Playlist,
    PlaylistEntry,
    Track,
    User,
)
from app.ingestion.metadata import AudioMetadata
from app.services import library_maintenance
from app.services.library_maintenance import (
    LibraryBackupService,
    LibraryHealthService,
)
from app.storage.memory import InMemoryMusicStore


def test_health_scan_reports_missing_broken_and_identical_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate_file = tmp_path / "duplicate.mp3"
    duplicate_file.write_bytes(b"same bytes")
    broken_file = tmp_path / "broken.mp3"
    broken_file.write_bytes(b"not audio")

    store = InMemoryMusicStore()
    for track in (
        Track(id="missing", title="Missing", artist="Artist", local_path=str(tmp_path / "gone.mp3")),
        Track(id="one", title="One", artist="Artist", duration_ms=120_000, local_path=str(duplicate_file)),
        Track(id="two", title="Two", artist="Artist", duration_ms=120_000, local_path=str(duplicate_file)),
        Track(id="broken", title="Broken", artist="Artist", local_path=str(broken_file)),
    ):
        store.add_track(track)

    def fake_metadata(path: Path) -> AudioMetadata:
        if path == broken_file:
            raise ValueError("unsupported or unreadable")
        return AudioMetadata(None, None, 120_000)

    monkeypatch.setattr(library_maintenance, "read_audio_metadata", fake_metadata)
    monkeypatch.setattr(
        LibraryHealthService,
        "_acoustic_fingerprint",
        staticmethod(lambda _path: (1.0, 0.0)),
    )

    report = LibraryHealthService(store).scan()

    assert [issue.track.id for issue in report.missing_files] == ["missing"]
    assert [issue.track.id for issue in report.broken_audio] == ["broken"]
    assert len(report.exact_duplicates) == 1
    assert {track.id for track in report.exact_duplicates[0].tracks} == {"one", "two"}
    assert report.acoustic_duplicates == ()


def test_backup_creates_json_and_restorable_zip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    library_dir = data_dir / "library"
    library_dir.mkdir(parents=True)
    (data_dir / "music.db").write_bytes(b"database snapshot")
    (library_dir / "song.flac").write_bytes(b"audio snapshot")
    monkeypatch.setattr(library_maintenance, "DATA_DIR", data_dir)

    store = InMemoryMusicStore()
    created_at = datetime(2026, 1, 2, tzinfo=UTC)
    user = User(id="user-1", display_name="Alex", created_at=created_at)
    track = Track(
        id="track-1",
        title="Track",
        artist="Artist",
        created_at=created_at,
        genres=("ambient",),
        track_embedding=(0.2, 0.8),
        local_path=str(library_dir / "song.flac"),
    )
    playlist = Playlist(id="playlist-1", name="Favorites", created_at=created_at)
    store.add_user(user)
    store.add_track(track)
    store.add_playlist(playlist)
    store.replace_playlist_entries(
        playlist.id,
        [PlaylistEntry(playlist.id, track.id, 0)],
    )
    store.add_interaction(
        Interaction(user.id, track.id, InteractionType.LIKE, created_at)
    )

    service = LibraryBackupService(store)
    json_path = tmp_path / "export.json"
    zip_path = tmp_path / "backup.zip"

    json_summary = service.export_json(json_path)
    zip_summary = service.create_zip_backup(zip_path)

    assert json_summary.includes_audio is False
    assert zip_summary.includes_audio is True
    assert '"track_embedding": [' in json_path.read_text(encoding="utf-8")
    with ZipFile(zip_path) as archive:
        assert "manifest.json" in archive.namelist()
        assert "library.json" in archive.namelist()
        assert "data/music.db" in archive.namelist()
        assert "data/library/song.flac" in archive.namelist()

    (data_dir / "music.db").write_bytes(b"changed")
    (library_dir / "song.flac").unlink()
    service.restore_zip_backup(zip_path)

    assert (data_dir / "music.db").read_bytes() == b"database snapshot"
    assert (library_dir / "song.flac").read_bytes() == b"audio snapshot"
