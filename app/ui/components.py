from __future__ import annotations

import html
import re
import time
from collections.abc import Mapping
from pathlib import Path
from random import SystemRandom
from types import MappingProxyType
from typing import ClassVar

from PySide6.QtCore import (
    Property,
    QByteArray,
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFontMetrics,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QStyleOptionToolButton,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from app.ui.dialog_style import prepare_dialog


class SvgIconButton(QAbstractButton):
    """A compact rounded button that paints an SVG at any display scale."""

    def __init__(
        self,
        svg: str,
        *,
        tooltip: str,
        diameter: int = 38,
        flat: bool = False,
        icon_offset_y: int = 0,
        flat_background_inset: int = 2,
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._flat = flat
        self._icon_offset_y = icon_offset_y
        self._flat_background_inset = max(0, flat_background_inset)
        self._renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(diameter, diameter)

    def sizeHint(self) -> QSize:
        return QSize(self._diameter, self._diameter)

    def set_svg(self, svg: str) -> None:
        self._renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.isDown():
            background = QColor(112, 224, 190, 42)
        elif self.underMouse():
            background = QColor(112, 224, 190, 25)
        else:
            background = QColor(255, 255, 255, 10)

        if self._flat:
            if self.isDown() or self.underMouse():
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(background)
                inset = min(self._flat_background_inset, self.width() // 2)
                background_rect = self.rect().adjusted(
                    inset,
                    inset,
                    -inset,
                    -inset,
                )
                background_rect.translate(0, self._icon_offset_y)
                painter.drawEllipse(background_rect)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(
                self.rect().adjusted(1, 1, -1, -1),
                12,
                12,
            )
        padding = 6 if self._flat else 10
        icon_rect = self.rect().adjusted(
            padding,
            padding,
            -padding,
            -padding,
        )
        icon_rect.translate(0, self._icon_offset_y)
        self._renderer.render(
            painter,
            icon_rect,
        )


class HoverCircleMenuButton(QToolButton):
    """A menu button with the same quiet hover circle as the like control."""

    def __init__(
        self,
        *,
        diameter: int = 32,
        offset_x: int = 0,
        offset_y: int = 2,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._background_inset = 2
        self._offset_x = offset_x
        self._offset_y = offset_y
        self.setFixedSize(diameter, diameter)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def paintEvent(self, event: object) -> None:
        option = QStyleOptionToolButton()
        self.initStyleOption(option)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isDown() or self.underMouse():
            background = QColor(
                112,
                224,
                190,
                42 if self.isDown() else 25,
            )
            background_rect = self.rect().adjusted(
                self._background_inset,
                self._background_inset,
                -self._background_inset,
                -self._background_inset,
            )
            background_rect.translate(self._offset_x, self._offset_y)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawEllipse(background_rect)

        self.style().drawComplexControl(
            QStyle.ComplexControl.CC_ToolButton,
            option,
            painter,
            self,
        )
        painter.end()


def _color_with_alpha(value: str, alpha: int) -> QColor:
    color = QColor(value)
    color.setAlpha(alpha)
    return color


def _clamp_opacity(value: float) -> float:
    """Keep animated UI opacity values inside Qt's valid range."""

    return max(0.0, min(1.0, float(value)))


class RailIconButton(QToolButton):
    """A rail action with a quiet, per-icon graph-shaped hover glow."""

    BUTTON_SIZE = 42
    # Keep the glyph in a bounded, centered area.  The SVG artwork uses an
    # 18px coordinate grid; the graph-shaped hover surface is painted by the
    # same widget, so it never gets detached from the icon.
    ICON_SIZE = 24
    CONTENT_OFFSET_X = 0

    _GRAPH_VARIANTS: ClassVar[
        Mapping[str, tuple[tuple[tuple[float, float], ...], tuple[str, str]]]
    ] = MappingProxyType({
        "download": (
            (
                (0.28, 0.30),
                (0.58, 0.20),
                (0.79, 0.42),
                (0.70, 0.76),
                (0.32, 0.72),
            ),
            ("#9EEFD2", "#2C8176"),
        ),
        "library": (
            (
                (0.22, 0.48),
                (0.36, 0.23),
                (0.65, 0.20),
                (0.80, 0.48),
                (0.65, 0.77),
                (0.30, 0.73),
            ),
            ("#B2F2D8", "#4C786E"),
        ),
        "map": (
            (
                (0.26, 0.30),
                (0.72, 0.28),
                (0.80, 0.55),
                (0.56, 0.77),
                (0.25, 0.66),
            ),
            ("#8BDCC1", "#326D68"),
        ),
        "log": (
            (
                (0.28, 0.24),
                (0.73, 0.28),
                (0.78, 0.60),
                (0.58, 0.78),
                (0.24, 0.66),
            ),
            ("#B5FBE0", "#3C8176"),
        ),
    })

    def __init__(
        self,
        svg: str,
        *,
        tooltip: str,
        variant: str,
        icon_size: int = ICON_SIZE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        self._variant = variant
        self._icon_size = icon_size
        self._graph_opacity = 0.0
        self._graph_animation = QPropertyAnimation(
            self,
            b"graphOpacity",
            self,
        )
        self._graph_animation.setDuration(280)
        self._graph_animation.setEasingCurve(
            QEasingCurve(QEasingCurve.Type.InOutCubic)
        )
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(self.BUTTON_SIZE, self.BUTTON_SIZE)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._graph_opacity > 0.0:
            self._paint_graph_hover(painter, self._graph_opacity)

        content_offset = self.CONTENT_OFFSET_X
        icon_size = min(self._icon_size, self.width(), self.height())
        icon_left = (self.width() - icon_size) // 2 + content_offset
        icon_top = (self.height() - icon_size) // 2
        self._renderer.render(
            painter,
            self.rect().adjusted(
                icon_left,
                icon_top,
                -(self.width() - icon_left - icon_size),
                -(self.height() - icon_top - icon_size),
            ),
        )

    @Property(float)
    def graphOpacity(self) -> float:
        return self._graph_opacity

    @graphOpacity.setter
    def graphOpacity(self, value: float) -> None:
        self._graph_opacity = _clamp_opacity(value)
        self.update()

    def enterEvent(self, event: object) -> None:
        super().enterEvent(event)
        self._animate_graph_opacity(1.0)

    def leaveEvent(self, event: object) -> None:
        super().leaveEvent(event)
        self._animate_graph_opacity(0.0)

    def _animate_graph_opacity(self, target: float) -> None:
        self._graph_animation.stop()
        self._graph_animation.setStartValue(self._graph_opacity)
        self._graph_animation.setEndValue(target)
        self._graph_animation.start()

    def _paint_graph_hover(self, painter: QPainter, opacity: float) -> None:
        points, colors = self._GRAPH_VARIANTS.get(
            self._variant,
            self._GRAPH_VARIANTS["map"],
        )
        # Give the hover graph a little breathing room around the smaller
        # glyph, while keeping its expanded contour inside the button.
        hover_scale = 1.2
        coordinates = [
            (
                self.width()
                * (0.5 + (x - 0.5) * hover_scale),
                self.height()
                * (0.5 + (y - 0.5) * hover_scale),
            )
            for x, y in points
        ]

        # Quadratic segments through the midpoints make a closed, softly
        # rounded polygon instead of a sharp diamond or a rigid circle.
        blob_path = QPainterPath()
        last_x, last_y = coordinates[-1]
        first_x, first_y = coordinates[0]
        blob_path.moveTo(
            (last_x + first_x) / 2,
            (last_y + first_y) / 2,
        )
        for index, (x, y) in enumerate(coordinates):
            next_x, next_y = coordinates[(index + 1) % len(coordinates)]
            blob_path.quadTo(
                x,
                y,
                (x + next_x) / 2,
                (y + next_y) / 2,
            )
        blob_path.closeSubpath()

        fill = QLinearGradient(0, 0, self.width(), self.height())
        fill.setColorAt(
            0.0,
            _color_with_alpha(colors[0], round(50 * opacity)),
        )
        fill.setColorAt(
            0.5,
            _color_with_alpha(colors[1], round(42 * opacity)),
        )
        fill.setColorAt(
            1.0,
            _color_with_alpha("#101718", round(100 * opacity)),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawPath(blob_path)

        edge_pen = QPen(
            _color_with_alpha(colors[0], round(86 * opacity)),
            1.0,
        )
        edge_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(edge_pen)
        for index, start in enumerate(coordinates):
            end = coordinates[(index + 1) % len(coordinates)]
            painter.drawLine(
                round(start[0]),
                round(start[1]),
                round(end[0]),
                round(end[1]),
            )

        for index, (x, y) in enumerate(coordinates):
            glow = QRadialGradient(x, y, 5.5)
            glow.setColorAt(
                0.0,
                _color_with_alpha(colors[0], round(125 * opacity)),
            )
            glow.setColorAt(
                0.52,
                _color_with_alpha(colors[1], round(80 * opacity)),
            )
            glow.setColorAt(1.0, _color_with_alpha(colors[1], 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(
                round(x - 5.5),
                round(y - 5.5),
                11,
                11,
            )
            painter.setBrush(
                _color_with_alpha(
                    colors[0],
                    round((122 if index == 0 else 82) * opacity),
                )
            )
            painter.drawEllipse(
                round(x - 1.8),
                round(y - 1.8),
                4,
                4,
            )


class HoverTableWidget(QTableWidget):
    """QTableWidget that exposes the full row under the mouse pointer."""

    row_hovered = Signal(int)
    row_clicked = Signal(int)
    row_double_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row_widgets: dict[QWidget, int] = {}
        self._hovered_row = -1
        self._pending_click_row: int | None = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(220)
        self._click_timer.timeout.connect(self._emit_pending_row_click)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)

    def paintEvent(self, event: object) -> None:
        """Paint a translucent row wash after the table's own contents."""

        super().paintEvent(event)
        hovered_row = getattr(self, "_hovered_row", -1)
        if hovered_row < 0 or hovered_row == self.currentRow():
            return

        index = self.model().index(hovered_row, 0)
        row_rect = self.visualRect(index)
        if not row_rect.isValid() or row_rect.height() <= 0:
            return

        painter = QPainter(self.viewport())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 18))
        painter.drawRect(
            QRect(
                0,
                row_rect.top(),
                self.viewport().width(),
                row_rect.height(),
            )
        )
        painter.end()

    def register_row_widget(
        self,
        widget: QWidget,
        row_index: int,
    ) -> None:
        for child in (widget, *widget.findChildren(QWidget)):
            self._row_widgets[child] = row_index
            child.installEventFilter(self)

    def clear_row_widgets(self) -> None:
        """Forget embedded row controls before the table is rebuilt.

        QTableWidget destroys cell widgets when its row count is reset, but
        the hover table's event-filter registry otherwise keeps references to
        every old control.  Playlist switches and sorting would therefore
        make each later rebuild more expensive than the previous one.
        """

        for child in tuple(self._row_widgets):
            try:
                child.removeEventFilter(self)
            except RuntimeError:
                # Qt may already have deleted a cell widget while the table
                # was being cleared.
                pass
        self._row_widgets.clear()

    def eventFilter(self, watched: object, event: object) -> bool:
        if watched is self.viewport():
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove:
                self._publish_row_hover(
                    self.rowAt(int(event.position().y()))
                )
            elif event_type == QEvent.Type.MouseButtonPress:
                if event.button() == Qt.MouseButton.LeftButton:
                    self._queue_row_click(
                        self.rowAt(int(event.position().y()))
                    )
            elif event_type == QEvent.Type.MouseButtonDblClick:
                self._click_timer.stop()
                self._pending_click_row = None
                row_index = self.rowAt(int(event.position().y()))
                if row_index >= 0:
                    self.row_double_clicked.emit(row_index)
                    return True
            elif event_type == QEvent.Type.Leave:
                self._publish_row_hover(-1)
        elif watched in self._row_widgets:
            event_type = event.type()
            object_name = getattr(watched, "objectName", lambda: "")()
            if event_type == QEvent.Type.MouseButtonPress:
                if (
                    event.button() == Qt.MouseButton.LeftButton
                    and object_name
                    not in {
                        "playlistTrackCheck",
                        "playlistRemoveButton",
                        "trackQueueButton",
                    }
                ):
                    self._queue_row_click(self._row_widgets[watched])
            elif event_type == QEvent.Type.MouseButtonDblClick:
                self._click_timer.stop()
                self._pending_click_row = None
                self.row_double_clicked.emit(self._row_widgets[watched])
                return True
            if event_type in (
                QEvent.Type.Enter,
                QEvent.Type.MouseMove,
            ):
                self._publish_row_hover(self._row_widgets[watched])
            elif event_type == QEvent.Type.Leave:
                local_pos = self.viewport().mapFromGlobal(QCursor.pos())
                if not self.viewport().rect().contains(local_pos):
                    self._publish_row_hover(-1)

        return super().eventFilter(watched, event)

    def _queue_row_click(self, row_index: int) -> None:
        if row_index < 0:
            return
        self._pending_click_row = row_index
        self._click_timer.start()

    def _emit_pending_row_click(self) -> None:
        row_index = self._pending_click_row
        self._pending_click_row = None
        if row_index is not None:
            self.row_clicked.emit(row_index)

    def _publish_row_hover(self, row_index: int) -> None:
        if row_index == self._hovered_row:
            return
        self._hovered_row = row_index
        self.row_hovered.emit(row_index)
        self.viewport().update()


class RoundedScrollBar(QScrollBar):
    """A compact scrollbar with a hand-painted pill-shaped handle."""

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        self._hovered = False
        self._pressed = False
        self.setMouseTracking(True)
        if orientation == Qt.Orientation.Vertical:
            self.setFixedWidth(14)
        else:
            self.setFixedHeight(14)

    def enterEvent(self, event: object) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: object) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: object) -> None:
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: object) -> None:
        super().mouseReleaseEvent(event)
        self._pressed = False
        self.update()

    def mouseMoveEvent(self, event: object) -> None:
        super().mouseMoveEvent(event)
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        margin = 1.0
        if self.orientation() == Qt.Orientation.Vertical:
            track_length = max(1.0, self.height() - margin * 2)
            handle_length = self._handle_length(track_length)
            travel = max(0.0, track_length - handle_length)
            offset = self._handle_offset(travel)
            handle_rect = QRectF(
                margin,
                margin + offset,
                max(1.0, self.width() - margin * 2),
                handle_length,
            )
            gradient = QLinearGradient(
                handle_rect.left(),
                handle_rect.top(),
                handle_rect.right(),
                handle_rect.top(),
            )
        else:
            track_length = max(1.0, self.width() - margin * 2)
            handle_length = self._handle_length(track_length)
            travel = max(0.0, track_length - handle_length)
            offset = self._handle_offset(travel)
            handle_rect = QRectF(
                margin + offset,
                margin,
                handle_length,
                max(1.0, self.height() - margin * 2),
            )
            gradient = QLinearGradient(
                handle_rect.left(),
                handle_rect.top(),
                handle_rect.left(),
                handle_rect.bottom(),
            )

        if self._pressed:
            colors = (
                QColor("#82D1B5"),
                QColor("#5DB292"),
                QColor("#36776B"),
            )
        elif self._hovered:
            colors = (
                QColor("#6ABAA0"),
                QColor("#4E9A83"),
                QColor("#2E655B"),
            )
        else:
            colors = (
                QColor("#4D8F7D"),
                QColor("#347262"),
                QColor("#214B46"),
            )

        gradient.setColorAt(0.0, colors[0])
        gradient.setColorAt(0.5, colors[1])
        gradient.setColorAt(1.0, colors[2])
        painter.setBrush(gradient)
        radius = min(handle_rect.width(), handle_rect.height()) / 2
        painter.drawRoundedRect(handle_rect, radius, radius)
        painter.end()

    def _handle_length(self, track_length: float) -> float:
        scroll_range = self.maximum() - self.minimum()
        page_step = max(1, self.pageStep())
        if scroll_range <= 0:
            return track_length

        proportional_length = track_length * page_step / (
            scroll_range + page_step
        )
        minimum_length = 34.0
        return min(track_length, max(minimum_length, proportional_length))

    def _handle_offset(self, travel: float) -> float:
        if travel <= 0 or self.maximum() <= self.minimum():
            return 0.0

        position = self.value() - self.minimum()
        return travel * position / (self.maximum() - self.minimum())


class FadingVolumeSlider(QSlider):
    """Gradient volume control whose knob rests out of the way when idle."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._handle_opacity = 1.0
        self._fade_timer = QTimer(self)
        self._fade_timer.setSingleShot(True)
        self._fade_timer.setInterval(2400)
        self._fade_timer.timeout.connect(self._fade_handle)
        self._fade_animation = QPropertyAnimation(
            self,
            b"handleOpacity",
            self,
        )
        self._fade_animation.setDuration(420)
        self.valueChanged.connect(self._show_handle)
        self.valueChanged.connect(self._arm_handle_fade)
        self.sliderReleased.connect(self._arm_handle_fade)
        self._fade_timer.start()
        self.setFixedHeight(20)

    @Property(float)
    def handleOpacity(self) -> float:
        return self._handle_opacity

    @handleOpacity.setter
    def handleOpacity(self, value: float) -> None:
        self._handle_opacity = _clamp_opacity(value)
        self.update()

    def mousePressEvent(self, event: object) -> None:
        self._show_handle()
        super().mousePressEvent(event)

    def paintEvent(self, _event: object) -> None:
        option = QStyleOptionSlider()
        self.initStyleOption(option)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        left = 7
        right = max(left + 1, self.width() - 7)
        center_y = self.height() // 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(39, 47, 48))
        painter.drawRoundedRect(
            left,
            center_y - 2,
            right - left,
            4,
            2,
            2,
        )

        position = QStyle.sliderPositionFromValue(
            self.minimum(),
            self.maximum(),
            self.value(),
            right - left,
            option.upsideDown,
        )
        handle_x = left + position
        gradient = QLinearGradient(left, 0, right, 0)
        gradient.setColorAt(0.0, QColor("#B5FBE0"))
        gradient.setColorAt(0.5, QColor("#5DD8B7"))
        gradient.setColorAt(1.0, QColor("#32877C"))
        painter.setBrush(gradient)
        painter.drawRoundedRect(
            left,
            center_y - 2,
            max(1, handle_x - left),
            4,
            2,
            2,
        )

        alpha = int(255 * self._handle_opacity)
        if alpha <= 0:
            return

        painter.setBrush(QColor(139, 235, 203, alpha))
        painter.setPen(QPen(QColor(208, 255, 237, alpha), 1.5))
        painter.drawEllipse(
            handle_x - 6,
            center_y - 6,
            12,
            12,
        )

    def _show_handle(self) -> None:
        self._fade_timer.stop()
        self._fade_animation.stop()
        self.handleOpacity = 1.0

    def _arm_handle_fade(self) -> None:
        self._fade_timer.start()

    def _fade_handle(self) -> None:
        self._fade_animation.stop()
        self._fade_animation.setStartValue(self._handle_opacity)
        self._fade_animation.setEndValue(0.0)
        self._fade_animation.start()


class LiquidGlassPanel(QFrame):
    """A borderless panel with the shared liquid-glass background style."""


class MarqueeLabel(QLabel):
    """A clipped title that pauses at the start before slowly scrolling."""

    def __init__(
        self,
        text: str = "",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._full_text = ""
        self._offset = 0
        self._pause_until = 0.0
        self._scroll_step = 1
        self._gap = 36
        self._timer = QTimer(self)
        self._timer.setInterval(72)
        self._timer.timeout.connect(self._advance_marquee)
        self._underline_on_hover = False
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full_text = str(text)
        self._offset = 0
        self._pause_until = time.monotonic() + 1.7
        super().setText("")
        self._update_timer_state()
        self.update()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        self._update_timer_state()
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = self.font()
        font.setUnderline(self._underline_on_hover and self.underMouse())
        painter.setFont(font)
        painter.setPen(self.palette().color(self.foregroundRole()))
        painter.setClipRect(self.rect())

        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self._full_text)
        baseline = (
            (self.height() - metrics.height()) // 2
            + metrics.ascent()
        )
        available_width = max(0, self.width())

        if text_width <= available_width:
            painter.drawText(0, baseline, self._full_text)
            return

        x = -self._offset
        painter.drawText(x, baseline, self._full_text)
        painter.drawText(
            x + text_width + self._gap,
            baseline,
            self._full_text,
        )

    def enterEvent(self, event: object) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event: object) -> None:
        super().leaveEvent(event)
        self.update()

    def _update_timer_state(self) -> None:
        metrics = QFontMetrics(self.font())
        should_scroll = (
            bool(self._full_text)
            and metrics.horizontalAdvance(self._full_text) > self.width()
        )
        if should_scroll:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def _advance_marquee(self) -> None:
        if time.monotonic() < self._pause_until:
            return

        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self._full_text)
        if text_width <= self.width():
            self._timer.stop()
            return

        self._offset += self._scroll_step
        if self._offset >= text_width + self._gap:
            self._offset = 0
            self._pause_until = time.monotonic() + 1.7
        self.update()


class ClickableMarqueeLabel(MarqueeLabel):
    """A marquee label that exposes a left-click action."""

    clicked = Signal()

    def __init__(
        self,
        text: str = "",
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent=parent)
        self._underline_on_hover = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def svg_icon(svg: str, size: int = 18) -> QIcon:
    """Create a crisp menu icon without shipping a raster asset."""

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, pixmap.rect())
    painter.end()
    return QIcon(pixmap)


class LibraryHeaderView(QHeaderView):
    """Header whose active sort chevron sits above the column label."""

    _SORTABLE_COLUMNS = frozenset({2, 3, 4, 5})
    _CENTERED_COLUMNS = frozenset({3, 4, 5})

    def __init__(
        self,
        orientation: Qt.Orientation,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(orientation, parent)
        # Qt's native indicator is anchored to the section edge.  Hiding it
        # lets us place a compact chevron over the actual heading text.
        self.setSortIndicatorShown(False)
        self.setMouseTracking(True)

    def paintSection(
        self,
        painter: QPainter,
        rect,
        logicalIndex: int,
    ) -> None:
        super().paintSection(painter, rect, logicalIndex)

        if (
            logicalIndex not in self._SORTABLE_COLUMNS
            or logicalIndex != self.sortIndicatorSection()
        ):
            return

        model = self.model()
        if model is None:
            return
        label = model.headerData(
            logicalIndex,
            Qt.Orientation.Horizontal,
            Qt.ItemDataRole.DisplayRole,
        )
        if not isinstance(label, str) or not label:
            return

        # Metadata headers are left aligned.  Centering over the measured
        # label keeps the chevron attached to "Genres", "Added" and
        # "Duration" instead of the wider section's right edge.  The title
        # section is stretch-sized, so its indicator is centered in the whole
        # section instead of being pushed to the far right.
        metrics = QFontMetrics(self.font())
        label_width = metrics.horizontalAdvance(label)
        if logicalIndex == 2:
            center_x = rect.center().x()
            top = rect.center().y() - 1.5
        elif logicalIndex in self._CENTERED_COLUMNS:
            label_x = rect.left() + 7
            center_x = label_x + label_width / 2
            top = rect.top() + 3
        else:
            center_x = rect.right() - 10
            top = rect.top() + 3

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(
            QPen(
                QColor("#A9A9B0"),
                1.35,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        path = QPainterPath()
        if self.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder:
            path.moveTo(center_x - 3.0, top)
            path.lineTo(center_x, top + 3.0)
            path.lineTo(center_x + 3.0, top)
        else:
            path.moveTo(center_x - 3.0, top + 3.0)
            path.lineTo(center_x, top)
            path.lineTo(center_x + 3.0, top + 3.0)
        painter.drawPath(path)
        painter.restore()


IMPORT_ICON = """
<svg viewBox="3 3 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
 <defs><linearGradient id="accent" x1="4" y1="4" x2="20" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#A2F6D9"/><stop offset=".52" stop-color="#55CDB0"/><stop offset="1" stop-color="#327E76"/></linearGradient></defs>
 <path d="M12 4v10m0 0 4-4m-4 4-4-4M5 16v3h14v-3" stroke="url(#accent)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""
SEARCH_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="10.8" cy="10.8" r="6.4" stroke="#B7B8BE" stroke-width="1.8"/>
  <path d="m16 16 4.2 4.2" stroke="#B7B8BE" stroke-width="1.8" stroke-linecap="round"/>
</svg>
"""
CLEAR_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="m6.5 6.5 11 11m0-11-11 11" stroke="#B7B8BE" stroke-width="1.8" stroke-linecap="round"/>
</svg>
"""
_MUSEFY_MARK_PATH = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "musefy-mark.svg"
)
MUSEFY_MARK_SVG = _MUSEFY_MARK_PATH.read_text(encoding="utf-8")
_MUSEFY_ICON_PATH = _MUSEFY_MARK_PATH.with_name("musefy-icon.svg")
MUSEFY_ICON_SVG = _MUSEFY_ICON_PATH.read_text(encoding="utf-8")
PLAYLIST_SCROLL_LEFT_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M14.25 5.75 8 12l6.25 6.25" stroke="#B5FBE0" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""
PLAYLIST_SCROLL_RIGHT_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="m9.75 5.75 6.25 6.25-6.25 6.25" stroke="#B5FBE0" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""
_LIBRARY_ICON_PATH = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "library-icon.svg"
)
LIBRARY_ICON = _LIBRARY_ICON_PATH.read_text(encoding="utf-8")
_STATISTICS_ICON_PATH = _LIBRARY_ICON_PATH.with_name("statistics-icon.svg")
STATISTICS_ICON = _STATISTICS_ICON_PATH.read_text(encoding="utf-8")
MAP_ICON = """
<svg viewBox="3 3 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
 <defs><linearGradient id="accent" x1="4" y1="4" x2="20" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#B5FBE0"/><stop offset=".52" stop-color="#5DD8B7"/><stop offset="1" stop-color="#32877C"/></linearGradient></defs>
 <circle cx="12" cy="12" r="8.6" stroke="url(#accent)" stroke-width="1.35"/>
 <path d="M12 3.4v2.1M12 18.5v2.1M3.4 12h2.1M18.5 12h2.1" stroke="url(#accent)" stroke-width="1.2" stroke-linecap="round"/>
 <path d="m15.8 7.6-2.4 5.8-5.2 3 2.4-5.8 5.2-3Z" fill="url(#accent)" fill-opacity=".72" stroke="url(#accent)" stroke-width="1.05" stroke-linejoin="round"/>
 <circle cx="12" cy="12" r="1.25" fill="#D0FFED"/>
</svg>
"""
LOCAL_FILE_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
 <path d="M6 3h8l4 4v14H6V3Z" stroke="#C9C9CE" stroke-width="1.6" stroke-linejoin="round"/><path d="M14 3v5h4" stroke="#C9C9CE" stroke-width="1.6" stroke-linejoin="round"/>
