from pathlib import Path

import pytest

pytest.importorskip("torch")

from app.cli import build_parser
from app.ml.artifacts import (
    load_logistic_ranker,
    load_mlp_ranker,
    save_logistic_ranker,
    save_mlp_ranker,
)
from app.ml.logistic_ranker import train_logistic_ranker
from app.ml.ranker import (
    predict_scores,
    score_feature_snapshot,
    train_mlp_ranker,
    train_pairwise_mlp_ranker,
)
from app.ml.training_data import (
    make_synthetic_ranker_dataset,
    split_ranker_dataset_by_time,
)


def test_mlp_ranker_trains_and_scores_synthetic_data() -> None:
    dataset = make_synthetic_ranker_dataset(
        user_count=4,
        examples_per_user=20,
        seed=13,
    )
    train, validation = split_ranker_dataset_by_time(
        dataset,
        train_fraction=0.75,
    )

    result = train_mlp_ranker(
        train,
        validation_dataset=validation,
        epochs=8,
        hidden_dims=(16, 8),
        seed=13,
    )
    scores = predict_scores(result.model, validation)
    one_score = score_feature_snapshot(
        result.model,
        result.feature_names,
        validation.examples[0].feature_snapshot,
    )

    assert len(scores) == len(validation.examples)
    assert len(result.train_losses) == 8
    assert len(result.validation_losses) == 8
    assert all(loss >= 0.0 for loss in result.train_losses)
    assert one_score == pytest.approx(scores[0], abs=1e-6)


def test_logistic_and_pairwise_rankers_use_the_same_synthetic_contract() -> None:
    dataset = make_synthetic_ranker_dataset(
        user_count=5,
        examples_per_user=16,
        seed=17,
    )
    train, validation = split_ranker_dataset_by_time(
        dataset,
        train_fraction=0.75,
    )

    logistic = train_logistic_ranker(train)
    pairwise = train_pairwise_mlp_ranker(
        train,
        validation_dataset=validation,
        epochs=6,
        hidden_dims=(16, 8),
        seed=17,
    )

    assert len(logistic.predict_scores(validation)) == len(
        validation.examples
    )
    assert len(pairwise.train_losses) == 6
    assert pairwise.train_losses[-1] < pairwise.train_losses[0]


def test_mlp_artifact_round_trip_preserves_scores(tmp_path: Path) -> None:
    dataset = make_synthetic_ranker_dataset(
        user_count=3,
        examples_per_user=12,
        seed=19,
    )
    train, validation = split_ranker_dataset_by_time(dataset)
    result = train_mlp_ranker(
        train,
        epochs=3,
        hidden_dims=(8,),
        seed=19,
    )
    artifact_path = tmp_path / "ranker.pt"

    save_mlp_ranker(
        result,
        artifact_path,
        approved_for_activation=False,
        approval_reason="Validation candidate",
    )
    loaded = load_mlp_ranker(artifact_path)

    assert loaded.feature_names == result.feature_names
    assert loaded.approved_for_activation is False
    assert loaded.approval_reason == "Validation candidate"
    assert predict_scores(loaded.model, validation) == pytest.approx(
        predict_scores(result.model, validation),
        abs=1e-6,
    )


def test_cli_exposes_synthetic_ranker_pipeline() -> None:
    arguments = build_parser().parse_args(
        ["train-synthetic-ranker", "--epochs", "2"]
    )

    assert arguments.command == "train-synthetic-ranker"
    assert arguments.epochs == 2


def test_cli_exposes_real_ranker_backends() -> None:
    arguments = build_parser().parse_args(
        [
            "train-ranker",
            "--backend",
            "pairwise",
            "--minimum-examples",
            "12",
        ]
    )

    assert arguments.command == "train-ranker"
    assert arguments.backend == "pairwise"
    assert arguments.minimum_examples == 12


def test_cli_exposes_ranker_status() -> None:
    arguments = build_parser().parse_args(
        ["ranker-status", "--minimum-examples", "12"]
    )

    assert arguments.command == "ranker-status"
    assert arguments.minimum_examples == 12


def test_logistic_artifact_round_trip_preserves_scores(tmp_path: Path) -> None:
    dataset = make_synthetic_ranker_dataset(
        user_count=3,
        examples_per_user=12,
        seed=29,
    )
    train, validation = split_ranker_dataset_by_time(dataset)
    ranker = train_logistic_ranker(train)
    artifact_path = tmp_path / "ranker.joblib"

    save_logistic_ranker(ranker, artifact_path)
    loaded = load_logistic_ranker(artifact_path)

    assert loaded.feature_names == ranker.feature_names
    assert loaded.predict_scores(validation) == pytest.approx(
        ranker.predict_scores(validation),
        abs=1e-9,
    )
