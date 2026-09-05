from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import Interaction, InteractionType, Track, User
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
            mood_tags=(("mood/theme---dark", 0.91),),
            mood_profiles=(("dark", 0.88), ("energetic", 0.54)),
            mood_analysis_version="music2emo-v1",
        )
    )

    loaded_track = store.get_track("track-1")

    assert loaded_track is not None
    assert loaded_track.mood == MoodVector(
        valence=-0.6,
        arousal=0.8,
    )
    assert loaded_track.mood_tags == (("mood/theme---dark", 0.91),)
    assert loaded_track.mood_profiles == (
        ("dark", 0.88),
        ("energetic", 0.54),
    )
    assert loaded_track.mood_analysis_version == "music2emo-v1"


def test_recommendation_session_round_trip(
    store: SQLAlchemyMusicStore,
) -> None:
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="track-1",
            title="Track",
            artist="Artist",
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="track-1",
            interaction_type=InteractionType.PLAY_START,
            recommendation_session_id="radio-1",
        )
    )

    interactions = list(store.list_interactions())

    assert interactions[0].recommendation_session_id == "radio-1"


def test_sql_store_compacts_duplicate_preferences(
    store: SQLAlchemyMusicStore,
) -> None:
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="track-1",
            title="Track",
            artist="Artist",
        )
    )
    like = Interaction(
        user_id="user-1",
        track_id="track-1",
        interaction_type=InteractionType.LIKE,
    )
    store.add_interaction(like)
    store.add_interaction(like)

    assert store.compact_preference_interactions() == 1
    assert len(store.list_interactions()) == 1