</svg>
"""
YOUTUBE_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
 <path d="M21 12c0 2.9-.35 4.72-.62 5.66a2.8 2.8 0 0 1-1.72 1.72C17.72 19.65 15.9 20 12 20s-5.72-.35-6.66-.62a2.8 2.8 0 0 1-1.72-1.72C3.35 16.72 3 14.9 3 12s.35-4.72.62-5.66a2.8 2.8 0 0 1 1.72-1.72C6.28 4.35 8.1 4 12 4s5.72.35 6.66.62a2.8 2.8 0 0 1 1.72 1.72C20.65 7.28 21 9.1 21 12Z" fill="#AD5E62"/><path d="m10 8 5 4-5 4V8Z" fill="#F5F5F6"/>
</svg>
"""
SPOTIFY_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
 <circle cx="12" cy="12" r="9" fill="#698D73"/><path d="M7.5 10.2c3.55-.92 6.6-.55 8.8.63M7.8 13c2.87-.64 5.4-.3 7.3.58m-6.9 2.37c2.2-.4 4.08-.1 5.55.5" stroke="#F4F4F5" stroke-width="1.25" stroke-linecap="round"/>
</svg>
"""
SOUNDCLOUD_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
 <path d="M5 17.4h13.2a3.8 3.8 0 0 0 .45-7.57A6.35 6.35 0 0 0 6.56 8.4 4.5 4.5 0 0 0 5 17.4Z" fill="#D27A54"/>
 <path d="M7 11.1v4.6m2-5.8v5.8m2-6.8v6.8m2-6.5v6.5" stroke="#F8E8DF" stroke-width="1.1" stroke-linecap="round"/>
</svg>
"""
JSON_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
 <path d="M9 5c-2 0-2 2-2 3.2v1.2c0 1.1-.58 1.6-1.5 1.6.92 0 1.5.5 1.5 1.6v1.2C7 15 7 17 9 17M15 5c2 0 2 2 2 3.2v1.2c0 1.1.58 1.6 1.5 1.6-.92 0-1.5.5-1.5 1.6v1.2c0 1.2 0 3.2-2 3.2" stroke="#C9C9CE" stroke-width="1.6" stroke-linecap="round"/>
