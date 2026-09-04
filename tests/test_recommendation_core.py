import pytest

from app.domain.models import (
    InteractionType,
    Track,
    User,
)
from app.domain.mood import MOOD_PRESETS
from app.domain.recommendations import RecommendationContext
from app.recommenders.mood import MoodRecommender
from app.recommenders.popularity import (
    MostPopularRecommender,
)
from app.services.interactions import InteractionService
from app.services.recommendations import RecommendationService
from app.storage.memory import InMemoryMusicStore


class RecordingRecommender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def recommend(
        self,
        user_id: str,
        limit: int = 10,
    ) -> list:
        self.calls.append((user_id, limit))
        return []


def make_store() -> InMemoryMusicStore:
    store = InMemoryMusicStore()

    store.add_user(
        User(
            id="user-1",
            display_name="Test User",
        )
    )
    store.add_user(
        User(
            id="user-2",
            display_name="Other User",
        )
    )

    store.add_track(
        Track(
            id="track-1",
            title="Track One",
            artist="Artist One",
        )
    )
    store.add_track(
        Track(
            id="track-2",
            title="Track Two",
            artist="Artist Two",
        )
    )

    return store


def test_recommendation_service_strips_user_id():
    recommender = RecordingRecommender()
    service = RecommendationService(recommender)

    assert service.get_recommendations(
        "  user-1  ",
        limit=3,
    ) == []
    assert recommender.calls == [("user-1", 3)]


def test_recommendation_service_rejects_empty_user_id():
    service = RecommendationService(
        RecordingRecommender()
    )

    with pytest.raises(
        ValueError,
        match="User ID must not be empty",
    ):
        service.get_recommendations("   ")


def test_recommender_rejects_invalid_limit():
    recommender = MostPopularRecommender(
        make_store()
    )

    with pytest.raises(
        ValueError,
        match="Recommendation limit must be positive",
    ):
        recommender.recommend("user-1", limit=0)


def test_recommender_rejects_invalid_configuration():
    store = make_store()

    with pytest.raises(
        ValueError,
        match="Replay cooldown must not be negative",
    ):
        MostPopularRecommender(
            store,
            replay_cooldown=-1,
        )

    with pytest.raises(
        ValueError,
        match="Exploration pool size must be positive",
    ):
        MostPopularRecommender(
            store,
            exploration_pool_size=0,
        )


def test_like_from_any_user_affects_global_popularity():
    store = make_store()

    InteractionService(store).record(
        user_id="user-2",
        track_id="track-1",
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

    assert recommendations[0].track.id == "track-1"
    assert recommendations[0].score == 4.0


def test_mood_context_does_not_affect_global_popularity():
    store = make_store()

    InteractionService(store).record(
        user_id="user-2",
        track_id="track-1",
        interaction_type=InteractionType.LIKE,
        mood_context="sad",
    )

    recommendations = MostPopularRecommender(
        store,
        exploration_pool_size=1,
    ).recommend(
        user_id="user-1",
        limit=1,
    )

    assert recommendations[0].score == 0.0


def test_mood_skip_is_scoped_to_the_same_mood():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="dark-track",
            title="Dark Track",
            artist="Artist One",
            mood=MOOD_PRESETS["dark"],
        )
    )
    store.add_track(
        Track(
            id="happy-track",
            title="Happy Track",
            artist="Artist Two",
            mood=MOOD_PRESETS["happy"],
        )
    )

    InteractionService(store).record(
        user_id="user-1",
        track_id="dark-track",
        interaction_type=InteractionType.SKIP,
        mood_context="sad",
    )

    recommender = MoodRecommender(
        store,
        replay_cooldown=0,
        exploration_pool_size=1,
    )
    same_mood = recommender.recommend(
        user_id="user-1",
        target_mood=MOOD_PRESETS["dark"],
        mood_name="sad",
        limit=10,
    )
    other_mood = recommender.recommend(
        user_id="user-1",
        target_mood=MOOD_PRESETS["dark"],
        mood_name="happy",
        limit=1,
    )

    assert [item.track.id for item in same_mood] == [
        "happy-track"
    ]
    assert other_mood[0].track.id == "dark-track"


