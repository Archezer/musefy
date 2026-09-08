from datetime import UTC, datetime

import pytest

pytest.importorskip("torch")

from app.domain.models import Recommendation, Track, User
from app.domain.recommendations import RecommendationMode
from app.ml.logistic_ranker import train_logistic_ranker
from app.ml.ranker import train_mlp_ranker
from app.ml.training_data import make_synthetic_ranker_dataset
from app.services.hybrid_recommendations import HybridRecommendationRanker
from app.storage.memory import InMemoryMusicStore


def _recommendations() -> list[Recommendation]:
    return [
        Recommendation(
            track=Track(id="track-1", title="One", artist="Artist"),
            score=0.8,
            reason="baseline",
            mode=RecommendationMode.POPULARITY,
        ),
        Recommendation(
            track=Track(id="track-2", title="Two", artist="Artist"),
            score=0.7,
            reason="baseline",
            mode=RecommendationMode.POPULARITY,
        ),
    ]


def test_hybrid_ranker_without_model_returns_baseline() -> None:
    store = InMemoryMusicStore()
    ranker = HybridRecommendationRanker(store)
    recommendations = _recommendations()

    result = ranker.rerank("user-1", recommendations)

    assert result == recommendations


def test_hybrid_ranker_scores_candidates_without_changing_the_candidate_set() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    for recommendation in _recommendations():
        store.add_track(recommendation.track)
    train = make_synthetic_ranker_dataset(
        user_count=3,
        examples_per_user=12,
        seed=23,
    )
    model = train_mlp_ranker(
        train,
        epochs=2,
        hidden_dims=(8,),
        dropout=0.0,
        seed=23,
    )
    ranker = HybridRecommendationRanker(
        store,
        model,
        model_weight=1.0,
    )

    result = ranker.rerank(
        "user-1",
        _recommendations(),
        shown_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert {recommendation.track.id for recommendation in result} == {
        "track-1",
        "track-2",
    }
    assert all(recommendation.score != 0.0 for recommendation in result)
    assert all(
        recommendation.baseline_score in {0.8, 0.7}
        for recommendation in result
    )


def test_hybrid_ranker_supports_logistic_ranker() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    recommendations = _recommendations()
    for recommendation in recommendations:
        store.add_track(recommendation.track)
    dataset = make_synthetic_ranker_dataset(
        user_count=3,
        examples_per_user=12,
        seed=23,
    )
    model = train_logistic_ranker(dataset)
    ranker = HybridRecommendationRanker(
        store,
        model,
        model_weight=1.0,
    )

    result = ranker.rerank(
        "user-1",
        recommendations,
        shown_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert {recommendation.track.id for recommendation in result} == {
        "track-1",
        "track-2",
    }
