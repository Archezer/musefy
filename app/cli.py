import argparse
from pathlib import Path

from app.domain.models import InteractionType
from app.ingestion.audio import AudioIngestionService
from app.services.interactions import InteractionService
from app.storage.database import (
    create_database,
    create_session,
)
from app.storage.repository import SQLAlchemyMusicStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Music recommendation system CLI"
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    import_command = commands.add_parser(
        "import",
        help="Import one local audio file",
    )

    import_command.add_argument(
        "file_path",
        type=Path,
        help="Path to an audio file",
    )
    import_command.add_argument(
        "--title",
        help="Override the title from audio metadata",
    )
    import_command.add_argument(
        "--artist",
        help="Override the artist from audio metadata",
    )
    import_command.add_argument(
        "--genres",
        default="",
        help="Comma-separated genres",
    )

    interaction_command = commands.add_parser(
        "interact",
        help="Record a user interaction",
    )

    interaction_command.add_argument(
        "user_id",
        help="User identifier",
    )

    interaction_command.add_argument(
        "track_id",
        help="Track identifier",
    )

    interaction_command.add_argument(
        "interaction_type",
        choices=[
            interaction.value
            for interaction in InteractionType
        ],
        help="Interaction type",
    )

    return parser


def import_track(arguments: argparse.Namespace) -> None:
    create_database()

    store = SQLAlchemyMusicStore(create_session)
    ingestion_service = AudioIngestionService(store)

    track = ingestion_service.ingest(
        arguments.file_path,
        title=arguments.title,
        artist=arguments.artist,
        genres=parse_genres(arguments.genres),
        source="local_import",
    )

    print("Track imported successfully:")
    print(f"ID: {track.id}")
    print(f"Title: {track.title}")
    print(f"Artist: {track.artist}")
    print(f"Duration: {format_duration(track.duration_ms)}")
    print(f"Genres: {', '.join(track.genres) or 'Not specified'}")


def record_interaction(
    arguments: argparse.Namespace,
) -> None:
    create_database()

    store = SQLAlchemyMusicStore(create_session)
    interaction_service = InteractionService(store)

    interaction_type = InteractionType(
        arguments.interaction_type
    )

    result = interaction_service.record(
        user_id=arguments.user_id,
        track_id=arguments.track_id,
        interaction_type=interaction_type,
    )

    interaction = result.interaction

    if result.created:
        print("Interaction recorded successfully:")
    else:
        print("Interaction already existed:")

    print(f"User: {interaction.user_id}")
    print(f"Track: {interaction.track_id}")
    print(
        "Type: "
        f"{interaction.interaction_type.value}"
    )
    print(
        "Weight: "
        f"{interaction.interaction_type.weight}"
    )


def parse_genres(value: str) -> tuple[str, ...]:
    return tuple(
        genre.strip().lower()
        for genre in value.split(",")
        if genre.strip()
    )


def format_duration(duration_ms: int | None) -> str:
    if duration_ms is None:
        return "Unknown"

    total_seconds = duration_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)

    return f"{minutes}:{seconds:02d}"


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.command == "import":
        import_track(arguments)
    elif arguments.command == "interact":
        record_interaction(arguments)


if __name__ == "__main__":
    main()
