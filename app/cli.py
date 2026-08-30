import argparse
from pathlib import Path

from app.domain.models import InteractionType
from app.ingestion.audio import AudioIngestionService
from app.services.interactions import InteractionService
from app.services.youtube_import import YouTubeImportService
from app.sources.youtube import (
    YouTubeCandidate,
    YouTubeSearchProvider,
)
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

    youtube_search_command = commands.add_parser(
        "youtube-search",
        help="Search five YouTube videos",
    )

    youtube_search_command.add_argument(
        "query",
        help="Video title or search query",
    )

    youtube_import_command = commands.add_parser(
        "youtube-import",
        help="Select and import a YouTube video",
    )

    youtube_import_command.add_argument(
        "query",
        help="Video title or search query",
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


def search_youtube(
    arguments: argparse.Namespace,
) -> None:
    provider = YouTubeSearchProvider()

    try:
        candidates = provider.search(
            arguments.query,
            max_results=5,
        )
    except (
        RuntimeError,
        ValueError,
    ) as error:
        raise SystemExit(str(error)) from error

    print_youtube_candidates(candidates)


def import_youtube_track(
    arguments: argparse.Namespace,
) -> None:
    provider = YouTubeSearchProvider()

    try:
        candidates = provider.search(
            arguments.query,
            max_results=5,
        )
    except (
        RuntimeError,
        ValueError,
    ) as error:
        raise SystemExit(str(error)) from error

    print_youtube_candidates(candidates)
    selected_candidate = choose_youtube_candidate(
        candidates
    )

    try:
        create_database()

        store = SQLAlchemyMusicStore(create_session)
        ingestion_service = AudioIngestionService(store)
        import_service = YouTubeImportService(
            ingestion_service,
            provider=provider,
        )
        track = import_service.download_and_import(
            selected_candidate,
        )
    except (
        PermissionError,
        RuntimeError,
        ValueError,
        FileNotFoundError,
    ) as error:
        raise SystemExit(str(error)) from error

    print("YouTube track imported successfully:")
    print(f"ID: {track.id}")
    print(f"Title: {track.title}")
    print(f"Artist: {track.artist}")
    print(
        f"Duration: "
        f"{format_duration(track.duration_ms)}"
    )
    print(f"Local path: {track.local_path}")


def print_youtube_candidates(
    candidates: list[YouTubeCandidate],
) -> None:
    if not candidates:
        print("No videos found")
        return

    for index, candidate in enumerate(
        candidates,
        start=1,
    ):
        print(
            f"{index}. {candidate.title}"
        )
        print(
            f"   Channel: "
            f"{candidate.channel_title}"
        )
        print(
            f"   Duration: "
            f"{format_duration(candidate.duration_ms)}"
        )
        print(
            f"   Views: "
            f"{format_views(candidate.view_count)}"
        )
        print(
            f"   URL: {candidate.url}"
        )
        print()


def choose_youtube_candidate(
    candidates: list[YouTubeCandidate],
) -> YouTubeCandidate:
    if not candidates:
        raise SystemExit(
            "No videos available for selection"
        )

    while True:
        value = input(
            "Select video number: "
        ).strip()

        try:
            selected_index = int(value)
        except ValueError:
            print(
                "Please enter a valid number."
            )
            continue

        if not 1 <= selected_index <= len(
            candidates
        ):
            print(
                "Selected number is out of range."
            )
            continue

        return candidates[selected_index - 1]


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


def format_views(view_count: int | None) -> str:
    if view_count is None:
        return "Unknown"

    return f"{view_count:,}"


def main() -> None:
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.command == "import":
        import_track(arguments)
    elif arguments.command == "interact":
        record_interaction(arguments)
    elif arguments.command == "youtube-search":
        search_youtube(arguments)
    elif arguments.command == "youtube-import":
        import_youtube_track(arguments)


if __name__ == "__main__":
    main()
