from __future__ import annotations

import io
import time
import wave
from pathlib import Path

import musan
import numpy as np
import torchaudio


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "data" / "library"


PATTERNS = (
    "*ANTARCTICA*.mp4",
    "*O PANA!*.mp4",
    "*NOT EVEN GHOSTS*.mp4",
    "*The Lazy Song*.mp4",
    "*Never Gonna Give You Up*.m4a",
    "*Zombie*.mp4",
    "*cry, cry*.mp3",
    "*Feel Good Inc*.mp4",
    "*All The Things She Said*.mp4",
    "*Bad at Love*.mp4",
)


def find_track(pattern: str) -> Path | None:
    matches = sorted(LIBRARY.glob(pattern))
    return matches[0] if matches else None


def to_wav_bytes(path: Path) -> bytes:
    waveform, sample_rate = torchaudio.load(str(path))
    waveform = waveform.mean(dim=0).numpy()
    pcm = (
        np.clip(waveform, -1.0, 1.0) * 32767
    ).astype(np.int16).tobytes()

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)

    return buffer.getvalue()


def main() -> None:
    happy_sad_model, relaxing_energetic_model = (
        musan.load_pretraned_models()
    )

    for pattern in PATTERNS:
        path = find_track(pattern)

        if path is None:
            print("MISSING:", pattern)
            continue

        audio_bytes = to_wav_bytes(path)
        started_at = time.perf_counter()
        result = musan.predict(
            audio_bytes,
            model_hs=happy_sad_model,
            model_re=relaxing_energetic_model,
            verbose=False,
        )
        elapsed = time.perf_counter() - started_at

        print(path.name)
        print(
            {
                key: round(value, 4)
                if isinstance(value, float)
                else value
                for key, value in result.items()
            }
        )
        print("TIME_SECONDS:", round(elapsed, 3))


if __name__ == "__main__":
    main()
