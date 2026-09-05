import os
import sys
from pathlib import Path


def _runtime_root() -> Path:
    """Use the executable folder for frozen builds and cwd for source runs."""

    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Musefy"
        return Path(sys.executable).resolve().parent

    return Path.cwd()


def _bundled_data_dir() -> Path | None:
    """Find read-only model data shipped with a frozen application."""

    if not getattr(sys, "frozen", False):
        return None

    candidates = [Path(sys.executable).resolve().parent / "data"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "data")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


_configured_data_dir = os.environ.get("MUSEFY_DATA_DIR")
DATA_DIR = (
    Path(_configured_data_dir).expanduser()
    if _configured_data_dir
    else _runtime_root() / "data"
)
BUNDLED_DATA_DIR = _bundled_data_dir()
DATABASE_PATH = DATA_DIR / "music.db"
LIBRARY_DIR = DATA_DIR / "library"
PLAYLIST_EXPORTS_DIR = _runtime_root() / "playlist_exports"
PLAYLIST_COVERS_DIR = DATA_DIR / "playlist_covers"
TRACK_COVERS_DIR = DATA_DIR / "track_covers"
MUSIC_MAP_SNAPSHOT_PATH = DATA_DIR / "music_map_snapshot.png"
MUSIC_MAP_SNAPSHOT_METADATA_PATH = DATA_DIR / "music_map_snapshot.json"


def resolve_mert_source(model_name: str) -> str:
    """Use the local bundled MERT snapshot when the packaged app has one."""

    data_dirs = [DATA_DIR]
    if BUNDLED_DATA_DIR is not None:
        data_dirs.append(BUNDLED_DATA_DIR)

    for data_dir in data_dirs:
        model_dir = data_dir / "models" / "mert"
        if (model_dir / "config.json").is_file():
            return str(model_dir)

    return model_name


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
