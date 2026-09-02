from pathlib import Path

import app.ingestion.artwork as artwork_module


def test_embedded_artwork_is_persisted_as_track_cover(
    tmp_path: Path,
    monkeypatch,
) -> None:
    covers_directory = tmp_path / "track_covers"
    monkeypatch.setattr(
        artwork_module,
        "TRACK_COVERS_DIR",
        covers_directory,
    )
    monkeypatch.setattr(
        artwork_module,
        "ensure_storage_directories",
        lambda: covers_directory.mkdir(parents=True, exist_ok=True),
    )
    monkeypatch.setattr(
        artwork_module,
        "extract_embedded_artwork",
        lambda _path: (b"\x89PNG\r\n\x1a\ncover", "image/png"),
    )

    cover_path = artwork_module.save_embedded_artwork(
        tmp_path / "track.m4a",
        "track-1",
    )

    assert cover_path is not None
    assert Path(cover_path).name == "track-1.png"
    assert Path(cover_path).read_bytes().startswith(b"\x89PNG")


def test_missing_embedded_artwork_uses_ui_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        artwork_module,
        "extract_embedded_artwork",
        lambda _path: None,
    )

    assert artwork_module.save_embedded_artwork(
        tmp_path / "track.mp3",
        "track-1",
    ) is None
