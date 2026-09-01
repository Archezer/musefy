from app.domain.models import Track
from app.recommenders.similarity import TrackSimilarityIndex
from app.recommenders.smart_shuffle import SmartShuffleBuilder


def test_smart_shuffle_inserts_bridges_between_pairs() -> None:
    tracks = [
        Track(
            id="a",
            title="A",
            artist="Artist",
            track_embedding=(1.0, 0.0),
        ),
        Track(
            id="b",
            title="B",
            artist="Artist",
            track_embedding=(0.8, 0.2),
        ),
        Track(
            id="c",
            title="C",
            artist="Artist",
            track_embedding=(0.0, 1.0),
        ),
        Track(
            id="d",
            title="D",
            artist="Artist",
            track_embedding=(0.2, 0.8),
        ),
        Track(
            id="bridge-ab",
            title="Bridge AB",
            artist="Artist",
            track_embedding=(0.95, 0.05),
        ),
        Track(
            id="bridge-cd",
            title="Bridge CD",
            artist="Artist",
            track_embedding=(0.05, 0.95),
        ),
    ]
    index = TrackSimilarityIndex(
        tracks,
        neighbors_per_track=5,
    )
    builder = SmartShuffleBuilder(tracks, index)

    result = builder.build(("a", "b", "c", "d"))

    assert result == (
        "a",
        "b",
        "bridge-ab",
        "c",
        "d",
        "bridge-cd",
    )


def test_smart_shuffle_does_not_duplicate_playlist_tracks() -> None:
    tracks = [
        Track(
            id="a",
            title="A",
            artist="Artist",
            track_embedding=(1.0, 0.0),
        ),
        Track(
            id="b",
            title="B",
            artist="Artist",
            track_embedding=(0.9, 0.1),
        ),
    ]
    index = TrackSimilarityIndex(tracks)
    builder = SmartShuffleBuilder(tracks, index)

    result = builder.build(("a", "b"))

    assert result == ("a", "b")


def test_smart_shuffle_keeps_tracks_without_embeddings() -> None:
    tracks = [
        Track(
            id="analyzed",
            title="Analyzed",
            artist="Artist",
            track_embedding=(1.0, 0.0),
        ),
        Track(
            id="not-analyzed",
            title="Not analyzed",
            artist="Artist",
        ),
    ]
    index = TrackSimilarityIndex(tracks)
    builder = SmartShuffleBuilder(tracks, index)

    result = builder.build(("analyzed", "not-analyzed"))

    assert result == ("analyzed", "not-analyzed")
