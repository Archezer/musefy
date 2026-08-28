from app.domain.models import Interaction, InteractionType, Track
from app.recommenders.popularity import MostPopularRecommender
from app.storage.memory import InMemoryMusicStore


def build_store() -> InMemoryMusicStore:
    store = InMemoryMusicStore()

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

    recommendations = recommender.recommend(
        user_id='user-1',
        limit=3
    )

    print("Recommendations for user-1:")

    for position, track in enumerate(recommendations, start=1):
        print(
            f"{position}. {track.artist} — {track.title}"
        )


if __name__ == '__main__':
    main()