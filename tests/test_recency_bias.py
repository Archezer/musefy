from datetime import UTC, datetime, timedelta
from random import Random

from app.domain.models import Track, User
from app.recommenders.popularity import MostPopularRecommender
from app.recommenders.recency import MAX_RECENCY_BONUS, recency_bonus
from app.storage.memory import InMemoryMusicStore


def test_recency_bonus_decays_from_recent_track() -> None:
    now = datetime(2026, 9, 7, tzinfo=UTC)
    newest = Track(id="new", title="New", artist="Artist", created_at=now)
    older = Track(
        id="old",
        title="Old",
        artist="Artist",
        created_at=now - timedelta(days=365),
    )

    assert recency_bonus(newest, now=now) == MAX_RECENCY_BONUS
    assert recency_bonus(older, now=now) == MAX_RECENCY_BONUS / 2


def test_popularity_gives_newer_track_a_small_tie_breaking_priority() -> None:
    now = datetime(2026, 9, 7, tzinfo=UTC)
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="old",
            title="A track",
            artist="Artist",
            created_at=now - timedelta(days=10),
        )
    )
    store.add_track(
        Track(
            id="new",
            title="Z track",
            artist="Artist",
            created_at=now,
        )
    )

    recommendations = MostPopularRecommender(
        store,
        exploration_pool_size=1,
        random_generator=Random(4),
    ).recommend(
        "user-1",
        limit=1,
        now=now,
    )

    assert recommendations[0].track.id == "new"
