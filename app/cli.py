import argparse
from pathlib import Path

from app.domain.models import (
    DetectedGenre,
    InteractionType,
    Track,
)
from app.ingestion.audio import AudioIngestionService
from app.ml.genre_analysis import GenreAnalysisService
from app.ml.training_data import (
    build_ranker_dataset,
    inspect_ranker_data,
    make_synthetic_ranker_dataset,
    split_ranker_dataset_by_time,
)
from app.services.interactions import InteractionService
from app.services.spotify_favorites_import import (
    SpotifyFavoritesImportService,
)
from app.services.spotify_history_import import (
    SpotifyListeningHistoryImportService,
)
from app.services.tracks import TrackManagementService
from app.services.youtube_import import YouTubeImportService
from app.sources.spotify import SpotifyMetadataProvider
from app.sources.youtube import (
    YouTubeCandidate,
    YouTubeSearchProvider,
)
from app.storage.database import (
    create_database,
    create_session,
)
from app.storage.paths import (
    LOGISTIC_RANKER_MODEL_PATH,
    RANKER_MODEL_PATH,
    SYNTHETIC_RANKER_MODEL_PATH,
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

    youtube_import_url_command = commands.add_parser(
        "youtube-import-url",
        help="Download and import a YouTube URL",
    )

    youtube_import_url_command.add_argument(
        "url",
        help="YouTube video URL",
    )

    spotify_import_favorites_command = commands.add_parser(
        "spotify-import-favorites",
        help="Import Spotify favorite metadata for recommendations",
    )
    spotify_import_favorites_command.add_argument(
        "--user-id",
        default="user-1",
        help="Musefy user identifier (default: user-1)",
    )

    commands.add_parser(
        "spotify-reauthorize",
        help="Refresh Spotify OAuth authorization and saved token",
    )

    spotify_history_command = commands.add_parser(
        "spotify-import-history",
        help="Import Spotify Extended Streaming History JSON/ZIP",
    )
    spotify_history_command.add_argument(
        "file_path",
        type=Path,
        help="Path to Spotify Extended Streaming History JSON or ZIP",
    )

    ranker_command = commands.add_parser(
        "train-synthetic-ranker",
        help="Smoke-test all rankers on a synthetic multi-user dataset",
    )
    ranker_command.add_argument(
        "--user-count",
        type=int,
        default=8,
        help="Number of synthetic users (default: 8)",
    )
    ranker_command.add_argument(
        "--examples-per-user",
        type=int,
        default=80,
        help="Examples per user (default: 80)",
    )
    ranker_command.add_argument(
        "--epochs",
        type=int,
        default=30,
        help="Training epochs for PyTorch rankers (default: 30)",
    )
    ranker_command.add_argument(
        "--output",
        type=Path,
        default=SYNTHETIC_RANKER_MODEL_PATH,
        help="Output MLP artifact path",
    )
    real_ranker_command = commands.add_parser(
        "train-ranker",
        help="Train a ranker from stored recommendation impressions",
    )
    real_ranker_command.add_argument(
        "--backend",
        choices=("logistic", "mlp", "pairwise"),
        default="mlp",
        help="Ranker backend (default: mlp)",
    )
    real_ranker_command.add_argument(
        "--user-id",
        help="Train for one user; omit to use all users",
    )
    real_ranker_command.add_argument(
        "--attribution-days",
        type=int,
        default=1,
        help="Reaction attribution window (default: 1)",
    )
    real_ranker_command.add_argument(
        "--minimum-examples",
        type=int,
        default=100,
        help="Minimum labelled rows before training (default: 100)",
    )
    real_ranker_command.add_argument(
        "--epochs",
        type=int,
        default=30,
        help="Training epochs for PyTorch backends (default: 30)",
    )
    real_ranker_command.add_argument(
        "--output",
        type=Path,
        help="Artifact path; defaults by backend",
    )
    readiness_command = commands.add_parser(
        "ranker-status",
        help="Show whether stored impressions are ready for training",
    )
    readiness_command.add_argument(
        "--user-id",
        help="Inspect one user; omit to use all users",
    )
    readiness_command.add_argument(
        "--attribution-days",
        type=int,
        default=1,
        help="Reaction attribution window (default: 1)",
    )
    readiness_command.add_argument(
        "--minimum-examples",
        type=int,
        default=100,
        help="Minimum labelled rows for ready status (default: 100)",
    )

    return parser


def import_track(arguments: argparse.Namespace) -> None:
    create_database()

    store = SQLAlchemyMusicStore(create_session)
    ingestion_service = AudioIngestionService(store)
    track_management_service = TrackManagementService(store)
    genre_analysis_service = GenreAnalysisService(
        top_k=10,
        min_score=0.1,
    )

    track = ingestion_service.ingest(
        arguments.file_path,
        title=arguments.title,
        artist=arguments.artist,
        source="local_import",
    )

    track = analyze_track_genres(
        track=track,
        genre_analysis_service=genre_analysis_service,
        track_management_service=track_management_service,
    )

    print("Track imported successfully:")
    print(f"ID: {track.id}")
    print(f"Title: {track.title}")
    print(f"Artist: {track.artist}")
    print(f"Duration: {format_duration(track.duration_ms)}")
    print(f"Genres: {', '.join(track.genres) or 'Not specified'}")


def import_spotify_favorites(arguments: argparse.Namespace) -> None:
    """Import Spotify favorites without downloading or analyzing audio."""

    create_database()

    store = SQLAlchemyMusicStore(create_session)
    provider = SpotifyMetadataProvider()
    service = SpotifyFavoritesImportService(store, provider)
    result = service.import_all(arguments.user_id)

    print(
        "Spotify favorite metadata imported for recommendations. "
        "Audio was not downloaded."
    )
    print(f"Fetched: {result.fetched}")
    print(f"New metadata rows: {result.imported_metadata}")
    print(f"Updated metadata rows: {result.updated_metadata}")
    print(f"Skipped: {result.skipped_tracks}")


def reauthorize_spotify(_arguments: argparse.Namespace) -> None:
    """Force a fresh Spotify OAuth flow and save the new token."""

    provider = SpotifyMetadataProvider()
    provider.reauthorize()
    print("Spotify OAuth completed. Token was refreshed.")


def import_spotify_history(arguments: argparse.Namespace) -> None:
    """Import Spotify listening stats without creating library tracks."""

    create_database()
    store = SQLAlchemyMusicStore(create_session)
    service = SpotifyListeningHistoryImportService(store)
    result = service.import_path(arguments.file_path)

    print(
        "Spotify listening history imported for recommendations. "
        "Audio was not downloaded."
    )
    print(f"Source files: {result.source_files}")
    print(f"History entries: {result.total_entries}")
    print(f"New stats rows: {result.imported_stats}")
    print(f"Updated stats rows: {result.updated_stats}")
    print(f"Skipped entries: {result.skipped_entries}")


def train_synthetic_ranker(arguments: argparse.Namespace) -> None:
    """Exercise all ranker backends without reading or changing the DB."""

    from app.ml.artifacts import save_mlp_ranker
    from app.ml.logistic_ranker import train_logistic_ranker
    from app.ml.ranker import train_mlp_ranker, train_pairwise_mlp_ranker

    dataset = make_synthetic_ranker_dataset(
        user_count=arguments.user_count,
        examples_per_user=arguments.examples_per_user,
    )
    train, validation = split_ranker_dataset_by_time(dataset)
    logistic = train_logistic_ranker(train)
    mlp = train_mlp_ranker(
        train,
        validation_dataset=validation,
        epochs=arguments.epochs,
    )
    pairwise = train_pairwise_mlp_ranker(
        train,
        validation_dataset=validation,
        epochs=arguments.epochs,
    )
    save_mlp_ranker(mlp, arguments.output)

    print("Synthetic ranker pipeline completed.")
    print(f"Examples: {len(dataset.examples)}")
    print(
        "Train/validation: "
        f"{len(train.examples)}/{len(validation.examples)}"
    )
    print(f"Features: {', '.join(dataset.feature_names)}")
    print(f"Logistic scores: {len(logistic.predict_scores(validation))}")
    print(f"MLP final train loss: {mlp.train_losses[-1]:.4f}")
    print(f"Pairwise final train loss: {pairwise.train_losses[-1]:.4f}")
    print(f"MLP artifact: {arguments.output}")


def train_ranker(arguments: argparse.Namespace) -> None:
    """Train from labelled impressions already stored by Musefy."""

    from app.ml.artifacts import (
        save_logistic_ranker,
        save_mlp_ranker,
    )
    from app.ml.logistic_ranker import train_logistic_ranker
    from app.ml.ranker import train_mlp_ranker, train_pairwise_mlp_ranker

    create_database()
    store = SQLAlchemyMusicStore(create_session)
    readiness = inspect_ranker_data(
        store,
        user_id=arguments.user_id,
        attribution_days=arguments.attribution_days,
        minimum_examples=arguments.minimum_examples,
    )
    if not readiness.ready:
        raise SystemExit(
            "Ranker data is not ready: "
            f"{readiness.labelled_examples}/"
            f"{readiness.minimum_examples} labelled examples, "
            f"positive={readiness.positive_examples}, "
            f"negative={readiness.negative_examples}. "
            "Run ranker-status or collect more explicit reactions."
        )
    dataset = build_ranker_dataset(
        store,
        user_id=arguments.user_id,
        attribution_days=arguments.attribution_days,
    )
    if not dataset.examples:
        raise SystemExit(
            "No labelled impressions with feature snapshots yet. "
            "Show recommendations and collect explicit reactions first."
        )

    train, validation = split_ranker_dataset_by_time(dataset)
    output = arguments.output
    if arguments.backend == "logistic":
        ranker = train_logistic_ranker(train)
        if output is None:
            output = LOGISTIC_RANKER_MODEL_PATH
        save_logistic_ranker(ranker, output)
        validation_scores = ranker.predict_scores(validation)
        print(f"Validation scores: {len(validation_scores)}")
    elif arguments.backend == "pairwise":
        result = train_pairwise_mlp_ranker(
            train,
            validation_dataset=validation,
            epochs=arguments.epochs,
        )
        if output is None:
            output = RANKER_MODEL_PATH
        save_mlp_ranker(result, output)
        print(f"Final pairwise train loss: {result.train_losses[-1]:.4f}")
    else:
        result = train_mlp_ranker(
            train,
            validation_dataset=validation,
            epochs=arguments.epochs,
        )
        if output is None:
            output = RANKER_MODEL_PATH
        save_mlp_ranker(result, output)
        print(f"Final MLP train loss: {result.train_losses[-1]:.4f}")

    print("Real ranker training completed.")
    print(f"Examples: {len(dataset.examples)}")
    print(
        "Train/validation: "
        f"{len(train.examples)}/{len(validation.examples)}"
    )
    print(f"Features: {', '.join(dataset.feature_names)}")
    print(f"Artifact: {output}")


def show_ranker_status(arguments: argparse.Namespace) -> None:
    """Print ranker data readiness without training or writing an artifact."""

    create_database()
    store = SQLAlchemyMusicStore(create_session)
    readiness = inspect_ranker_data(
        store,
        user_id=arguments.user_id,
        attribution_days=arguments.attribution_days,
        minimum_examples=arguments.minimum_examples,
    )

    print(f"Ranker data status: {readiness.status}")
    print(f"Impressions: {readiness.total_impressions}")
    print(f"With feature snapshots: {readiness.snapshot_impressions}")
    print(f"Labelled examples: {readiness.labelled_examples}")
    print(f"Positive examples: {readiness.positive_examples}")
    print(f"Negative examples: {readiness.negative_examples}")
    print(f"Users represented: {readiness.user_count}")
    print(f"Minimum examples: {readiness.minimum_examples}")
    print(f"Features: {', '.join(readiness.feature_names) or 'none'}")


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
        track_management_service = TrackManagementService(store)
        genre_analysis_service = GenreAnalysisService(
            top_k=10,
            min_score=0.1,
        )
        import_service = YouTubeImportService(
            ingestion_service,
            provider=provider,
        )
        track = import_service.download_and_import(
            selected_candidate,
        )
        track = analyze_track_genres(
            track=track,
            genre_analysis_service=genre_analysis_service,
            track_management_service=track_management_service,
        )
    except (
        OSError,
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


def import_youtube_url(
    arguments: argparse.Namespace,
) -> None:
    try:
        create_database()

        store = SQLAlchemyMusicStore(create_session)
        ingestion_service = AudioIngestionService(store)
        track_management_service = TrackManagementService(store)
        genre_analysis_service = GenreAnalysisService(
            top_k=10,
            min_score=0.1,
        )
        import_service = YouTubeImportService(
            ingestion_service,
        )
        track = import_service.download_and_import_url(
            arguments.url,
        )
        track = analyze_track_genres(
            track=track,
            genre_analysis_service=genre_analysis_service,
            track_management_service=track_management_service,
        )
    except (
        OSError,
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


def analyze_track_genres(
    *,
    track: Track,
    genre_analysis_service: GenreAnalysisService,
    track_management_service: TrackManagementService,
) -> Track:
    if not track.local_path:
        return track

    predictions = genre_analysis_service.analyze(
        Path(track.local_path)
    )
    detected_genres = tuple(
        DetectedGenre(
            genre=prediction.genre,
            parent_genre=prediction.parent_genre,
            subgenre=prediction.subgenre,
            score=prediction.score,
            rank=prediction.rank,
            rank_weight=prediction.rank_weight,
            weighted_score=prediction.weighted_score,
        )
        for prediction in predictions
    )

    return track_management_service.update_detected_genres(
        track_id=track.id,
        detected_genres=detected_genres,
    )


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
    elif arguments.command == "youtube-import-url":
        import_youtube_url(arguments)
    elif arguments.command == "spotify-import-favorites":
        import_spotify_favorites(arguments)
    elif arguments.command == "spotify-reauthorize":
        reauthorize_spotify(arguments)
    elif arguments.command == "spotify-import-history":
        import_spotify_history(arguments)
    elif arguments.command == "train-synthetic-ranker":
        train_synthetic_ranker(arguments)
    elif arguments.command == "train-ranker":
        train_ranker(arguments)
    elif arguments.command == "ranker-status":
        show_ranker_status(arguments)


if __name__ == "__main__":
    main()
