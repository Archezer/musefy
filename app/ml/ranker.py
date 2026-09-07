"""Small PyTorch ranker used after the existing recommenders."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import torch
from torch import Tensor, nn

from app.ml.preprocessing import FeatureStandardizer
from app.ml.training_data import RankerDataset


class MLPRanker(nn.Module):
    """Pointwise MLP that returns one relevance logit per candidate."""

    def __init__(
        self,
        input_dim: int,
        *,
        hidden_dims: Sequence[int] = (64, 32),
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if input_dim <= 0:
            raise ValueError("Input dimension must be positive")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("Dropout must be in the range [0, 1)")

        self.input_dim = input_dim
        self.hidden_dims = tuple(hidden_dims)
        self.dropout = dropout
        self.feature_scaler: FeatureStandardizer | None = None
        layers: list[nn.Module] = []
        previous_dim = input_dim
        for hidden_dim in hidden_dims:
            if hidden_dim <= 0:
                raise ValueError("Hidden dimensions must be positive")
            layers.extend(
                (
                    nn.Linear(previous_dim, hidden_dim),
                    nn.ReLU(),
                    nn.Dropout(dropout),
                )
            )
            previous_dim = hidden_dim
        layers.append(nn.Linear(previous_dim, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, features: Tensor) -> Tensor:
        return self.network(features).squeeze(-1)


@dataclass(frozen=True)
class MLPTrainingResult:
    model: MLPRanker
    feature_names: tuple[str, ...]
    train_losses: tuple[float, ...]
    validation_losses: tuple[float, ...]
    scaler: FeatureStandardizer | None = None


def train_mlp_ranker(
    train_dataset: RankerDataset,
    *,
    validation_dataset: RankerDataset | None = None,
    epochs: int = 30,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-4,
    hidden_dims: Sequence[int] = (64, 32),
    dropout: float = 0.1,
    seed: int = 7,
) -> MLPTrainingResult:
    """Fit a CPU-safe pointwise ranker and return its learning history."""

    if not train_dataset.examples:
        raise ValueError("Training dataset must not be empty")
    if not train_dataset.feature_names:
        raise ValueError("Training dataset must have features")
    if epochs <= 0:
        raise ValueError("Epochs must be positive")
    if learning_rate <= 0.0:
        raise ValueError("Learning rate must be positive")

    torch.manual_seed(seed)
    model = MLPRanker(
        len(train_dataset.feature_names),
        hidden_dims=hidden_dims,
        dropout=dropout,
    )
    scaler = FeatureStandardizer.fit(train_dataset)
    model.feature_scaler = scaler
    inputs = _as_tensor(scaler.transform_dataset(train_dataset))
    labels = _as_tensor(train_dataset.labels)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    criterion = nn.BCEWithLogitsLoss()
    train_losses: list[float] = []
    validation_losses: list[float] = []

    for _ in range(epochs):
        model.train()
        optimizer.zero_grad()
        loss = criterion(model(inputs), labels)
        loss.backward()
        optimizer.step()
        train_losses.append(float(loss.detach().cpu().item()))

        if validation_dataset is not None and validation_dataset.examples:
            model.eval()
            with torch.no_grad():
                validation_loss = criterion(
                    model(_as_tensor(scaler.transform_dataset(validation_dataset))),
                    _as_tensor(validation_dataset.labels),
                )
            validation_losses.append(
                float(validation_loss.detach().cpu().item())
            )

    return MLPTrainingResult(
        model=model,
        feature_names=train_dataset.feature_names,
        train_losses=tuple(train_losses),
        validation_losses=tuple(validation_losses),
        scaler=scaler,
    )


def train_pairwise_mlp_ranker(
    train_dataset: RankerDataset,
    *,
    validation_dataset: RankerDataset | None = None,
    epochs: int = 30,
    learning_rate: float = 1e-3,
    weight_decay: float = 1e-4,
    hidden_dims: Sequence[int] = (64, 32),
    dropout: float = 0.1,
    seed: int = 7,
) -> MLPTrainingResult:
    """Fit an MLP with a pairwise loss within each synthetic user."""

    pairs = _make_user_pairs(train_dataset)
    if not pairs:
        raise ValueError("Pairwise training needs positive and negative rows")
    if epochs <= 0:
        raise ValueError("Epochs must be positive")

    torch.manual_seed(seed)
    model = MLPRanker(
        len(train_dataset.feature_names),
        hidden_dims=hidden_dims,
        dropout=dropout,
    )
    scaler = FeatureStandardizer.fit(train_dataset)
    model.feature_scaler = scaler
    inputs = _as_tensor(scaler.transform_dataset(train_dataset))
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    train_losses: list[float] = []
    validation_losses: list[float] = []

    for _ in range(epochs):
        model.train()
        optimizer.zero_grad()
        positive_scores = model(inputs[[pair[0] for pair in pairs]])
        negative_scores = model(inputs[[pair[1] for pair in pairs]])
        loss = torch.nn.functional.softplus(
            -(positive_scores - negative_scores)
        ).mean()
        loss.backward()
        optimizer.step()
        train_losses.append(float(loss.detach().cpu().item()))

        if validation_dataset is not None:
            validation_pairs = _make_user_pairs(validation_dataset)
            if validation_pairs:
                model.eval()
                with torch.no_grad():
                    validation_inputs = _as_tensor(
                        scaler.transform_dataset(validation_dataset)
                    )
                    validation_loss = torch.nn.functional.softplus(
                        -(
                            model(
                                validation_inputs[
                                    [pair[0] for pair in validation_pairs]
                                ]
                            )
                            - model(
                                validation_inputs[
                                    [pair[1] for pair in validation_pairs]
                                ]
                            )
                        )
                    ).mean()
                validation_losses.append(
                    float(validation_loss.detach().cpu().item())
                )

    return MLPTrainingResult(
        model=model,
        feature_names=train_dataset.feature_names,
        train_losses=tuple(train_losses),
        validation_losses=tuple(validation_losses),
        scaler=scaler,
    )


def predict_scores(
    model: MLPRanker,
    dataset: RankerDataset,
) -> tuple[float, ...]:
    """Return relevance logits in the same order as dataset examples."""

    if dataset.examples and not dataset.feature_names:
        raise ValueError("Dataset must have features")
    model.eval()
    scaler = model.feature_scaler
    with torch.no_grad():
        inputs = (
            scaler.transform_dataset(dataset)
            if scaler is not None
            else dataset.as_matrix()
        )
        scores = model(_as_tensor(inputs))
    return tuple(float(value) for value in scores.cpu().tolist())


def score_feature_snapshot(
    model: MLPRanker,
    feature_names: tuple[str, ...],
    feature_snapshot: tuple[tuple[str, float], ...],
) -> float:
    """Score one candidate using the model's frozen feature order."""

    values = dict(feature_snapshot)
    scaler = getattr(model, "feature_scaler", None)
    if scaler is not None:
        vector = scaler.transform_snapshot(feature_snapshot)
    else:
        vector = tuple(values.get(name, 0.0) for name in feature_names)
    model.eval()
    with torch.no_grad():
        score = model(_as_tensor((vector,)))[0]
    return float(score.cpu().item())


def _as_tensor(values: object) -> Tensor:
    return torch.as_tensor(values, dtype=torch.float32)


def _make_user_pairs(
    dataset: RankerDataset,
) -> tuple[tuple[int, int], ...]:
    grouped: dict[str, list[int]] = {}
    for index, example in enumerate(dataset.examples):
        grouped.setdefault(example.user_id, []).append(index)

    pairs: list[tuple[int, int]] = []
    for indices in grouped.values():
        positives = [index for index in indices if dataset.examples[index].label]
        negatives = [index for index in indices if not dataset.examples[index].label]
        pairs.extend(
            (positive, negative)
            for positive in positives
            for negative in negatives
        )
    return tuple(pairs)
