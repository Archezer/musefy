"""Offline evaluation and activation gate for recommendation rankers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import exp, log

from sklearn.metrics import roc_auc_score


@dataclass(frozen=True)
class RankerEvaluation:
    example_count: int
    positive_count: int
    negative_count: int
    roc_auc: float | None
    log_loss: float


@dataclass(frozen=True)
class RankerGateDecision:
    approved: bool
    reason: str
    baseline: RankerEvaluation
    candidate: RankerEvaluation
    minimum_improvement: float

    @property
    def roc_auc_improvement(self) -> float | None:
        if self.baseline.roc_auc is None or self.candidate.roc_auc is None:
            return None
        return self.candidate.roc_auc - self.baseline.roc_auc


def evaluate_ranker(
    labels: Sequence[int],
    scores: Sequence[float],
    *,
    scores_are_logits: bool = False,
) -> RankerEvaluation:
    """Evaluate binary relevance scores without changing model state."""

    if len(labels) != len(scores):
        raise ValueError("Labels and scores must have equal length")
    if not labels:
        raise ValueError("Evaluation data must not be empty")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("Labels must be binary")

    probabilities = tuple(
        _sigmoid(score) if scores_are_logits else _clamp_probability(score)
        for score in scores
    )
    positive_count = sum(label == 1 for label in labels)
    negative_count = sum(label == 0 for label in labels)
    roc_auc = (
        float(roc_auc_score(labels, probabilities))
        if positive_count and negative_count
        else None
    )
    loss = -sum(
        label * log(probability)
        + (1 - label) * log(1.0 - probability)
        for label, probability in zip(labels, probabilities, strict=True)
    ) / len(labels)
    return RankerEvaluation(
        example_count=len(labels),
        positive_count=positive_count,
        negative_count=negative_count,
        roc_auc=roc_auc,
        log_loss=loss,
    )


def decide_ranker_activation(
    labels: Sequence[int],
    baseline_scores: Sequence[float],
    candidate_scores: Sequence[float],
    *,
    candidate_scores_are_logits: bool = False,
    minimum_validation_examples: int = 30,
    minimum_improvement: float = 0.01,
) -> RankerGateDecision:
    """Approve a candidate only when it beats baseline on held-out rows."""

    if minimum_validation_examples <= 0:
        raise ValueError("Minimum validation examples must be positive")
    if minimum_improvement < 0.0:
        raise ValueError("Minimum improvement must not be negative")

    baseline = evaluate_ranker(labels, baseline_scores)
    candidate = evaluate_ranker(
        labels,
        candidate_scores,
        scores_are_logits=candidate_scores_are_logits,
    )
    improvement = (
        candidate.roc_auc - baseline.roc_auc
        if candidate.roc_auc is not None and baseline.roc_auc is not None
        else None
    )
    approved = (
        len(labels) >= minimum_validation_examples
        and improvement is not None
        and improvement >= minimum_improvement
    )
    if len(labels) < minimum_validation_examples:
        reason = "Validation set is too small"
    elif improvement is None:
        reason = "Validation set needs both positive and negative labels"
    elif approved:
        reason = "Candidate beats baseline by the required ROC-AUC margin"
    else:
        reason = "Candidate does not beat baseline by the required margin"
    return RankerGateDecision(
        approved=approved,
        reason=reason,
        baseline=baseline,
        candidate=candidate,
        minimum_improvement=minimum_improvement,
    )


def _sigmoid(value: float) -> float:
    if value >= 0.0:
        return 1.0 / (1.0 + exp(-value))
    positive = exp(value)
    return positive / (1.0 + positive)


def _clamp_probability(value: float) -> float:
    return min(max(float(value), 1e-7), 1.0 - 1e-7)
