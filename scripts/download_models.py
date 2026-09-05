"""Download the model artifacts required by a source installation."""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "data" / "models"
MERT_ROOT = MODEL_ROOT / "mert"
CHUNK_SIZE = 8 * 1024 * 1024
DOWNLOAD_ATTEMPTS = 3


@dataclass(frozen=True)
class ModelFile:
    relative_path: str
    url: str
    expected_size: int


MODEL_FILES = (
    ModelFile(
        "maest/maest.onnx",
        os.environ.get(
            "MUSEFY_MAEST_URL",
            "https://essentia.upf.edu/models/feature-extractors/"
            "maest/discogs-maest-30s-pw-519l-2.onnx",
        ),
        348_052_337,
    ),
    ModelFile(
        "music2emo/inference/data/btc_model_large_voca.pt",
        "https://huggingface.co/amaai-lab/music2emo/resolve/main/"
        "inference/data/btc_model_large_voca.pt?download=true",
        12_229_576,
    ),
    ModelFile(
        "music2emo/saved_models/J_all.ckpt",
        "https://huggingface.co/amaai-lab/music2emo/resolve/main/"
        "saved_models/J_all.ckpt?download=true",
        12_958_092,
    ),
)

MERT_REQUIRED_FILES = (
    "config.json",
    "configuration_MERT.py",
    "modeling_MERT.py",
    "preprocessor_config.json",
    "pytorch_model.bin",
)


def _download_file(model_file: ModelFile) -> None:
    destination = MODEL_ROOT / model_file.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size == model_file.expected_size:
        print(f"[OK] {destination} already exists.")
        return

    temporary_path = destination.with_name(destination.name + ".download")
    request = urllib.request.Request(
        model_file.url,
        headers={"User-Agent": "Musefy-model-installer"},
    )
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            print(f"[INFO] Downloading {destination} (attempt {attempt}/{DOWNLOAD_ATTEMPTS})")
            transferred = 0
            with urllib.request.urlopen(request, timeout=60) as response, temporary_path.open(
                "wb"
            ) as output:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    transferred += len(chunk)
                    print(
                        f"\r       {transferred / 1_000_000:.0f} MB",
                        end="",
                        flush=True,
                    )
            print()
            if transferred != model_file.expected_size:
                raise RuntimeError(
                    f"expected {model_file.expected_size} bytes, got {transferred}"
                )
            os.replace(temporary_path, destination)
            print(f"[OK] Downloaded {destination}.")
            return
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            temporary_path.unlink(missing_ok=True)
            if attempt == DOWNLOAD_ATTEMPTS:
                raise SystemExit(
                    f"[ERROR] Could not download {destination}: {error}\n"
                    "Check the internet connection or VPN. For MAEST, set "
                    "MUSEFY_MAEST_URL to an accessible mirror."
                ) from error
            print(f"[WARNING] Download failed: {error}")


def _ensure_mert() -> None:
    if all((MERT_ROOT / filename).is_file() for filename in MERT_REQUIRED_FILES):
        print(f"[OK] MERT model already exists in {MERT_ROOT}.")
        return

    print("[INFO] Downloading MERT-v1-95M from Hugging Face...")
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            repo_id="m-a-p/MERT-v1-95M",
            local_dir=str(MERT_ROOT),
        )
    except Exception as error:
        raise SystemExit(
            f"[ERROR] Could not download MERT-v1-95M: {error}\n"
            "Check the internet connection or VPN and run install_musefy.bat again."
        ) from error

    missing = [
        filename
        for filename in MERT_REQUIRED_FILES
        if not (MERT_ROOT / filename).is_file()
    ]
    if missing:
        raise SystemExit(
            "[ERROR] MERT download completed but required files are missing:\n"
            + "\n".join(f"  - {filename}" for filename in missing)
        )
    print(f"[OK] MERT model downloaded to {MERT_ROOT}.")


def main() -> int:
    print("\nMusefy model setup\n")
    for model_file in MODEL_FILES:
        _download_file(model_file)
    _ensure_mert()
    print("\n[OK] All Musefy model files are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