def test_replay_cooldown_excludes_recently_played_track():
    store = make_store()

    InteractionService(store).record(
        user_id="user-1",
        track_id="track-1",
        interaction_type=InteractionType.PLAY,
    )

    recommender = MostPopularRecommender(
        store,
        replay_cooldown=1,
        exploration_pool_size=1,
    )

    recommendations = recommender.recommend(
        user_id="user-1",
        limit=10,
    )

    assert [
        recommendation.track.id
        for recommendation in recommendations
    ] == ["track-2"]


def test_selected_mood_prioritizes_matching_tracks():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="dark-track",
            title="Dark Track",
            artist="Artist One",
            mood=MOOD_PRESETS["dark"],
        )
    )
    store.add_track(
        Track(
            id="happy-track",
            title="Happy Track",
            artist="Artist Two",
            mood=MOOD_PRESETS["happy"],
        )
    )

    service = RecommendationService(
        MostPopularRecommender(
            store,
            exploration_pool_size=1,
        ),
        mood_recommender=MoodRecommender(store),
    )

    recommendations = service.get_recommendations(
        user_id="user-1",
        limit=1,
        context=RecommendationContext.mood(
            MOOD_PRESETS["dark"]
        ),
    )

    assert recommendations[0].track.id == "dark-track"
    assert recommendations[0].reason == "Matches the selected mood"


def test_selected_mood_ignores_large_interaction_score():
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="dark-track",
            title="Dark Track",
            artist="Dark Artist",
            mood=MOOD_PRESETS["dark"],
        )
    )
    store.add_track(
        Track(
            id="happy-track",
            title="Happy Track",
            artist="Happy Artist",
            mood=MOOD_PRESETS["happy"],
        )
    )

    interactions = InteractionService(store)
    for _ in range(20):
        interactions.record(
            user_id="user-1",
            track_id="happy-track",
            interaction_type=InteractionType.PLAY,
        )

    service = RecommendationService(
        MostPopularRecommender(
            store,
            exploration_pool_size=1,
        ),
        mood_recommender=MoodRecommender(store),
    )
    recommendations = service.get_recommendations(
        user_id="user-1",
        limit=1,
        context=RecommendationContext.mood(
            MOOD_PRESETS["dark"]
        ),
    )

    assert recommendations[0].track.id == "dark-track"


def test_my_wave_uses_positive_user_history() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="favorite",
            title="Favorite",
            artist="Favorite Artist",
            mood=MOOD_PRESETS["dark"],
            track_embedding=(1.0, 0.0),
        )
    )
    store.add_track(
        Track(
            id="similar",
            title="Similar",
            artist="Other Artist",
            mood=MOOD_PRESETS["dark"],
            track_embedding=(0.9, 0.1),
        )
    )
    store.add_track(
        Track(
            id="different",
            title="Different",
            artist="Other Artist",
            mood=MOOD_PRESETS["happy"],
            track_embedding=(-1.0, 0.0),
        )
    )
    InteractionService(store).record(
        user_id="user-1",
        track_id="favorite",
        interaction_type=InteractionType.LIKE,
    )

    service = RecommendationService(
        MostPopularRecommender(store, exploration_pool_size=1),
        mood_recommender=MoodRecommender(
            store,
            replay_cooldown=0,
            exploration_pool_size=1,
        ),
    )
    recommendations = service.get_recommendations(
        user_id="user-1",
        limit=2,
        context=RecommendationContext.my_wave(),
    )

    assert [item.track.id for item in recommendations] == [
        "similar",
        "different",
    ]
    assert recommendations[0].mode.value == "my_wave"
    assert recommendations[0].reason == "Based on your listening history"
