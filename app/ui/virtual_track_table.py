"""A model/view track table that paints only the visible rows."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QAbstractTableModel,
    QByteArray,
    QEvent,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from app.domain.models import Track
from app.ui.components import PLAY_ICON, search_match_spans, track_cover_pixmap

HEADERS = ("#", "", "Title", "Genres", "Added", "Duration", "", "Analysis", "")


class _TrackModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[Track] = []

    def set_rows(self, rows: list[Track]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def replace_row(self, row_index: int, track: Track) -> None:
        if not 0 <= row_index < len(self.rows):
            return
        self.rows[row_index] = track
        self.dataChanged.emit(self.index(row_index, 0), self.index(row_index, 8))

    def rowCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(self.rows)

    def columnCount(self, parent: QModelIndex | None = None) -> int:
        return 0 if parent is not None and parent.isValid() else len(HEADERS)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        track = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return track.id
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return (str(index.row() + 1), "", track.title, "", "", "", "", "", "")[
            index.column()
        ]

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
        ):
            return HEADERS[section]
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.TextAlignmentRole
        ):
            if section == 0:
                return Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter
            return Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        return super().headerData(section, orientation, role)


class _TrackDelegate(QStyledItemDelegate):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        # Reuse the exact play artwork used by queue rows instead of a text
        # glyph, whose shape and baseline vary between installed fonts.
        self._play_renderer = QSvgRenderer(QByteArray(PLAY_ICON.encode("utf-8")))

    def paint(
        self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex
    ) -> None:
        model = index.model()
        if not isinstance(model, _TrackModel):
            return
        track = model.rows[index.row()]
        view = self.parent()
        assert isinstance(view, VirtualTrackTable)
        rect = option.rect
        # Use the view's current index explicitly: style options can lose the
        # selection flag when the table is unfocused.
        selected = index.row() == view.currentRow()
        hovered = view.hovered_row == index.row()
        if selected:
            painter.fillRect(rect, QColor("#303334"))
        elif hovered:
            painter.fillRect(rect, QColor(255, 255, 255, 18))

        painter.save()
        painter.setPen(QColor("#EEEEF0"))
        column = index.column()
        if column == 0:
            if view.add_mode:
                self._paint_checkbox(
                    painter,
                    rect,
                    checked=track.id in view.selected_ids,
                    hovered=hovered and view.hovered_column == 0,
                )
            elif hovered or selected:
                diameter = min(32, rect.width() - 8, rect.height() - 8)
                button_center_x = rect.center().x() + 1
                button_center_y = rect.center().y() + 1
                button_rect = QRect(
                    button_center_x - diameter // 2,
                    button_center_y - diameter // 2,
                    diameter,
                    diameter,
                )
                if hovered and view.hovered_column == 0:
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QColor(112, 224, 190, 25))
                    painter.drawEllipse(button_rect.adjusted(2, 2, -2, -2))
                icon_size = min(18, button_rect.width(), button_rect.height())
                icon_rect = QRect(
                    button_center_x - icon_size // 2,
                    button_center_y - icon_size // 2,
                    icon_size,
                    icon_size,
                )
                self._play_renderer.render(painter, icon_rect)
            else:
                painter.drawText(
                    rect,
                    Qt.AlignmentFlag.AlignCenter,
                    str(index.row() + 1),
                )
        elif column == 1:
            if view.show_covers:
                pixmap = view.cover_for(track)
                x = rect.left() + max(0, (rect.width() - 40) // 2)
                painter.drawPixmap(x, rect.top() + 11, pixmap)
        elif column == 2:
            left = rect.left() + 8
            base_font = painter.font()
            title_font = painter.font()
            # Queue labels use a 13px stylesheet size.  QFont point sizes are
            # larger on screen, so use pixels here to keep the two views aligned.
            title_font.setPixelSize(13)
            title_font.setWeight(QFont.Weight.DemiBold)
            painter.setFont(title_font)
            title_rect = rect.adjusted(left - rect.left(), 10, -8, -30)
            title_text = painter.fontMetrics().elidedText(
                track.title, Qt.TextElideMode.ElideRight, title_rect.width()
            )
            _draw_search_highlighted_text(
                painter,
                title_rect,
                title_text,
                view.search_query,
                QColor("#EEEEF0"),
            )
            painter.setFont(base_font)
            artist_color = QColor("#96969E")
            artist_rect = rect.adjusted(left - rect.left(), 31, -8, -8)
            artist_text = painter.fontMetrics().elidedText(
                track.artist, Qt.TextElideMode.ElideRight, artist_rect.width()
            )
            _draw_search_highlighted_text(
                painter,
                artist_rect,
                artist_text,
                view.search_query,
                artist_color,
            )
        elif column in (3, 4, 7):
            value = view.text_for(track)[(3, 4, 7).index(column)]
            alignment = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            if column != 4:
                alignment |= Qt.TextFlag.TextWordWrap
            else:
                alignment |= Qt.TextFlag.TextSingleLine
            painter.drawText(
                rect.adjusted(7, 0, -5, 0),
                alignment,
                value,
            )
        elif column == 5:
            painter.drawText(
                rect, Qt.AlignmentFlag.AlignCenter, view.text_for(track)[2]
            )
        elif column == 6 and view.playlist_open:
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "×")
        elif column == 8:
            if view.hovered_row == index.row() and view.hovered_column == 8:
                diameter = max(1, min(rect.width() - 14, rect.height() - 20))
                hover_rect = QRect(
                    rect.center().x() - diameter // 2,
                    rect.center().y() - diameter // 2,
                    diameter,
                    diameter,
                )
                hover_rect.translate(-1, 1)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(93, 216, 183, 30))
                painter.drawEllipse(hover_rect)
                painter.setPen(QColor("#B5FBE0"))
            painter.drawText(
                rect.translated(0, -1),
                Qt.AlignmentFlag.AlignCenter,
                "≡+",
            )
        painter.restore()

    @staticmethod
    def _paint_checkbox(
        painter: QPainter,
        rect: QRect,
        *,
        checked: bool,
        hovered: bool,
    ) -> None:
        size = max(16, min(18, rect.width() - 12, rect.height() - 28))
        checkbox_rect = QRect(
            rect.center().x() - size // 2,
            rect.center().y() - size // 2,
            size,
            size,
        )

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(93, 216, 183, 28))
            painter.drawRoundedRect(
                checkbox_rect.adjusted(-6, -6, 6, 6),
                9,
                9,
            )

        painter.setPen(
            QPen(
                QColor("#5DD8B7" if checked else "#697A75"),
                1.6,
            )
        )
        painter.setBrush(
            QColor("#5DD8B7" if checked else "#182323")
        )
        painter.drawRoundedRect(checkbox_rect, 5, 5)

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        return QSize(0, 62)


class VirtualTrackTable(QTableView):
    """A lightweight track table: no cell widgets and no per-row layouts."""

    row_hovered = Signal(int)
    row_clicked = Signal(int)
    row_double_clicked = Signal(int)
    row_play_requested = Signal(int)
    row_queue_requested = Signal(int)
    row_remove_requested = Signal(int)
    row_check_requested = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._track_model = _TrackModel()
        self.setModel(self._track_model)
        self.setItemDelegate(_TrackDelegate(self))
        self.hovered_row = -1
        self.hovered_column = -1
        self.add_mode = False
        self.playlist_open = False
        self.show_covers = True
        self.search_query = ""
        self.selected_ids: set[str] = set()
        self._cover_pixmaps: dict[str, QPixmap] = {}
        self._row_text_cache: dict[str, tuple[str, str, str, str]] = {}
        self._text_for_track: Callable[[Track], tuple[str, str, str, str]] = (
            lambda _track: ("", "", "", "")
        )
        # The table lives directly on the liquid-glass panel.  QTableView is
        # opaque by default, unlike the previous library table stylesheet.
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.viewport().setAutoFillBackground(False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        # The viewport is a child widget, so moving from a row to the header
        # does not send leaveEvent() to the table itself.
        self.viewport().installEventFilter(self)

    def set_tracks(
        self,
        tracks: list[Track],
        *,
        add_mode: bool,
        playlist_open: bool,
        show_covers: bool,
        selected_ids: set[str],
        text_for_track: Callable[[Track], tuple[str, str, str, str]],
    ) -> None:
        self.add_mode = add_mode
        self.playlist_open = playlist_open
        self.show_covers = show_covers
        self.selected_ids = set(selected_ids)
        self._text_for_track = text_for_track
        self._row_text_cache.clear()
        self.hovered_row = -1
        self.hovered_column = -1
        self._track_model.set_rows(tracks)

    def set_search_query(self, query: str) -> None:
        """Update the query used to highlight title and artist matches."""

        self.search_query = query.strip()
        self.viewport().update()

        # Materialized rows use TrackIdentityWidget while rows outside the
        # viewport use the delegate below. Keep both render paths in sync.
        for widget in self.findChildren(QWidget):
            set_query = getattr(widget, "set_search_query", None)
            if callable(set_query):
                set_query(self.search_query)

    def set_selected_ids(self, selected_ids: set[str]) -> None:
        self.selected_ids = set(selected_ids)
        self.viewport().update()

    def text_for(self, track: Track) -> tuple[str, str, str, str]:
        """Format metadata only when a row reaches the viewport."""

        cached = self._row_text_cache.get(track.id)
        if cached is None:
            cached = self._text_for_track(track)
            self._row_text_cache[track.id] = cached
        return cached

    def cover_for(self, track: Track) -> QPixmap:
        """Load each visible cover once instead of touching disk per repaint."""

        cached = self._cover_pixmaps.get(track.id)
        if cached is None:
            cached = track_cover_pixmap(track.title, track.cover_path, 40)
            self._cover_pixmaps[track.id] = cached
        return cached

    def rowCount(self) -> int:
        return self._track_model.rowCount()

    def currentRow(self) -> int:
        return self.currentIndex().row()

    def track_id_at(self, row: int) -> str | None:
        if 0 <= row < len(self._track_model.rows):
            return self._track_model.rows[row].id
        return None

    def refresh_row(self, row: int) -> None:
        if 0 <= row < self.rowCount():
            # Repaint the complete row so every cell clears a stale hover
            # background when the pointer moves to another widget.
            row_rect = self.visualRect(self._track_model.index(row, 0))
            row_rect.setLeft(0)
            row_rect.setRight(self.viewport().width())
            self.viewport().update(row_rect)

    def update_row(self, row_index: int, track: Track) -> None:
        self._cover_pixmaps.pop(track.id, None)
        self._row_text_cache.pop(track.id, None)
        self._track_model.replace_row(row_index, track)

    def mouseMoveEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        row = index.row() if index.isValid() else -1
        column = index.column() if index.isValid() else -1
        interactive = index.isValid() and (
            column in {0, 8}
        )
        self.viewport().setCursor(
            Qt.CursorShape.PointingHandCursor
            if interactive
            else Qt.CursorShape.ArrowCursor
        )
        if (row, column) != (self.hovered_row, self.hovered_column):
            previous = self.hovered_row
            self.hovered_row = row
            self.hovered_column = column
            if row != previous:
                self.row_hovered.emit(row)
            for changed_row in (previous, row):
                if changed_row >= 0:
                    self.refresh_row(changed_row)
        super().mouseMoveEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() == QEvent.Type.Leave:
            self._clear_hover()
        return super().eventFilter(watched, event)

    def leaveEvent(self, event) -> None:
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
        self._clear_hover()
        super().leaveEvent(event)

    def _clear_hover(self) -> None:
        if self.hovered_row < 0:
            self.hovered_column = -1
            return
        previous = self.hovered_row
        self.hovered_row = -1
        self.hovered_column = -1
        self.row_hovered.emit(-1)
        self.refresh_row(previous)

    def mousePressEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and index.isValid():
            if index.column() == 0:
                signal = (
                    self.row_check_requested
                    if self.add_mode
                    else self.row_play_requested
                )
            else:
                signal = {
                    6: self.row_remove_requested,
                    8: self.row_queue_requested,
                }.get(index.column())
            if (
                signal is not None
                and (index.column() != 6 or self.playlist_open)
            ):
                signal.emit(index.row())
                return
            self.row_clicked.emit(index.row())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            if self.add_mode and index.column() == 0:
                return
            self.row_double_clicked.emit(index.row())
            return
        super().mouseDoubleClickEvent(event)


def _draw_search_highlighted_text(
    painter: QPainter,
    rect: QRect,
    text: str,
    query: str,
    text_color: QColor,
) -> None:
    """Draw left-aligned text with turquoise search-match backgrounds."""

    matches = search_match_spans(text, query)
    if not matches:
        painter.setPen(text_color)
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        return

    metrics = painter.fontMetrics()
    x = rect.left()
    baseline = (
        rect.top()
        + max(0, (rect.height() - metrics.height()) // 2)
        + metrics.ascent()
    )
    highlight_top = rect.top() + max(0, (rect.height() - metrics.height()) // 2)
    cursor = 0

    for start, end in matches:
        prefix = text[cursor:start]
        if prefix:
            painter.setPen(text_color)
            painter.drawText(QPoint(x, baseline), prefix)
            x += metrics.horizontalAdvance(prefix)

        match = text[start:end]
        match_width = metrics.horizontalAdvance(match)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#5DD8B7"))
        painter.drawRoundedRect(
            QRect(x - 2, highlight_top, match_width + 4, metrics.height()),
            3,
            3,
        )
        painter.setPen(QColor("#07100F"))
        painter.drawText(QPoint(x, baseline), match)
        x += match_width
        cursor = end

    suffix = text[cursor:]
    if suffix:
        painter.setPen(text_color)
        painter.drawText(QPoint(x, baseline), suffix)

    painter.setBrush(Qt.BrushStyle.NoBrush)
