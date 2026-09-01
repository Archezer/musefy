from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch
import torchaudio
from torch import nn
from transformers import AutoModel, Wav2Vec2FeatureExtractor

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "data" / "library"
MODEL_ROOT = ROOT / "data" / "models" / "music2emo"
MERT_NAME = "m-a-p/MERT-v1-95M"
TARGET_SAMPLE_RATE = 24_000
WINDOW_SECONDS = 30

TRACK_NAMES = (
    "$uicideboy$ — $UICIDEBOY$ - ANTARCTICA (Lyric Video).mp4",
    "$uicideboy$ — $UICIDEBOY$ - O PANA!.mp4",
    "$uicideboy$ — $UICIDEBOY$ - NOT EVEN GHOSTS ARE THIS EMPTY.mp4",
    "Bruno Mars — Bruno Mars - The Lazy Song (Official Video).mp4",
    "Rick Astley — Rick Astley - Never Gonna Give You Up.m4a",
    "TheCranberriesTV — The Cranberries - Zombie (Official Music Video).mp4",
    "Mazzy Star — cry, cry.mp3",
    "Gorillaz — Gorillaz - Feel Good Inc. (Official Video).mp4",
)


class Music2EmoHead(nn.Module):
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
        chord_root: torch.Tensor | None = None,
        chord_attr: torch.Tensor | None = None,
        key: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        batch_size = mert.shape[0]
        if chord_root is None:
            chord_root = torch.zeros(
                batch_size, 100, dtype=torch.long, device=mert.device
            )
        if chord_attr is None:
            chord_attr = torch.zeros_like(chord_root)
        root = self.chord_root_embedding(chord_root)
        attr = self.chord_attr_embedding(chord_attr)
        chord = torch.cat((root, attr), dim=-1)
        chord = chord + self.position_encoding[:, :chord.shape[1], :]
        cls = torch.zeros_like(chord[:, :1, :])
        chord = self.chord_transformer(torch.cat((cls, chord), dim=1))
        chord_summary = chord[:, 0, :]
        if key is None:
            key = torch.zeros(batch_size, 1, device=mert.device)
        combined = torch.cat((mert, chord_summary, key), dim=1)
        hidden = self.input_proj(combined)
        return self.classification_branch(hidden), self.regression_branch(hidden)


def load_head(device: torch.device) -> Music2EmoHead:
    head = Music2EmoHead().to(device)
    checkpoint = torch.load(
        MODEL_ROOT / "saved_models" / "J_all.ckpt",
        map_location=device,
        weights_only=True,
    )
    state_dict = {
        key.removeprefix("model."): value
        for key, value in checkpoint["state_dict"].items()
    }
    model_keys = set(head.state_dict())
    head.load_state_dict(
        {
            key: value
            for key, value in state_dict.items()
            if key in model_keys
        },
        strict=True,
    )
    head.eval()
    return head


def load_mert(device: torch.device):
    processor = Wav2Vec2FeatureExtractor.from_pretrained(
        MERT_NAME,
        trust_remote_code=True,
    )
    model = AutoModel.from_pretrained(
        MERT_NAME,
        trust_remote_code=True,
    ).to(device)
    model.eval()
    return processor, model


def track_mert_embedding(
    path: Path,
    processor: Wav2Vec2FeatureExtractor,
    model: nn.Module,
    device: torch.device,
) -> torch.Tensor:
    waveform, sample_rate = torchaudio.load(str(path))
    waveform = waveform.mean(dim=0)
    if sample_rate != TARGET_SAMPLE_RATE:
        waveform = torchaudio.functional.resample(
            waveform,
            sample_rate,
            TARGET_SAMPLE_RATE,
        )

    window_size = TARGET_SAMPLE_RATE * WINDOW_SECONDS
    windows = []
    for start in range(0, waveform.shape[0], window_size):
        window = waveform[start : start + window_size]
        if window.numel() > 0:
            windows.append(window)

    embeddings = []
    with torch.inference_mode():
        for window in windows:
            inputs = processor(
                window.numpy(),
                sampling_rate=TARGET_SAMPLE_RATE,
                return_tensors="pt",
            )
            inputs = {name: value.to(device) for name, value in inputs.items()}
            outputs = model(**inputs, output_hidden_states=True)
            hidden_states = torch.stack(outputs.hidden_states)[1:]
            layer_5 = hidden_states[5].mean(dim=1)
            layer_6 = hidden_states[6].mean(dim=1)
            embeddings.append(torch.cat((layer_5, layer_6), dim=1))

    return torch.cat(embeddings, dim=0).mean(dim=0, keepdim=True)


def main() -> None:
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    head = load_head(device)
    processor, mert = load_mert(device)
    tag_list = np.load(
        MODEL_ROOT / "inference" / "data" / "tag_list.npy",
        allow_pickle=True,
    )[127:]

    print("DEVICE:", device)
    for track_name in TRACK_NAMES:
        path = LIBRARY / track_name
        if not path.exists():
            print("MISSING:", track_name)
            continue

        started_at = time.perf_counter()
        mert_embedding = track_mert_embedding(path, processor, mert, device)
        with torch.inference_mode():
            logits, regression = head(mert_embedding)
            probabilities = torch.sigmoid(logits)[0].cpu().numpy()
            top_indices = np.argsort(probabilities)[::-1][:8]
            moods = [
                (str(tag_list[index]), round(float(probabilities[index]), 4))
                for index in top_indices
            ]
            valence, arousal = regression[0].cpu().tolist()

        print("\nTRACK:", path.name)
        print("MOODS:", moods)
        print(
            "VALENCE_AROUSAL:",
            (round(valence, 4), round(arousal, 4)),
        )
        print("TIME_SECONDS:", round(time.perf_counter() - started_at, 3))


if __name__ == "__main__":
    main()
