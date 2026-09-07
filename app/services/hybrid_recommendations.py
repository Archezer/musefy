"""Optional ML reranking layered on top of existing baseline recommenders."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from math import exp
from typing import TYPE_CHECKING

from app.domain.models import Recommendation
from app.ml.feature_snapshot import build_recommendation_feature_snapshot
from app.storage.protocols import MusicStore

if TYPE_CHECKING:
    from app.ml.ranker import MLPTrainingResult


class HybridRecommendationRanker:
    """Blend a trained ranker with baseline scores and fail back safely."""

    def __init__(
        self,
        store: MusicStore,
        model: MLPTrainingResult | None = None,
        *,
        model_weight: float = 0.35,
    ) -> None:
        if not 0.0 <= model_weight <= 1.0:
            raise ValueError("Model weight must be in the range [0, 1]")
        self.store = store
        self.model = model
        self.model_weight = model_weight

    def rerank(
        self,
        user_id: str,
        recommendations: list[Recommendation],
        *,
        shown_at: datetime | None = None,
    ) -> list[Recommendation]:
        """Return ML-ranked candidates, or the unchanged baseline on failure."""

        if self.model is None or not recommendations:
            return list(recommendations)

        try:
            from app.ml.ranker import score_feature_snapshot

            timestamp = shown_at or datetime.now(UTC)
            scored: list[tuple[int, Recommendation, float]] = []
            for position, recommendation in enumerate(
                recommendations,
                start=1,
            ):
                snapshot = build_recommendation_feature_snapshot(
                    self.store,
                    user_id=user_id,
                    recommendation=recommendation,
                    position=position,
                    shown_at=timestamp,
                )
                model_logit = score_feature_snapshot(
                    self.model.model,
                    self.model.feature_names,
                    snapshot,
                )
                model_probability = 1.0 / (1.0 + exp(-model_logit))
                blended_score = (
                    (1.0 - self.model_weight) * recommendation.score
                    + self.model_weight * model_probability
                )
                scored.append((position, recommendation, blended_score))
        except (KeyError, RuntimeError, TypeError, ValueError):
            return list(recommendations)

        scored.sort(key=lambda item: (-item[2], item[0]))
        return [
            replace(recommendation, score=score)
            for _, recommendation, score in scored
        ]
