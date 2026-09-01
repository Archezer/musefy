from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.domain.models import Track
from app.services.playlists import PlaylistManagementService
from app.storage.models import Base
from app.storage.repository import SQLAlchemyMusicStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SQLAlchemyMusicStore]:
    database_path = tmp_path / "playlists.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}"
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys = ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    music_store = SQLAlchemyMusicStore(session_factory)

    yield music_store

    engine.dispose()


def test_playlist_entries_persist_and_follow_track_deletion(
    store: SQLAlchemyMusicStore,
) -> None:
    store.add_track(
        Track(
            id="track-1",
            title="Track One",
            artist="Artist One",
        )
    )
    service = PlaylistManagementService(store)
    playlist = service.create_playlist("Persistent playlist")

    service.add_track(playlist.id, "track-1")

    assert [
        track.id
        for track in service.get_playlist_tracks(playlist.id)
    ] == ["track-1"]

    store.delete_track("track-1")

    assert list(store.list_playlist_entries(playlist.id)) == []
