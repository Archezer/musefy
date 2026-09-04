from pathlib import Path
from typing import Self

import app.services.playlists as playlist_service_module
from app.domain.models import PlaylistEntry, Track
from app.services.playlists import PlaylistManagementService
from app.storage.memory import InMemoryMusicStore


def make_service() -> PlaylistManagementService:
    store = InMemoryMusicStore()
    store.add_track(
        Track(
            id="track-1",
            title="Track One",
            artist="Artist One",
        )
    )
    store.add_track(
        Track(
            id="track-2",
            title="Track Two",
            artist="Artist Two",
        )
    )

    return PlaylistManagementService(store)


def test_playlist_tracks_keep_their_order() -> None:
    service = make_service()
    playlist = service.create_playlist("Road trip")

    service.add_track(playlist.id, "track-2")
    service.add_track(playlist.id, "track-1")

    assert [
        track.id
        for track in service.get_playlist_tracks(playlist.id)
    ] == ["track-2", "track-1"]


def test_removing_one_duplicate_keeps_the_other() -> None:
    service = make_service()
    playlist = service.create_playlist("Duplicates")

    service.add_track(playlist.id, "track-1")
    service.add_track(playlist.id, "track-2")
    service.add_track(playlist.id, "track-1")
    service.remove_track_at(playlist.id, 0)

    assert [
        track.id
        for track in service.get_playlist_tracks(playlist.id)
    ] == ["track-2", "track-1"]


def test_adding_track_repairs_non_consecutive_playlist_positions() -> None:
    service = make_service()
    playlist = service.create_playlist("Repair positions")

    service.replace_tracks(playlist.id, ("track-1", "track-2"))
    # Simulate a legacy database row left with a gap after a track cascade.
    service.store.playlist_entries[playlist.id][1] = PlaylistEntry(
        playlist_id=playlist.id,
        track_id="track-2",
        position=2,
    )

    service.add_track(playlist.id, "track-1")

    entries = service.store.list_playlist_entries(playlist.id)
    assert [entry.position for entry in entries] == [0, 1, 2]


def test_remove_track_removes_the_first_matching_occurrence() -> None:
    service = make_service()
    playlist = service.create_playlist("Remove track")
    service.replace_tracks(
        playlist.id,
        ("track-1", "track-2", "track-1"),
    )

    service.remove_track(playlist.id, "track-1")

    assert [
        track.id
        for track in service.get_playlist_tracks(playlist.id)
    ] == ["track-2", "track-1"]


def test_renaming_a_playlist_preserves_entries() -> None:
    service = make_service()
    playlist = service.create_playlist("Old name")
    service.add_track(playlist.id, "track-1")

    updated_playlist = service.rename_playlist(
        playlist.id,
        "New name",
    )

    assert updated_playlist.name == "New name"
    assert [
        track.id
        for track in service.get_playlist_tracks(playlist.id)
    ] == ["track-1"]


def test_playlist_artwork_is_copied_and_persisted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = make_service()
    playlist = service.create_playlist("Artwork")
    source = tmp_path / "cover.png"
    source.write_bytes(b"not-a-real-png-but-a-valid-user-file")
    covers_directory = tmp_path / "playlist_covers"
    monkeypatch.setattr(
        playlist_service_module,
        "PLAYLIST_COVERS_DIR",
        covers_directory,
    )

    updated_playlist = service.set_cover(playlist.id, source)

    assert updated_playlist.cover_path is not None
    copied_cover = Path(updated_playlist.cover_path)
    assert copied_cover.parent == covers_directory
    assert copied_cover.read_bytes() == source.read_bytes()
    assert service.store.get_playlist(playlist.id) == updated_playlist


def test_playlist_artwork_can_be_downloaded_from_export_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class FakeHeaders:
        @staticmethod
        def get_content_type() -> str:
            return "image/png"

    class FakeResponse:
        headers = FakeHeaders()

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        @staticmethod
        def read(_size: int) -> bytes:
            return b"\x89PNG\r\n\x1a\ncover"

    service = make_service()
    playlist = service.create_playlist("Remote artwork")
    covers_directory = tmp_path / "playlist_covers"
    monkeypatch.setattr(
        playlist_service_module,
        "PLAYLIST_COVERS_DIR",
        covers_directory,
    )
    monkeypatch.setattr(
        playlist_service_module,
        "urlopen",
        lambda _request, timeout: FakeResponse(),
    )

    updated_playlist = service.set_cover_from_url(
        playlist.id,
        "https://example.com/cover.png",
    )

    assert updated_playlist.cover_path is not None
    assert Path(updated_playlist.cover_path).read_bytes().startswith(
        b"\x89PNG"
    )
