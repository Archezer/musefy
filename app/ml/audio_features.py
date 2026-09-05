import os
from pathlib import Path

from app.storage.paths import BUNDLED_DATA_DIR

_ffmpeg_dll_dir = None

ffmpeg_bins: list[Path] = []
if BUNDLED_DATA_DIR is not None:
    ffmpeg_bins.append(BUNDLED_DATA_DIR / "ffmpeg")

local_app_data = os.environ.get("LOCALAPPDATA")

if local_app_data:
    ffmpeg_bins.extend(
        sorted(
            Path(local_app_data).glob(
            "Microsoft/WinGet/Packages/"
            "Gyan.FFmpeg.Shared_*/*/bin"
            )
        )
    )

if ffmpeg_bins:
    ffmpeg_bin = ffmpeg_bins[0]
    if not (ffmpeg_bin / "ffmpeg.exe").is_file():
        ffmpeg_bin = ffmpeg_bins[-1]

    os.environ["PATH"] = (
        str(ffmpeg_bin)
        + os.pathsep
        + os.environ.get("PATH", "")
    )

    if hasattr(os, "add_dll_directory"):
        _ffmpeg_dll_dir = os.add_dll_directory(str(ffmpeg_bin))

import torch
import torchaudio


class AudioWindowLoader:
    def __init__(
        self,
        sample_rate: int = 16_000,
        window_seconds: int = 30,
        hop_seconds: int = 15,
    ) -> None:
        self.sample_rate = sample_rate
        self.window_size = sample_rate * window_seconds
        self.hop_size = sample_rate * hop_seconds
        self.mel_spectrogram = (
            torchaudio.transforms.MelSpectrogram(
                sample_rate=sample_rate,
                n_fft=512,
                hop_length=256,
                n_mels=96,
                power=2.0,
                center=True,
                pad_mode="constant",
                norm="slaney",
                mel_scale="slaney",
            )
        )

    def load(self, audio_path: Path) -> torch.Tensor:
        waveform, source_rate = torchaudio.load(
            str(audio_path)
        )

        waveform = waveform.mean(dim=0)

        if source_rate != self.sample_rate:
            waveform = torchaudio.functional.resample(
                waveform,
                source_rate,
                self.sample_rate,
            )

        if waveform.numel() < self.window_size:
            waveform = torch.nn.functional.pad(
                waveform,
                (0, self.window_size - waveform.numel()),
            )

        last_start = waveform.numel() - self.window_size
        starts = range(0, last_start + 1, self.hop_size)

        windows = [
            waveform[start:start + self.window_size]
            for start in starts
        ]

        if not windows or starts[-1] != last_start:
            windows.append(
                waveform[-self.window_size:]
            )

        return torch.stack(windows)


    def to_mel_batch(
            self,
            windows: torch.Tensor
    ) -> torch.Tensor:
        if windows.ndim != 2:
            raise ValueError(
                "Windows must have shape "
                "[batch, samples]."
            )

        mel = self.mel_spectrogram(windows)
        mel = torch.log10(
            1.0 + mel.clamp_min(1e-30) * 10_000
        )
        mel = (
            mel - 2.06755686098554
        ) / (1.268292820667291 * 2)

        return mel.transpose(1, 2)
