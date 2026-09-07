"""Persistence for locally trained MLP ranker artifacts."""

from __future__ import annotations

from pathlib import Path

import joblib
import torch

from app.ml.logistic_ranker import LogisticRanker
from app.ml.preprocessing import FeatureStandardizer
from app.ml.ranker import MLPRanker, MLPTrainingResult


def save_mlp_ranker(
    result: MLPTrainingResult,
    path: Path,
    *,
    approved_for_activation: bool = True,
    approval_reason: str = "",
) -> None:
    """Save weights and the exact feature/model contract."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "artifact_type": "musefy_mlp_ranker",
        "version": 1,
        "feature_names": result.feature_names,
        "input_dim": result.model.input_dim,
        "hidden_dims": result.model.hidden_dims,
        "dropout": result.model.dropout,
        "scaler": result.scaler.to_payload() if result.scaler else None,
        "approved_for_activation": approved_for_activation,
        "approval_reason": approval_reason,
        "state_dict": {
            name: value.detach().cpu()
            for name, value in result.model.state_dict().items()
        },
    }
    torch.save(payload, path)


def load_mlp_ranker(path: Path) -> MLPTrainingResult:
    """Load a previously saved MLP and reject incompatible artifacts."""

    payload = torch.load(path, map_location="cpu")
    if payload.get("artifact_type") != "musefy_mlp_ranker":
        raise ValueError("Unsupported ranker artifact")
    feature_names = tuple(payload["feature_names"])
    input_dim = int(payload["input_dim"])
    if input_dim != len(feature_names):
        raise ValueError("Ranker input dimension does not match features")

    model = MLPRanker(
        input_dim,
        hidden_dims=tuple(payload["hidden_dims"]),
        dropout=float(payload["dropout"]),
    )
    model.load_state_dict(payload["state_dict"])
    model.eval()
    scaler_payload = payload.get("scaler")
    scaler = (
        FeatureStandardizer.from_payload(scaler_payload)
        if scaler_payload is not None
        else None
    )
    model.feature_scaler = scaler
    return MLPTrainingResult(
        model=model,
        feature_names=feature_names,
        train_losses=(),
        validation_losses=(),
        scaler=scaler,
        approved_for_activation=bool(
            payload.get("approved_for_activation", True)
        ),
        approval_reason=str(payload.get("approval_reason", "")),
    )


def save_logistic_ranker(
    ranker: LogisticRanker,
    path: Path,
    *,
    approved_for_activation: bool = True,
    approval_reason: str = "",
) -> None:
    """Save the interpretable baseline with its feature order."""

    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "artifact_type": "musefy_logistic_ranker",
            "version": 1,
            "feature_names": ranker.feature_names,
            "scaler": ranker.scaler.to_payload() if ranker.scaler else None,
            "approved_for_activation": approved_for_activation,
            "approval_reason": approval_reason,
            "model": ranker.model,
        },
        path,
    )


def load_logistic_ranker(path: Path) -> LogisticRanker:
    """Load a logistic artifact and validate its feature contract."""

    payload = joblib.load(path)
    if payload.get("artifact_type") != "musefy_logistic_ranker":
        raise ValueError("Unsupported logistic ranker artifact")
    feature_names = tuple(payload["feature_names"])
    model = payload["model"]
    if model.n_features_in_ != len(feature_names):
        raise ValueError("Logistic input dimension does not match features")
    scaler_payload = payload.get("scaler")
    scaler = (
        FeatureStandardizer.from_payload(scaler_payload)
        if scaler_payload is not None
        else None
    )
    return LogisticRanker(
        model=model,
        feature_names=feature_names,
        scaler=scaler,
        approved_for_activation=bool(
            payload.get("approved_for_activation", True)
        ),
        approval_reason=str(payload.get("approval_reason", "")),
    )
