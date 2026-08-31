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


@dataclass(frozen=True)
class MaestAnalysisResult:
    genres: tuple[GenrePrediction, ...]
    track_embedding: np.ndarray


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

        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        self.input_shape = tuple(model_input.shape)
        self.prediction_output_name = "activations"
        self.embedding_output_name = "layer_07_embeddings"

        output_names = {
            output.name
            for output in self.session.get_outputs()
        }
        required_outputs = {
            self.prediction_output_name,
            self.embedding_output_name,
        }

        if not required_outputs.issubset(output_names):
            missing_outputs = required_outputs - output_names
            raise RuntimeError(
                "MAEST model is missing outputs: "
                f"{sorted(missing_outputs)}"
            )

        metadata = json.loads(
            labels_path.read_text(encoding="utf-8")
        )
        self.labels: list[str] = metadata["classes"]


    def _extract_cls_embeddings(
        self,
        token_embeddings: np.ndarray,
    ) -> np.ndarray:
        if token_embeddings.ndim == 4:
            token_embeddings = token_embeddings[:, 0]

        if token_embeddings.ndim != 3:
            raise ValueError(
                "Unexpected MAEST embedding shape: "
                f"{token_embeddings.shape}"
            )

        return token_embeddings[:, 0, :]

    def _run_inference(
        self,
        mel_batch: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        prepared_batch = mel_batch.astype(
            np.float32,
            copy=False,
        )

        if prepared_batch.shape[0] == 0:
            raise ValueError("Mel batch must not be empty.")

        output_names = [
            self.prediction_output_name,
            self.embedding_output_name,
        ]

        fixed_batch_size = self.input_shape[0]

        if fixed_batch_size == 1:
            window_scores = []
            window_embeddings = []

            for window in prepared_batch:
                scores, token_embeddings = self.session.run(
                    output_names,
                    {
                        self.input_name: window[None, ...],
                    },
                )

                embeddings = self._extract_cls_embeddings(
                    token_embeddings
                )

                window_scores.append(scores[0])
                window_embeddings.append(embeddings[0])

            return (
                np.asarray(window_scores),
                np.asarray(window_embeddings),
            )

        scores, token_embeddings = self.session.run(
            output_names,
            {self.input_name: prepared_batch},
        )

        return (
            scores,
            self._extract_cls_embeddings(token_embeddings),
        )


    def _rank_predictions(
        self,
        mean_predictions: np.ndarray,
        top_k: int,
        min_score: float,
    ) -> list[GenrePrediction]:
        if top_k < 1:
            raise ValueError("top_k must be positive.")

        if min_score < 0:
            raise ValueError(
                "min_score cannot be negative."
            )

        indexes = np.argsort(
            mean_predictions
        )[::-1]

        results = []

        for rank, index in enumerate(
            indexes,
            start=1,
        ):
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
                    weighted_score=score * rank_weight,
                )
            )

            if len(results) >= top_k:
                break

        return results


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

        predictions, _ = self._run_inference(mel_batch)

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
        min_score: float = 0.1,
    ) -> list[GenrePrediction]:
        if mel_batch.ndim != 3:
            raise ValueError(
                "Mel batch must have shape "
                "[batch, 1876, 96]."
            )

        scores, _ = self._run_inference(
            mel_batch
        )

        return self._rank_predictions(
            mean_predictions=scores.mean(axis=0),
            top_k=top_k,
            min_score=min_score,
        )


    def analyze(
        self,
        mel_batch: np.ndarray,
        top_k: int = 10,
        min_score: float = 0.1,
    ) -> MaestAnalysisResult:
        if mel_batch.ndim != 3:
            raise ValueError(
                "Mel batch must have shape "
                "[batch, 1876, 96]."
            )

        scores, window_embeddings = (
            self._run_inference(mel_batch)
        )

        genres = self._rank_predictions(
            mean_predictions=scores.mean(axis=0),
            top_k=top_k,
            min_score=min_score,
        )

        track_embedding = window_embeddings.mean(
            axis=0
        )

        norm = np.linalg.norm(track_embedding)

        if not np.isfinite(norm) or norm == 0:
            raise RuntimeError(
                "Could not normalize track embedding."
            )

        track_embedding = (
            track_embedding / norm
        ).astype(np.float32)

        return MaestAnalysisResult(
            genres=tuple(genres),
            track_embedding=track_embedding,
        )

    
