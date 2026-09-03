"""Build a portable, Windows-friendly Musefy desktop bundle.

The application data and ML models are deliberately not copied into the
bundle: they are user state and can be very large. Place a ``data`` folder
next to ``Musefy.exe`` (or set ``MUSEFY_DATA_DIR``) when distributing it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / ".build_tools"
if TOOLS_DIR.is_dir():
    sys.path.insert(0, str(TOOLS_DIR))


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
            "--paths",
            str(ROOT),
            "--hidden-import",
            "scdl.scdl",
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
        "Musefy portable bundle\n"
        "======================\n\n"
        "The executable keeps user data outside the code bundle.\n"
        "Copy your data folder next to Musefy.exe, or set the\n"
        "MUSEFY_DATA_DIR environment variable to its location.\n\n"
        "To pin Musefy: right-click Musefy.exe, choose Show more options,\n"
        "then Pin to taskbar (or Create shortcut).\n",
        encoding="utf-8",
    )
    print(f"Built {bundle_root / 'Musefy.exe'}")


if __name__ == "__main__":
    main()
