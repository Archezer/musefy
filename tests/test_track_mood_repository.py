from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import Track
from app.domain.mood import MoodVector
from app.storage.models import Base
from app.storage.repository import SQLAlchemyMusicStore


@pytest.fixture
def store(tmp_path: Path) -> Iterator[SQLAlchemyMusicStore]:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'tracks.db').as_posix()}"
    )
    Base.metadata.create_all(engine)

    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    yield SQLAlchemyMusicStore(session_factory)
    engine.dispose()


def test_track_mood_round_trip(
    store: SQLAlchemyMusicStore,
) -> None:
    store.add_track(
        Track(
            id="track-1",
            title="Dark track",
            artist="Artist",
            mood=MoodVector(
                valence=-0.6,
                arousal=0.8,
            ),
        )
    )

    loaded_track = store.get_track("track-1")

    assert loaded_track is not None
    assert loaded_track.mood == MoodVector(
        valence=-0.6,
        arousal=0.8,
    )
