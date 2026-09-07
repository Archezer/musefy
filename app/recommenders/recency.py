"""Small, explainable freshness bias shared by the recommenders."""

from __future__ import annotations

from datetime import UTC, datetime
from math import exp, log

from app.domain.models import Track

RECENCY_HALF_LIFE_DAYS = 365.0
MAX_RECENCY_BONUS = 0.03


def recency_bonus(
    track: Track,
    *,
    now: datetime,
    half_life_days: float = RECENCY_HALF_LIFE_DAYS,
) -> float:
    """Return a small bonus that favors recently added tracks.

    ``Track.created_at`` is the time the track entered the local library.  A
    half-life keeps the bonus from turning the recommender into a permanent
    new-release sorter: a track added a year ago still gets half of the
    maximum bonus, while strong taste and similarity signals remain dominant.
    """

    if half_life_days <= 0.0:
        raise ValueError("Recency half-life must be positive")

    created_at = track.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)

    current_time = now
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)
    else:
        current_time = current_time.astimezone(UTC)

    age_days = max(
        0.0,
        (current_time - created_at).total_seconds() / 86_400.0,
    )
    return MAX_RECENCY_BONUS * exp(-log(2.0) * age_days / half_life_days)
