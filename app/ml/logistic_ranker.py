"""Interpretable scikit-learn baseline for the recommendation ranker."""

from __future__ import annotations

from dataclasses import dataclass

from sklearn.linear_model import LogisticRegression

from app.ml.training_data import RankerDataset


@dataclass(frozen=True)
class LogisticRanker:
    model: LogisticRegression
    feature_names: tuple[str, ...]

    def predict_scores(self, dataset: RankerDataset) -> tuple[float, ...]:
        probabilities = self.model.predict_proba(dataset.as_matrix())[:, 1]
        return tuple(float(value) for value in probabilities)

    def score_feature_snapshot(
        self,
        feature_snapshot: tuple[tuple[str, float], ...],
    ) -> float:
        values = dict(feature_snapshot)
        vector = tuple(values.get(name, 0.0) for name in self.feature_names)
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
    model.fit(dataset.as_matrix(), dataset.labels)
    return LogisticRanker(
        model=model,
        feature_names=dataset.feature_names,
    )
