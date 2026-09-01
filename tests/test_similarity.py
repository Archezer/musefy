import pytest

from app.domain.models import Track
from app.recommenders.similarity import (
    TrackSimilarityIndex,
    cosine_similarity,
)


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