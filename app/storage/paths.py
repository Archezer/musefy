from pathlib import Path

DATA_DIR = Path("data")
DATABASE_PATH = DATA_DIR / "music.db"
LIBRARY_DIR = DATA_DIR / "library"
PLAYLIST_EXPORTS_DIR = Path("playlist_exports")


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
