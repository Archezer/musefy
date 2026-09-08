"""Windows-wide media hotkeys used by the desktop player."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication

WM_HOTKEY = 0x0312
MOD_NOREPEAT = 0x4000

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3


class GlobalMediaHotkeys(QAbstractNativeEventFilter):
    """Register the standard Windows media keys for the current app thread."""

    _HOTKEYS = (
        (0x4D51, VK_MEDIA_PLAY_PAUSE, "play_pause"),
        (0x4D52, VK_MEDIA_PREV_TRACK, "previous"),
        (0x4D53, VK_MEDIA_NEXT_TRACK, "next"),
    )

    def __init__(
        self,
        *,
        on_play_pause: Callable[[], None],
        on_previous: Callable[[], None],
        on_next: Callable[[], None],
    ) -> None:
        super().__init__()
        self._callbacks = {
            "play_pause": on_play_pause,
            "previous": on_previous,
            "next": on_next,
        }
        self._application = QCoreApplication.instance()
        self._user32 = None
        self._registered_ids: set[int] = set()
        self._id_to_action: dict[int, str] = {}

        if sys.platform != "win32" or self._application is None:
            return

        try:
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._configure_user32()
            if not self._register_hotkeys():
                self.unregister()
                return
            self._application.installNativeEventFilter(self)
        except (AttributeError, OSError, TypeError, ValueError):
            self.unregister()

    @property
    def is_active(self) -> bool:
        """Whether all three global media hotkeys are registered."""

        return len(self._registered_ids) == len(self._HOTKEYS)

    def unregister(self) -> None:
        """Release native resources before the Qt application exits."""

        if self._application is not None:
            self._application.removeNativeEventFilter(self)

        if self._user32 is not None:
            for hotkey_id in tuple(self._registered_ids):
                self._user32.UnregisterHotKey(None, hotkey_id)

        self._registered_ids.clear()
        self._id_to_action.clear()

    def nativeEventFilter(self, event_type, message):
        if event_type not in (
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
            "windows_generic_MSG",
            "windows_dispatcher_MSG",
        ):
            return False, 0

        try:
            message_address = int(message)
        except (TypeError, ValueError):
            try:
                message_address = message.__int__()
            except (AttributeError, TypeError, ValueError):
                return False, 0

        if not message_address:
            return False, 0

        try:
            native_message = ctypes.cast(
                message_address,
                ctypes.POINTER(wintypes.MSG),
            ).contents
        except (OSError, TypeError, ValueError):
            return False, 0

        if native_message.message != WM_HOTKEY:
            return False, 0

        action = self._id_to_action.get(int(native_message.wParam))
        if action is None:
            return False, 0

        self._callbacks[action]()
        return True, 0

    def _configure_user32(self) -> None:
        if self._user32 is None:
            return

        self._user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.RegisterHotKey.restype = wintypes.BOOL
        self._user32.UnregisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
        ]
        self._user32.UnregisterHotKey.restype = wintypes.BOOL

    def _register_hotkeys(self) -> bool:
        if self._user32 is None:
            return False

        for hotkey_id, virtual_key, action in self._HOTKEYS:
            if not self._user32.RegisterHotKey(
                None,
                hotkey_id,
                MOD_NOREPEAT,
                virtual_key,
            ):
                return False
            self._registered_ids.add(hotkey_id)
            self._id_to_action[hotkey_id] = action

        return True
