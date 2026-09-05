from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.models import (
    Interaction,
    InteractionType,
    Recommendation,
    Track,
    User,
)
from app.domain.recommendations import RecommendationMode
from app.services.recommendation_analytics import (
    RecommendationAnalyticsService,
)
from app.storage.memory import InMemoryMusicStore
from app.storage.models import Base
from app.storage.repository import SQLAlchemyMusicStore


@pytest.fixture
def sql_store(tmp_path: Path) -> Iterator[SQLAlchemyMusicStore]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'analytics.db').as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )
    yield SQLAlchemyMusicStore(session_factory)
    engine.dispose()


def test_recommendation_metrics_attribute_follow_up_events() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(Track(id="track-1", title="One", artist="Artist A"))
    store.add_track(Track(id="track-2", title="Two", artist="Artist B"))
    service = RecommendationAnalyticsService(store)
    shown_at = datetime(2026, 1, 1, tzinfo=UTC)
    recommendations = [
        Recommendation(
            track=store.get_track("track-1"),  # type: ignore[arg-type]
            score=0.9,
            reason="Because",
            mode=RecommendationMode.MY_WAVE,
        ),
        Recommendation(
            track=store.get_track("track-2"),  # type: ignore[arg-type]
            score=0.8,
            reason="Because",
            mode=RecommendationMode.MY_WAVE,
        ),
    ]
    service.record_impressions(
        "user-1",
        recommendations,
        session_id="wave-1",
        shown_at=shown_at,
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="track-1",
            interaction_type=InteractionType.PLAY_START,
            created_at=shown_at + timedelta(hours=1),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="track-1",
            interaction_type=InteractionType.COMPLETED_80,
            created_at=shown_at + timedelta(hours=2),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="track-2",
            interaction_type=InteractionType.PLAY_START,
            created_at=shown_at + timedelta(hours=1),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="track-2",
            interaction_type=InteractionType.SKIP,
            created_at=shown_at + timedelta(hours=1, minutes=1),
        )
    )

    metrics = service.build(
        "user-1",
        now=shown_at + timedelta(days=1),
        days=30,
    )

    assert metrics.impressions == 2
    assert metrics.started == 2
    assert metrics.completed == 1
    assert metrics.skipped == 1
    assert metrics.completion_rate == 0.5
    assert metrics.skip_rate == 0.5
    assert metrics.recall_at_10 == 1.0
    assert metrics.ndcg_at_10 == 1.0
    assert metrics.artist_diversity == 1.0


def test_old_impression_does_not_attribute_events_after_window() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(Track(id="track-1", title="One", artist="Artist"))
    service = RecommendationAnalyticsService(store, attribution_days=1)
    shown_at = datetime(2026, 1, 1, tzinfo=UTC)
    recommendation = Recommendation(
        track=store.get_track("track-1"),  # type: ignore[arg-type]
        score=1.0,
        reason="Because",
    )
    service.record_impressions("user-1", [recommendation], shown_at=shown_at)
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="track-1",
            interaction_type=InteractionType.PLAY_START,
            created_at=shown_at + timedelta(days=2),
        )
    )

    metrics = service.build(
        "user-1",
        now=shown_at + timedelta(days=3),
        days=30,
    )

    assert metrics.started == 0


def test_impression_positions_continue_across_batches() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    first_track = Track(id="track-1", title="One", artist="Artist A")
    second_track = Track(id="track-2", title="Two", artist="Artist B")
    store.add_track(first_track)
    store.add_track(second_track)
    service = RecommendationAnalyticsService(store)

    service.record_impressions(
        "user-1",
        [
            Recommendation(
                track=first_track,
                score=0.9,
                reason="Because",
                mode=RecommendationMode.MOOD,
            )
        ],
        session_id="mood-1",
    )
    service.record_impressions(
        "user-1",
        [
            Recommendation(
                track=second_track,
                score=0.8,
                reason="Because",
                mode=RecommendationMode.MOOD,
            )
        ],
        session_id="mood-1",
        position_offset=1,
    )

    impressions = list(store.list_recommendation_impressions())
    assert [impression.position for impression in impressions] == [1, 2]
    assert {impression.session_id for impression in impressions} == {"mood-1"}


def test_linked_playback_only_attributes_to_its_recommendation_session() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    track = Track(id="track-1", title="One", artist="Artist")
    store.add_track(track)
    service = RecommendationAnalyticsService(store)
    shown_at = datetime(2026, 1, 1, tzinfo=UTC)
    recommendation = Recommendation(
        track=track,
        score=1.0,
        reason="Because",
        mode=RecommendationMode.MOOD,
    )
    service.record_impressions(
        "user-1",
        [recommendation],
        session_id="mood-1",
        shown_at=shown_at,
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id=track.id,
            interaction_type=InteractionType.PLAY_START,
            created_at=shown_at + timedelta(hours=1),
            recommendation_session_id="different-session",
        )
    )

    metrics = service.build(
        "user-1",
        now=shown_at + timedelta(days=1),
        days=30,
    )

    assert metrics.started == 0


def test_sqlalchemy_impressions_round_trip_and_track_cleanup(
    sql_store: SQLAlchemyMusicStore,
) -> None:
    sql_store.add_user(User(id="user-1", display_name="Test User"))
    track = Track(id="track-1", title="One", artist="Artist")
    sql_store.add_track(track)
    service = RecommendationAnalyticsService(sql_store)
    recommendation = Recommendation(
        track=track,
        score=0.75,
        reason="Because",
        mode=RecommendationMode.MY_WAVE,
    )

    service.record_impressions(
        "user-1",
        [recommendation],
        session_id="wave-1",
    )

    impressions = list(sql_store.list_recommendation_impressions())
    assert len(impressions) == 1
    assert impressions[0].mode == RecommendationMode.MY_WAVE
    assert impressions[0].session_id == "wave-1"

    sql_store.delete_track("track-1")
    assert list(sql_store.list_recommendation_impressions()) == []
