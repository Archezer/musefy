from app.domain.genres import popular_user_genres, track_genre_evidence
from app.domain.models import DetectedGenre, Interaction, InteractionType, Track, User
from app.domain.recommendations import RecommendationContext, RecommendationMode
from app.recommenders.popularity import MostPopularRecommender
from app.storage.memory import InMemoryMusicStore


def test_detected_genres_take_priority_over_parent_metadata() -> None:
    track = Track(
        id="shoegaze",
        title="Shoegaze track",
        artist="Artist",
        genres=("alternative",),
        detected_genres=(
            DetectedGenre(
                genre="Alternative---Shoegaze",
                parent_genre="Alternative",
                subgenre="Shoegaze",
                score=0.9,
                rank=1,
                rank_weight=1.0,
                weighted_score=0.9,
            ),
        ),
    )

    assert track_genre_evidence(track) == (("Shoegaze", 0.9),)


def test_popular_user_genres_use_history_and_fill_from_catalogue() -> None:
    tracks = [
        Track(id="one", title="One", artist="A", genres=("ambient",)),
        Track(id="two", title="Two", artist="B", genres=("phonk",)),
        Track(id="three", title="Three", artist="C", genres=("ambient",)),
    ]
    interactions = [
        Interaction(
            user_id="user-1",
            track_id="two",
            interaction_type=InteractionType.LIKE,
        )
    ]

    assert popular_user_genres(
        tracks,
        interactions,
        "user-1",
        limit=2,
    ) == ("Phonk",)
    assert popular_user_genres(
        tracks,
        (),
        "user-1",
        limit=2,
    ) == ("Ambient", "Phonk")


def test_genre_context_and_recommender_select_matching_tracks() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="User"))
    store.add_track(
        Track(id="ambient", title="Ambient", artist="A", genres=("ambient",))
    )
    store.add_track(
        Track(id="phonk", title="Phonk", artist="B", genres=("phonk",))
    )

    context = RecommendationContext.genre("Phonk")
    assert context.mode == RecommendationMode.GENRE
    assert [
        item.track.id
        for item in MostPopularRecommender(store, replay_cooldown=0).recommend_genre(
            "user-1",
            context.genre_name or "",
            limit=10,
        )
    ] == ["phonk"]
