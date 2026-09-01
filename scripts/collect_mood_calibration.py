from __future__ import annotations

import csv
from pathlib import Path
from statistics import mean

from app.ml.music2emo import Music2EmoMoodAnalyzer

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "data" / "library"
OUTPUT = ROOT / "data" / "mood_calibration_raw.csv"

EXTENSIONS = {
    ".mp3",
    ".mp4",
    ".m4a",
    ".wav",
    ".flac",
    ".ogg",
    ".opus",
}


def main() -> None:
    files = sorted(
        path
        for path in LIBRARY.iterdir()
        if path.is_file()
        and path.suffix.lower() in EXTENSIONS
    )

    if not files:
        raise FileNotFoundError("No audio files found.")

    analyzer = Music2EmoMoodAnalyzer()
    valences: list[float] = []
    arousals: list[float] = []

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "index",
                "file_name",
                "model_valence",
                "model_arousal",
                "top_profiles",
            ],
        )
        writer.writeheader()

        print("DEVICE:", analyzer.device)

        for index, audio_path in enumerate(files):
            result = analyzer.analyze(audio_path)

            valences.append(result.valence)
            arousals.append(result.arousal)

            profiles = ";".join(
                (
                    f"{item.profile}:{item.score:.3f}"
                    f"(affect={item.affect_score:.3f},"
                    f"tag={item.tag_score:.3f})"
                )
                for item in result.profiles
            )

            writer.writerow(
                {
                    "index": index,
                    "file_name": audio_path.name,
                    "model_valence": f"{result.valence:.4f}",
                    "model_arousal": f"{result.arousal:.4f}",
                    "top_profiles": profiles,
                }
            )

            print(index, audio_path.name)

    analyzer.unload()

    print(f"Saved: {OUTPUT}")
    print(
        "VALENCE:",
        f"min={min(valences):.3f}",
        f"max={max(valences):.3f}",
        f"mean={mean(valences):.3f}",
    )
    print(
        "AROUSAL:",
        f"min={min(arousals):.3f}",
        f"max={max(arousals):.3f}",
        f"mean={mean(arousals):.3f}",
    )


if __name__ == "__main__":
    main()
