import pytest

from app.domain.models import Interaction, InteractionType, Track, User
from app.recommenders.similarity import (
    TrackSimilarityIndex,
    cosine_similarity,
)
from app.services.track_similarity import TrackSimilarityService
from app.storage.memory import InMemoryMusicStore


def test_cosine_similarity_finds_identical_vectors() -> None:
    assert cosine_similarity(
        (1.0, 0.0),
        (1.0, 0.0),
    ) == pytest.approx(1.0)


def test_index_returns_closest_tracks_first() -> None:
    tracks = [
        Track(
            id="track-a",
            title="A",
            artist="Artist",
            track_embedding=(1.0, 0.0),
        ),
        Track(
            id="track-b",
            title="B",
            artist="Artist",
            track_embedding=(0.9, 0.1),
        ),
        Track(
            id="track-c",
            title="C",
            artist="Artist",
            track_embedding=(0.0, 1.0),
        ),
        Track(
            id="track-without-embedding",
            title="Unknown",
            artist="Artist",
        ),
    ]

    index = TrackSimilarityIndex(
        tracks,
        neighbors_per_track=2,
    )

    neighbors = index.neighbors_for("track-a")

    assert [neighbor.track_id for neighbor in neighbors] == [
        "track-b",
        "track-c",
    ]
    assert neighbors[0].score > neighbors[1].score
    assert index.neighbors_for("track-without-embedding") == ()


def test_index_updates_neighbors_without_rebuilding_everything() -> None:
    track_a = Track(
        id="track-a",
        title="A",
        artist="Artist",
        track_embedding=(1.0, 0.0),
    )
    track_b = Track(
        id="track-b",
        title="B",
        artist="Artist",
        track_embedding=(0.0, 1.0),
    )
    track_c = Track(
        id="track-c",
        title="C",
        artist="Artist",
        track_embedding=(-1.0, 0.0),
    )

    index = TrackSimilarityIndex(
        [track_a, track_b],
        neighbors_per_track=2,
    )

    index.upsert(track_c)

    assert index.neighbors_for("track-a")[0].track_id == "track-b"
    assert index.neighbors_for("track-c")[0].track_id == "track-b"

    updated_track_b = Track(
        id="track-b",
        title="B",
        artist="Artist",
        track_embedding=(1.0, 0.0),
    )
    index.upsert(updated_track_b)

    assert index.neighbors_for("track-a")[0].track_id == "track-b"
    assert index.neighbors_for("track-c")[0].track_id == "track-a"


def test_similarity_service_returns_recommendations_for_seed() -> None:
    store = InMemoryMusicStore()
    store.add_track(
        Track(
            id="seed",
            title="Seed",
            artist="Artist",
            track_embedding=(1.0, 0.0),
        )
    )
    store.add_track(
        Track(
            id="neighbor",
            title="Neighbor",
            artist="Artist",
            track_embedding=(0.9, 0.1),
        )
    )

    recommendations = TrackSimilarityService(
        store
    ).recommendations_for("seed", limit=1)

    assert recommendations[0].track.id == "neighbor"
    assert recommendations[0].reason == (
        "Similar to the selected track"
    )


def test_similarity_service_removes_deleted_track_from_index() -> None:
    store = InMemoryMusicStore()
    store.add_track(
        Track(
            id="seed",
            title="Seed",
            artist="Artist",
            track_embedding=(1.0, 0.0),
        )
    )
    store.add_track(
        Track(
            id="neighbor",
            title="Neighbor",
            artist="Artist",
            track_embedding=(0.9, 0.1),
        )
    )

    service = TrackSimilarityService(store)
    assert service.recommendations_for("seed", limit=1)

    service.remove_track("neighbor")

    assert service.recommendations_for("seed", limit=1) == []


def test_similarity_service_respects_permanent_user_block() -> None:
    store = InMemoryMusicStore()
    store.add_user(User(id="user-1", display_name="Test User"))
    store.add_track(
        Track(
            id="seed",
            title="Seed",
            artist="Artist",
            track_embedding=(1.0, 0.0),
        )
    )
    store.add_track(
        Track(
            id="neighbor",
            title="Neighbor",
            artist="Artist",
            track_embedding=(0.9, 0.1),
        )
    )
    store.add_interaction(
        Interaction(
            user_id="user-1",
            track_id="neighbor",
            interaction_type=InteractionType.DO_NOT_RECOMMEND,
        )
    )

    recommendations = TrackSimilarityService(store).recommendations_for(
        "seed",
        limit=1,
        user_id="user-1",
    )

    assert recommendations == []
