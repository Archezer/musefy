from pathlib import Path

DATA_DIR = Path("data")
DATABASE_PATH = DATA_DIR / "music.db"
LIBRARY_DIR = DATA_DIR / "library"
PLAYLIST_EXPORTS_DIR = Path("playlist_exports")
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
