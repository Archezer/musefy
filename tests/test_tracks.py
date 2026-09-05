from pathlib import Path

import app.services.tracks as tracks_service
from app.domain.models import DetectedGenre, Playlist, PlaylistEntry, Track
from app.services.playlists import PlaylistManagementService
from app.services.tracks import TrackManagementService
from app.storage.memory import InMemoryMusicStore


def test_analysis_is_shared_by_every_playlist_reference() -> None:
    store = InMemoryMusicStore()
    track = Track(
        id="shared-track",
        title="Shared track",
        artist="Artist",
    )
    store.add_track(track)
    first_playlist = Playlist(id="playlist-1", name="First")
    second_playlist = Playlist(id="playlist-2", name="Second")
    store.add_playlist(first_playlist)
    store.add_playlist(second_playlist)
    store.replace_playlist_entries(
        first_playlist.id,
        [PlaylistEntry(first_playlist.id, track.id, 0)],
    )
    store.replace_playlist_entries(
        second_playlist.id,
        [PlaylistEntry(second_playlist.id, track.id, 0)],
    )

    detected = DetectedGenre(
        genre="Rock---Black Metal",
        parent_genre="Rock",
        subgenre="Black Metal",
        score=0.9,
        rank=1,
        rank_weight=1.0,
        weighted_score=0.9,
    )
    TrackManagementService(store).update_detected_genres(
        track_id=track.id,
        detected_genres=(detected,),
        track_embedding=(1.0, 0.0),
    )

    playlist_service = PlaylistManagementService(store)
    assert playlist_service.get_playlist_tracks(first_playlist.id)[0].genres == (
        "rock",
    )
    assert playlist_service.get_playlist_tracks(second_playlist.id)[0].detected_genres == (
        detected,
    )


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
