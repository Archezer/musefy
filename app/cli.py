import argparse
from pathlib import Path

from app.ingestion.audio import AudioIngestionService
from app.storage.memory import InMemoryMusicStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Music recommendation system CLI"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    ingest_parser = subparsers.add_parser(
        "ingest",
        help="Read an audio file and add it to the catalog",
    )

    ingest_parser.add_argument(
        "file_path",
        type=Path,
        help="Path to the local audio file",
    )

    return parser


def handle_ingest(file_path: Path) -> None:
    store = InMemoryMusicStore()
    ingestion_service = AudioIngestionService(store)

    track = ingestion_service.ingest(
        file_path,
        source="local_upload",
    )

    print("Track ingested successfully.")
    print()
    print(f"ID: {track.id}")
    print(f"Title: {track.title}")
    print(f"Artist: {track.artist}")
    print(f"Duration: {_format_duration(track.duration_ms)}")
    print(f"Source: {track.source}")
    print(f"Local path: {track.local_path}")


def _format_duration(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "Unknown"

    total_seconds = duration_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)

    return f"{minutes}:{seconds:02d}"


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.command == "ingest":
        handle_ingest(arguments.file_path)


if __name__ == "__main__":
    main()