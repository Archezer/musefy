"""Local recommendation impressions and quality metrics.

The analytics layer deliberately stays small and offline.  It records what
the desktop actually presented (or queued), then attributes later playback
events to the most recent matching impression within a short window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from math import log2
from uuid import uuid4

from app.domain.models import (
    Interaction,
    InteractionType,
    Recommendation,
    RecommendationImpression,
)
from app.recommenders.feedback import COMPLETION_INTERACTION_TYPES
from app.storage.protocols import MusicStore

# A recommendation should only claim a later playback when the user acted
# shortly after seeing it.  A long window makes an unrelated manual playback
# look like recommendation success.
DEFAULT_ATTRIBUTION_DAYS = 1
POSITIVE_INTERACTION_TYPES = frozenset(
    {
        InteractionType.LIKE,
        InteractionType.SAVE,
        InteractionType.PLAYED_30S,
        InteractionType.COMPLETED_80,
        InteractionType.LISTEN,
        InteractionType.REPEAT,
    }
)
START_INTERACTION_TYPES = frozenset(
    {
        InteractionType.PLAY,
        InteractionType.PLAY_START,
        InteractionType.REPEAT,
    }
)
SKIP_INTERACTION_TYPES = frozenset(
    {
        InteractionType.SKIP,
        InteractionType.SKIP_UNDER_30S,
    }
)


@dataclass(frozen=True)
class RecommendationMetrics:
    """Aggregated recommendation quality for one user and time period."""

    period_start: datetime
    period_end: datetime
    impressions: int
    started: int
    completed: int
    skipped: int
    completion_rate: float
    skip_rate: float
    recall_at_10: float
    ndcg_at_10: float
    artist_diversity: float


class RecommendationAnalyticsService:
    def __init__(
        self,
        store: MusicStore,
        *,
        attribution_days: int = DEFAULT_ATTRIBUTION_DAYS,
    ) -> None:
        if attribution_days <= 0:
            raise ValueError("Attribution days must be positive")
        self.store = store
        self.attribution_window = timedelta(days=attribution_days)

    def record_impressions(
        self,
        user_id: str,
        recommendations: list[Recommendation] | tuple[Recommendation, ...],
        *,
        session_id: str | None = None,
        position_offset: int = 0,
        shown_at: datetime | None = None,
    ) -> str:
        """Persist one ordered recommendation batch and return its batch id."""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("User ID must not be empty")
        if position_offset < 0:
            raise ValueError("Position offset must not be negative")

        batch_id = session_id or uuid4().hex
        timestamp = self._as_utc(shown_at or datetime.now(UTC))
        for position, recommendation in enumerate(
            recommendations,
            start=position_offset + 1,
        ):
            self.store.add_recommendation_impression(
                RecommendationImpression(
                    user_id=normalized_user_id,
                    track_id=recommendation.track.id,
                    mode=recommendation.mode,
                    position=position,
                    score=float(recommendation.score),
                    reason=recommendation.reason,
                    shown_at=timestamp,
                    session_id=batch_id,
                )
            )
        return batch_id

    def build(
        self,
        user_id: str,
        *,
        now: datetime | None = None,
        days: int = 30,
    ) -> RecommendationMetrics:
        if days <= 0:
            raise ValueError("Days must be positive")
        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            raise ValueError("User ID must not be empty")

        period_end = self._as_utc(now or datetime.now(UTC))
        period_start = period_end - timedelta(days=max(1, days) - 1)
        impressions = [
            impression
            for impression in self.store.list_recommendation_impressions()
            if (
                impression.user_id == normalized_user_id
                and period_start
                <= self._as_utc(impression.shown_at)
                <= period_end
            )
        ]
        impressions.sort(
            key=lambda impression: (
                self._as_utc(impression.shown_at),
                impression.session_id or "",
                impression.position,
            )
        )
        interactions = [
            interaction
            for interaction in self.store.list_interactions()
            if interaction.user_id == normalized_user_id
        ]
        attributed = self._attribute_interactions(impressions, interactions)

        started_ids = {
            index
            for index, events in attributed.items()
            if any(
                event.interaction_type in START_INTERACTION_TYPES
                for event in events
            )
        }
        completed_ids = {
            index
            for index, events in attributed.items()
            if any(
                event.interaction_type in COMPLETION_INTERACTION_TYPES
                for event in events
            )
        }
        skipped_ids = {
            index
            for index, events in attributed.items()
            if any(
                event.interaction_type in SKIP_INTERACTION_TYPES
                for event in events
            )
        }

        denominator = len(started_ids)
        completion_rate = len(completed_ids) / denominator if denominator else 0.0
        skip_rate = len(skipped_ids) / denominator if denominator else 0.0
        recall_at_10, ndcg_at_10 = self._ranking_metrics(
            impressions,
            attributed,
        )
        artist_diversity = self._artist_diversity(impressions)

        return RecommendationMetrics(
            period_start=period_start,
            period_end=period_end,
            impressions=len(impressions),
            started=len(started_ids),
            completed=len(completed_ids),
            skipped=len(skipped_ids),
            completion_rate=completion_rate,
            skip_rate=skip_rate,
            recall_at_10=recall_at_10,
            ndcg_at_10=ndcg_at_10,
            artist_diversity=artist_diversity,
        )

    def _attribute_interactions(
        self,
        impressions: list[RecommendationImpression],
        interactions: list[Interaction],
    ) -> dict[int, list[Interaction]]:
        attributed: dict[int, list[Interaction]] = {}
        for interaction in interactions:
            event_time = self._as_utc(interaction.created_at)
            matching = [
                (index, impression)
                for index, impression in enumerate(impressions)
                if (
                    impression.track_id == interaction.track_id
                    and (
                        interaction.recommendation_session_id is None
                        or impression.session_id
                        == interaction.recommendation_session_id
                    )
                    and self._as_utc(impression.shown_at) <= event_time
                    <= self._as_utc(impression.shown_at)
                    + self.attribution_window
                )
            ]
            if not matching:
                continue
            index, _ = max(
                matching,
                key=lambda item: self._as_utc(item[1].shown_at),
            )
            attributed.setdefault(index, []).append(interaction)
        return attributed

    def _ranking_metrics(
        self,
        impressions: list[RecommendationImpression],
        attributed: dict[int, list[Interaction]],
    ) -> tuple[float, float]:
        batches: dict[str, list[int]] = {}
        for index, impression in enumerate(impressions):
            batch_id = impression.session_id or f"impression-{index}"
            batches.setdefault(batch_id, []).append(index)

        recalls: list[float] = []
        ndcgs: list[float] = []
        for indices in batches.values():
            indices.sort(key=lambda index: impressions[index].position)
            relevant = {
                index
                for index in indices
                if any(
                    event.interaction_type in POSITIVE_INTERACTION_TYPES
                    for event in attributed.get(index, ())
                )
            }
            if not relevant:
                continue
            top_indices = indices[:10]
            recalls.append(len(relevant & set(top_indices)) / len(relevant))
            dcg = sum(
                1.0 / log2(position + 2)
                for position, index in enumerate(top_indices)
                if index in relevant
            )
            ideal_length = min(len(relevant), 10)
            idcg = sum(
                1.0 / log2(position + 2)
                for position in range(ideal_length)
            )
            ndcgs.append(dcg / idcg if idcg else 0.0)

        return (
            sum(recalls) / len(recalls) if recalls else 0.0,
            sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
        )

    def _artist_diversity(
        self,
        impressions: list[RecommendationImpression],
    ) -> float:
        tracks = {track.id: track for track in self.store.list_tracks()}
        batches: dict[str, list[RecommendationImpression]] = {}
        for index, impression in enumerate(impressions):
            batch_id = impression.session_id or f"impression-{index}"
            batches.setdefault(batch_id, []).append(impression)

        ratios: list[float] = []
        for batch in batches.values():
            artists = {
                tracks[item.track_id].artist.casefold()
                for item in batch
                if item.track_id in tracks
            }
            if batch:
                ratios.append(len(artists) / len(batch))
        return sum(ratios) / len(ratios) if ratios else 0.0

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
