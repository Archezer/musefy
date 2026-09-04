from datetime import UTC, datetime, timedelta

import pytest

from app.domain.models import (
    Interaction,
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


def test_play_start_is_telemetry_not_positive_signal():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(id="started", title="Started", artist="Z Artist")
    )
    store.add_track(
        Track(id="fresh", title="Fresh", artist="A Artist")
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="started",
            interaction_type=InteractionType.PLAY_START,
        )
    )

    recommendations = MostPopularRecommender(
        store,
        replay_cooldown=0,
        exploration_pool_size=1,
    ).recommend("user-1", limit=1)

    assert recommendations[0].track.id == "fresh"
    assert recommendations[0].score == 0.0


def test_playback_interest_decays_at_configured_half_life():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(id="recent", title="Recent", artist="Artist A")
    )
    store.add_track(
        Track(id="old", title="Old", artist="Artist B")
    )
    now = datetime(2026, 9, 4, tzinfo=UTC)
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="recent",
            interaction_type=InteractionType.PLAYED_30S,
            created_at=now,
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="old",
            interaction_type=InteractionType.PLAYED_30S,
            created_at=now - timedelta(days=45),
        )
    )

    recommendations = MostPopularRecommender(
        store,
        replay_cooldown=0,
        exploration_pool_size=2,
    ).recommend("user-1", limit=2, now=now)

    scores = {item.track.id: item.score for item in recommendations}
    assert scores["recent"] == pytest.approx(1.5)
    assert scores["old"] == pytest.approx(0.75)


def test_skip_expires_but_do_not_recommend_remains_permanent():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(Track(id="snoozed", title="Snoozed", artist="A"))
    store.add_track(Track(id="blocked", title="Blocked", artist="B"))
    now = datetime(2026, 9, 4, tzinfo=UTC)
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="snoozed",
            interaction_type=InteractionType.SKIP,
            created_at=now - timedelta(days=15),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="blocked",
            interaction_type=InteractionType.DO_NOT_RECOMMEND,
            created_at=now - timedelta(days=365),
        )
    )

    recommendations = MostPopularRecommender(
        store,
        replay_cooldown=0,
        exploration_pool_size=1,
    ).recommend("user-1", limit=10, now=now)

    assert [item.track.id for item in recommendations] == ["snoozed"]


def test_manual_play_does_not_clear_permanent_block_until_allowed():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(Track(id="blocked", title="Blocked", artist="A"))
    store.add_track(Track(id="other", title="Other", artist="B"))
    now = datetime(2026, 9, 4, tzinfo=UTC)
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="blocked",
            interaction_type=InteractionType.DO_NOT_RECOMMEND,
            created_at=now - timedelta(days=10),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="blocked",
            interaction_type=InteractionType.PLAY_START,
            created_at=now - timedelta(days=1),
        )
    )

    recommender = MostPopularRecommender(
        store,
        replay_cooldown=0,
        exploration_pool_size=1,
    )
    assert [item.track.id for item in recommender.recommend(
        "user-1", limit=10, now=now
    )] == ["other"]

    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="blocked",
            interaction_type=InteractionType.ALLOW_RECOMMEND,
            created_at=now,
        )
    )
    assert {item.track.id for item in recommender.recommend(
        "user-1", limit=10, now=now
    )} == {"blocked", "other"}
