import gc
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

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

MODEL_IDLE_TIMEOUT_SECONDS = 180.0
CPU_ANALYSIS_WORKERS = 2


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
        self.classifier: MaestClassifier | None = None
        self._classifier_last_used_at: float | None = None
        # Preprocessing can run concurrently, but keep one shared classifier
        # session and its lifecycle consistent across worker threads.
        self._classifier_lock = RLock()
        self.mood_analyzer = Music2EmoMoodAnalyzer(
            idle_timeout_seconds=MODEL_IDLE_TIMEOUT_SECONDS,
        )

    @property
    def analysis_worker_count(self) -> int:
        """Return a safe pool size for the current inference device.

        CUDA inference remains single-file-at-a-time so activations do not
        pile up in VRAM.  On CPU, two workers overlap audio decoding and
        feature extraction while sharing the already-loaded model objects.
        """

        if self.mood_analyzer.device.type == "cuda":
            return 1
        return min(CPU_ANALYSIS_WORKERS, max(1, os.cpu_count() or 1))

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

        with self._classifier_lock:
            classifier = self._ensure_classifier()
            result = classifier.analyze(
                mel_array,
                top_k=self.top_k,
                min_score=self.min_score,
            )
            self._classifier_last_used_at = time.monotonic()
        return result

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
        mood_unloaded = self.mood_analyzer.unload_if_idle()
        classifier_unloaded = self._unload_classifier_if_idle()
        return mood_unloaded or classifier_unloaded

    def _ensure_classifier(self) -> MaestClassifier:
        with self._classifier_lock:
            if self.classifier is None:
                self.classifier = MaestClassifier()

            self._classifier_last_used_at = time.monotonic()
            return self.classifier

    def _unload_classifier_if_idle(self) -> bool:
        with self._classifier_lock:
            if (
                self.classifier is None or
                self._classifier_last_used_at is None
            ):
                return False

            if (
                time.monotonic() - self._classifier_last_used_at
                < self.mood_analyzer.idle_timeout_seconds
            ):
                return False

            self.classifier = None
            self._classifier_last_used_at = None
            gc.collect()
            return True

    