</svg>
"""
def _cover_palette(pixmap: QPixmap) -> tuple[QColor, QColor, QColor]:
    """Build a same-hue surface palette from the cover's dominant color."""

    image = pixmap.toImage()
    buckets: dict[tuple[int, int, int], int] = {}
    if not image.isNull():
        step_x = max(1, image.width() // 16)
        step_y = max(1, image.height() // 10)
        for y in range(0, image.height(), step_y):
            for x in range(0, image.width(), step_x):
                color = image.pixelColor(x, y)
                if color.alpha() < 20:
                    continue
                red, green, blue, _ = color.getRgb()
                bucket = (
                    (red // 32) * 32,
                    (green // 32) * 32,
                    (blue // 32) * 32,
                )
                buckets[bucket] = buckets.get(bucket, 0) + 1

    if buckets:
        dominant_rgb = max(
            buckets,
            key=lambda rgb: (
                buckets[rgb]
                * (1.0 + QColor(*rgb).saturation() / 255.0 * 0.75)
                * (0.65 + QColor(*rgb).value() / 255.0)
            ),
        )
        dominant = QColor(*dominant_rgb)
    else:
        # Only used for a missing or fully transparent cover.
        dominant = QColor("#4EA98C")

    hue = dominant.hue()
    if hue < 0:
        hue = 164
    saturation = max(84, min(232, dominant.saturation()))
    value = max(72, min(188, dominant.value()))

    return (
        QColor.fromHsv(
            hue,
            saturation,
            min(255, value + 24),
        ),
        QColor.fromHsv(
            hue,
            max(72, saturation - 18),
            min(255, value + 58),
        ),
        QColor.fromHsv(
            (hue + 8) % 360,
            max(60, saturation - 34),
            min(255, value + 92),
        ),
    )


class PlaylistGradientSurface(QFrame):
    """A card surface that crossfades into a cover-colored hover gradient."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors: tuple[QColor, QColor, QColor] = (
            QColor("#4EA98C"),
            QColor("#477CB2"),
            QColor("#8C5AAB"),
        )
        self._hover_opacity = 0.0
        self._selected = False
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._hover_animation = QPropertyAnimation(
            self,
            b"hoverOpacity",
            self,
        )
        self._hover_animation.setDuration(220)
        self._hover_animation.setEasingCurve(
            QEasingCurve(QEasingCurve.Type.InOutCubic)
        )

    @Property(float)
    def hoverOpacity(self) -> float:
        return self._hover_opacity

    @hoverOpacity.setter
    def hoverOpacity(self, value: float) -> None:
        self._hover_opacity = _clamp_opacity(value)
        self.update()

    def set_colors(self, colors: tuple[QColor, QColor, QColor]) -> None:
        self._colors = (
            QColor(colors[0]),
            QColor(colors[1]),
            QColor(colors[2]),
        )
        self.update()

    def set_hovered(self, hovered: bool) -> None:
        self._hover_animation.stop()
        self._hover_animation.setStartValue(self._hover_opacity)
        self._hover_animation.setEndValue(1.0 if hovered else 0.0)
        self._hover_animation.start()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 0, -1, -1)
        radius = 12.0

        base_alpha = 14 if self._selected else 6
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, base_alpha))
        painter.drawRoundedRect(rect, radius, radius)

        # Keep the selected playlist visibly "lit" after the pointer leaves
        # it; hovering raises the same gradient to full intensity.
        gradient_opacity = max(
            self._hover_opacity * 0.72,
            0.42 if self._selected else 0.0,
        )
        if gradient_opacity <= 0.0:
            painter.end()
            return

        primary, secondary, accent = self._colors
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(
            0.0,
            self._tinted(primary.lighter(116), 142 * gradient_opacity),
        )
        gradient.setColorAt(
            0.46,
            self._tinted(secondary.lighter(102), 126 * gradient_opacity),
        )
        gradient.setColorAt(
            1.0,
            self._tinted(accent.lighter(104), 132 * gradient_opacity),
        )
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, radius, radius)

        # A restrained white sheen gives the surface depth without restoring
        # any external decoration or outline.
        sheen = QLinearGradient(0, 0, 0, self.height())
        sheen.setColorAt(
            0.0,
            self._tinted(QColor(255, 255, 255), 24 * gradient_opacity),
        )
        sheen.setColorAt(
            0.42,
            self._tinted(QColor(255, 255, 255), 0),
        )
        painter.setBrush(sheen)
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()

    @staticmethod
    def _tinted(color: QColor, alpha: float) -> QColor:
        tinted = QColor(color)
        tinted.setAlpha(round(max(0.0, min(255.0, alpha))))
        return tinted


class _PlaylistHoverMixin:
    def _setup_playlist_hover(
        self,
        cover: QPixmap,
    ) -> None:
        self._cover_colors = _cover_palette(cover)
        self.setMouseTracking(True)

    def enterEvent(self, event: object) -> None:
        super().enterEvent(event)
        self._set_surface_hovered(True)

    def leaveEvent(self, event: object) -> None:
        super().leaveEvent(event)
        self._set_surface_hovered(False)

    def _set_surface_hovered(self, hovered: bool) -> None:
        surface = getattr(self, "_card_surface", None)
        if surface is None:
            return
        set_colors = getattr(surface, "set_colors", None)
        if set_colors is not None:
            set_colors(self._cover_colors)
        set_hovered = getattr(surface, "set_hovered", None)
        if set_hovered is not None:
            set_hovered(hovered)


_PLAYLIST_ARTWORK_RANDOM = SystemRandom()
_PLAYLIST_ARTWORK_PALETTES = (
    # Each artwork chooses one narrow background family and one contrasting
    # family for its graph.  The colors deliberately do not span the whole
    # green-to-purple spectrum in a single cover, and avoid muddy olive or
    # yellow-green backgrounds.
    (
        ("#16805D", "#35C596", "#8DEFC0"),
        ("#8C70F5", "#C7A6FF", "#E58BFF"),
        ("#08251F", "#0E4A38", "#171D3A"),
    ),
    (
        ("#24966F", "#55D5AA", "#AEF5D2"),
        ("#7664E8", "#BBA0FF", "#ED9BFF"),
        ("#092B25", "#145541", "#1A2040"),
    ),
    (
        ("#167986", "#25C9C5", "#8BF2DF"),
        ("#7A68F0", "#BDA4FF", "#E6A0FF"),
        ("#061F2B", "#0D4650", "#182044"),
    ),
    (
        ("#218AA5", "#39BDD0", "#A0F0EB"),
        ("#6DE0C0", "#A78BFF", "#E0B0FF"),
        ("#082331", "#10465B", "#1B2147"),
    ),
    (
        ("#2450A0", "#4B82E8", "#9ABEFF"),
        ("#59E7C4", "#8DF0DC", "#C5B3FF"),
        ("#0A1B3C", "#173B70", "#251B50"),
    ),
    (
        ("#3D4DB2", "#6377E4", "#AAB8FF"),
        ("#60E8C5", "#8DEFD9", "#D1B8FF"),
        ("#101A43", "#253A70", "#2B1D55"),
    ),
    (
        ("#4B2A82", "#7658D4", "#B99AFF"),
        ("#68E6BF", "#9BEBD6", "#C6B3FF"),
        ("#1B1038", "#34205C", "#20204A"),
    ),
    (
        ("#6D3C91", "#A766C2", "#D3A8F0"),
        ("#67DFC0", "#9DEBD8", "#9EDBFF"),
        ("#24123D", "#45235D", "#24214B"),
    ),
)


class SvgArtworkWidget(QWidget):
    """Paint playlist artwork as SVG instead of a pre-rasterized pixmap."""

    def __init__(
        self,
        svg: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._renderer.render(painter, QRectF(self.rect()))
        painter.end()


def _random_playlist_artwork_svg() -> str:
    """Build a fresh graph artwork with a varied color family."""

    rng = _PLAYLIST_ARTWORK_RANDOM
    background_range, node_range, dark_range = rng.choice(
        _PLAYLIST_ARTWORK_PALETTES
    )
    background_a, _background_mid, _background_b = background_range
    dark_a, dark_mid, dark_b = dark_range

    clip_id = f"artwork-clip-{rng.randrange(1_000_000)}"
    background_id = f"background-{rng.randrange(1_000_000)}"

    background_angle = rng.randrange(0, 360)
    background = f"""
    <linearGradient id="{background_id}" x1="0" y1="0" x2="1" y2="1"
                    gradientTransform="rotate({background_angle} .5 .5)">
      <stop stop-color="{dark_a}"/>
      <stop offset=".48" stop-color="{dark_mid}"/>
      <stop offset="1" stop-color="{dark_b}"/>
    </linearGradient>
    """

    nodes = [
        (
            rng.randrange(18, 168),
            rng.randrange(16, 86),
            rng.choice(node_range),
            rng.choice((1.5, 1.8, 2.1)),
        )
        for _ in range(rng.randrange(6, 10))
    ]
    edge_pairs: set[tuple[int, int]] = set()
    for index in range(1, len(nodes)):
        edge_pairs.add((index, rng.randrange(index)))
    for _ in range(rng.randrange(2, 5)):
        first = rng.randrange(len(nodes))
        second = rng.randrange(len(nodes))
        if first != second:
            edge_pairs.add((first, second))

    edges = "".join(
        f'<path d="M {nodes[first][0]} {nodes[first][1]} '
        f'L {nodes[second][0]} {nodes[second][1]}" '
        f'stroke="{rng.choice(node_range)}" '
        f'stroke-opacity=".{rng.randrange(18, 42)}" '
        f'stroke-width="{rng.choice((.7, .9, 1.1))}"/>'
        for first, second in edge_pairs
    )
    node_marks = "".join(
        f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}" '
        f'fill-opacity=".{rng.randrange(48, 88)}" '
        f'stroke="{rng.choice(node_range)}" '
        f'stroke-opacity=".{rng.randrange(42, 78)}" stroke-width=".7"/>'
        for x, y, color, radius in nodes
    )

    return f"""
    <svg viewBox="0 0 184 100" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        {background}
        <clipPath id="{clip_id}">
          <rect width="184" height="100" rx="17"/>
        </clipPath>
      </defs>
      <rect width="184" height="100" rx="17" fill="url(#{background_id})"/>
      <g clip-path="url(#{clip_id})">
        <path d="M 8 28 C 48 4 91 18 125 9 C 151 3 171 14 184 28"
              stroke="{background_a}" stroke-opacity=".24" stroke-width="1.4"/>
        <g>{edges}{node_marks}</g>
      </g>
    </svg>
    """


def generate_playlist_artwork_svg() -> str:
    """Return a new generated artwork for a playlist."""

    return _random_playlist_artwork_svg()


class PlaylistCard(_PlaylistHoverMixin, QFrame):
    """A horizontally-scrollable playlist tile with a stored or generated cover."""

    activated = Signal(str)
    context_requested = Signal(str, object)

    def __init__(
        self,
        *,
        playlist_id: str,
        name: str,
        cover_path: str | None,
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self.playlist_id = playlist_id
        self._full_name = name
        self.setObjectName("playlistCardWrapper")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(126, 104)

        self._card_surface = PlaylistGradientSurface(self)
        self._card_surface.setObjectName("playlistCard")
        self._card_surface.setGeometry(11, 11, 104, 82)
        self._card_surface.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        layout = QVBoxLayout(self._card_surface)
        layout.setContentsMargins(6, 5, 6, 4)
        layout.setSpacing(3)

        cover_size = QSize(92, 50)
        stored_svg = None
        if cover_path and Path(cover_path).suffix.lower() == ".svg":
            try:
                stored_svg = Path(cover_path).read_text(encoding="utf-8")
            except OSError:
                stored_svg = None

        source_cover = QPixmap()
        if cover_path and not stored_svg:
            source_cover = QPixmap(str(Path(cover_path)))
        if stored_svg:
            cover = _svg_cover_pixmap(stored_svg, cover_size)
            self.cover_label = SvgArtworkWidget(stored_svg)
        elif not source_cover.isNull():
            scaled_cover = source_cover.scaled(
                cover_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            cover = _rounded_pixmap(
                scaled_cover,
                radius=12,
                size=cover_size,
            )
            self.cover_label = QLabel()
            self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cover_label.setPixmap(cover)
        else:
            cover_svg = generate_playlist_artwork_svg()
            cover = _svg_cover_pixmap(cover_svg, cover_size)
            self.cover_label = SvgArtworkWidget(cover_svg)
        self.cover_label.setFixedSize(cover_size)
        self._setup_playlist_hover(cover)
        self._card_surface.set_colors(self._cover_colors)
        layout.addWidget(self.cover_label)

        self.name_label = MarqueeLabel(name)
        self.name_label.setObjectName("playlistCardName")
        self.name_label.setWordWrap(False)
        self.name_label.setFixedHeight(16)
        self.name_label.setToolTip(name)
        self.name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
        )
        layout.addWidget(self.name_label)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._card_surface.set_selected(selected)

    def mouseReleaseEvent(self, event: object) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            self.context_requested.emit(
                self.playlist_id,
                self.mapToGlobal(event.position().toPoint()),
            )
            return

        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit(self.playlist_id)

MAIN_LIBRARY_SVG = """
<svg viewBox="0 0 160 100" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="mainLibraryBackground" x1="18" y1="10" x2="142" y2="94" gradientUnits="userSpaceOnUse">
      <stop stop-color="#214A43"/>
      <stop offset=".55" stop-color="#102A2A"/>
      <stop offset="1" stop-color="#071316"/>
    </linearGradient>
    <linearGradient id="mainLibraryAccent" x1="45" y1="29" x2="116" y2="82" gradientUnits="userSpaceOnUse">
      <stop stop-color="#B5FBE0"/>
      <stop offset=".52" stop-color="#5DD8B7"/>
      <stop offset="1" stop-color="#32877C"/>
    </linearGradient>
    <radialGradient id="mainLibraryGlow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(78 46) rotate(90) scale(54 76)">
      <stop stop-color="#5DD8B7" stop-opacity=".28"/>
      <stop offset="1" stop-color="#5DD8B7" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="160" height="100" rx="17" fill="url(#mainLibraryBackground)"/>
  <ellipse cx="78" cy="46" rx="76" ry="54" fill="url(#mainLibraryGlow)"/>
  <path d="m56 52 24-20 24 20v24H56V52Z" fill="#0A181A" fill-opacity=".62" stroke="url(#mainLibraryAccent)" stroke-width="2.4" stroke-linejoin="round"/>
  <path d="M73 76V59h14v17" stroke="url(#mainLibraryAccent)" stroke-width="2.4" stroke-linejoin="round"/>
  <path d="m52 54 28-24 28 24" stroke="url(#mainLibraryAccent)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""

CREATE_PLAYLIST_SVG = """
<svg viewBox="0 0 160 100" fill="none" xmlns="http://www.w3.org/2000/svg"
     shape-rendering="geometricPrecision">
  <defs>
    <linearGradient id="createPlaylistBackground" x1="14" y1="8" x2="146" y2="94" gradientUnits="userSpaceOnUse">
      <stop stop-color="#214A43"/>
      <stop offset=".55" stop-color="#102A2A"/>
      <stop offset="1" stop-color="#071316"/>
    </linearGradient>
    <linearGradient id="createPlaylistAccent" x1="55" y1="25" x2="115" y2="80" gradientUnits="userSpaceOnUse">
      <stop stop-color="#B5FBE0"/>
      <stop offset=".52" stop-color="#5DD8B7"/>
      <stop offset="1" stop-color="#32877C"/>
    </linearGradient>
    <radialGradient id="createPlaylistGlow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(82 48) rotate(90) scale(54 74)">
      <stop stop-color="#5DD8B7" stop-opacity=".28"/>
      <stop offset="1" stop-color="#5DD8B7" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="160" height="100" rx="17" fill="url(#createPlaylistBackground)"/>
  <ellipse cx="82" cy="48" rx="74" ry="52" fill="url(#createPlaylistGlow)"/>
  <path d="M80 28v44M58 50h44"
        stroke="url(#createPlaylistAccent)"
        stroke-width="2.8"
        stroke-linecap="round"
        vector-effect="non-scaling-stroke"/>
</svg>
"""


def _svg_cover_pixmap(svg: str, size: QSize) -> QPixmap:
    pixmap = QPixmap(size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(
        painter,
        pixmap.rect(),
    )
    painter.end()
    return pixmap


def _rounded_pixmap(
    pixmap: QPixmap,
    *,
    radius: int,
    size: QSize | None = None,
) -> QPixmap:
    """Clip artwork to the same rounded shape as the playlist cover frame."""

    if pixmap.isNull():
        return pixmap

    if size is not None and pixmap.size() != size:
        crop_x = max(0, (pixmap.width() - size.width()) // 2)
        crop_y = max(0, (pixmap.height() - size.height()) // 2)
        pixmap = pixmap.copy(
            crop_x,
            crop_y,
            min(size.width(), pixmap.width() - crop_x),
            min(size.height(), pixmap.height() - crop_y),
        )

    rounded = QPixmap(pixmap.size())
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip_path = QPainterPath()
    clip_path.addRoundedRect(
        pixmap.rect().adjusted(0, 0, -1, -1),
        radius,
        radius,
    )
    painter.setClipPath(clip_path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return rounded


class UtilityPlaylistCard(_PlaylistHoverMixin, QFrame):
    """A playlist-sized navigation or creation tile for the carousel."""

    activated = Signal()

    def __init__(
        self,
        *,
        title: str,
        cover_svg: str,
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self._full_name = title
        self.setObjectName("playlistCardWrapper")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(126, 104)

        self._card_surface = PlaylistGradientSurface(self)
        self._card_surface.setObjectName("playlistCard")
        self._card_surface.setGeometry(11, 11, 104, 82)
        self._card_surface.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        layout = QVBoxLayout(self._card_surface)
        layout.setContentsMargins(6, 5, 6, 4)
        layout.setSpacing(3)

        cover = SvgArtworkWidget(cover_svg)
        cover.setFixedSize(92, 50)
        cover_pixmap = _svg_cover_pixmap(cover_svg, cover.size())
        self._setup_playlist_hover(cover_pixmap)
        self._card_surface.set_colors(self._cover_colors)
        layout.addWidget(cover)

        name_label = MarqueeLabel(title)
        name_label.setObjectName("playlistCardName")
        name_label.setWordWrap(False)
        name_label.setFixedHeight(16)
        name_label.setToolTip(title)
        name_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.NoTextInteraction
        )
        self.name_label = name_label
        layout.addWidget(name_label)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)

    def set_selected(self, selected: bool) -> None:
        self._card_surface.set_selected(selected)

    def mouseReleaseEvent(self, event: object) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self.activated.emit()


class MainLibraryCard(UtilityPlaylistCard):
    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(
            title="Music library",
            cover_svg=MAIN_LIBRARY_SVG,
            parent=parent,
        )


class CreatePlaylistCard(UtilityPlaylistCard):
    def __init__(self, parent: QFrame | None = None) -> None:
        super().__init__(
            title="Create playlist",
            cover_svg=CREATE_PLAYLIST_SVG,
            parent=parent,
        )


CALM_MOOD_SVG = """
<svg viewBox="0 0 160 100" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="moodAccent" x1="25" y1="20" x2="133" y2="83" gradientUnits="userSpaceOnUse">
      <stop stop-color="#B5FBE0"/>
      <stop offset=".5" stop-color="#5DD8B7"/>
      <stop offset="1" stop-color="#32877C"/>
    </linearGradient>
    <radialGradient id="moodGlow" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(82 50) rotate(90) scale(38 58)">
      <stop stop-color="#5DD8B7" stop-opacity=".28"/>
      <stop offset="1" stop-color="#5DD8B7" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect width="160" height="100" rx="17" fill="#1B2021"/>
  <ellipse cx="82" cy="50" rx="58" ry="38" fill="url(#moodGlow)"/>
  <circle cx="103" cy="38" r="16" stroke="url(#moodAccent)" stroke-width="2"/>
  <path d="M28 65C42 52 57 52 71 65C85 78 100 78 132 55" stroke="url(#moodAccent)" stroke-opacity=".86" stroke-width="2.2" stroke-linecap="round"/>
  <path d="M28 74C42 63 57 63 71 74C85 85 103 85 132 66" stroke="url(#moodAccent)" stroke-opacity=".38" stroke-width="2" stroke-linecap="round"/>
</svg>
"""


WAVE_SVG = CALM_MOOD_SVG


class WavePlaylistCard(_PlaylistHoverMixin, QFrame):
    """The compact entry point for mood, genre and My Wave sessions."""

    mood_selected = Signal(str)
    genre_selected = Signal(str)
    my_wave_selected = Signal()

    def __init__(
        self,
        mood_names: tuple[str, ...],
        genre_names: tuple[str, ...] = (),
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self._mood_names = mood_names
        self._genre_names = genre_names
        self.setObjectName("playlistCardWrapper")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(126, 104)

        self._card_surface = PlaylistGradientSurface(self)
        self._card_surface.setObjectName("playlistCard")
        self._card_surface.setGeometry(11, 11, 104, 82)
        self._card_surface.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        layout = QVBoxLayout(self._card_surface)
        layout.setContentsMargins(6, 5, 6, 4)
        layout.setSpacing(3)

        cover = SvgArtworkWidget(WAVE_SVG)
        cover.setFixedSize(92, 50)
        cover_pixmap = _svg_cover_pixmap(WAVE_SVG, cover.size())
        self._setup_playlist_hover(cover_pixmap)
        self._card_surface.set_colors(self._cover_colors)
        layout.addWidget(cover)

        title = QLabel("Wave")
        title.setObjectName("playlistCardName")
        title.setFixedHeight(16)
        layout.addWidget(title)

    def set_selected(self, selected: bool) -> None:
        self._card_surface.set_selected(selected)

    def mouseReleaseEvent(self, event: object) -> None:
        super().mouseReleaseEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return

        menu = self._build_wave_menu()
        menu.exec(self.mapToGlobal(event.position().toPoint()))

    def _build_wave_menu(self) -> QMenu:
        """Build the two-column picker used by the Wave card."""

        menu = QMenu(self)
        menu.setObjectName("waveMenu")
        menu_widget = QWidget(menu)
        menu_widget.setMinimumWidth(350)
        menu_layout = QVBoxLayout(menu_widget)
        menu_layout.setContentsMargins(10, 10, 10, 10)
        menu_layout.setSpacing(8)

        my_wave_button = QPushButton("My Wave", menu_widget)
        my_wave_button.setObjectName("wavePrimaryButton")
        my_wave_button.setCursor(Qt.CursorShape.PointingHandCursor)

        def select_my_wave() -> None:
            menu.close()
            self.my_wave_selected.emit()

        my_wave_button.clicked.connect(select_my_wave)
        menu_layout.addWidget(my_wave_button)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(10)
        menu_layout.addLayout(columns)

        def add_column(
            heading: str,
            values: tuple[str, ...],
            selected: Signal,
        ) -> None:
            column = QWidget(menu_widget)
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(2)

            heading_label = QLabel(heading, column)
            heading_label.setObjectName("waveMenuHeading")
            column_layout.addWidget(heading_label)
            for value in values:
                display_value = (
                    value.title()
                    if heading == "Mood"
                    else value
                )
                button = QPushButton(display_value, column)
                button.setObjectName("waveMenuItem")
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setToolTip(display_value)

                def select_value(
                    checked: bool = False,
                    *,
                    selected_value: str = value,
                ) -> None:
                    del checked
                    menu.close()
                    selected.emit(selected_value)

                button.clicked.connect(select_value)
                column_layout.addWidget(button)
            column_layout.addStretch(1)
            columns.addWidget(column, 1)

        add_column("Mood", self._mood_names, self.mood_selected)
        add_column("Genres", self._genre_names, self.genre_selected)

        menu_action = QWidgetAction(menu)
        menu_action.setDefaultWidget(menu_widget)
        menu.addAction(menu_action)
        return menu


# Keep the old import name working for extensions that imported the card
# before it became the combined Wave picker.
MoodPlaylistCard = WavePlaylistCard


class TrackNumberPlayWidget(QWidget):
    """A table-row index that turns into the row's play action."""

    play_requested = Signal()
    CONTENT_OFFSET_X = -5

    def __init__(
        self,
        number: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("trackRowCell")
        self.setMinimumWidth(48)
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Expanding,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._number_label = QLabel(str(number), self)
        self._number_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._number_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )

        self._play_button = SvgIconButton(
            PLAY_ICON,
            tooltip="Play track",
            diameter=32,
            flat=True,
            parent=self,
        )
        self._play_button.clicked.connect(self.play_requested)
        self._play_button.hide()

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        content_offset = self.CONTENT_OFFSET_X
        self._number_label.setGeometry(
            content_offset,
            0,
            self.width(),
            self.height(),
        )
        button_size = self._play_button.sizeHint()
        x = max(
            0,
            (self.width() - button_size.width()) // 2 + content_offset,
        )
        y = max(0, (self.height() - button_size.height()) // 2)
        self._play_button.setGeometry(
            x,
            y,
            button_size.width(),
            button_size.height(),
        )

    def set_play_visible(self, visible: bool) -> None:
        self._number_label.setVisible(not visible)
        self._play_button.setVisible(visible)


class TrackIdentityWidget(QWidget):
    """A title and muted artist label, optionally with a play affordance."""

    play_requested = Signal()

    def __init__(
        self,
        title: str,
        artist: str,
        *,
        cover_path: str | None = None,
        compact: bool = False,
        include_play_button: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._artist = artist
        self._search_query = ""
        self._include_play_button = include_play_button
        self.setObjectName("trackRowCell")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6 if include_play_button else 2)

        if include_play_button:
            play_button = SvgIconButton(
                PLAY_ICON,
                tooltip="Play track",
                diameter=28 if compact else 30,
                flat=True,
            )
            play_button.clicked.connect(self.play_requested)
            layout.addWidget(play_button)

        text_container = QWidget()
        text_container.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        text_container.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        text_layout = QVBoxLayout(text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        self._title_label = QLabel(html.escape(title))
        self._title_label.setObjectName("trackCellTitle")
        self._artist_label = QLabel(html.escape(artist))
        self._artist_label.setObjectName("trackCellArtist")
        for label in (self._title_label, self._artist_label):
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setWordWrap(False)
            label.setMinimumWidth(0)
            label.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
        self._title_label.setFixedHeight(20)
        self._artist_label.setFixedHeight(16)
        self._title_label.setToolTip(title)
        self._artist_label.setToolTip(artist)
        text_layout.addWidget(self._title_label)
        text_layout.addWidget(self._artist_label)
        layout.addWidget(text_container, 1)

    def resizeEvent(self, event: object) -> None:
        super().resizeEvent(event)
        available_width = max(
            8,
            self.width() - (44 if self._include_play_button else 4),
        )
        self._set_display_text(
            self._title_label,
            self._title,
            available_width,
        )
        self._set_display_text(
            self._artist_label,
            self._artist,
            available_width,
        )

    def set_search_query(self, query: str) -> None:
        """Highlight the current library search in title and artist text."""

        self._search_query = query.strip()
        self._refresh_display_text()

    def _refresh_display_text(self) -> None:
        available_width = max(
            8,
            self.width() - (44 if self._include_play_button else 4),
        )
        self._set_display_text(
            self._title_label,
            self._title,
            available_width,
        )
        self._set_display_text(
            self._artist_label,
            self._artist,
            available_width,
        )

    def _set_display_text(
        self,
        label: QLabel,
        text: str,
        available_width: int,
    ) -> None:
        elided_text = QFontMetrics(label.font()).elidedText(
            text,
            Qt.TextElideMode.ElideRight,
            available_width,
        )
        label.setText(
            _highlight_search_text(
                elided_text,
                self._search_query,
            )
        )


def _highlight_search_text(text: str, query: str) -> str:
    """Escape row text and highlight case-insensitive query matches."""

    escaped_text = html.escape(text)
    normalized_query = query.strip()
    if not normalized_query:
        return escaped_text

    pattern = re.compile(re.escape(normalized_query), re.IGNORECASE)
    parts: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        parts.append(html.escape(text[cursor : match.start()]))
        parts.append(
            '<span style="background-color:#5DD8B7; '
            'color:#07100F; border-radius:3px; padding:0 2px;">'
            f"{html.escape(match.group(0))}</span>"
        )
        cursor = match.end()

    if not parts:
        return escaped_text

    parts.append(html.escape(text[cursor:]))
    return "".join(parts)


def track_cover_pixmap(
    title: str,
    cover_path: str | None,
    size: int,
) -> QPixmap:
    """Load a stored cover or draw the deliberately dark fallback tile."""

    if cover_path:
        pixmap = QPixmap(str(Path(cover_path)))
        if not pixmap.isNull():
            return pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    shade = 25 + sum(ord(character) for character in title) % 18
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(shade, shade, shade))
    painter.drawRoundedRect(pixmap.rect(), 6, 6)
    painter.setPen(QColor(130, 130, 130))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(max(9, size // 3))
    painter.setFont(font)
    painter.drawText(
        pixmap.rect(),
        Qt.AlignmentFlag.AlignCenter,
        title[:1].upper() or "♫",
    )
    return pixmap


class QueueDialog(QDialog):
    """A lightweight non-modal playback queue window."""

    track_play_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        prepare_dialog(self)
        self.setWindowTitle("Queue")
        self.setMinimumSize(340, 330)
        self.resize(380, 440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        title_label = QLabel("Queue")
        title_label.setObjectName("appTitle")
        layout.addWidget(title_label)
        self.track_list = QListWidget()
        layout.addWidget(self.track_list)

    def set_tracks(self, tracks: list[tuple[str, str]]) -> None:
        self.begin_tracks(len(tracks))
        self.append_tracks(tracks)

    def begin_tracks(self, total_count: int) -> None:
        """Reset the list before incremental queue rows are appended."""

        self.track_list.clear()
        if total_count <= 0:
            self.track_list.addItem("Nothing queued")

    def append_tracks(
        self,
        tracks: list[tuple[str, str]],
        track_ids: list[str] | tuple[str, ...] = (),
    ) -> None:
        """Append only the next rendered queue slice."""

        for index, (title, artist) in enumerate(tracks):
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 46))
            self.track_list.addItem(item)
            identity = TrackIdentityWidget(title, artist, compact=True)
            if index < len(track_ids):
                track_id = track_ids[index]
                identity.play_requested.connect(
                    lambda track_id=track_id: self.track_play_requested.emit(
                        track_id
                    )
                )
            self.track_list.setItemWidget(
                item,
                identity,
            )


PLAY_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="accent" x1="6" y1="4" x2="19" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#B5FBE0"/><stop offset=".5" stop-color="#5DD8B7"/><stop offset="1" stop-color="#32877C"/></linearGradient></defs>
  <path fill="url(#accent)" d="M8 5.3v13.4c0 .7.8 1.1 1.4.7l9.3-6.7a.86.86 0 0 0 0-1.4L9.4 4.6A.86.86 0 0 0 8 5.3Z"/>
</svg>
"""

PAUSE_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="accent" x1="6" y1="4" x2="19" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#B5FBE0"/><stop offset=".5" stop-color="#5DD8B7"/><stop offset="1" stop-color="#32877C"/></linearGradient></defs>
  <path fill="url(#accent)" d="M7 5.5c0-.8.7-1.5 1.5-1.5S10 4.7 10 5.5v13c0 .8-.7 1.5-1.5 1.5S7 19.3 7 18.5v-13Zm7.5 0c0-.8.7-1.5 1.5-1.5s1.5.7 1.5 1.5v13c0 .8-.7 1.5-1.5 1.5s-1.5-.7-1.5-1.5v-13Z"/>
</svg>
"""

PREVIOUS_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path fill="#D8D8D8" d="M6 5h2v14H6V5Zm12.6.9v12.2c0 .7-.8 1.1-1.4.7L9.4 12.7a.86.86 0 0 1 0-1.4l7.8-6.1c.6-.5 1.4 0 1.4.7Z"/>
</svg>
"""

NEXT_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path fill="#D8D8D8" d="M16 5h2v14h-2V5ZM5.4 5.9v12.2c0 .7.8 1.1 1.4.7l7.8-6.1a.86.86 0 0 0 0-1.4L6.8 5.2c-.6-.5-1.4 0-1.4.7Z"/>
</svg>
"""

HEART_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path fill="#D8D8D8" d="M12 20.1 4.8 13C2.4 10.6 2.6 6.7 5.2 4.7A5.1 5.1 0 0 1 12 5.3a5.1 5.1 0 0 1 6.8-.6c2.6 2 2.8 5.9.4 8.3L12 20.1Zm-5.6-14c-1.4 0-2.5 1.1-2.5 2.5 0 .8.4 1.6 1 2.2l7.1 7 7.1-7c1.1-1.1 1.3-2.8.4-4.1a3 3 0 0 0-4.7-.2L12 9.5 8.7 6.5a3.1 3.1 0 0 0-2.3-.4Z"/>
</svg>
"""

HEART_LIKED_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="accent" x1="4" y1="4" x2="20" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#C0FFE6"/><stop offset=".48" stop-color="#61E0BC"/><stop offset="1" stop-color="#2D9684"/></linearGradient></defs>
  <path fill="url(#accent)" d="M12 20.1 4.8 13C2.4 10.6 2.6 6.7 5.2 4.7A5.1 5.1 0 0 1 12 5.3a5.1 5.1 0 0 1 6.8-.6c2.6 2 2.8 5.9.4 8.3L12 20.1Z"/>
</svg>
"""

ADD_TO_QUEUE_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M4 6.5h10M4 11h10M4 15.5h7"
        stroke="#D8D8D8" stroke-width="1.6" stroke-linecap="round"/>
  <path d="M18 5v6M15 8h6"
        stroke="#D8D8D8" stroke-width="1.6" stroke-linecap="round"/>
</svg>
"""

QUEUE_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path fill="#D8D8D8" d="M4 6h11v2H4V6Zm0 5h11v2H4v-2Zm0 5h8v2H4v-2Zm13-5 4 3-4 3v-2h-3v-2h3v-2Z"/>
</svg>
"""

SEQUENTIAL_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path fill="#D8D8D8" d="M5 6h10.2l-2.1-2.1L14.5 2.5 19 7l-4.5 4.5-1.4-1.4L15.2 8H5V6Zm0 10h10.2l-2.1-2.1 1.4-1.4L19 17l-4.5 4.5-1.4-1.4 2.1-2.1H5v-2Z"/>
</svg>
"""

SHUFFLE_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M4 7h1.8c1.6 0 2.6.7 3.6 2l5.2 6c1 1.3 2 2 3.6 2H20" stroke="#D8D8D8" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M4 17h1.8c1.6 0 2.6-.7 3.6-2l5.2-6c1-1.3 2-2 3.6-2H20" stroke="#D8D8D8" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="m17.1 4.2 3.1 2.8-3.1 2.8ZM17.1 14.2l3.1 2.8-3.1 2.8Z" fill="#D8D8D8"/>
</svg>
"""

SMART_SHUFFLE_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M4 7h1.8c1.6 0 2.6.7 3.6 2l5.2 6c1 1.3 2 2 3.6 2H20" stroke="#D8D8D8" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M4 17h1.8c1.6 0 2.6-.7 3.6-2l5.2-6c1-1.3 2-2 3.6-2H20" stroke="#D8D8D8" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="m17.1 4.2 3.1 2.8-3.1 2.8ZM17.1 14.2l3.1 2.8-3.1 2.8Z" fill="#D8D8D8"/>
  <path fill="#5DD8B7" d="M6.5 8.2 7.2 10.3 9.3 11l-2.1.7-.7 2.1-.7-2.1-2.1-.7 2.1-.7.7-2.1Z"/>
</svg>
"""

RADIO_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path fill="#D8D8D8" d="M12 13.2a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4Zm0-3.5a4.7 4.7 0 0 0-3.4 1.5l1.4 1.4a2.8 2.8 0 0 1 4 0l1.4-1.4A4.7 4.7 0 0 0 12 9.7Zm0-4.1a8.8 8.8 0 0 0-6.3 2.6l1.4 1.4a6.8 6.8 0 0 1 9.8 0l1.4-1.4A8.8 8.8 0 0 0 12 5.6Z"/>
</svg>
"""

RADIO_ACTIVE_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="accent" x1="5" y1="4" x2="19" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#B5FBE0"/><stop offset=".5" stop-color="#5DD8B7"/><stop offset="1" stop-color="#32877C"/></linearGradient></defs>
  <path fill="url(#accent)" d="M12 13.2a1.2 1.2 0 1 0 0 2.4 1.2 1.2 0 0 0 0-2.4Zm0-3.5a4.7 4.7 0 0 0-3.4 1.5l1.4 1.4a2.8 2.8 0 0 1 4 0l1.4-1.4A4.7 4.7 0 0 0 12 9.7Zm0-4.1a8.8 8.8 0 0 0-6.3 2.6l1.4 1.4a6.8 6.8 0 0 1 9.8 0l1.4-1.4A8.8 8.8 0 0 0 12 5.6Z"/>
</svg>
"""

REPEAT_OFF_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M6.4 10.2A5.8 5.8 0 0 1 17.1 7.3L19 9.2m0-3.2v3.2h-3.2M17.6 13.8A5.8 5.8 0 0 1 6.9 16.7L5 14.8m0 3.2v-3.2h3.2" stroke="#D8D8D8" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""

REPEAT_QUEUE_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="repeatAccent" x1="3" y1="4" x2="21" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#B5FBE0"/><stop offset=".5" stop-color="#5DD8B7"/><stop offset="1" stop-color="#32877C"/></linearGradient></defs>
  <path d="M6.4 10.2A5.8 5.8 0 0 1 17.1 7.3L19 9.2m0-3.2v3.2h-3.2M17.6 13.8A5.8 5.8 0 0 1 6.9 16.7L5 14.8m0 3.2v-3.2h3.2" stroke="url(#repeatAccent)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""

REPEAT_TRACK_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="repeatAccent" x1="3" y1="4" x2="21" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#B5FBE0"/><stop offset=".5" stop-color="#5DD8B7"/><stop offset="1" stop-color="#32877C"/></linearGradient></defs>
  <path d="M6.4 10.2A5.8 5.8 0 0 1 17.1 7.3L19 9.2m0-3.2v3.2h-3.2M17.6 13.8A5.8 5.8 0 0 1 6.9 16.7L5 14.8m0 3.2v-3.2h3.2" stroke="url(#repeatAccent)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="12" cy="12" r="2.15" fill="#081113"/>
  <path d="M12 10.9v2.2m-1.1-1.1h2.2" stroke="url(#repeatAccent)" stroke-width=".9" stroke-linecap="round"/>
</svg>
"""

VOLUME_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="accent" x1="4" y1="5" x2="21" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#B5FBE0"/><stop offset=".5" stop-color="#5DD8B7"/><stop offset="1" stop-color="#32877C"/></linearGradient></defs>
  <path fill="url(#accent)" d="M4 9h4l5-4v14l-5-4H4V9Zm12.7-.7a1 1 0 0 1 1.4 0 5.3 5.3 0 0 1 0 7.4 1 1 0 0 1-1.4-1.4 3.3 3.3 0 0 0 0-4.6 1 1 0 0 1 0-1.4Zm2.8-2.8a1 1 0 0 1 1.4 0 9.2 9.2 0 0 1 0 13 1 1 0 1 1-1.4-1.4 7.2 7.2 0 0 0 0-10.2 1 1 0 0 1 0-1.4Z"/>
</svg>
"""
