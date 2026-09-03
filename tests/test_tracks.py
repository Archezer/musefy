from pathlib import Path

import app.services.tracks as tracks_service
from app.domain.models import Track
from app.services.tracks import TrackManagementService
from app.storage.memory import InMemoryMusicStore


def test_delete_track_removes_record_when_file_is_missing(
    tmp_path: Path,
) -> None:
    store = InMemoryMusicStore()
    track = Track(
        id="track-missing-file",
        title="Missing file",
        artist="Artist",
        local_path=str(tmp_path / "missing.mp3"),
    )
    store.add_track(track)

    TrackManagementService(store).delete_track(track.id)

    assert store.get_track(track.id) is None


def test_delete_track_keeps_unmanaged_file_but_removes_record(
    tmp_path: Path,
    monkeypatch,
) -> None:
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    unmanaged_file = tmp_path / "outside-library.mp3"
    unmanaged_file.write_bytes(b"audio")

    monkeypatch.setattr(tracks_service, "LIBRARY_DIR", library_dir)

    store = InMemoryMusicStore()
    track = Track(
        id="track-moved-file",
        title="Moved file",
        artist="Artist",
        local_path=str(unmanaged_file),
    )
    store.add_track(track)

    TrackManagementService(store).delete_track(track.id)

    assert store.get_track(track.id) is None
    assert unmanaged_file.exists()
