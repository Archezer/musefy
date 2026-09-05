from __future__ import annotations

import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock

import librosa
import numpy as np
import torch
import torchaudio
from torch import nn
from torch.serialization import add_safe_globals
from transformers import AutoModel, Wav2Vec2FeatureExtractor

from app.domain.mood import MoodVector
from app.ml.mood_profiles import (
    MoodProfilePrediction,
    blend_mood_with_profiles,
    music2emo_to_vector,
    predict_mood_profiles,
)
from app.storage.paths import DATA_DIR

MODEL_ROOT = DATA_DIR / "models" / "music2emo"
MERT_NAME = "m-a-p/MERT-v1-95M"
MERT_SAMPLE_RATE = 24_000
CHORD_SAMPLE_RATE = 22_050
MERT_WINDOW_SECONDS = 30
CHORD_INSTANCE_SECONDS = 10
CHORD_TIMESTEP = 108
MUSIC2EMO_ANALYSIS_VERSION = "music2emo-v1"


@dataclass(frozen=True)
class Music2EmoAnalysisResult:
    mood: MoodVector
    tags: tuple[tuple[str, float], ...]
    profiles: tuple[MoodProfilePrediction, ...]
    valence: float
    arousal: float
    analysis_version: str = MUSIC2EMO_ANALYSIS_VERSION


