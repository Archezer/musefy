import app.ingestion.audio as audio_module
from app.domain.models import Track
from app.ingestion.audio import AudioIngestionService
from app.storage.memory import InMemoryMusicStore


def test_ensure_cover_can_replace_existing_artwork(tmp_path, monkeypatch) -> None:
    store = InMemoryMusicStore()
    existing_cover = tmp_path / "old-cover.jpg"
    existing_cover.touch()
    track = Track(
        id="track-1",
        title="Title",
        artist="Artist",
        cover_path=str(existing_cover),
    )
    store.add_track(track)
    spotify_cover = tmp_path / "spotify-cover.jpg"
    spotify_cover.touch()
    monkeypatch.setattr(
        audio_module,
        "save_remote_artwork",
        lambda url, track_id: (
            str(spotify_cover)
            if url == "https://i.scdn.co/image/spotify-cover"
            and track_id == "track-1"
            else None
        ),
    )

    updated_track = AudioIngestionService(store).ensure_cover(
        track,
        cover_url="https://i.scdn.co/image/spotify-cover",
        replace_existing=True,
    )

    assert updated_track.cover_path == str(spotify_cover)
    assert store.get_track("track-1") == updated_track
