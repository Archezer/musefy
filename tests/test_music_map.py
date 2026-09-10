import numpy as np
import pytest

from app.domain.models import Track
from app.ui.music_map import (
    MAP_MAX_NEIGHBOR_COUNT,
    MAP_SIMILARITY_THRESHOLD,
    MusicMapWidget,
)


def test_map_edges_skip_pairs_below_similarity_threshold() -> None:
    embeddings = np.asarray(
        [
            [1.0, 0.0],
            [0.95, 0.3122499],
            [0.8, 0.6],
            [0.0, 1.0],
        ],
        dtype=np.float32,
    )

    edges = MusicMapWidget._build_edges(embeddings)

    assert edges
    assert all(
        edge.strength >= MAP_SIMILARITY_THRESHOLD
        for edge in edges
    )
    assert all(
        3 not in (edge.left_index, edge.right_index)
        for edge in edges
    )


def test_map_edges_cap_each_track_without_forcing_fixed_degree() -> None:
    embeddings = np.asarray(
        [[1.0, index * 0.01] for index in range(20)],
        dtype=np.float32,
    )

    edges = MusicMapWidget._build_edges(embeddings)
    degrees = np.zeros(len(embeddings), dtype=np.int16)
    for edge in edges:
        degrees[edge.left_index] += 1
        degrees[edge.right_index] += 1

    assert max(degrees) <= MAP_MAX_NEIGHBOR_COUNT
    assert len(set(degrees.tolist())) > 1


def test_map_projection_keeps_points_bounded_and_two_dimensional() -> None:
    embeddings = np.asarray(
        [
            [1.0, 0.0, 0.0, 0.1],
            [0.98, 0.05, 0.0, 0.1],
            [0.95, 0.1, 0.0, 0.12],
            [0.0, 1.0, 0.0, 0.1],
            [0.05, 0.98, 0.0, 0.1],
            [0.1, 0.95, 0.0, 0.12],
            [0.0, 0.0, 1.0, 0.1],
            [0.0, 0.05, 0.98, 0.1],
        ],
        dtype=np.float32,
    )

    points = MusicMapWidget._project_embeddings(embeddings)

    assert points.shape == (len(embeddings), 2)
    assert np.isfinite(points).all()
    assert float(np.abs(points).max()) <= 0.82


def test_map_track_percentage_uses_stable_share_of_analyzed_tracks() -> None:
    tracks = [
        Track(
            id=f"track-{index}",
            title=f"Track {index}",
            artist="Artist",
            duration_ms=1,
            track_embedding=(float(index), 1.0),
        )
        for index in range(10)
    ]

    selection = MusicMapWidget.select_tracks_for_percentage(tracks, 30)

    assert len(selection) == 3
    assert selection == MusicMapWidget.select_tracks_for_percentage(tracks, 30)
    assert MusicMapWidget.select_tracks_for_percentage(tracks, 100) == tracks


def test_map_track_percentage_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        MusicMapWidget.select_tracks_for_percentage([], 0)
