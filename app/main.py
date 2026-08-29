from app.domain.models import (
    Interaction,
    InteractionType,
    Track,
    User,
)
from app.recommenders.popularity import MostPopularRecommender
from app.services.recommendations import RecommendationService
from app.storage.database import (
    create_database,
    create_session,
)
from app.storage.repository import SQLAlchemyMusicStore


def build_store() -> SQLAlchemyMusicStore:
    create_database()

    store = SQLAlchemyMusicStore(
        create_session
    )

    seed_users = [
        User(
            id="user-1",
            display_name="Alex",
        ),
        User(
            id="user-2",
            display_name="Mira",
        ),
        User(
            id="user-3",
            display_name="Nikita",
        ),
    ]

    for user in seed_users:
        if store.get_user(user.id) is None:
            store.add_user(user)

    if store.list_tracks():
        return store

    tracks = [
        Track(
            id="track-1",
            title="Everything In Its Right Place",
            artist="Radiohead",
            genres=("alternative", "electronic"),
        ),
        Track(
            id="track-2",
            title="Teardrop",
            artist="Massive Attack",
            genres=("trip-hop", "electronic"),
        ),
        Track(
            id="track-3",
            title="Roads",
            artist="Portishead",
            genres=("trip-hop",),
        ),
        Track(
            id="track-4",
            title="Hyperballad",
            artist="Björk",
            genres=("alternative", "electronic"),
        )
    ]

    for track in tracks:
        store.add_track(track)

    interactions = [
        Interaction(
            user_id="user-1",
            track_id="track-1",
            interaction_type=InteractionType.PLAY,
        ),
        Interaction(
            user_id="user-2",
            track_id="track-2",
            interaction_type=InteractionType.LIKE,
        ),
        Interaction(
            user_id="user-3",
            track_id="track-2",
            interaction_type=InteractionType.LIKE,
        ),
        Interaction(
            user_id="user-2",
            track_id="track-3",
            interaction_type=InteractionType.SAVE,
        )
    ]

    for interaction in interactions:
        store.add_interaction(interaction)

    return store

def main() -> None:
    store =  build_store()
    recommender = MostPopularRecommender(store)
    recommendation_service = RecommendationService(recommender)

    recommendations = recommendation_service.get_recommendations(
        user_id="user-1",
        limit=3,
    )

    print("Recommendations for user-1:")

    for position, recommendation in enumerate(
        recommendations,
        start=1,
    ):
        track = recommendation.track

        print(
            f"{position}. {track.artist} — {track.title}"
        )
        print(f"   Score: {recommendation.score}")
        print(f"   Reason: {recommendation.reason}")
        
if __name__ == '__main__':
    main()