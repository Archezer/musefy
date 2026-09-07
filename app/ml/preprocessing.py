"""Leakage-safe preprocessing shared by all ranker backends."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite, sqrt

from app.ml.training_data import RankerDataset


@dataclass(frozen=True)
class FeatureStandardizer:
    """Store train-only means and scales for a stable feature contract."""

    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]

    @classmethod
    def fit(cls, dataset: RankerDataset) -> FeatureStandardizer:
        if not dataset.examples:
            raise ValueError("Cannot fit preprocessing on an empty dataset")
        rows = dataset.as_matrix()
        means = tuple(
            sum(row[index] for row in rows) / len(rows)
            for index in range(len(dataset.feature_names))
        )
        scales = tuple(
            _safe_scale(
                sum(
                    (row[index] - means[index]) ** 2
                    for row in rows
                )
                / len(rows)
            )
            for index in range(len(dataset.feature_names))
        )
        return cls(dataset.feature_names, means, scales)

    def transform_dataset(
        self,
        dataset: RankerDataset,
    ) -> tuple[tuple[float, ...], ...]:
        return tuple(
            self.transform_snapshot(example.feature_snapshot)
            for example in dataset.examples
        )

    def transform_snapshot(
        self,
        feature_snapshot: tuple[tuple[str, float], ...],
    ) -> tuple[float, ...]:
        values = dict(feature_snapshot)
        return tuple(
            (float(values.get(name, 0.0)) - mean) / scale
            for name, mean, scale in zip(
                self.feature_names,
                self.means,
                self.scales,
                strict=True,
            )
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "feature_names": self.feature_names,
            "means": self.means,
            "scales": self.scales,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> FeatureStandardizer:
        feature_names = tuple(str(name) for name in payload["feature_names"])
        means = tuple(float(value) for value in payload["means"])
        scales = tuple(float(value) for value in payload["scales"])
        if not len(feature_names) == len(means) == len(scales):
            raise ValueError("Preprocessing dimensions do not match")
        return cls(feature_names, means, scales)


def _safe_scale(variance: float) -> float:
    scale = sqrt(max(variance, 0.0))
    return scale if isfinite(scale) and scale > 0.0 else 1.0
