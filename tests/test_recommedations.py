import pytest

from app.domain.models import (
    InteractionType,
    Track,
    User,
)
from app.recommenders.popularity import (
    ARTIST_PREFERENCE_FACTOR,
    MostPopularRecommender,
)
from app.services.interactions import InteractionService
from app.storage.memory import InMemoryMusicStore


@pytest.fixture
def store():
    store = InMemoryMusicStore()

    store.add_user(
        User(
            id="user-1",
            display_name="Test User",
        )
    )

    store.add_track(
        Track(
            id="track-liked",
            title="Liked Track",
            artist="Artist One",
        )
    )

    store.add_track(
        Track(
            id="track-other",
            title="Other Track",
            artist="Artist Two",
        )
    )

    return store


def test_like_increases_recommendation_score(store):

    InteractionService(store).record(
        user_id="user-1",
        track_id="track-liked",
        interaction_type=InteractionType.LIKE,
    )

    recommender = MostPopularRecommender(
        store,
        exploration_pool_size=1,
    )

    recommendations = recommender.recommend(
        user_id="user-1",
        limit=1,
    )

    assert len(recommendations) == 1
    assert (
        recommendations[0].track.id
        == "track-liked"
    )
    assert (
        recommendations[0].score
        == InteractionType.LIKE.weight
        * (1 + ARTIST_PREFERENCE_FACTOR)
    )


def test_skip_excludes_track_from_recommendations(store):

    InteractionService(store).record(
        user_id="user-1",
        track_id="track-liked",
        interaction_type=InteractionType.SKIP,
    )

    recommender = MostPopularRecommender(
        store,
        replay_cooldown=0,
        exploration_pool_size=1,
    )

    recommendations = recommender.recommend(
        user_id="user-1",
        limit=10,
    )

    assert recommendations
    assert all(
        recommendation.track.id
        != "track-liked"
        for recommendation in recommendations
    )


def test_save_increases_recommendation_score(store):
    InteractionService(store).record(
        user_id="user-1",
        track_id="track-liked",
        interaction_type=InteractionType.SAVE,
    )

    recommender = MostPopularRecommender(
        store,
        exploration_pool_size=1,
    )

    recommendations = recommender.recommend(
        user_id="user-1",
        limit=1,
    )

    assert recommendations[0].track.id == "track-liked"
    assert (
        recommendations[0].score
        == InteractionType.SAVE.weight
        * (1 + ARTIST_PREFERENCE_FACTOR)
    )
