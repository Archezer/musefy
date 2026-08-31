from pathlib import Path

from app.ml.audio_features import AudioWindowLoader
from app.ml.maest import (
    GenrePrediction,
    MaestAnalysisResult,
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

    def analyze_result(
        self,
        audio_path: Path,
    ) -> MaestAnalysisResult:
        windows = self.loader.load(audio_path)

        mel_batch = self.loader.to_mel_batch(
            windows
        )

        mel_array = (
            mel_batch.detach()
            .cpu()
            .numpy()
        )

        return self.classifier.analyze(
            mel_array,
            top_k=self.top_k,
            min_score=self.min_score,
        )

    def analyze(
        self,
        audio_path: Path,
    ) -> list[GenrePrediction]:
        result = self.analyze_result(audio_path)

        return list(result.genres)

    
