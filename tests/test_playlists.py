from app.domain.models import Track
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
