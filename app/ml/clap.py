from __future__ import annotations

import numpy as np
import torch
import torch.nn.functional as F
from transformers import (
    AutoFeatureExtractor,
    AutoModel,
    AutoTokenizer,
)

DEFAULT_CLAP_MODEL = "laion/clap-htsat-unfused"


class ClapTextEncoder:
    def __init__(
        self,
        model_name: str = DEFAULT_CLAP_MODEL,
        device: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )

        self._tokenizer = None
        self._feature_extractor = None
        self._model = None

    def _ensure_loaded(self) -> None:
        if self._tokenizer is not None and self._model is not None:
            return

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
        )

        self._feature_extractor = AutoFeatureExtractor.from_pretrained(
            self.model_name,
        )

        self._model = AutoModel.from_pretrained(
            self.model_name,
        )

        self._model.to(self.device)
        self._model.eval()

    def encode_text(self, text: str) -> np.ndarray:
        text = text.strip()

        if not text:
            raise ValueError("Text prompt must not be empty.")

        self._ensure_loaded()

        assert self._model is not None
        assert self._tokenizer is not None

        inputs = self._tokenizer(
            [text],
            return_tensors="pt",
            padding=True,
            truncation=True,
)

        inputs = {
            name: value.to(self.device)
            for name, value in inputs.items()
        }

        with torch.inference_mode():
            features = self._model.get_text_features(**inputs)
            features = F.normalize(features, p=2, dim=-1)

        return features[0].detach().cpu().numpy().astype(np.float32)

    def encode_audio(
        self,
        audio: np.ndarray,
        sampling_rate: int
    ) -> np.ndarray:
        self._ensure_loaded()

        if audio.ndim == 2:
            audio = audio.mean(axis=0)

        if audio.ndim != 1:
            raise ValueError(
                "Audio must have shape [samples] or [channels, samples]."
            )

        audio = audio.astype(np.float32)

        if sampling_rate != 48_000:
            import torchaudio

            waveform = torch.from_numpy(audio)
            waveform = torchaudio.functional.resample(
                waveform,
                sampling_rate,
                48_000,
            )
            audio = waveform.numpy()

        target_samples = 48_000 * 10
        audio = audio[:target_samples]

        if len(audio) < target_samples:
            audio = np.pad(
                audio,
                (0, target_samples - len(audio)),
            )

        assert self._feature_extractor is not None
        assert self._model is not None

        inputs = self._feature_extractor(
            audio,
            sampling_rate=48_000,
            return_tensors="pt",
        )

        inputs = {
            name: value.to(self.device)
            for name, value in inputs.items()
        }

        with torch.inference_mode():
            features = self._model.get_audio_features(**inputs)
            features = F.normalize(features, p=2, dim=-1)

        return features[0].detach().cpu().numpy().astype(np.float32)


    def unload(self) -> None:
        self._model = None
        self._feature_extractor = None
        self._tokenizer = None

        if self.device.type == "cuda":
            torch.cuda.empty_cache()