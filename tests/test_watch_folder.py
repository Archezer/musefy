import shutil
from pathlib import Path

from app.domain.models import Track
from app.services import watch_folder
from app.services.watch_folder import WatchFolderService
from app.storage.memory import InMemoryMusicStore


class FakeIngestion:
    def __init__(self, store: InMemoryMusicStore, managed_dir: Path) -> None:
        self.store = store
        self.managed_dir = managed_dir
        self.counter = 0

    def ingest(self, path: Path, *, source: str, source_id: str) -> Track:
        self.counter += 1
        managed_path = self.managed_dir / f"copy-{self.counter}.mp3"
        shutil.copy2(path, managed_path)
        track = Track(
            id=f"track-{self.counter}",
            title=path.stem,
            artist="Unknown Artist",
            source=source,
            source_id=source_id,
            local_path=str(managed_path),
            duration_ms=1000,
        )
        self.store.add_track(track)
        return track


class FakeTrackManagement:
    def update_metadata(self, **_kwargs) -> Track:
        raise AssertionError("metadata update is not expected in this test")


def test_watch_folder_is_incremental_and_reports_removed_source(
    tmp_path: Path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    config_path = data_dir / "watch-folder.json"
    folder = tmp_path / "watch"
    managed = tmp_path / "managed"
    folder.mkdir()
    managed.mkdir()
    data_dir.mkdir()
    song = folder / "song.mp3"
    song.write_bytes(b"audio")
    monkeypatch.setattr(watch_folder, "DATA_DIR", data_dir)
    monkeypatch.setattr(watch_folder, "WATCH_CONFIG_PATH", config_path)

    store = InMemoryMusicStore()
    service = WatchFolderService(store)
    service.configure(folder)
    ingestion = FakeIngestion(store, managed)
    management = FakeTrackManagement()

    first = service.sync(ingestion, management)
    second = service.sync(ingestion, management)
    song.unlink()
    third = service.sync(ingestion, management)

    assert len(first.imported) == 1
    assert second.skipped == 1
    assert len(third.removed_files) == 1
    assert len(third.removed_tracks) == 1
