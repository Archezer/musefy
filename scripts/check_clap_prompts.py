from pathlib import Path

import numpy as np
import torch
import torchaudio

from app.ml.clap import ClapTextEncoder


audio_path = sorted(
    Path("data/library").glob("*.mp4")
)[0]

waveform, sample_rate = torchaudio.load(str(audio_path))
waveform = waveform.mean(dim=0)

if sample_rate != 48_000:
    waveform = torchaudio.functional.resample(
        waveform,
        sample_rate,
        48_000,
    )

audio = waveform.numpy()
window_size = 48_000 * 10

windows = []

for start in range(0, len(audio), window_size):
    window = audio[start:start + window_size]

    if len(window) == 0:
        continue

    windows.append(window)

encoder = ClapTextEncoder()

audio_vectors = [
    encoder.encode_audio(window, 48_000)
    for window in windows
]

track_vector = np.mean(audio_vectors, axis=0)
track_vector /= np.linalg.norm(track_vector)

prompts = [
    "rage music for gym",
    "dark aggressive hip hop",
    "energetic workout music",
    "sad melancholic music",
    "calm relaxing music",
    "happy upbeat pop music",
    "romantic love song",
    "jazz music",
]

results = []

for prompt in prompts:
    text_vector = encoder.encode_text(prompt)
    score = float(np.dot(track_vector, text_vector))
    results.append((prompt, score))

for prompt, score in sorted(
    results,
    key=lambda item: item[1],
    reverse=True,
):
    print(f"{score:.4f} | {prompt}")

print("WINDOWS:", len(windows))

encoder.unload()