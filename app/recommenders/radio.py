from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from app.domain.models import Recommendation

DEFAULT_MAX_SAME_ARTIST = 2


def build_radio_sequence(
    recommendations: Sequence[Recommendation],
    *,
    limit: int,
    initial_artist: str | None = None,
    max_same_artist: int = DEFAULT_MAX_SAME_ARTIST,
) -> list[Recommendation]:
    """Arrange ranked radio candidates into a varied playback sequence.

    The highest-ranked eligible candidate is selected at each position.  A
    candidate from the previous artist is postponed when another option is
    available, and an artist is used at most ``max_same_artist`` times before
    the constraint is relaxed for a small library.
    """

    if limit <= 0:
        raise ValueError("Radio sequence limit must be positive")
    if max_same_artist <= 0:
        raise ValueError("Maximum same-artist count must be positive")

    remaining = list(recommendations)
    selected: list[Recommendation] = []
    artist_counts: Counter[str] = Counter()
    previous_artist = _artist_key(initial_artist)

    while remaining and len(selected) < limit:
        eligible = [
            recommendation
            for recommendation in remaining
            if (
                _artist_key(recommendation.track.artist) != previous_artist
                and artist_counts[_artist_key(recommendation.track.artist)]
                < max_same_artist
            )
        ]

        if not eligible:
            eligible = [
                recommendation
                for recommendation in remaining
                if artist_counts[_artist_key(recommendation.track.artist)]
                < max_same_artist
            ]
        if not eligible:
            # There are fewer distinct artists than the requested constraint;
            # returning a shorter queue is worse than relaxing it.
            eligible = remaining

        selected_item = max(
            eligible,
            key=lambda recommendation: recommendation.score,
        )
        selected.append(selected_item)
        remaining.remove(selected_item)
        previous_artist = _artist_key(selected_item.track.artist)
        artist_counts[previous_artist] += 1

    return selected


def _artist_key(artist: str | None) -> str:
    return (artist or "").strip().casefold()
