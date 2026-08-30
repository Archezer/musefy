import json
from pathlib import Path

import numpy as np
import onnxruntime as ort

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "data" / "models" / "maest"


class MeastClassifier:
    def __init__(
        self,
        model_path: Path = MODEL_DIR / "maest.onnx",
        labels_path: Path = MODEL_DIR / "maest.json",
    ) -> None:
        self.session = ort.InferenceSession(
            str(model_path),
            providers=["CPUExecutionProvider"],
        )

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
    