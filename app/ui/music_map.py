from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from app.domain.models import Track


# Dusty rather than neon: the map should feel like a music atlas, not a chart.
COMMUNITY_COLORS = (
    (115, 137, 166),  # slate blue
    (153, 108, 132),  # muted rose
    (161, 126, 84),   # smoked amber
    (100, 145, 132),  # muted teal
    (128, 111, 157),  # dusty violet
    (137, 151, 105),  # moss
    (177, 113, 105),  # clay
    (104, 132, 144),  # steel teal
    (158, 137, 160),  # lavender gray
    (143, 127, 116),  # warm gray
)


@dataclass(frozen=True)
class _MapNode:
    track_id: str
    title: str
    artist: str
    community: int


@dataclass(frozen=True)
class _MapEdge:
    left_index: int
    right_index: int
    strength: float


class MusicMapWidget(QWidget):
    """A Graphify-inspired local map of music similarity communities."""

    track_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nodes: tuple[_MapNode, ...] = ()
        self._edges: tuple[_MapEdge, ...] = ()
        self._points = np.empty((0, 2), dtype=np.float32)
        self._mode = "focus"
        self._zoom = 1.0
        self._pan = QPointF()
        self._active_node_index: int | None = None
        self._last_pointer_position: QPointF | None = None
        self._drag_start_position: QPointF | None = None
        self._is_panning = False
        self._hovered_node_index: int | None = None
        self.setMouseTracking(True)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.update()

    def set_tracks(self, tracks: list[Track]) -> None:
        embedded_tracks = [
            track
            for track in tracks
            if track.track_embedding is not None
        ][-220:]

        if len(embedded_tracks) < 2:
            self._nodes = ()
            self._edges = ()
            self._points = np.empty((0, 2), dtype=np.float32)
            self.update()
            return

        embeddings = np.asarray(
            [track.track_embedding for track in embedded_tracks],
            dtype=np.float32,
        )
        communities = self._assign_communities(embeddings)
        self._nodes = tuple(
            _MapNode(
                track_id=track.id,
                title=track.title,
                artist=track.artist,
                community=int(communities[index]),
            )
            for index, track in enumerate(embedded_tracks)
        )
        self._edges = self._build_edges(embeddings)
        self._points = self._force_layout(
            self._project_embeddings(embeddings),
            self._edges,
            communities,
        )
        self._reset_view()
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self._nodes:
            painter.setPen(QColor(163, 163, 170, 145))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "The map appears after two tracks are analysed.",
            )
            return

        positions = self._screen_positions()
        degrees = np.zeros(len(self._nodes), dtype=np.int16)
        for edge in self._edges:
            degrees[edge.left_index] += 1
            degrees[edge.right_index] += 1
            source = self._node_color(edge.left_index)
            alpha = int(15 + edge.strength * 28)
            painter.setPen(QPen(QColor(*source, alpha), 0.7))
            painter.drawLine(
                positions[edge.left_index],
                positions[edge.right_index],
            )

        base_radius = 2.0 if self._mode == "mini" else 2.7
        for index, position in enumerate(positions):
            colour = self._node_color(index)
            is_hovered = index == self._hovered_node_index
            radius = base_radius + min(1.35, degrees[index] * 0.14)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(*colour, 52 if is_hovered else 19))
            painter.drawEllipse(
                position,
                radius * (3.4 if is_hovered else 2.1),
                radius * (3.4 if is_hovered else 2.1),
            )
            painter.setBrush(
                QColor(246, 246, 248)
                if is_hovered
                else QColor(*colour, 230)
            )
            painter.drawEllipse(position, radius, radius)

    def wheelEvent(self, event: object) -> None:
        if not self._nodes:
            return

        factor = 1.15 if event.angleDelta().y() > 0 else 0.87
        self._zoom = min(3.0, max(0.55, self._zoom * factor))
        self.update()

    def mousePressEvent(self, event: object) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        position = event.position()
        self._last_pointer_position = position
        self._drag_start_position = position
        self._active_node_index = self._nearest_node_index(position)
        self._is_panning = self._active_node_index is None
        if self._is_panning:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: object) -> None:
        if not self._nodes:
            return

        position = event.position()
        if self._active_node_index is not None:
            self._move_node(self._active_node_index, position)
            self.update()
            return

        if self._is_panning and self._last_pointer_position is not None:
            self._pan += position - self._last_pointer_position
            self._last_pointer_position = position
            self.update()
            return

        self._update_hover(position)

    def mouseReleaseEvent(self, event: object) -> None:
        active_node_index = self._active_node_index
        was_panning = self._is_panning
        self._active_node_index = None
        self._is_panning = False
        self._last_pointer_position = None
        self.unsetCursor()

        if (
            active_node_index is not None
            and self._drag_start_position is not None
            and self._distance(self._drag_start_position, event.position()) < 5.0
        ):
            self.track_activated.emit(self._nodes[active_node_index].track_id)
        self._drag_start_position = None

        if was_panning:
            self._update_hover(event.position())
        self.update()

    def mouseDoubleClickEvent(self, _event: object) -> None:
        self._reset_view()
        self.update()

    def leaveEvent(self, _event: object) -> None:
        self._hovered_node_index = None
        QToolTip.hideText()
        self.unsetCursor()
        self.update()

    def _node_color(self, index: int) -> tuple[int, int, int]:
        return COMMUNITY_COLORS[
            self._nodes[index].community % len(COMMUNITY_COLORS)
        ]

    def _update_hover(self, position: QPointF) -> None:
        node_index = self._nearest_node_index(position)
        if node_index == self._hovered_node_index:
            return

        self._hovered_node_index = node_index
        if node_index is None:
            QToolTip.hideText()
            self.unsetCursor()
        else:
            node = self._nodes[node_index]
            QToolTip.showText(
                self.mapToGlobal(position.toPoint()),
                f"{node.title}\n{node.artist}",
                self,
            )
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.update()

    def _move_node(self, node_index: int, position: QPointF) -> None:
        center = self.rect().center()
        radius_x, radius_y = self._radii()
        point = np.asarray(
            [
                (position.x() - center.x() - self._pan.x())
                / (radius_x * self._zoom),
                (position.y() - center.y() - self._pan.y())
                / (radius_y * self._zoom),
            ],
            dtype=np.float32,
        )
        self._points[node_index] = np.clip(point, -1.2, 1.2)

    def _nearest_node_index(self, position: QPointF) -> int | None:
        nearest_index: int | None = None
        nearest_distance = 15.0
        for index, node_position in enumerate(self._screen_positions()):
            distance = self._distance(node_position, position)
            if distance < nearest_distance:
                nearest_index = index
                nearest_distance = distance
        return nearest_index

    def _screen_positions(self) -> list[QPointF]:
        center = self.rect().center()
        radius_x, radius_y = self._radii()
        return [
            QPointF(
                center.x() + self._pan.x() + point[0] * radius_x * self._zoom,
                center.y() + self._pan.y() + point[1] * radius_y * self._zoom,
            )
            for point in self._points
        ]

    def _radii(self) -> tuple[float, float]:
        return (
            max(40.0, self.width() * 0.45),
            max(34.0, self.height() * 0.43),
        )

    def _reset_view(self) -> None:
        self._zoom = 1.0
        self._pan = QPointF()
        self._active_node_index = None
        self._hovered_node_index = None

    @staticmethod
    def _distance(left: QPointF, right: QPointF) -> float:
        return float(np.hypot(left.x() - right.x(), left.y() - right.y()))

    @staticmethod
    def _project_embeddings(embeddings: np.ndarray) -> np.ndarray:
        centered = embeddings - embeddings.mean(axis=0, keepdims=True)
        _, _, components = np.linalg.svd(centered, full_matrices=False)
        projected = centered @ components[:2].T
        scale = np.maximum(np.abs(projected).max(axis=0), 1e-6)
        return (projected / scale * 0.48).astype(np.float32)

    @staticmethod
    def _assign_communities(embeddings: np.ndarray) -> np.ndarray:
        normalized = embeddings / np.maximum(
            np.linalg.norm(embeddings, axis=1, keepdims=True),
            1e-6,
        )
        cluster_count = min(10, max(3, round(np.sqrt(len(normalized)) / 1.5)))
        center_indexes = [0]
        closest_similarity = normalized @ normalized[0]
        for _ in range(1, cluster_count):
            index = int(np.argmin(closest_similarity))
            center_indexes.append(index)
            closest_similarity = np.maximum(
                closest_similarity,
                normalized @ normalized[index],
            )

        centers = normalized[center_indexes].copy()
        labels = np.zeros(len(normalized), dtype=np.int16)
        for _ in range(28):
            labels = np.argmax(normalized @ centers.T, axis=1).astype(np.int16)
            for cluster_index in range(cluster_count):
                members = normalized[labels == cluster_index]
                if len(members) == 0:
                    continue
                center = members.mean(axis=0)
                centers[cluster_index] = center / max(
                    float(np.linalg.norm(center)),
                    1e-6,
                )
        return labels

    @staticmethod
    def _force_layout(
        points: np.ndarray,
        edges: tuple[_MapEdge, ...],
        communities: np.ndarray,
    ) -> np.ndarray:
        """Force-direct the similarity graph into readable local communities."""

        result = points.copy()
        indexes = np.arange(len(result), dtype=np.float32)
        result += np.column_stack(
            (np.cos(indexes * 2.41), np.sin(indexes * 1.73))
        ) * 0.015

        for iteration in range(150):
            deltas = result[:, np.newaxis, :] - result[np.newaxis, :, :]
            squared_distance = np.sum(deltas * deltas, axis=2, keepdims=True)
            repulsion = (
                deltas / np.maximum(squared_distance, 0.016)
            ).sum(axis=1) * 0.0026
            movement = repulsion

            for edge in edges:
                delta = result[edge.right_index] - result[edge.left_index]
                distance = max(float(np.linalg.norm(delta)), 1e-4)
                ideal_distance = 0.17 + (1.0 - edge.strength) * 0.25
                pull = delta * (distance - ideal_distance) * edge.strength * 0.095
                movement[edge.left_index] += pull
                movement[edge.right_index] -= pull

            for community in np.unique(communities):
                member_indexes = np.flatnonzero(communities == community)
                if len(member_indexes) < 2:
                    continue
                center = result[member_indexes].mean(axis=0)
                movement[member_indexes] += (
                    center - result[member_indexes]
                ) * 0.0038

            cooling = 1.0 - iteration / 185
            result += np.clip(movement, -0.032, 0.032) * cooling

        result -= result.mean(axis=0, keepdims=True)
        scale = np.maximum(np.abs(result).max(axis=0), 1e-6)
        return np.clip(result / scale * 0.94, -1.1, 1.1).astype(np.float32)

    @staticmethod
    def _build_edges(embeddings: np.ndarray) -> tuple[_MapEdge, ...]:
        normalized = embeddings / np.maximum(
            np.linalg.norm(embeddings, axis=1, keepdims=True),
            1e-6,
        )
        similarities = normalized @ normalized.T
        edges: list[_MapEdge] = []
        seen: set[tuple[int, int]] = set()

        for index, row in enumerate(similarities):
            neighbor_indexes = np.argsort(row)[::-1][1:4]
            for neighbor_index in neighbor_indexes:
                strength = float(row[neighbor_index])
                if strength < 0.55:
                    continue
                key = tuple(sorted((index, int(neighbor_index))))
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    _MapEdge(
                        left_index=key[0],
                        right_index=key[1],
                        strength=strength,
                    )
                )
        return tuple(edges)
