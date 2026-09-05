import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.domain.models import Track, User
from app.ingestion.audio import AudioIngestionService
from app.recommenders.mood import MoodRecommender
from app.recommenders.popularity import MostPopularRecommender
from app.services.interactions import InteractionService
from app.services.mp3party_import import Mp3PartyImportService
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
from app.storage.paths import BUNDLED_DATA_DIR
from app.storage.repository import SQLAlchemyMusicStore
from app.ui.components import MUSEFY_ICON_SVG, svg_icon
from app.ui.main_window import MainWindow

CURRENT_USER_ID = "user-1"
DEMO_TRACK_SOURCE = "musefy_easter_egg"
DEMO_TRACK_SOURCE_ID = "never-gonna-give-you-up"
DEMO_TRACK_FILENAME = "Rick Astley — Rick Astley - Never Gonna Give You Up.m4a"
_NATIVE_MUSEFY_ICON_HANDLE = None


def main() -> None:
    create_database()

    store = SQLAlchemyMusicStore(create_session)
    _ensure_current_user(store)

    ingestion_service = AudioIngestionService(store)
    demo_track = _ensure_demo_track(ingestion_service, store)
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
    mp3party_import_service = Mp3PartyImportService(
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
        mp3party_import_service=mp3party_import_service,
        playback_queue_service=playback_queue_service,
        playlist_management_service=playlist_management_service,
        user_id=CURRENT_USER_ID,
    )
    window.setWindowIcon(musefy_icon)
    window.show()
    _apply_windows_taskbar_icon(window)
    if demo_track is not None:
        window._enqueue_genre_analysis(demo_track)

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


def _ensure_demo_track(
    ingestion_service: AudioIngestionService,
    store: SQLAlchemyMusicStore,
) -> Track | None:
    """Install the bundled test track into the user's library once."""

    if BUNDLED_DATA_DIR is None:
        return None

    existing_track = store.get_track_by_source(
        DEMO_TRACK_SOURCE,
        DEMO_TRACK_SOURCE_ID,
    )
    if existing_track is not None:
        return None

    bundled_track_path = BUNDLED_DATA_DIR / "demo" / DEMO_TRACK_FILENAME
    if not bundled_track_path.is_file():
        return None

    return ingestion_service.ingest(
        bundled_track_path,
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        source=DEMO_TRACK_SOURCE,
        source_id=DEMO_TRACK_SOURCE_ID,
    )


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
        _set_windows_taskbar_properties(hwnd, icon_path)
        _NATIVE_MUSEFY_ICON_HANDLE = handle
    except (AttributeError, OSError, TypeError, ValueError, ctypes.ArgumentError):
        # Qt's icon remains active if the optional native shell call fails.
        return


def _set_windows_taskbar_properties(hwnd: int, icon_path: Path) -> None:
    """Tell the shell which icon belongs to an explicit taskbar identity.

    A source launch is hosted by ``uv``/Python, whose executable has a generic
    icon.  ``WM_SETICON`` updates the title bar, but Windows can still use the
    host executable for an unpinned taskbar button when an explicit
    AppUserModelID is present.  The shell property store lets us provide the
    same icon resource for that AppUserModelID without adding a Windows-only
    dependency such as pywin32.
    """

    class _Guid(ctypes.Structure):
        _fields_ = [
            ("data1", ctypes.c_ulong),
            ("data2", ctypes.c_ushort),
            ("data3", ctypes.c_ushort),
            ("data4", ctypes.c_ubyte * 8),
        ]

    class _PropertyKey(ctypes.Structure):
        _fields_ = [("fmtid", _Guid), ("pid", ctypes.c_ulong)]

    class _PropVariantValue(ctypes.Union):
        _fields_ = [("pwsz_val", ctypes.c_wchar_p)]

    class _PropVariant(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [
            ("vt", ctypes.c_ushort),
            ("reserved1", ctypes.c_ushort),
            ("reserved2", ctypes.c_ushort),
            ("reserved3", ctypes.c_ushort),
            ("value", _PropVariantValue),
        ]

    def _guid(
        data1: int,
        data2: int,
        data3: int,
        data4: tuple[int, ...],
    ) -> _Guid:
        value = _Guid()
        value.data1 = data1
        value.data2 = data2
        value.data3 = data3
        value.data4[:] = data4
        return value

    # GUID used by PKEY_AppUserModel_ID and PKEY_AppUserModel_RelaunchIconResource.
    app_user_model_fmtid = _guid(
        0x9F4C2855,
        0x9F79,
        0x4B39,
        (0xA8, 0xD0, 0xE1, 0xD4, 0x2D, 0xE1, 0xD5, 0xF3),
    )
    property_store_iid = _guid(
        0x886D8EEB,
        0x8CF2,
        0x4446,
        (0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99),
    )
    app_id_key = _PropertyKey(app_user_model_fmtid, 5)
    relaunch_icon_key = _PropertyKey(app_user_model_fmtid, 3)
    app_id_value = _PropVariant(vt=31, pwsz_val="Archzer.Musefy")
    icon_value = _PropVariant(
        vt=31,
        pwsz_val=f"{icon_path},0",
    )

    ole32 = ctypes.windll.ole32
    shell32 = ctypes.windll.shell32
    ole32.CoInitialize.argtypes = [ctypes.c_void_p]
    ole32.CoInitialize.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    shell32.SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(_Guid),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHGetPropertyStoreForWindow.restype = ctypes.c_long

    initialized = ole32.CoInitialize(None)
    try:
        store = ctypes.c_void_p()
        result = shell32.SHGetPropertyStoreForWindow(
            hwnd,
            ctypes.byref(property_store_iid),
            ctypes.byref(store),
        )
        if result != 0 or not store.value:
            return

        vtable = ctypes.cast(
            store,
            ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ).contents
        set_value = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            ctypes.c_void_p,
            ctypes.POINTER(_PropertyKey),
            ctypes.POINTER(_PropVariant),
        )(vtable[6])
        commit = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtable[7])
        release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])

        try:
            if (
                set_value(
                    store,
                    ctypes.byref(app_id_key),
                    ctypes.byref(app_id_value),
                )
                != 0
            ):
                return
            if (
                set_value(
                    store,
                    ctypes.byref(relaunch_icon_key),
                    ctypes.byref(icon_value),
                )
                != 0
            ):
                return
            commit(store)
        finally:
            release(store)
    finally:
        if initialized in (0, 1):
            ole32.CoUninitialize()


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
