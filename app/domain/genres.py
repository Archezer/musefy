"""Shared helpers for presenting and ranking the library's genres."""

from collections import defaultdict
from datetime import UTC, datetime

from app.domain.models import Interaction, Track
from app.recommenders.feedback import aggregate_user_track_weights

SUBGENRE_RECOMMENDATION_MIN_SCORE = 0.25


def _display_label(value: str) -> str:
    """Turn a model/database genre value into a compact UI label."""

    parts = [part.strip() for part in value.split("---") if part.strip()]
    if not parts:
        return ""

    label = parts[-1]
    special_labels = {
        "r&b": "R&B",
        "edm": "EDM",
        "idm": "IDM",
        "uk garage": "UK Garage",
    }
    return special_labels.get(label.casefold(), label.title())


def track_genre_evidence(track: Track) -> tuple[tuple[str, float], ...]:
    """Return displayable genre labels and their per-track relevance.

    MAEST predictions are preferred because ``Track.genres`` stores only the
    parent labels after analysis.  Low-confidence MAEST subgenres follow the
    same cutoff as the recommendation model and are omitted from the Wave
    picker.  Metadata remains a useful fallback for unanalyzed imports.
    """

    evidence: list[tuple[str, float]] = []
    if track.detected_genres:
        predictions = sorted(
            track.detected_genres,
            key=lambda prediction: (
                prediction.rank,
                -prediction.weighted_score,
            ),
        )
        for prediction in predictions:
            if prediction.subgenre and (
                prediction.score < SUBGENRE_RECOMMENDATION_MIN_SCORE
            ):
                continue
            raw_label = prediction.subgenre or prediction.parent_genre
            label = _display_label(raw_label)
            if not label:
                continue
            relevance = max(
                float(prediction.weighted_score),
                float(prediction.score),
                0.01,
            )
            evidence.append((label, relevance))
        if evidence:
            return tuple(evidence)

    for raw_genre in track.genres:
        label = _display_label(raw_genre)
        if label:
            evidence.append((label, 1.0))
    return tuple(evidence)


def popular_user_genres(
    tracks: list[Track] | tuple[Track, ...],
    interactions: list[Interaction] | tuple[Interaction, ...],
    user_id: str,
    *,
    limit: int,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Return the user's strongest genres, with a library fallback.

    Positive playback and explicit preference signals rank genres for a user.
    A user without positive history gets a deterministic catalogue ranking so
    the Wave picker is useful immediately after importing music.
    """

    if limit <= 0:
        raise ValueError("Genre limit must be positive")

    track_list = list(tracks)
    interaction_list = list(interactions)
    current_time = now or datetime.now(UTC)
    track_weights = aggregate_user_track_weights(
        user_id,
        interaction_list,
        now=current_time,
    )
    has_user_signal = any(
        track_weights.get(track.id, 0.0) > 0.0
        for track in track_list
    )

    scores: dict[str, float] = defaultdict(float)
    occurrences: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for track in track_list:
        track_weight = track_weights.get(track.id, 0.0)
        if has_user_signal:
            if track_weight <= 0.0:
                continue
        else:
            track_weight = 1.0

        seen_on_track: set[str] = set()
        for label, relevance in track_genre_evidence(track):
            key = label.casefold()
            if key in seen_on_track:
                continue
            seen_on_track.add(key)
            labels.setdefault(key, label)
            scores[key] += track_weight * relevance
            occurrences[key] += 1

    ranked_keys = sorted(
        scores,
        key=lambda key: (
            -scores[key],
            -occurrences[key],
            labels[key].casefold(),
        ),
    )
    return tuple(labels[key] for key in ranked_keys[:limit])
