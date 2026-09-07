from pathlib import Path
from subprocess import CompletedProcess

import pytest

from app.services import loudness

SUMMARY = """
[Parsed_ebur128_0 @ 000000] Summary:
  Integrated loudness:
    I:         -18.4 LUFS
  True peak:
    Peak:       -2.2 dBFS
"""


def test_loudness_summary_parser_ignores_per_frame_values() -> None:
    loudness_value, peak_value = loudness._parse_summary(SUMMARY)

    assert loudness_value == pytest.approx(-18.4)
    assert peak_value == pytest.approx(-2.2)


def test_normalization_gain_is_limited_by_true_peak() -> None:
    gain = loudness.calculate_normalization_gain(
        integrated_lufs=-18.4,
        true_peak_db=-2.2,
    )

    assert gain == pytest.approx(1.2)


def test_analyze_loudness_uses_ffmpeg_and_returns_gain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"audio")
    calls: list[list[str]] = []

    monkeypatch.setattr(
        loudness,
        "_find_ffmpeg",
        lambda: Path("ffmpeg.exe"),
    )

    def fake_run(command, **_kwargs):
        calls.append(command)
        return CompletedProcess(
            command,
            0,
            stdout=b"",
            stderr=SUMMARY.encode("utf-8"),
        )

    monkeypatch.setattr(loudness.subprocess, "run", fake_run)

    result = loudness.analyze_loudness(audio_path)

    assert result.integrated_lufs == pytest.approx(-18.4)
    assert result.true_peak_db == pytest.approx(-2.2)
    assert result.gain_db == pytest.approx(1.2)
    assert calls[0][0] == "ffmpeg.exe"
    assert "ebur128=peak=true" in calls[0]
