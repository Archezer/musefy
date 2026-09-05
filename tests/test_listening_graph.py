from app.ui.dialogs import ListeningGraph


def _track(title: str, artist: str) -> tuple[
    str,
    str,
    int,
    tuple[float, ...] | None,
    tuple[str, ...],
]:
    return (title, artist, 1, (1.0, 0.0), ("electronic",))


def test_graph_groups_require_high_confidence_links() -> None:
    tracks = (
        _track("Ambient A", "Ambient Artist"),
        _track("Ambient B", "Ambient Artist"),
        _track("DSBM A", "Black Metal Artist"),
        _track("DSBM B", "Black Metal Artist"),
    )
    edges = (
        (0, 1, 0.94),
        (1, 2, 0.74),
        (2, 3, 0.93),
    )

    groups = ListeningGraph._build_cluster_groups(tracks, edges)

    assert groups == ((0, 1), (2, 3))


def test_graph_keeps_same_artist_tracks_together_without_embedding_link() -> None:
    tracks = (
        _track("Track A", "One Artist"),
        _track("Track B", "One Artist"),
    )

    groups = ListeningGraph._build_cluster_groups(tracks, ())

    assert groups == ((0, 1),)
