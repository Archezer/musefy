import os
import sys
from pathlib import Path


def _runtime_root() -> Path:
    """Use the executable folder for frozen builds and cwd for source runs."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path.cwd()


_configured_data_dir = os.environ.get("MUSEFY_DATA_DIR")
DATA_DIR = (
    Path(_configured_data_dir).expanduser()
    if _configured_data_dir
    else _runtime_root() / "data"
)
DATABASE_PATH = DATA_DIR / "music.db"
LIBRARY_DIR = DATA_DIR / "library"
PLAYLIST_EXPORTS_DIR = _runtime_root() / "playlist_exports"
PLAYLIST_COVERS_DIR = DATA_DIR / "playlist_covers"
TRACK_COVERS_DIR = DATA_DIR / "track_covers"


def ensure_storage_directories() -> None:
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    LIBRARY_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    PLAYLIST_EXPORTS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    PLAYLIST_COVERS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    TRACK_COVERS_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
