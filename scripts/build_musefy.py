"""Build a complete portable Musefy application directory.

The output is an onedir PyInstaller bundle. It contains the Python runtime,
all application dependencies, and every ML model required by the desktop app.
The separate installer then packages this directory for end users.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / ".build_tools"
if TOOLS_DIR.is_dir():
    sys.path.insert(0, str(TOOLS_DIR))

MODEL_ROOT = ROOT / "data" / "models"
DEMO_TRACK_PATH = (
    ROOT
    / "data"
    / "library"
    / "Rick Astley — Rick Astley - Never Gonna Give You Up.m4a"
)


def _find_mert_snapshot() -> Path:
    """Find a downloaded MERT snapshot without relying on a live user cache."""

    cache_roots: list[Path] = []
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        cache_roots.extend((Path(hf_home) / "hub", Path(hf_home)))

    hf_hub_cache = os.environ.get("HF_HUB_CACHE")
    if hf_hub_cache:
        cache_roots.append(Path(hf_hub_cache))

    cache_roots.append(Path.home() / ".cache" / "huggingface" / "hub")

    seen: set[Path] = set()
    for cache_root in cache_roots:
        cache_root = cache_root.expanduser()
        if cache_root in seen:
            continue
        seen.add(cache_root)

        model_cache = cache_root / "models--m-a-p--MERT-v1-95M"
        snapshots_dir = model_cache / "snapshots"
        snapshots = sorted(
            (path for path in snapshots_dir.glob("*") if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for snapshot in snapshots:
            required = (
                "config.json",
                "configuration_MERT.py",
                "modeling_MERT.py",
                "preprocessor_config.json",
                "pytorch_model.bin",
            )
            if all((snapshot / filename).is_file() for filename in required):
                return snapshot

    raise SystemExit(
        "MERT is not cached. Run the pre-download command from README.md "
        "before building the installer."
    )


def _find_ffmpeg_bin() -> Path:
    """Find the shared FFmpeg directory to ship with the installer."""

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return Path(ffmpeg_path).resolve().parent

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates = sorted(
            Path(local_app_data).glob(
                "Microsoft/WinGet/Packages/"
                "Gyan.FFmpeg.Shared_*/*/bin"
            )
        )
        for candidate in reversed(candidates):
            if (candidate / "ffmpeg.exe").is_file():
                return candidate

    raise SystemExit(
        "Shared FFmpeg was not found. Install Gyan.FFmpeg.Shared and "
        "run the installer build again."
    )


def _add_data_files(
    arguments: list[str],
    source_root: Path,
    target_root: str,
    *,
    skip_filenames: set[str] | None = None,
) -> None:
    """Add individual files so temporary model caches never enter the bundle."""

    skip_filenames = skip_filenames or set()
    for source_path in sorted(source_root.rglob("*")):
        if not source_path.is_file():
            continue

        relative_path = source_path.relative_to(source_root)
        if any(part in {".cache", "__pycache__"} for part in relative_path.parts):
            continue
        if source_path.name in skip_filenames:
            continue

        target_dir = Path(target_root) / relative_path.parent
        arguments.extend(
            [
                "--add-data",
                f"{source_path}{os.pathsep}{target_dir}",
            ]
        )


def _model_data_arguments() -> list[str]:
    """Validate and collect all model files used by the packaged application."""

    required_files = (
        MODEL_ROOT / "maest" / "maest.onnx",
        MODEL_ROOT / "maest" / "maest.json",
        MODEL_ROOT / "music2emo" / "inference" / "data" / "btc_model_large_voca.pt",
        MODEL_ROOT / "music2emo" / "saved_models" / "J_all.ckpt",
    )
    missing_files = [path for path in required_files if not path.is_file()]
    if missing_files:
        missing = "\n".join(f"  - {path}" for path in missing_files)
        raise SystemExit(
            "Required model files are missing. Download them using README.md:\n"
            f"{missing}"
        )

    arguments: list[str] = []
    _add_data_files(
        arguments,
        MODEL_ROOT,
        "data/models",
        skip_filenames={"maest-519l-1.onnx"},
    )
    _add_data_files(arguments, _find_mert_snapshot(), "data/models/mert")
    _add_data_files(arguments, _find_ffmpeg_bin(), "data/ffmpeg")
    if DEMO_TRACK_PATH.is_file():
        arguments.extend(
            [
                "--add-data",
                f"{DEMO_TRACK_PATH}{os.pathsep}data/demo",
            ]
        )
    else:
        print(
            "Demo track not found; building without the optional Easter egg: "
            f"{DEMO_TRACK_PATH}"
        )
    return arguments


def _make_windows_icon() -> Path:
    """Render the circular PNG mark into a taskbar-ready multi-size ICO."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    icon_svg_path = ROOT / "assets" / "musefy-icon.svg"
    icon_png_path = ROOT / "assets" / "musefy-icon.png"
    ico_path = ROOT / "assets" / "musefy-mark.ico"
    svg_data = icon_svg_path.read_bytes()
    qt_application = QGuiApplication.instance() or QGuiApplication([])
    icon_image = QImage(256, 256, QImage.Format.Format_ARGB32)
    icon_image.fill(Qt.GlobalColor.transparent)
    icon_painter = QPainter(icon_image)
    icon_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg_data)).render(icon_painter)
    icon_painter.end()
    icon_image.save(str(icon_png_path), "PNG")

    source = Image.open(icon_png_path).convert("RGBA")
    rendered: list[Image.Image] = []

    for size in (16, 24, 32, 48, 64, 128, 256):
        rendered.append(source.resize((size, size), Image.Resampling.LANCZOS))

    rendered[-1].save(
        ico_path,
        format="ICO",
        sizes=[(image.width, image.height) for image in rendered],
    )
    qt_application.quit()
    return ico_path


def main() -> None:
    ico_path = _make_windows_icon()
    from PyInstaller.__main__ import run

    assets = ROOT / "assets"
    model_data_arguments = _model_data_arguments()
    run(
        [
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name",
            "Musefy",
            "--icon",
            str(ico_path),
            "--add-data",
            f"{assets}{os.pathsep}assets",
            *model_data_arguments,
            "--paths",
            str(ROOT),
            str(ROOT / "app" / "desktop.py"),
        ]
    )

    bundle_root = ROOT / "dist" / "Musefy"
    # PyInstaller can pick up ICU DLLs from optional packages. They shadow
    # Qt's bundled ICU data on Windows and make QtWidgets fail with WinError
    # 127; Musefy uses Qt's own icudtl.dat instead.
    for conflicting_dll in ("icuuc.dll", "icudt78.dll"):
        conflicting_path = bundle_root / "_internal" / conflicting_dll
        if conflicting_path.exists():
            conflicting_path.unlink()

    bundle_root.joinpath("README.txt").write_text(
        "Musefy application bundle\n"
        "======================\n\n"
        "ML models are included in this installation.\n"
        "User data is stored in %LOCALAPPDATA%\\Musefy\\data.\n"
        "Set MUSEFY_DATA_DIR to use another location.\n\n"
        "To pin Musefy: right-click Musefy.exe, choose Show more options,\n"
        "then Pin to taskbar (or Create shortcut).\n",
        encoding="utf-8",
    )
    print(f"Built {bundle_root / 'Musefy.exe'}")


if __name__ == "__main__":
    main()
