"""Lifecycle management for modeless dialogs owned by the main window."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QToolButton, QWidget


class AuxiliaryDialogManager(QObject):
    """Keep modeless dialogs and their compact restore chips in sync."""

    _REGISTERED_PROPERTY = "musefyAuxiliaryRegistered"
    _MINIMIZED_PROPERTY = "musefyAuxiliaryMinimized"

    def __init__(
        self,
        *,
        container: QWidget,
        layout: QHBoxLayout,
        reposition: Callable[[], None],
        cancel_task: Callable[[QDialog], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._container = container
        self._layout = layout
        self._reposition = reposition
        self._cancel_task = cancel_task
        self._dialogs: set[QDialog] = set()
        self._restore_buttons: dict[QDialog, QToolButton] = {}

    def show(self, dialog: QDialog) -> None:
        """Show a modeless dialog and wire its in-app minimize affordance."""

        self._register(dialog)
        self.restore(dialog)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def close_all(self) -> None:
        """Close every registered dialog before the main window exits."""

        for dialog in tuple(self._dialogs):
            dialog.close()

    def event_filter(self, watched: object, event: object) -> bool:
        if (
            isinstance(watched, QDialog)
            and watched in self._dialogs
            and isinstance(event, QEvent)
            and event.type() == QEvent.Type.WindowStateChange
            and watched.windowState() & Qt.WindowState.WindowMinimized
        ):
            self.minimize(watched)
            return True

        return False

    def _register(self, dialog: QDialog) -> None:
        """Track a dialog so native minimize becomes an in-app chip."""

        if dialog.property(self._REGISTERED_PROPERTY):
            self._dialogs.add(dialog)
            return

        self._dialogs.add(dialog)
        dialog.setProperty(self._REGISTERED_PROPERTY, True)
        dialog.installEventFilter(self)
        dialog.finished.connect(
            lambda _result, target=dialog: self._forget(target)
        )
        closed_signal = getattr(dialog, "closed", None)
        if closed_signal is not None:
            closed_signal.connect(
                lambda target=dialog: self._cancel_task(target)
            )

    def _forget(self, dialog: QDialog) -> None:
        """Remove a closed dialog's restore chip, if it still has one."""

        self._dialogs.discard(dialog)
        button = self._restore_buttons.pop(dialog, None)
        if button is not None:
            self._layout.removeWidget(button)
            button.deleteLater()

        if not self._restore_buttons:
            self._container.hide()
        self._schedule_reposition()

    def minimize(self, dialog: QDialog) -> None:
        """Hide a dialog and expose a compact restore button in the top bar."""

        if dialog in self._restore_buttons:
            return

        title = dialog.windowTitle().strip() or "Auxiliary window"
        if len(title) > 28:
            title = f"{title[:27].rstrip()}…"

        button = QToolButton(self._container)
        button.setObjectName("auxiliaryMinimizedButton")
        button.setText(title)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setToolTip(f"Restore {dialog.windowTitle()}")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setMaximumWidth(220)
        button.clicked.connect(
            lambda _checked=False, target=dialog: self.restore(target)
        )
        self._restore_buttons[dialog] = button
        self._layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._container.show()
        self._schedule_reposition()

        dialog.setProperty(self._MINIMIZED_PROPERTY, True)
        # Clear the native minimized state before hiding so the OS does not
        # retain an additional taskbar item for a window represented in Musefy.
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        # A native showMinimized() can finish its own visibility update after
        # WindowStateChange is delivered.  Deferring the final hide by one
        # event-loop turn makes the in-app chip win that race consistently.
        QTimer.singleShot(0, lambda target=dialog: self._hide_minimized(target))

    def _hide_minimized(self, dialog: QDialog) -> None:
        if (
            dialog in self._restore_buttons
            and dialog.property(self._MINIMIZED_PROPERTY)
        ):
            dialog.setWindowState(Qt.WindowState.WindowNoState)
            dialog.hide()

    def restore(self, dialog: QDialog) -> None:
        """Restore a dialog from its compact top-bar button."""

        was_minimized = bool(dialog.property(self._MINIMIZED_PROPERTY))
        button = self._restore_buttons.pop(dialog, None)
        if button is not None:
            self._layout.removeWidget(button)
            button.deleteLater()

        if not self._restore_buttons:
            self._container.hide()
        self._schedule_reposition()

        dialog.setProperty(self._MINIMIZED_PROPERTY, False)
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        if was_minimized:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

    def _schedule_reposition(self) -> None:
        self._reposition()
        QTimer.singleShot(0, self._reposition)
