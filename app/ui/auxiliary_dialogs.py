"""Lifecycle management for modeless dialogs owned by the main window."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QScrollArea,
    QToolButton,
    QWidget,
)


class AuxiliaryDialogManager(QObject):
    """Keep modeless dialogs and their compact restore chips in sync."""

    _REGISTERED_PROPERTY = "musefyAuxiliaryRegistered"
    _MINIMIZED_PROPERTY = "musefyAuxiliaryMinimized"
    TAB_WIDTH = 160
    TAB_MIN_WIDTH = 92
    TAB_HEIGHT = 30
    TAB_HORIZONTAL_PADDING = 22
    TAB_SPACING = 6

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

    def eventFilter(self, watched: object, event: object) -> bool:
        """Intercept native dialog minimization before Windows moves it away."""

        if self.event_filter(watched, event):
            return True
        return super().eventFilter(watched, event)

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

        self._sync_tabs()
        if not self._restore_buttons:
            self._container.hide()
        self._schedule_reposition()

    def minimize(self, dialog: QDialog) -> None:
        """Hide a dialog and expose a compact restore button in the top bar."""

        if dialog in self._restore_buttons:
            return

        button = QToolButton(self._container)
        button.setObjectName("auxiliaryMinimizedButton")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedWidth(self._natural_button_width(button, dialog))
        button.setFixedHeight(self.TAB_HEIGHT)
        self._update_button_title(button, dialog)
        button.clicked.connect(
            lambda _checked=False, target=dialog: self.restore(target)
        )
        self._restore_buttons[dialog] = button
        # Keep the oldest minimized window nearest the menu on the right.
        # New tabs are inserted before it, so the first tab does not jump
        # from the right edge to the left when another dialog is minimized.
        self._layout.insertWidget(
            0,
            button,
            0,
            Qt.AlignmentFlag.AlignVCenter,
        )
        self._sync_tabs()
        self._container.show()
        self._schedule_reposition()
        if isinstance(self._container, QScrollArea):
            # The new chip is inserted at the content's left edge.  Reset to
            # that exact edge after layout has assigned geometries instead of
            # asking QScrollArea to estimate a partially visible rectangle.
            QTimer.singleShot(
                0,
                lambda: self._container.horizontalScrollBar().setValue(
                    self._container.horizontalScrollBar().minimum()
                ),
            )

        dialog.setProperty(self._MINIMIZED_PROPERTY, True)
        # Clear the native minimized state before hiding so the OS does not
        # retain an additional taskbar item for a window represented in Musefy.
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        # A native showMinimized() can finish its own visibility update after
        # WindowStateChange is delivered.  Deferring the final hide by one
        # event-loop turn makes the in-app chip win that race consistently.
        QTimer.singleShot(0, lambda target=dialog: self._hide_minimized(target))

    def refresh(self, dialog: QDialog) -> None:
        """Refresh a minimized tab after its dialog title or progress changes."""

        button = self._restore_buttons.get(dialog)
        if button is not None:
            self._update_button_title(button, dialog)

    def preferred_width(self) -> int:
        """Return the natural width needed by the current minimized tabs."""

        count = len(self._restore_buttons)
        if count == 0:
            return 0
        return sum(
            button.width() for button in self._restore_buttons.values()
        ) + (count - 1) * self.TAB_SPACING

    def refresh_layout(self) -> None:
        """Recalculate tab widths after the host row has been resized."""

        self._sync_tabs()

    @staticmethod
    def _display_title(dialog: QDialog) -> str:
        title = dialog.windowTitle().strip() or "Auxiliary window"
        if len(title) > 28:
            title = f"{title[:27].rstrip()}…"
        return title

    @classmethod
    def _natural_button_width(
        cls,
        button: QToolButton,
        dialog: QDialog,
    ) -> int:
        title_width = button.fontMetrics().horizontalAdvance(
            cls._display_title(dialog)
        )
        return max(
            cls.TAB_MIN_WIDTH,
            min(
                cls.TAB_WIDTH,
                title_width + cls.TAB_HORIZONTAL_PADDING,
            ),
        )

    @classmethod
    def _update_button_title(
        cls,
        button: QToolButton,
        dialog: QDialog,
    ) -> None:
        title = cls._display_title(dialog)
        title = button.fontMetrics().elidedText(
            title,
            Qt.TextElideMode.ElideRight,
            max(20, button.width() - cls.TAB_HORIZONTAL_PADDING),
        )
        button.setText(title)
        button.setToolTip(f"Restore {dialog.windowTitle()}")

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

        self._sync_tabs()
        if not self._restore_buttons:
            self._container.hide()
        self._schedule_reposition()

        dialog.setProperty(self._MINIMIZED_PROPERTY, False)
        dialog.setWindowState(Qt.WindowState.WindowNoState)
        if was_minimized:
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()

    def _sync_tabs(self) -> None:
        """Resize the scroll area's content to the current tab row."""

        if not self._restore_buttons:
            return

        if isinstance(self._container, QScrollArea):
            viewport_width = self._container.viewport().width()
            buttons = tuple(self._restore_buttons.items())
            # Keep every chip tied to its own title.  Equalising all chips
            # whenever the row overflows made short titles grow after the
            # first scroll.  Only shrink the two-chip case when the viewport
            # itself is too narrow to contain both natural widths.
            button_widths = [
                self._natural_button_width(button, dialog)
                for dialog, button in buttons
            ]
            available_width = max(
                0,
                viewport_width - self.TAB_SPACING,
            )
            if len(buttons) <= 2 and sum(button_widths) > available_width:
                max_button_width = max(
                    self.TAB_MIN_WIDTH,
                    available_width // 2,
                )
                button_widths = [
                    min(width, max_button_width)
                    for width in button_widths
                ]

            for (dialog, button), button_width in zip(
                buttons,
                button_widths,
            ):
                button.setFixedWidth(button_width)
                self._update_button_title(button, dialog)

        self._layout.activate()
        content = self._layout.parentWidget()
        if content is not None:
            if isinstance(self._container, QScrollArea):
                content.setFixedHeight(
                    max(
                        self.TAB_HEIGHT + 4,
                        self._container.viewport().height(),
                    )
                )
            content_width = sum(
                button.width() for button in self._restore_buttons.values()
            ) + max(0, len(self._restore_buttons) - 1) * self.TAB_SPACING
            content.setFixedWidth(max(1, content_width))
            content.adjustSize()

    def _schedule_reposition(self) -> None:
        self._reposition()
        QTimer.singleShot(0, self._reposition)