class _Music2EmoHead(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.chord_root_embedding = nn.Embedding(14, 4)
        self.chord_attr_embedding = nn.Embedding(14, 4)

        position = torch.arange(100, dtype=torch.float32).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, 8, 2, dtype=torch.float32)
            * (-np.log(10_000.0) / 8)
        )
        position_encoding = torch.zeros(1, 100, 8)
        position_encoding[:, :, 0::2] = torch.sin(position * div_term)
        position_encoding[:, :, 1::2] = torch.cos(position * div_term)
        self.register_buffer("position_encoding", position_encoding)

        self.chord_transformer = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                d_model=8,
                nhead=8,
                dim_feedforward=64,
                dropout=0.1,
                batch_first=True,
            ),
            num_layers=2,
        )
        self.input_proj = nn.Sequential(
            nn.Linear(1536 + 8 + 1, 512),
            nn.ReLU(),
        )
        self.classification_branch = nn.Sequential(
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, 56),
        )
        self.regression_branch = nn.Sequential(
            nn.Linear(512, 256),
            nn.ReLU(),
            nn.Linear(256, 2),
        )

    def forward(
        self,
        mert: torch.Tensor,
        chord_root: torch.Tensor,
        chord_attr: torch.Tensor,
        key: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        root = self.chord_root_embedding(chord_root)
        attr = self.chord_attr_embedding(chord_attr)
        chord = torch.cat((root, attr), dim=-1)
        chord = chord + self.position_encoding[:, :chord.shape[1], :]
        cls = torch.zeros_like(chord[:, :1, :])
        chord = self.chord_transformer(torch.cat((cls, chord), dim=1))
        chord_summary = chord[:, 0, :]
        hidden = self.input_proj(torch.cat((mert, chord_summary, key), dim=1))
        return (
            self.classification_branch(hidden),
            self.regression_branch(hidden),
        )


class Music2EmoMoodAnalyzer:
    """Lazy-loaded Music2Emo analyzer with a bounded idle lifetime."""

    def __init__(
        self,
        *,
        device: str | None = None,
        idle_timeout_seconds: float = 300.0,
        top_tag_count: int = 16,
    ) -> None:
        if idle_timeout_seconds <= 0:
            raise ValueError("idle_timeout_seconds must be positive.")
        if top_tag_count < 1:
            raise ValueError("top_tag_count must be positive.")

        self.device = torch.device(
            device or ("cuda" if torch.cuda.is_available() else "cpu")
        )
        self.idle_timeout_seconds = idle_timeout_seconds
        self.top_tag_count = top_tag_count
        self._processor: Wav2Vec2FeatureExtractor | None = None
        self._mert: nn.Module | None = None
        self._mood_head: _Music2EmoHead | None = None
        self._chord_model: nn.Module | None = None
        self._chord_mean: float | None = None
        self._chord_std: float | None = None
        self._tags: np.ndarray | None = None
        self._last_used_at: float | None = None
        self._model_lock = RLock()

    @property
    def is_loaded(self) -> bool:
        return all(
            value is not None
            for value in (
                self._processor,
                self._mert,
                self._mood_head,
                self._chord_model,
            )
        )

    def analyze(
        self,
        audio_path: Path,
        *,
        genres: Iterable[tuple[str, float]] = (),
    ) -> Music2EmoAnalysisResult:
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio file does not exist: {audio_path}")

        self._ensure_loaded()
        self._last_used_at = time.monotonic()

        mert_embedding = self._extract_mert_embedding(audio_path)
        chord_root, chord_attr, key = self._extract_chord_inputs(audio_path)

        assert self._mood_head is not None
        assert self._tags is not None
        with torch.inference_mode():
            logits, regression = self._mood_head(
                mert_embedding,
                chord_root,
                chord_attr,
                key,
            )
            probabilities = torch.sigmoid(logits)[0].cpu().numpy()
            top_indexes = np.argsort(probabilities)[::-1][: self.top_tag_count]
            tags = tuple(
                (str(self._tags[index]), float(probabilities[index]))
                for index in top_indexes
            )
            valence = _clamp_affect(float(regression[0, 0].item()))
            arousal = _clamp_affect(float(regression[0, 1].item()))

        affect_mood = music2emo_to_vector(valence, arousal)
        profiles = predict_mood_profiles(
            valence=valence,
            arousal=arousal,
            tags=tags,
            genres=genres,
        )
        mood = blend_mood_with_profiles(
            affect_mood,
            profiles,
        )
        return Music2EmoAnalysisResult(
            mood=mood,
            tags=tags,
            profiles=profiles,
            valence=valence,
            arousal=arousal,
        )

    def unload(self) -> None:
        with self._model_lock:
            self._processor = None
            self._mert = None
            self._mood_head = None
            self._chord_model = None
            self._chord_mean = None
            self._chord_std = None
            self._tags = None
            self._last_used_at = None
            if self.device.type == "cuda":
                torch.cuda.empty_cache()

    def unload_if_idle(self, now: float | None = None) -> bool:
        if not self.is_loaded or self._last_used_at is None:
            return False

        current_time = now if now is not None else time.monotonic()
        if current_time - self._last_used_at < self.idle_timeout_seconds:
            return False

        self.unload()
        return True

    def _ensure_loaded(self) -> None:
        if self.is_loaded:
            return

        with self._model_lock:
            if self.is_loaded:
                return

            if not MODEL_ROOT.exists():
                raise FileNotFoundError(
                    f"Music2Emo model directory does not exist: {MODEL_ROOT}"
                )

            self._processor = Wav2Vec2FeatureExtractor.from_pretrained(
                MERT_NAME,
                trust_remote_code=True,
            )
            self._mert = AutoModel.from_pretrained(
                MERT_NAME,
                trust_remote_code=True,
            ).to(self.device)
            self._mert.eval()
            self._mood_head = _load_mood_head(self.device)
            (
                self._chord_model,
                self._chord_mean,
                self._chord_std,
            ) = _load_chord_model(self.device)
            self._tags = np.load(
                MODEL_ROOT / "inference" / "data" / "tag_list.npy",
                allow_pickle=True,
            )[127:]

    def _extract_mert_embedding(self, audio_path: Path) -> torch.Tensor:
        assert self._processor is not None
        assert self._mert is not None
        waveform, sample_rate = torchaudio.load(str(audio_path))
        waveform = waveform.mean(dim=0)
        if sample_rate != MERT_SAMPLE_RATE:
            waveform = torchaudio.functional.resample(
                waveform,
                sample_rate,
                MERT_SAMPLE_RATE,
            )

        window_size = MERT_SAMPLE_RATE * MERT_WINDOW_SECONDS
        embeddings = []
        with torch.inference_mode():
            for start in range(0, waveform.shape[0], window_size):
                window = waveform[start : start + window_size]
                inputs = self._processor(
                    window.numpy(),
                    sampling_rate=MERT_SAMPLE_RATE,
                    return_tensors="pt",
                )
                inputs = {
                    name: value.to(self.device)
                    for name, value in inputs.items()
                }
                outputs = self._mert(
                    **inputs,
                    output_hidden_states=True,
                )
                hidden_states = torch.stack(outputs.hidden_states)[1:]
                embeddings.append(
                    torch.cat(
                        (
                            hidden_states[5].mean(dim=1),
                            hidden_states[6].mean(dim=1),
                        ),
                        dim=1,
                    )
                )

        return torch.cat(embeddings, dim=0).mean(dim=0, keepdim=True)

    def _extract_chord_inputs(
        self,
        audio_path: Path,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert self._chord_model is not None
        assert self._chord_mean is not None
        assert self._chord_std is not None

        waveform, sample_rate = torchaudio.load(str(audio_path))
        waveform = waveform.mean(dim=0)
        if sample_rate != CHORD_SAMPLE_RATE:
            waveform = torchaudio.functional.resample(
                waveform,
                sample_rate,
                CHORD_SAMPLE_RATE,
            )
        audio = waveform.numpy()
        features = _cqt_features(audio)
        features = (features - self._chord_mean) / self._chord_std
        padding = CHORD_TIMESTEP - (features.shape[0] % CHORD_TIMESTEP)
        features = np.pad(features, ((0, padding), (0, 0)))

        predictions = []
        with torch.inference_mode():
            for start in range(0, features.shape[0], CHORD_TIMESTEP):
                batch = torch.from_numpy(
                    features[start : start + CHORD_TIMESTEP]
                ).float().unsqueeze(0).to(self.device)
                hidden, _ = self._chord_model.self_attn_layers(batch)
                logits = self._chord_model.output_layer(hidden)
                predictions.append(logits.argmax(dim=-1)[0].cpu().numpy())

        chord_indexes = np.concatenate(predictions)[: features.shape[0] - padding]
        root_ids = []
        attr_ids = []
        for index in chord_indexes[:100]:
            index = int(index)
            if index == 169:
                root_ids.append(0)
                attr_ids.append(0)
            else:
                root_ids.append(index // 14 + 1)
                attr_ids.append(index % 14)

        root_ids.extend([0] * (100 - len(root_ids)))
        attr_ids.extend([0] * (100 - len(attr_ids)))
        mode = _estimate_mode(audio)
        return (
            torch.tensor(root_ids, dtype=torch.long, device=self.device).unsqueeze(0),
            torch.tensor(attr_ids, dtype=torch.long, device=self.device).unsqueeze(0),
            torch.tensor([[float(mode)]], device=self.device),
        )


def _load_mood_head(device: torch.device) -> _Music2EmoHead:
    head = _Music2EmoHead().to(device)
    checkpoint = _safe_load(
        MODEL_ROOT / "saved_models" / "J_all.ckpt",
        device,
    )
    state_dict = {
        key.removeprefix("model."): value
        for key, value in checkpoint["state_dict"].items()
    }
    model_keys = set(head.state_dict())
    result = head.load_state_dict(
        {
            key: value
            for key, value in state_dict.items()
            if key in model_keys
        },
        strict=False,
    )
    if result.unexpected_keys:
        raise RuntimeError(
            f"Unexpected Music2Emo head keys: {result.unexpected_keys}"
        )
    return head.eval()


def _load_chord_model(
    device: torch.device,
) -> tuple[nn.Module, float, float]:
    if str(MODEL_ROOT) not in sys.path:
        sys.path.insert(0, str(MODEL_ROOT))
    from utils.btc_model import BTC_model
    from utils.hparams import HParams

    config = HParams.load(
        str(MODEL_ROOT / "inference" / "data" / "run_config.yaml")
    )
    config.model["probs_out"] = True
    model = BTC_model(config.model).to(device)
    checkpoint = _safe_load(
        MODEL_ROOT / "inference" / "data" / "btc_model_large_voca.pt",
        device,
    )
    model.load_state_dict(checkpoint["model"], strict=True)
    return model.eval(), float(checkpoint["mean"]), float(checkpoint["std"])


def _safe_load(path: Path, device: torch.device) -> dict:
    add_safe_globals(
        [
            (np._core.multiarray.scalar, "numpy.core.multiarray.scalar"),
            (np.dtype, "numpy.dtype"),
            (np.dtypes.Float64DType, "numpy.dtype[float64]"),
            (np.dtypes.Float32DType, "numpy.dtype[float32]"),
        ]
    )
    return torch.load(
        path,
        map_location=device,
        weights_only=True,
    )


def _cqt_features(audio: np.ndarray) -> np.ndarray:
    instance_size = CHORD_SAMPLE_RATE * CHORD_INSTANCE_SECONDS
    chunks = []
    for start in range(0, audio.shape[0], instance_size):
        chunk = audio[start : start + instance_size]
        if chunk.size == 0:
            continue
        chunks.append(
            librosa.cqt(
                chunk,
                sr=CHORD_SAMPLE_RATE,
                n_bins=144,
                bins_per_octave=24,
                hop_length=2_048,
            )
        )
    return np.log(np.abs(np.concatenate(chunks, axis=1)) + 1e-6).T


def _estimate_mode(audio: np.ndarray) -> int:
    chroma = librosa.feature.chroma_cqt(
        y=audio,
        sr=CHORD_SAMPLE_RATE,
        n_chroma=12,
        bins_per_octave=24,
    ).mean(axis=1)
    chroma /= max(float(np.linalg.norm(chroma)), 1e-8)
    major = np.array(
        [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52,
         5.19, 2.39, 3.66, 2.29, 2.88]
    )
    minor = np.array(
        [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54,
         4.75, 3.98, 2.69, 3.34, 3.17]
    )
    candidates = []
    for profile, mode in ((major, 0), (minor, 1)):
        profile /= np.linalg.norm(profile)
        candidates.extend(
            (float(np.dot(chroma, np.roll(profile, shift))), mode)
            for shift in range(12)
        )
    return max(candidates)[1]


def _clamp_affect(value: float) -> float:
    return min(9.0, max(1.0, value))
