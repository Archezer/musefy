import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.domain.models import User
from app.ingestion.audio import AudioIngestionService
from app.recommenders.mood import MoodRecommender
from app.recommenders.popularity import MostPopularRecommender
from app.services.interactions import InteractionService
from app.services.playback_queue import PlaybackQueueService
from app.services.playlist_bridge import PlaylistBridgeServer
from app.services.playlists import PlaylistManagementService
from app.services.recommendations import RecommendationService
from app.services.soundcloud_import import SoundCloudImportService
from app.services.track_similarity import TrackSimilarityService
from app.services.tracks import TrackManagementService
from app.services.youtube_import import YouTubeImportService
from app.storage.database import (
    create_database,
    create_session,
)
from app.storage.repository import SQLAlchemyMusicStore
from app.ui.components import MUSEFY_ICON_SVG, svg_icon
from app.ui.main_window import MainWindow

CURRENT_USER_ID = "user-1"
_NATIVE_MUSEFY_ICON_HANDLE = None


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
    soundcloud_import_service = SoundCloudImportService(
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

    _set_windows_app_user_model_id()
    qt_application = QApplication(sys.argv)
    qt_application.setApplicationName("Musefy")
    qt_application.setApplicationDisplayName("Musefy")
    musefy_icon = _load_musefy_icon()
    qt_application.setWindowIcon(musefy_icon)

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
        soundcloud_import_service=soundcloud_import_service,
        playback_queue_service=playback_queue_service,
        playlist_management_service=playlist_management_service,
        user_id=CURRENT_USER_ID,
    )
    window.setWindowIcon(musefy_icon)
    window.show()
    _apply_windows_taskbar_icon(window)

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


def _load_musefy_icon() -> QIcon:
    """Load the circular PNG mark, with an SVG fallback for source runs."""

    icon_path = _find_musefy_asset("musefy-icon.png")
    if icon_path is None:
        icon_path = _find_musefy_asset("musefy-mark.ico")
    if icon_path is not None:
        return QIcon(str(icon_path))

    return svg_icon(MUSEFY_ICON_SVG, size=128)


def _find_musefy_asset(filename: str) -> Path | None:
    roots = (
        Path(__file__).resolve().parents[1],
        Path(getattr(sys, "_MEIPASS", "")),
        Path(sys.executable).resolve().parent / "_internal",
    )
    for root in roots:
        candidate = root / "assets" / filename
        if candidate.is_file():
            return candidate
    return None


def _apply_windows_taskbar_icon(window: MainWindow) -> None:
    """Set the native HWND icons so Windows cannot fall back to uv/python."""

    global _NATIVE_MUSEFY_ICON_HANDLE
    if sys.platform != "win32":
        return

    icon_path = _find_musefy_asset("musefy-mark.ico")
    if icon_path is None:
        return

    try:
        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HANDLE
        handle = user32.LoadImageW(
            None,
            str(icon_path),
            1,  # IMAGE_ICON
            0,
            0,
            0x50,  # LR_DEFAULTSIZE | LR_LOADFROMFILE
        )
        if not handle:
            return

        hwnd = int(window.winId())
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = wintypes.LRESULT
        user32.SendMessageW(hwnd, 0x0080, 1, handle)  # WM_SETICON / ICON_BIG
        user32.SendMessageW(hwnd, 0x0080, 0, handle)  # WM_SETICON / ICON_SMALL
        set_class_long_ptr = getattr(user32, "SetClassLongPtrW", None)
        if set_class_long_ptr is not None:
            set_class_long_ptr.argtypes = [
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_void_p,
            ]
            set_class_long_ptr.restype = ctypes.c_void_p
            set_class_long_ptr(hwnd, -14, handle)  # GCLP_HICON
            set_class_long_ptr(hwnd, -34, handle)  # GCLP_HICONSM
        _NATIVE_MUSEFY_ICON_HANDLE = handle
    except (AttributeError, OSError, TypeError, ValueError):
        # Qt's icon remains active if the optional native shell call fails.
        return


def _set_windows_app_user_model_id() -> None:
    """Give source and packaged launches one stable taskbar identity."""

    if sys.platform != "win32":
        return

    try:
        shell32 = ctypes.windll.shell32
        shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [
            wintypes.LPCWSTR
        ]
        shell32.SetCurrentProcessExplicitAppUserModelID("Archzer.Musefy")
    except (AttributeError, OSError):
        # The desktop app is also runnable on non-Windows platforms and the
        # shell API may be unavailable there.
        pass


if __name__ == "__main__":
    main()
