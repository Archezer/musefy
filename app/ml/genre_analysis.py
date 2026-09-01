from dataclasses import dataclass
from pathlib import Path

from app.ml.audio_features import AudioWindowLoader
from app.ml.maest import (
    GenrePrediction,
    MaestAnalysisResult,
    MaestClassifier,
)
from app.ml.music2emo import (
    Music2EmoAnalysisResult,
    Music2EmoMoodAnalyzer,
)


@dataclass(frozen=True)
class TrackAnalysisResult:
    genre_result: MaestAnalysisResult
    mood_result: Music2EmoAnalysisResult


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
        self.mood_analyzer = Music2EmoMoodAnalyzer()

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

    def analyze_track_result(
        self,
        audio_path: Path,
    ) -> TrackAnalysisResult:
        genre_result = self.analyze_result(audio_path)
        genre_evidence = tuple(
            (prediction.genre, prediction.weighted_score)
            for prediction in genre_result.genres
        )
        return TrackAnalysisResult(
            genre_result=genre_result,
            mood_result=self.mood_analyzer.analyze(
                audio_path,
                genres=genre_evidence,
            ),
        )

    def unload_idle_models(self) -> bool:
        return self.mood_analyzer.unload_if_idle()

    
