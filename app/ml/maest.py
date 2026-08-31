import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "data" / "models" / "maest"
@dataclass(frozen=True)
class GenrePrediction:
    genre: str
    score: float
    rank: int
    rank_weight: float
    weighted_score: float

    @property
    def parent_genre(self) -> str:
        return self.genre.split('---', maxsplit=1)[0]

    @property
    def subgenre(self) -> str:
        parts = self.genre.split('---', maxsplit=1)

        if len(parts) == 1:
            return ''

        return parts[1]


class MaestClassifier:
    def __init__(
        self,
        model_path: Path = MODEL_DIR / "maest.onnx",
        labels_path: Path = MODEL_DIR / "maest.json",
    ) -> None:
        if hasattr(ort, "preload_dlls"):
            ort.preload_dlls()

        available_providers = ort.get_available_providers()

        providers = [
            provider
            for provider in (
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            )
            if provider in available_providers
        ]

        if not providers:
            raise RuntimeError(
                "No ONNX Runtime execution provider is available."
            )

        self.session = ort.InferenceSession(
            str(model_path),
            providers=providers,
        )

        self.provider = self.session.get_providers()[0]
        self.torch_cuda_available = torch.cuda.is_available()

        self.input_name = (
            self.session.get_inputs()[0].name
        )

        metadata = json.loads(
            labels_path.read_text(encoding="utf-8")
        )
        self.labels: list[str] = metadata["classes"]

    def predict(
        self,
        mel_batch: np.ndarray,
        top_k: int = 5,
    ) -> list[tuple[str, float]]:
        if mel_batch.ndim != 3:
            raise ValueError(
                "Mel batch must have shape "
                "[batch, 1876, 96]."
            )

        predictions = self.session.run(
            ["activations"],
            {self.input_name: mel_batch.astype(np.float32)},
        )[0]

        mean_predictions = predictions.mean(axis=0)
        indexes = np.argsort(mean_predictions)[::-1][:top_k]

        return [
            (
                self.labels[index],
                float(mean_predictions[index]),
            )
            for index in indexes
        ]

    def predict_ranked(
        self,
        mel_batch: np.ndarray,
        top_k: int = 10,
        min_score: float = 0.1
    ) -> list[GenrePrediction]:
        if mel_batch.ndim != 3:
            raise ValueError(
            "Mel batch must have shape "
            "[batch, 1876, 96]."
        )

        if top_k < 1:
            raise ValueError("top_k must be positive.")

        if min_score < 0:
            raise ValueError("min_score cannot be negative.")

        predictions = self.session.run(
            ['activations'],
            {self.input_name: mel_batch.astype(np.float32)},
        )[0]

        mean_predictions = predictions.mean(axis=0)
        indexes = np.argsort(mean_predictions)[::-1]

        results: list[GenrePrediction] = []

        for rank, index in enumerate(indexes, start=1):
            score = float(mean_predictions[index])

            if score <= min_score:
                break

            rank_weight = float(
                1.0 / np.log2(rank + 1)
            )

            results.append(
                GenrePrediction(
                    genre=self.labels[index],
                    score=score,
                    rank=rank,
                    rank_weight=rank_weight,
                    weighted_score=score * rank_weight
                )
            )

            if len(results) >= top_k:
                break

        return results

    
