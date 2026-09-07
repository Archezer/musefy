from datetime import UTC, datetime, timedelta

from app.domain.models import (
    Interaction,
    InteractionType,
    RecommendationImpression,
    Track,
    User,
)
from app.domain.recommendations import RecommendationMode
from app.ml.training_data import inspect_ranker_data
from app.storage.memory import InMemoryMusicStore


def test_ranker_readiness_reports_missing_data() -> None:
    store = InMemoryMusicStore()

    readiness = inspect_ranker_data(store, minimum_examples=2)

    assert readiness.status == "collecting_data"
    assert readiness.total_impressions == 0
    assert readiness.labelled_examples == 0


def test_ranker_readiness_counts_explicit_labels_only() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    shown_at = datetime(2026, 1, 1, tzinfo=UTC)
    for track_id in ("positive", "negative"):
        store.add_track(Track(id=track_id, title=track_id, artist="Artist"))
    store.add_recommendation_impression(
        RecommendationImpression(
            user_id="user-1",
            track_id="positive",
            mode=RecommendationMode.POPULARITY,
            position=1,
            score=0.8,
            shown_at=shown_at,
            feature_snapshot=(("baseline_score", 0.8),),
        )
    )
    store.add_recommendation_impression(
        RecommendationImpression(
            user_id="user-1",
            track_id="negative",
            mode=RecommendationMode.POPULARITY,
            position=2,
            score=0.7,
            shown_at=shown_at,
            feature_snapshot=(("baseline_score", 0.7),),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="positive",
            interaction_type=InteractionType.LIKE,
            created_at=shown_at + timedelta(minutes=1),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="negative",
            interaction_type=InteractionType.DISLIKE,
            created_at=shown_at + timedelta(minutes=1),
        )
    )

    readiness = inspect_ranker_data(store, minimum_examples=2)

    assert readiness.status == "ready"
    assert readiness.total_impressions == 2
    assert readiness.snapshot_impressions == 2
    assert readiness.labelled_examples == 2
    assert readiness.positive_examples == 1
    assert readiness.negative_examples == 1
