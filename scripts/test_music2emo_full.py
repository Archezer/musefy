from __future__ import annotations

import sys
import time
from pathlib import Path

import librosa
import numpy as np
import torch
import torchaudio
from torch.serialization import add_safe_globals

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.test_music2emo_moods import (
    MODEL_ROOT,
    Music2EmoHead,
    load_mert,
    track_mert_embedding,
)

LIBRARY = ROOT / "data" / "library"
MUSIC2EMO_ROOT = ROOT / "data" / "models" / "music2emo"
sys.path.insert(0, str(MUSIC2EMO_ROOT))

from utils.btc_model import BTC_model
from utils.hparams import HParams


def load_chord_model(device: torch.device) -> BTC_model:
    config = HParams.load(
        str(MUSIC2EMO_ROOT / "inference" / "data" / "run_config.yaml")
    )
    config.model["probs_out"] = True
    model = BTC_model(config.model).to(device)

    add_safe_globals(
        [
            (np._core.multiarray.scalar, "numpy.core.multiarray.scalar"),
            (np.dtype, "numpy.dtype"),
            (np.dtypes.Float64DType, "numpy.dtype[float64]"),
            (np.dtypes.Float32DType, "numpy.dtype[float32]"),
        ]
    )
    checkpoint = torch.load(
        MUSIC2EMO_ROOT / "inference" / "data" / "btc_model_large_voca.pt",
        map_location=device,
        weights_only=True,
    )
    model.load_state_dict(checkpoint["model"], strict=True)
    model.eval()
    model.mean = float(checkpoint["mean"])
    model.std = float(checkpoint["std"])
    return model


def load_waveform(path: Path) -> np.ndarray:
    waveform, sample_rate = torchaudio.load(str(path))
    waveform = waveform.mean(dim=0)
    if sample_rate != 22_050:
        waveform = torchaudio.functional.resample(
            waveform,
            sample_rate,
            22_050,
        )
    return waveform.numpy()


def cqt_features(audio: np.ndarray) -> np.ndarray:
    sample_rate = 22_050
    instance_size = sample_rate * 10
    chunks = []
    for start in range(0, audio.shape[0], instance_size):
        chunk = audio[start : start + instance_size]
        if chunk.size == 0:
            continue
        chunks.append(
            librosa.cqt(
                chunk,
                sr=sample_rate,
                n_bins=144,
                bins_per_octave=24,
                hop_length=2_048,
            )
        )

    features = np.concatenate(chunks, axis=1)
    return np.log(np.abs(features) + 1e-6).T


def estimate_mode(audio: np.ndarray) -> int:
    chroma = librosa.feature.chroma_cqt(
        y=audio,
        sr=22_050,
        n_chroma=12,
        bins_per_octave=24,
    ).mean(axis=1)
    chroma = chroma / max(float(np.linalg.norm(chroma)), 1e-8)
    major_profile = np.array(
        [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52,
         5.19, 2.39, 3.66, 2.29, 2.88]
    )
    minor_profile = np.array(
        [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54,
         4.75, 3.98, 2.69, 3.34, 3.17]
    )
    scores = []
    for profile, mode in ((major_profile, 0), (minor_profile, 1)):
        profile = profile / np.linalg.norm(profile)
        scores.extend(
            (float(np.dot(chroma, np.roll(profile, shift))), mode)
            for shift in range(12)
        )
    return max(scores)[1]


def chord_inputs(
    audio: np.ndarray,
    model: BTC_model,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    features = cqt_features(audio)
    features = (features - model.mean) / model.std
    timestep = 108
    padding = timestep - (features.shape[0] % timestep)
    features = np.pad(features, ((0, padding), (0, 0)))

    predictions = []
    with torch.inference_mode():
        for start in range(0, features.shape[0], timestep):
            batch = torch.from_numpy(
                features[start : start + timestep]
            ).float().unsqueeze(0).to(device)
            hidden, _ = model.self_attn_layers(batch)
            logits = model.output_layer(hidden)
            predictions.append(logits.argmax(dim=-1)[0].cpu().numpy())

    chord_indices = np.concatenate(predictions)[: features.shape[0] - padding]
    root_ids = []
    attr_ids = []
    for index in chord_indices[:100]:
        index = int(index)
        if index == 169:
            root_ids.append(0)
            attr_ids.append(0)
            continue

        root_ids.append(index // 14 + 1)
        attr_ids.append(index % 14)

    root_ids.extend([0] * (100 - len(root_ids)))
    attr_ids.extend([0] * (100 - len(attr_ids)))
    mode = estimate_mode(audio)
    return (
        torch.tensor(root_ids, dtype=torch.long, device=device).unsqueeze(0),
        torch.tensor(attr_ids, dtype=torch.long, device=device).unsqueeze(0),
        torch.tensor([[float(mode)]], device=device),
    )


def find_tracks() -> list[Path]:
    patterns = (
        "*ANTARCTICA*.mp4",
        "*O PANA!*.mp4",
        "*Never Gonna Give You Up*.m4a",
        "*Zombie*.mp4",
        "*cry, cry*.mp3",
        "*Feel Good Inc*.mp4",
    )
    tracks = []
    for pattern in patterns:
        match = sorted(LIBRARY.glob(pattern))
        if match:
            tracks.append(match[0])
    return tracks


def main() -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    mood_head = Music2EmoHead().to(device)
    checkpoint = torch.load(
        MODEL_ROOT / "saved_models" / "J_all.ckpt",
        map_location=device,
        weights_only=True,
    )
    load_result = mood_head.load_state_dict(
        {
            key.removeprefix("model."): value
            for key, value in checkpoint["state_dict"].items()
            if key.removeprefix("model.") in mood_head.state_dict()
        },
        strict=False,
    )
    if load_result.unexpected_keys:
        raise RuntimeError(
            f"Unexpected Music2Emo keys: {load_result.unexpected_keys}"
        )
    mood_head.eval()
    processor, mert = load_mert(device)
    chord_model = load_chord_model(device)
    tags = np.load(
        MODEL_ROOT / "inference" / "data" / "tag_list.npy",
        allow_pickle=True,
    )[127:]

    print("DEVICE:", device)
    for path in find_tracks():
        started_at = time.perf_counter()
        audio = load_waveform(path)
        roots, attrs, key = chord_inputs(audio, chord_model, device)
        mert_embedding = track_mert_embedding(path, processor, mert, device)
        with torch.inference_mode():
            logits, regression = mood_head(
                mert_embedding,
                roots,
                attrs,
                key,
            )
            probabilities = torch.sigmoid(logits)[0].cpu().numpy()
            top_indices = np.argsort(probabilities)[::-1][:8]
            moods = [
                (str(tags[index]), round(float(probabilities[index]), 4))
                for index in top_indices
            ]
            valence, arousal = regression[0].cpu().tolist()

        print("\nTRACK:", path.name)
        print("MOODS:", moods)
        print("VALENCE_AROUSAL:", (round(valence, 4), round(arousal, 4)))
        print("TIME_SECONDS:", round(time.perf_counter() - started_at, 3))


if __name__ == "__main__":
    main()
