import sys

from PySide6.QtWidgets import QApplication

from app.domain.models import User
from app.ingestion.audio import AudioIngestionService
from app.recommenders.mood import MoodRecommender
from app.recommenders.popularity import MostPopularRecommender
from app.services.interactions import InteractionService
from app.services.playback_queue import PlaybackQueueService
from app.services.playlists import PlaylistManagementService
from app.services.playlist_bridge import PlaylistBridgeServer
from app.services.recommendations import RecommendationService
from app.services.track_similarity import TrackSimilarityService
from app.services.tracks import TrackManagementService
from app.services.youtube_import import YouTubeImportService
from app.storage.database import (
    create_database,
    create_session,
)
from app.storage.repository import SQLAlchemyMusicStore
from app.ui.main_window import MainWindow

CURRENT_USER_ID = "user-1"


def main() -> None:
    create_database()

    store = SQLAlchemyMusicStore(create_session)
    _ensure_current_user(store)

    ingestion_service = AudioIngestionService(store)
    interaction_service = InteractionService(store)
    playback_queue_service = PlaybackQueueService()
    playlist_management_service = PlaylistManagementService(store)
    track_management_service = TrackManagementService(store)
    youtube_import_service = YouTubeImportService(
        ingestion_service
    )

    recommender = MostPopularRecommender(store)
    mood_recommender = MoodRecommender(store)
    # Keep a broad neighborhood available for track-radio streams; the UI
    # samples it in a lightly randomized order instead of returning only the
    # closest few matches.
    track_radio = TrackSimilarityService(
        store,
        neighbors_per_track=50,
    )
    recommendation_service = RecommendationService(
        recommender,
        mood_recommender=mood_recommender,
        track_radio=track_radio,
    )

    qt_application = QApplication(sys.argv)

    try:
        playlist_bridge = PlaylistBridgeServer()
        playlist_bridge.start()
    except OSError as error:
        print(
            f"Playlist browser bridge is unavailable: {error}",
            file=sys.stderr,
        )
    else:
        qt_application.aboutToQuit.connect(playlist_bridge.stop)

    window = MainWindow(
        store=store,
        ingestion_service=ingestion_service,
        interaction_service=interaction_service,
        recommendation_service=recommendation_service,
        track_management_service=track_management_service,
        youtube_import_service=youtube_import_service,
        playback_queue_service=playback_queue_service,
        playlist_management_service=playlist_management_service,
        user_id=CURRENT_USER_ID,
    )
    window.show()

    sys.exit(qt_application.exec())


def _ensure_current_user(
    store: SQLAlchemyMusicStore,
) -> None:
    if store.get_user(CURRENT_USER_ID) is not None:
        return

    store.add_user(
        User(
            id=CURRENT_USER_ID,
            display_name="Desktop User",
        )
    )


if __name__ == "__main__":
    main()
