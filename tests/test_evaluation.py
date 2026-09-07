import pytest

from app.ml.evaluation import (
    decide_ranker_activation,
    evaluate_ranker,
)


def test_evaluation_converts_logits_and_calculates_auc() -> None:
    evaluation = evaluate_ranker(
        [1, 1, 0, 0],
        [3.0, 1.0, -1.0, -3.0],
        scores_are_logits=True,
    )

    assert evaluation.example_count == 4
    assert evaluation.roc_auc == pytest.approx(1.0)
    assert evaluation.positive_count == 2
    assert evaluation.negative_count == 2


def test_gate_rejects_candidate_that_does_not_beat_baseline() -> None:
    decision = decide_ranker_activation(
        [1, 1, 0, 0],
        [0.9, 0.8, 0.2, 0.1],
        [0.6, 0.4, 0.5, 0.3],
        minimum_validation_examples=4,
    )

    assert decision.approved is False
    assert "does not beat" in decision.reason


def test_gate_rejects_tiny_validation_set_even_for_a_better_model() -> None:
    decision = decide_ranker_activation(
        [1, 0],
        [0.5, 0.5],
        [0.9, 0.1],
        minimum_validation_examples=30,
    )

    assert decision.approved is False
    assert decision.reason == "Validation set is too small"
