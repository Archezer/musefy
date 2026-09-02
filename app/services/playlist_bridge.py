from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from app.storage.paths import PLAYLIST_EXPORTS_DIR

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 8765
PLAYLIST_IMPORT_ENDPOINT = "/api/playlist-import"
MAX_REQUEST_BYTES = 10 * 1024 * 1024
SUPPORTED_SOURCES = frozenset({"vk", "spotify", "yandex"})


class PlaylistBridgeServer:
    """Accept playlist JSON exported by the local browser extension."""

    def __init__(
        self,
        export_dir: Path = PLAYLIST_EXPORTS_DIR,
        host: str = BRIDGE_HOST,
        port: int = BRIDGE_PORT,
    ) -> None:
        self.export_dir = export_dir
        self._server = ThreadingHTTPServer(
            (host, port),
            self._handler_type(),
        )
        self._server.daemon_threads = True
        self._thread: Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self._server.server_address
        return str(host), int(port)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self.export_dir.mkdir(parents=True, exist_ok=True)
        self._thread = Thread(
            target=self._server.serve_forever,
            name="playlist-bridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            self._server.server_close()
            return

        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        self._thread = None

    def save_export(self, payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise ValueError("Playlist export must be a JSON object.")

        playlist = payload.get("playlist")
        tracks = payload.get("tracks")

        if not isinstance(playlist, dict):
            raise ValueError("Playlist export does not contain playlist metadata.")

        if not isinstance(tracks, list):
            raise ValueError("Playlist export does not contain a tracks list.")

        source = str(playlist.get("source") or "").strip().lower()
        if source not in SUPPORTED_SOURCES:
            raise ValueError("Unsupported playlist source.")

        title = str(playlist.get("title") or "playlist").strip()
        source_dir = self.export_dir / source
        source_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        filename = f"{timestamp}-{_safe_filename(title)}.json"
        destination = source_dir / filename
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        return {
            "ok": True,
            "source": source,
            "track_count": len(tracks),
            "path": str(destination.resolve()),
            "relative_path": destination.as_posix(),
        }

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        bridge = self

        class PlaylistBridgeHandler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_OPTIONS(self) -> None:
                self.send_response(204)
                self._write_cors_headers()
                self.end_headers()

            def do_POST(self) -> None:
                if self.path != PLAYLIST_IMPORT_ENDPOINT:
                    self._send_json(404, {"ok": False, "error": "Not found."})
                    return

                content_length = self.headers.get("Content-Length")
                try:
                    request_size = int(content_length or "0")
                except ValueError:
                    self._send_json(
                        400,
                        {"ok": False, "error": "Invalid Content-Length."},
                    )
                    return

                if request_size <= 0 or request_size > MAX_REQUEST_BYTES:
                    self._send_json(
                        413,
                        {"ok": False, "error": "Playlist export is too large."},
                    )
                    return

                try:
                    payload = json.loads(self.rfile.read(request_size))
                    result = bridge.save_export(payload)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    self._send_json(
                        400,
                        {"ok": False, "error": f"Invalid JSON: {error}"},
                    )
                    return
                except ValueError as error:
                    self._send_json(400, {"ok": False, "error": str(error)})
                    return
                except OSError:
                    self._send_json(
                        500,
                        {"ok": False, "error": "Could not save playlist export."},
                    )
                    return

                self._send_json(200, result)

            def _send_json(self, status: int, payload: dict[str, object]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self._write_cors_headers()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _write_cors_headers(self) -> None:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

        return PlaylistBridgeHandler


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    return cleaned[:80] or "playlist"
