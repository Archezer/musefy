from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
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


@dataclass(frozen=True)
class MapBuildResult:
    """Computed map data that can safely cross the worker/UI boundary."""

    signature: tuple[tuple[str, int], ...]
    nodes: tuple[_MapNode, ...]
    edges: tuple[_MapEdge, ...]
    points: np.ndarray


# A track is connected only to genuinely similar tracks.  The larger local
# neighborhood keeps the web visible, while the threshold removes accidental
# long-range links between unrelated parts of the library.
MAP_MAX_NEIGHBOR_COUNT = 15
MAP_SIMILARITY_THRESHOLD = 0.62
MAP_EDGE_STRATEGY_VERSION = 7


class MusicMapWidget(QWidget):
    """A Graphify-inspired local map of music similarity communities."""

    track_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._nodes: tuple[_MapNode, ...] = ()
        self._edges: tuple[_MapEdge, ...] = ()
        self._points = np.empty((0, 2), dtype=np.float32)
        self._track_signature: tuple[tuple[str, int], ...] = ()
        self._map_data_ready = False
        self._snapshot: QImage | None = None
        self._snapshot_signature: tuple[tuple[str, int], ...] = ()
        self._is_loading = False
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
        self.apply_map_data(self.build_map_data(tracks))

    @staticmethod
    def track_signature(
        tracks: list[Track],
    ) -> tuple[tuple[str, int], ...]:
        embedded_tracks = [
            track
            for track in tracks
            if track.track_embedding
        ]
        return MusicMapWidget._signature_for_tracks(embedded_tracks)

    @staticmethod
    def select_tracks_for_percentage(
        tracks: list[Track],
        percentage: int,
    ) -> list[Track]:
        """Choose a stable representative share of analyzed library tracks."""

        if not 1 <= percentage <= 100:
            raise ValueError("Map track percentage must be between 1 and 100")

        embedded_tracks = [
            track
            for track in tracks
            if track.track_embedding
        ]
        if percentage == 100:
            return embedded_tracks

        selection_size = (len(embedded_tracks) * percentage + 99) // 100
        selected_ids = {
            track.id
            for track in sorted(
                embedded_tracks,
                key=lambda track: sha256(
                    track.id.encode("utf-8")
                ).digest(),
            )[:selection_size]
        }
        return [
            track for track in embedded_tracks if track.id in selected_ids
        ]

    @classmethod
    def build_map_data(cls, tracks: list[Track]) -> MapBuildResult:
        embedded_tracks = [
            track
            for track in tracks
            if track.track_embedding
        ]
        signature = cls._signature_for_tracks(embedded_tracks)

        if len(embedded_tracks) < 2:
            return MapBuildResult(
                signature=signature,
                nodes=(),
                edges=(),
                points=np.empty((0, 2), dtype=np.float32),
            )

        embeddings = np.asarray(
            [track.track_embedding for track in embedded_tracks],
            dtype=np.float32,
        )
        communities = cls._assign_communities(embeddings)
        nodes = tuple(
            _MapNode(
                track_id=track.id,
                title=track.title,
                artist=track.artist,
                community=int(communities[index]),
            )
            for index, track in enumerate(embedded_tracks)
        )
        edges = cls._build_edges(embeddings)
        points = cls._project_embeddings(embeddings)
        return MapBuildResult(
            signature=signature,
            nodes=nodes,
            edges=edges,
            points=points,
        )

    @staticmethod
    def _signature_for_tracks(
        tracks: list[Track],
    ) -> tuple[tuple[str, int], ...]:
        return tuple(
            (
                track.id,
                hash(track.track_embedding or ()),
            )
            for track in tracks
        )

    def apply_map_data(self, result: MapBuildResult) -> None:
        self._track_signature = result.signature
        self._nodes = result.nodes
        self._edges = result.edges
        self._points = result.points.copy()
        self._map_data_ready = True
        self._snapshot = None
        self._snapshot_signature = ()
        self._is_loading = False
        self._reset_view()
        self.update()

    def has_map_data_for(
        self,
        signature: tuple[tuple[str, int], ...],
    ) -> bool:
        return self._map_data_ready and self._track_signature == signature

    def set_loading(self, loading: bool) -> None:
        self._is_loading = loading
        self.update()

    def has_snapshot(self) -> bool:
        return self._snapshot is not None

    def load_snapshot(
        self,
        image_path: Path,
        metadata_path: Path,
        signature: tuple[tuple[str, int], ...],
    ) -> bool:
        """Load the last rendered map as a background preview.

        The snapshot may describe an older library revision.  It remains a
        useful visual until the user explicitly opens the interactive map and
        requests a rebuild for the current library.
        """

        if (
            not image_path.is_file()
            or not metadata_path.is_file()
        ):
            return False

        try:
            metadata = json.loads(
                metadata_path.read_text(encoding="utf-8")
            )
            if (
                not isinstance(metadata, dict)
                or metadata.get("edge_strategy_version")
                != MAP_EDGE_STRATEGY_VERSION
            ):
                return False
            stored_signature = tuple(
                (str(item[0]), int(item[1]))
                for item in metadata["signature"]
            )
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return False

        if not stored_signature:
            return False

        image = QImage()
        if not image.load(str(image_path)) or image.isNull():
            return False

        self._snapshot = image
        self._snapshot_signature = stored_signature
        self.update()
        return True

    def save_snapshot(
        self,
        image_path: Path,
        metadata_path: Path,
    ) -> bool:
        """Persist the current rendered map and its track signature."""

        if self._snapshot is None or not self._track_signature:
            return False

        image_tmp = image_path.with_name(
            f".{image_path.name}.tmp"
        )
        metadata_tmp = metadata_path.with_name(
            f".{metadata_path.name}.tmp"
        )
        try:
            image_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            if not self._snapshot.save(str(image_tmp), "PNG"):
                return False
            metadata_tmp.write_text(
                json.dumps(
                    {
                        "edge_strategy_version": MAP_EDGE_STRATEGY_VERSION,
                        "signature": [
                            [track_id, embedding_hash]
                            for track_id, embedding_hash in self._track_signature
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            image_tmp.replace(image_path)
            metadata_tmp.replace(metadata_path)
        except (OSError, TypeError, ValueError):
            image_tmp.unlink(missing_ok=True)
            metadata_tmp.unlink(missing_ok=True)
            return False

        return True

    def invalidate_snapshot(self) -> None:
        self._snapshot = None
        self._snapshot_signature = ()
        self.update()

    def invalidate_map_data(self) -> None:
        """Drop cached graph data after the library signature changes."""

        self._map_data_ready = False
        self._nodes = ()
        self._edges = ()
        self._points = np.empty((0, 2), dtype=np.float32)
        self.invalidate_snapshot()

    def capture_snapshot(self) -> None:
        if not self._nodes or self.width() <= 0 or self.height() <= 0:
            self._snapshot = None
            self._snapshot_signature = ()
            self.update()
            return

        image = QImage(
            self.size(),
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_graph(painter)
        painter.end()
        self._snapshot = image
        self._snapshot_signature = self._track_signature
        self.update()

    def paintEvent(self, _event: object) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._mode != "focus" and self._snapshot is not None:
            painter.drawImage(self.rect(), self._snapshot)
            return

        self._paint_graph(painter)

    def _paint_graph(self, painter: QPainter) -> None:

        if not self._nodes:
            if self._mode != "focus":
                return
            painter.setPen(QColor(163, 163, 170, 145))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                (
                    "Building the music map…"
                    if self._is_loading
                    else "Open the map to generate it."
                ),
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
            max(40.0, self.width() * 0.52),
            max(34.0, self.height() * 0.50),
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
        """Project tracks while preserving local similarity neighborhoods.

        PCA is useful as a deterministic fallback, but it mostly preserves the
        broadest global axes.  That is what made the old map stretch into a
        rectangular shell.  t-SNE works from cosine distance instead, so
        tracks with similar embeddings naturally settle into local groups.
        """

        if not len(embeddings):
            return np.empty((0, 2), dtype=np.float32)

        centered = embeddings - embeddings.mean(axis=0, keepdims=True)

        def pca_projection() -> np.ndarray:
            _, _, components = np.linalg.svd(centered, full_matrices=False)
            result = centered @ components[:2].T
            if result.shape[1] == 1:
                result = np.column_stack((result[:, 0], np.zeros(len(result))))
            return result

        projected: np.ndarray
        if len(embeddings) < 8:
            projected = pca_projection()
        else:
            try:
                from sklearn.manifold import TSNE

                perplexity = min(
                    30.0,
                    max(5.0, (len(embeddings) - 1) / 3.0),
                )
                projected = TSNE(
                    n_components=2,
                    metric="cosine",
                    perplexity=perplexity,
                    init="pca",
                    learning_rate="auto",
                    max_iter=500,
                    random_state=17,
                ).fit_transform(embeddings)
            except (ImportError, ValueError):
                # Keep map generation usable in a minimal installation and
                # for unusual embedding arrays that t-SNE cannot accept.
                projected = pca_projection()

        projected = np.asarray(projected, dtype=np.float32)
        projected -= projected.mean(axis=0, keepdims=True)
        radius_scale = max(
            float(np.percentile(np.linalg.norm(projected, axis=1), 98)),
            1e-6,
        )
        # Use one radial scale for both axes.  Independent axis scaling is
        # what previously forced the map into a box and destroyed density.
        return np.clip(
            projected / radius_scale * 0.72,
            -0.82,
            0.82,
        ).astype(np.float32)

    @staticmethod
    def _assign_communities(embeddings: np.ndarray) -> np.ndarray:
        """Assign colors from the embedding structure, not fixed genre bins."""

        normalized = embeddings / np.maximum(
            np.linalg.norm(embeddings, axis=1, keepdims=True),
            1e-6,
        )
        cluster_count = min(
            len(normalized),
            max(3, round(np.sqrt(len(normalized)) / 1.5)),
        )
        if cluster_count <= 1:
            return np.zeros(len(normalized), dtype=np.int16)

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
    def _build_edges(embeddings: np.ndarray) -> tuple[_MapEdge, ...]:
        normalized = embeddings / np.maximum(
            np.linalg.norm(embeddings, axis=1, keepdims=True),
            1e-6,
        )
        similarities = normalized @ normalized.T
        candidate_edges: dict[tuple[int, int], float] = {}

        for index, row in enumerate(similarities):
            neighbor_indexes = np.flatnonzero(
                row >= MAP_SIMILARITY_THRESHOLD
            )
            neighbor_indexes = neighbor_indexes[neighbor_indexes != index]
            if len(neighbor_indexes) > MAP_MAX_NEIGHBOR_COUNT:
                ranked_indexes = np.argsort(
                    row[neighbor_indexes]
                )[::-1]
                neighbor_indexes = neighbor_indexes[
                    ranked_indexes[:MAP_MAX_NEIGHBOR_COUNT]
                ]

            for neighbor_index in neighbor_indexes:
                strength = float(row[neighbor_index])
                key = tuple(sorted((index, int(neighbor_index))))
                candidate_edges[key] = max(
                    strength,
                    candidate_edges.get(key, 0.0),
                )

        # A pair can be selected by both endpoints.  Keep the strongest
        # candidate edges first and enforce the cap on the final undirected
        # graph as well, so an active hub cannot exceed 15 visible links just
        # because many other tracks selected it as their neighbor.
        degrees = np.zeros(len(normalized), dtype=np.int16)
        edges: list[_MapEdge] = []
        ranked_edges = sorted(
            candidate_edges.items(),
            key=lambda item: (-item[1], item[0]),
        )
        for (left_index, right_index), strength in ranked_edges:
            if (
                degrees[left_index] >= MAP_MAX_NEIGHBOR_COUNT
                or degrees[right_index] >= MAP_MAX_NEIGHBOR_COUNT
            ):
                continue
            degrees[left_index] += 1
            degrees[right_index] += 1
            edges.append(
                _MapEdge(
                    left_index=left_index,
                    right_index=right_index,
                    strength=strength,
                )
            )
        return tuple(edges)
