"""Interpretable scikit-learn baseline for the recommendation ranker."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.linear_model import LogisticRegression

from app.ml.preprocessing import FeatureStandardizer
from app.ml.training_data import RankerDataset


@dataclass(frozen=True)
class LogisticRanker:
    model: LogisticRegression
    feature_names: tuple[str, ...]
    scaler: FeatureStandardizer | None = None
    approved_for_activation: bool = True
    approval_reason: str = ""

    def predict_scores(self, dataset: RankerDataset) -> tuple[float, ...]:
        inputs = (
            self.scaler.transform_dataset(dataset)
            if self.scaler is not None
            else dataset.as_matrix()
        )
        probabilities = self.model.predict_proba(inputs)[:, 1]
        return tuple(float(value) for value in probabilities)

    def score_feature_snapshot(
        self,
        feature_snapshot: tuple[tuple[str, float], ...],
    ) -> float:
        values = dict(feature_snapshot)
        vector = (
            self.scaler.transform_snapshot(feature_snapshot)
            if self.scaler is not None
            else tuple(values.get(name, 0.0) for name in self.feature_names)
        )
        return float(self.model.predict_proba((vector,))[0, 1])


def train_logistic_ranker(
    dataset: RankerDataset,
    *,
    regularization: float = 1.0,
    seed: int = 7,
) -> LogisticRanker:
    """Fit a logistic baseline on the same feature contract as the MLP."""

    if not dataset.examples:
        raise ValueError("Training dataset must not be empty")
    if not dataset.feature_names:
        raise ValueError("Training dataset must have features")
    if regularization <= 0.0:
        raise ValueError("Regularization must be positive")
    if len(set(dataset.labels)) < 2:
        raise ValueError("Training dataset needs both labels")

    model = LogisticRegression(
        C=regularization,
        max_iter=500,
        random_state=seed,
    )
    scaler = FeatureStandardizer.fit(dataset)
    model.fit(scaler.transform_dataset(dataset), dataset.labels)
    return LogisticRanker(
        model=model,
        feature_names=dataset.feature_names,
        scaler=scaler,
    )
