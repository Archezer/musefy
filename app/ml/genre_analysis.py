from pathlib import Path

from app.ml.audio_features import AudioWindowLoader
from app.ml.maest import (
    GenrePrediction,
    MaestClassifier,
)


class GenreAnalysisService:
    def __init__(
        self,
        top_k: int = 10,
        min_score: float = 0.1
    ) -> None:
        self.top_k = top_k
        self.min_score = min_score

        self.loader = AudioWindowLoader()
        self.classifier = MaestClassifier()

    def analyze(
        self,
        audio_path: Path
    ) -> list[GenrePrediction]:
        windows = self.loader.load(audio_path)

        mel_batch = self.loader.to_mel_batch(windows)

        mel_array = (
            mel_batch.detach()
            .cpu()
            .numpy()
        )

        return self.classifier.predict_ranked(
            mel_array,
            top_k=self.top_k,
            min_score=self.min_score,
        )

    
