"""Shared window chrome for Musefy's auxiliary dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QGraphicsDropShadowEffect


def prepare_dialog(dialog: QDialog) -> None:
    """Apply the common rounded, softly elevated auxiliary-window style.

    The native title bar is intentionally kept: Windows supplies the familiar
    close and minimize controls, while the stylesheet paints the rounded
    content surface and the graphics effect adds a subtle shadow.
    """

    # Keep an opaque backing store so the QSS background is painted correctly
    # on Windows. The rounded surface and shadow remain visible without making
    # the entire top-level window transparent.
    dialog.setAttribute(
        Qt.WidgetAttribute.WA_TranslucentBackground,
        False,
    )
    dialog.setWindowFlags(
        dialog.windowFlags()
        | Qt.WindowType.WindowSystemMenuHint
        | Qt.WindowType.WindowMinimizeButtonHint
    )

    shadow = QGraphicsDropShadowEffect(dialog)
    shadow.setBlurRadius(24)
    shadow.setOffset(0, 5)
    shadow.setColor(QColor(0, 0, 0, 150))
    dialog.setGraphicsEffect(shadow)
