from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QEvent,
    QEasingCurve,
    Property,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QCursor,
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
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSlider,
    QStyle,
    QStyleOptionSlider,
    QTableWidget,
    QToolButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class SvgIconButton(QAbstractButton):
    """A compact rounded button that paints an SVG at any display scale."""

    def __init__(
        self,
        svg: str,
        *,
        tooltip: str,
        diameter: int = 38,
        flat: bool = False,
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._flat = flat
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
                painter.drawEllipse(
                    self.rect().adjusted(2, 2, -2, -2)
                )
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(
                self.rect().adjusted(1, 1, -1, -1),
                12,
                12,
            )
        padding = 6 if self._flat else 10
        self._renderer.render(
            painter,
            self.rect().adjusted(padding, padding, -padding, -padding),
        )


def _color_with_alpha(value: str, alpha: int) -> QColor:
    color = QColor(value)
    color.setAlpha(alpha)
    return color


class RailIconButton(QToolButton):
    """A rail action with a quiet, per-icon graph-shaped hover glow."""

    BUTTON_SIZE = 42
    # Keep the glyph in a bounded, centered area.  The SVG artwork uses an
    # 18px coordinate grid; the graph-shaped hover surface is painted by the
    # same widget, so it never gets detached from the icon.
    ICON_SIZE = 24
    CONTENT_OFFSET_X = 0

    _GRAPH_VARIANTS = {
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
    }

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
    def graphOpacity(self) -> float:  # noqa: N802 - Qt property name
        return self._graph_opacity

    @graphOpacity.setter
    def graphOpacity(self, value: float) -> None:  # noqa: N802
        self._graph_opacity = max(0.0, min(1.0, float(value)))
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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row_widgets: dict[QWidget, int] = {}
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)

    def register_row_widget(
        self,
        widget: QWidget,
        row_index: int,
    ) -> None:
        for child in (widget, *widget.findChildren(QWidget)):
            self._row_widgets[child] = row_index
            child.installEventFilter(self)

    def eventFilter(self, watched: object, event: object) -> bool:
        if watched is self.viewport():
            event_type = event.type()
            if event_type == QEvent.Type.MouseMove:
                self.row_hovered.emit(
                    self.rowAt(int(event.position().y()))
                )
            elif event_type == QEvent.Type.Leave:
                self.row_hovered.emit(-1)
        elif watched in self._row_widgets:
            if event.type() in (
                QEvent.Type.Enter,
                QEvent.Type.MouseMove,
            ):
                self.row_hovered.emit(self._row_widgets[watched])
            elif event.type() == QEvent.Type.Leave:
                local_pos = self.viewport().mapFromGlobal(QCursor.pos())
                if not self.viewport().rect().contains(local_pos):
                    self.row_hovered.emit(-1)

        return super().eventFilter(watched, event)


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
    def handleOpacity(self) -> float:  # noqa: N802 - Qt property name
        return self._handle_opacity

    @handleOpacity.setter
    def handleOpacity(self, value: float) -> None:  # noqa: N802
        self._handle_opacity = max(0.0, min(1.0, float(value)))
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
        self.setWordWrap(False)
        self.setMinimumWidth(0)
        self.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API name
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
        painter.setFont(self.font())
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


def svg_icon(svg: str, size: int = 18) -> QIcon:
    """Create a crisp menu icon without shipping a raster asset."""

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter, pixmap.rect())
    painter.end()
    return QIcon(pixmap)


IMPORT_ICON = """
<svg viewBox="3 3 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
 <defs><linearGradient id="accent" x1="4" y1="4" x2="20" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#A2F6D9"/><stop offset=".52" stop-color="#55CDB0"/><stop offset="1" stop-color="#327E76"/></linearGradient></defs>
 <path d="M12 4v10m0 0 4-4m-4 4-4-4M5 16v3h14v-3" stroke="url(#accent)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""
LIBRARY_ICON = """
<svg viewBox="3 3 18 18" fill="none" xmlns="http://www.w3.org/2000/svg">
 <defs><linearGradient id="accent" x1="3" y1="3" x2="21" y2="21" gradientUnits="userSpaceOnUse"><stop stop-color="#A2F6D9"/><stop offset=".52" stop-color="#55CDB0"/><stop offset="1" stop-color="#327E76"/></linearGradient></defs>
 <rect x="4" y="5" width="4" height="15" rx="1" stroke="url(#accent)" stroke-width="1.4"/><rect x="9.5" y="3.5" width="5" height="16.5" rx="1" stroke="url(#accent)" stroke-width="1.4"/><path d="m17.2 4.7 3 1-4.1 13.1-3-1 4.1-13.1Z" stroke="url(#accent)" stroke-width="1.4" stroke-linejoin="round"/><path d="M5 8h2m4.5-1h3m2.2 2.1 2.2.7" stroke="url(#accent)" stroke-width="1.1" stroke-linecap="round"/>
