import json
from datetime import UTC, datetime
from zipfile import ZIP_DEFLATED, ZipFile

from app.domain.models import SpotifyTrackMetadata
from app.services.spotify_history_import import (
    SpotifyListeningHistoryImportService,
)
from app.storage.memory import InMemoryMusicStore


def history_entry(
    spotify_id: str,
    *,
    timestamp: str,
    ms_played: int,
    reason_end: str = "trackdone",
    skipped: bool = False,
) -> dict:
    return {
        "ts": timestamp,
        "ms_played": ms_played,
        "spotify_track_uri": f"spotify:track:{spotify_id}",
        "reason_end": reason_end,
        "skipped": skipped,
    }


def test_history_import_stores_stats_without_tracks_or_interactions(
    tmp_path,
) -> None:
    store = InMemoryMusicStore()
    store.upsert_spotify_track_metadata(
        SpotifyTrackMetadata(
            spotify_id="spotify-1",
            title="First",
            artist="Artist",
            duration_ms=100_000,
            imported_at=datetime.now(UTC),
        )
    )
    history = [
        history_entry(
            "spotify-1",
            timestamp="2025-01-01T10:00:00Z",
            ms_played=90_000,
        ),
        history_entry(
            "spotify-1",
            timestamp="2025-01-02T10:00:00Z",
            ms_played=5_000,
            reason_end="fwdbtn",
            skipped=True,
        ),
        {
            "ts": "2025-01-03T10:00:00Z",
            "ms_played": 1_000,
            "master_metadata_track_name": "No external ID",
        },
    ]
    path = tmp_path / "Streaming_History_Audio_2025.json"
    path.write_text(json.dumps(history), encoding="utf-8")

    result = SpotifyListeningHistoryImportService(store).import_path(path)

    assert result.source_files == 1
    assert result.total_entries == 3
    assert result.imported_stats == 1
    assert result.updated_stats == 0
    assert result.skipped_entries == 1
    assert store.list_tracks() == []
    assert store.list_interactions() == []
    assert store.list_spotify_favorites("user-1") == []

    stats = store.get_spotify_listening_stats("spotify-1")
    assert stats is not None
    assert stats.play_count == 2
    assert stats.total_ms_played == 95_000
    assert stats.completion_count == 1
    assert stats.skip_count == 1
    assert stats.first_played_at == datetime(
        2025,
        1,
        1,
        10,
        tzinfo=UTC,
    )
    assert stats.last_played_at == datetime(
        2025,
        1,
        2,
        10,
        tzinfo=UTC,
    )


def test_history_import_reads_zip_and_is_idempotent(tmp_path) -> None:
    store = InMemoryMusicStore()
    first_history = [
        history_entry(
            "spotify-1",
            timestamp="2024-01-01T10:00:00Z",
            ms_played=60_000,
            reason_end="fwdbtn",
            skipped=True,
        )
    ]
    second_history = [
        history_entry(
            "spotify-1",
            timestamp="2024-02-01T10:00:00Z",
            ms_played=120_000,
        )
    ]
    path = tmp_path / "extended-history.zip"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "Streaming_History_Audio_2024_0.json",
            json.dumps(first_history),
        )
        archive.writestr(
            "Streaming_History_Audio_2024_1.json",
            json.dumps(second_history),
        )
        archive.writestr("account_data.json", json.dumps({"items": []}))

    service = SpotifyListeningHistoryImportService(store)
    first = service.import_path(path)
    second = service.import_path(path)

    assert first.source_files == 2
    assert first.total_entries == 2
    assert first.imported_stats == 1
    assert second.imported_stats == 0
    assert second.updated_stats == 0
    assert len(store.list_spotify_listening_stats()) == 1

    stats = store.get_spotify_listening_stats("spotify-1")
    assert stats is not None
    assert stats.play_count == 2
    assert stats.total_ms_played == 180_000
    assert stats.completion_count == 1
    assert stats.skip_count == 1
