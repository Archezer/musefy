"""Measure and calculate playback gain for track loudness normalization."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.storage.paths import BUNDLED_DATA_DIR

LOUDNESS_ANALYSIS_VERSION = "ffmpeg-ebur128-v1"
LOUDNESS_TARGET_LUFS = -14.0
LOUDNESS_TRUE_PEAK_TARGET_DB = -1.0
MAX_NORMALIZATION_BOOST_DB = 12.0
MIN_NORMALIZATION_CUT_DB = -24.0
LOUDNESS_ANALYSIS_TIMEOUT_SECONDS = 120


class LoudnessAnalysisError(RuntimeError):
    """Raised when a track cannot be measured for loudness."""


class LoudnessDecoderUnavailable(LoudnessAnalysisError):
    """Raised when FFmpeg is not available to the application."""


@dataclass(frozen=True)
class LoudnessAnalysis:
    """The loudness values and safe gain calculated for one audio file."""

    integrated_lufs: float
    true_peak_db: float
    gain_db: float


def analyze_loudness(
    audio_path: Path,
    *,
    target_lufs: float = LOUDNESS_TARGET_LUFS,
) -> LoudnessAnalysis:
    """Measure integrated LUFS and true peak through FFmpeg's EBU R128 filter."""

    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {audio_path}")

    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        raise LoudnessDecoderUnavailable(
            "FFmpeg is not installed or bundled."
        )

    command = [
        str(ffmpeg),
        "-nostdin",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        str(audio_path),
        "-filter_complex",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    creation_flags = (
        getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if os.name == "nt"
        else 0
    )

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            creationflags=creation_flags,
            timeout=LOUDNESS_ANALYSIS_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as error:
        raise LoudnessDecoderUnavailable(
            "FFmpeg could not be started."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise LoudnessAnalysisError(
            "FFmpeg timed out while measuring loudness."
        ) from error
    except OSError as error:
        raise LoudnessDecoderUnavailable(
            f"FFmpeg could not be started: {error}"
        ) from error

    output = _decode_output(completed.stderr)
    if completed.returncode != 0:
        detail = output.strip().splitlines()[-1] if output.strip() else "unknown FFmpeg error"
        raise LoudnessAnalysisError(detail)

    integrated_lufs, true_peak_db = _parse_summary(output)
    gain_db = calculate_normalization_gain(
        integrated_lufs,
        true_peak_db,
        target_lufs=target_lufs,
    )
    return LoudnessAnalysis(
        integrated_lufs=integrated_lufs,
        true_peak_db=true_peak_db,
        gain_db=gain_db,
    )


def calculate_normalization_gain(
    integrated_lufs: float,
    true_peak_db: float,
    *,
    target_lufs: float = LOUDNESS_TARGET_LUFS,
) -> float:
    """Return a loudness gain limited by true peak and safe boost bounds."""

    if not (-70.0 < integrated_lufs < 10.0):
        raise ValueError("Integrated loudness is outside the usable range")
    if not (-100.0 < true_peak_db < 10.0):
        raise ValueError("True peak is outside the usable range")

    desired_gain_db = target_lufs - integrated_lufs
    peak_limited_gain_db = LOUDNESS_TRUE_PEAK_TARGET_DB - true_peak_db
    return round(
        min(
            MAX_NORMALIZATION_BOOST_DB,
            peak_limited_gain_db,
            max(MIN_NORMALIZATION_CUT_DB, desired_gain_db),
        ),
        2,
    )


def _parse_summary(output: str) -> tuple[float, float]:
    """Parse only FFmpeg's final summary, not its per-frame progress lines."""

    summary = output.rsplit("Summary:", 1)[-1]
    loudness_match = re.search(
        r"^\s*I:\s*(-?(?:\d+(?:\.\d+)?|\.\d+))\s+LUFS\s*$",
        summary,
        flags=re.MULTILINE,
    )
    peak_match = re.search(
        r"True peak:.*?^\s*Peak:\s*"
        r"([-+]?(?:\d+(?:\.\d+)?|\.\d+))\s+dBFS\s*$",
        summary,
        flags=re.MULTILINE | re.DOTALL,
    )
    if loudness_match is None or peak_match is None:
        raise LoudnessAnalysisError(
            "FFmpeg did not return an EBU R128 loudness summary."
        )

    integrated_lufs = float(loudness_match.group(1))
    true_peak_db = float(peak_match.group(1))
    if integrated_lufs <= -70.0:
        raise LoudnessAnalysisError("Audio contains no measurable signal.")
    return integrated_lufs, true_peak_db


def _find_ffmpeg() -> Path | None:
    """Locate the bundled or installed FFmpeg executable."""

    if BUNDLED_DATA_DIR is not None:
        bundled = BUNDLED_DATA_DIR / "ffmpeg" / "ffmpeg.exe"
        if bundled.is_file():
            return bundled

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return Path(system_ffmpeg)

    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None

    candidates = sorted(
        Path(local_app_data).glob(
            "Microsoft/WinGet/Packages/"
            "Gyan.FFmpeg.Shared_*/*/bin/ffmpeg.exe"
        )
    )
    return candidates[-1] if candidates else None


def _decode_output(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