</svg>
"""
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
JSON_ICON = """
<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
 <path d="M9 5c-2 0-2 2-2 3.2v1.2c0 1.1-.58 1.6-1.5 1.6.92 0 1.5.5 1.5 1.6v1.2C7 15 7 17 9 17M15 5c2 0 2 2 2 3.2v1.2c0 1.1.58 1.6 1.5 1.6-.92 0-1.5.5-1.5 1.6v1.2c0 1.2 0 3.2-2 3.2" stroke="#C9C9CE" stroke-width="1.6" stroke-linecap="round"/>
</svg>
"""


def playlist_badge_text(name: str) -> str:
    """Create a compact, readable badge from a playlist name."""

    words = [word for word in name.split() if word]
    if not words:
        return "♫"

    if len(words) == 1:
        letters = "".join(character for character in words[0] if character.isalnum())
        return (letters[:2] or "♫").upper()

    return "".join(word[0] for word in words[:2]).upper()


class PlaylistCard(QFrame):
    """A horizontally-scrollable playlist tile with a stored or generated cover."""

    activated = Signal(str)

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
        self.setObjectName("playlistCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(104, 82)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 4)
        layout.setSpacing(3)

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(92, 50)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setPixmap(self._cover_pixmap(name, cover_path))
        layout.addWidget(self.cover_label)

        self.name_label = QLabel(name)
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
        self.name_label.setText(
            QFontMetrics(self.name_label.font()).elidedText(
                self._full_name,
                Qt.TextElideMode.ElideRight,
                max(8, self.name_label.width()),
            )
        )

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event: object) -> None:
        super().mouseReleaseEvent(event)
        self.activated.emit(self.playlist_id)

    def _cover_pixmap(
        self,
        name: str,
        cover_path: str | None,
    ) -> QPixmap:
        if cover_path:
            pixmap = QPixmap(str(Path(cover_path)))
            if not pixmap.isNull():
                return pixmap.scaled(
                    self.cover_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )

        pixmap = QPixmap(self.cover_label.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient_index = 0
        for character in name:
            # A stable rolling hash keeps artwork reproducible without the
            # collisions that made common playlist names look identical.
            gradient_index = (
                gradient_index * 31 + ord(character)
            ) % 5
        gradient_stops = (
            ("#24453F", "#081113", "#7FD9C0"),
            ("#283E55", "#0A111A", "#76B7D5"),
            ("#463A5E", "#110E18", "#C09BD6"),
            ("#5A3154", "#140B16", "#D79ACB"),
            ("#29335E", "#0C101C", "#99A9F0"),
        )[gradient_index]
        cover_rect = pixmap.rect().adjusted(0, 0, -1, -1)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(cover_rect, 12, 12)
        painter.save()
        painter.setClipPath(clip_path)

        gradient_vectors = (
            (0, 0, pixmap.width(), pixmap.height()),
            (pixmap.width(), 0, 0, pixmap.height()),
            (0, pixmap.height(), pixmap.width(), 0),
            (pixmap.width(), pixmap.height(), 0, 0),
            (pixmap.width() * 0.2, 0, pixmap.width() * 0.8, pixmap.height()),
        )
        base_gradient = QLinearGradient(*gradient_vectors[gradient_index])
        base_gradient.setColorAt(0.0, QColor(gradient_stops[0]))
        base_gradient.setColorAt(0.56, QColor(gradient_stops[1]))
        base_gradient.setColorAt(1.0, QColor(gradient_stops[2]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base_gradient)
        painter.drawRect(pixmap.rect())

        blob_layouts = (
            (
                (0.12, 0.12, 0.82, gradient_stops[2], 118),
                (0.88, 0.82, 0.50, gradient_stops[0], 72),
                (0.52, 0.42, 0.42, "#D8E9E3", 18),
            ),
            (
                (0.84, 0.12, 0.70, gradient_stops[0], 106),
                (0.18, 0.82, 0.60, gradient_stops[2], 92),
                (0.52, 0.52, 0.34, "#D8E9E3", 24),
            ),
            (
                (0.28, 0.52, 0.76, gradient_stops[2], 124),
                (0.88, 0.18, 0.44, gradient_stops[0], 68),
                (0.76, 0.86, 0.40, "#D8E9E3", 18),
            ),
            (
                (0.84, 0.72, 0.86, gradient_stops[2], 102),
                (0.16, 0.18, 0.54, gradient_stops[0], 82),
                (0.52, 0.24, 0.30, "#D8E9E3", 28),
            ),
            (
                (0.52, 0.44, 0.88, gradient_stops[2], 116),
                (0.08, 0.84, 0.46, gradient_stops[0], 66),
                (0.94, 0.10, 0.44, "#D8E9E3", 22),
            ),
        )
        blob_specs = blob_layouts[gradient_index]
        for x_ratio, y_ratio, radius_ratio, color, alpha in blob_specs:
            center_x = pixmap.width() * x_ratio
            center_y = pixmap.height() * y_ratio
            radius = pixmap.width() * radius_ratio
            blob = QRadialGradient(center_x, center_y, radius)
            blob.setColorAt(0.0, _color_with_alpha(color, alpha))
            blob.setColorAt(0.58, _color_with_alpha(color, alpha // 2))
            blob.setColorAt(1.0, _color_with_alpha(color, 0))
            painter.setBrush(blob)
            painter.drawEllipse(
                round(center_x - radius),
                round(center_y - radius),
                round(radius * 2),
                round(radius * 2),
            )
        painter.restore()

        initials = playlist_badge_text(name)
        font = painter.font()
        font.setPointSize(22 if len(initials) > 1 else 24)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor("#E4E9E7"))
        painter.drawText(
            pixmap.rect().adjusted(0, -2, 0, -2),
            Qt.AlignmentFlag.AlignCenter,
            initials,
        )
        return pixmap


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


class MoodPlaylistCard(QFrame):
    """The first, calm entry point for an ad-hoc mood session."""

    mood_selected = Signal(str)

    def __init__(
        self,
        mood_names: tuple[str, ...],
        parent: QFrame | None = None,
    ) -> None:
        super().__init__(parent)
        self._mood_names = mood_names
        self.setObjectName("playlistCard")
        self.setProperty("moodCard", True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(104, 82)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 5, 6, 4)
        layout.setSpacing(3)

        cover = QLabel()
        cover.setFixedSize(92, 50)
        cover.setPixmap(self._mood_pixmap(cover.size()))
        layout.addWidget(cover)

        title = QLabel("Mood")
        title.setObjectName("playlistCardName")
        title.setFixedHeight(16)
        layout.addWidget(title)

    def mouseReleaseEvent(self, event: object) -> None:
        super().mouseReleaseEvent(event)
        menu = QMenu(self)
        menu.setTitle("Choose a mood")
        for mood_name in self._mood_names:
            action = menu.addAction(mood_name.title())
            action.triggered.connect(
                lambda checked=False, value=mood_name: self.mood_selected.emit(value)
            )
        menu.exec(self.mapToGlobal(event.position().toPoint()))

    @staticmethod
    def _mood_pixmap(size: QSize) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        renderer = QSvgRenderer(QByteArray(CALM_MOOD_SVG.encode("utf-8")))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, pixmap.rect())
        painter.end()
        return pixmap


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
        self._title_label = QLabel(title)
        self._title_label.setObjectName("trackCellTitle")
        self._artist_label = QLabel(artist)
        self._artist_label.setObjectName("trackCellArtist")
        for label in (self._title_label, self._artist_label):
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
        self._title_label.setText(
            QFontMetrics(self._title_label.font()).elidedText(
                self._title,
                Qt.TextElideMode.ElideRight,
                available_width,
            )
        )
        self._artist_label.setText(
            QFontMetrics(self._artist_label.font()).elidedText(
                self._artist,
                Qt.TextElideMode.ElideRight,
                available_width,
            )
        )


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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
        self.track_list.clear()

        if not tracks:
            self.track_list.addItem("Nothing queued")
            return

        for title, artist in tracks:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 46))
            self.track_list.addItem(item)
            self.track_list.setItemWidget(
                item,
                TrackIdentityWidget(title, artist, compact=True),
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

QUEUE_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <path fill="#D8D8D8" d="M4 6h11v2H4V6Zm0 5h11v2H4v-2Zm0 5h8v2H4v-2Zm13-5 4 3-4 3v-2h-3v-2h3v-2Z"/>
</svg>
"""

VOLUME_ICON = """
<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="accent" x1="4" y1="5" x2="21" y2="20" gradientUnits="userSpaceOnUse"><stop stop-color="#B5FBE0"/><stop offset=".5" stop-color="#5DD8B7"/><stop offset="1" stop-color="#32877C"/></linearGradient></defs>
  <path fill="url(#accent)" d="M4 9h4l5-4v14l-5-4H4V9Zm12.7-.7a1 1 0 0 1 1.4 0 5.3 5.3 0 0 1 0 7.4 1 1 0 0 1-1.4-1.4 3.3 3.3 0 0 0 0-4.6 1 1 0 0 1 0-1.4Zm2.8-2.8a1 1 0 0 1 1.4 0 9.2 9.2 0 0 1 0 13 1 1 0 1 1-1.4-1.4 7.2 7.2 0 0 0 0-10.2 1 1 0 0 1 0-1.4Z"/>
</svg>
"""
