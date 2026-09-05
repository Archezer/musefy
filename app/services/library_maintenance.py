"""Library health checks and portable local-library backups.

The acoustic check deliberately differs from the SHA-256 check used while
ingesting files: it decodes a short audio sample and compares a compact
spectral/chroma signature, so an MP3 and FLAC of the same recording can be
identified even though their bytes are entirely different.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.domain.models import (
    Interaction,
    Playlist,
    PlaylistEntry,
    Track,
    User,
)
from app.ingestion.metadata import read_audio_metadata
from app.storage.paths import DATA_DIR, ensure_storage_directories
from app.storage.protocols import MusicStore

JSON_EXPORT_FORMAT = "musefy-library-export"
ZIP_BACKUP_FORMAT = "musefy-library-backup"
BACKUP_VERSION = 1


@dataclass(frozen=True)
class TrackIssue:
    track: Track
    detail: str


@dataclass(frozen=True)
class DuplicateGroup:
    kind: str
    tracks: tuple[Track, ...]
    similarity: float | None = None


@dataclass(frozen=True)
class LibraryHealthReport:
    checked_tracks: int
    missing_files: tuple[TrackIssue, ...]
    broken_audio: tuple[TrackIssue, ...]
    exact_duplicates: tuple[DuplicateGroup, ...]
    acoustic_duplicates: tuple[DuplicateGroup, ...]
    fingerprint_unavailable: tuple[TrackIssue, ...]


@dataclass(frozen=True)
class BackupSummary:
    path: Path
    track_count: int
    playlist_count: int
    interaction_count: int
    includes_audio: bool


class LibraryHealthService:
    """Inspect registered files without changing the library."""

    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def scan(self) -> LibraryHealthReport:
        tracks = list(self.store.list_tracks())
        missing: list[TrackIssue] = []
        broken: list[TrackIssue] = []
        unavailable: list[TrackIssue] = []
        hash_groups: dict[str, list[Track]] = {}
        fingerprints: list[tuple[Track, tuple[float, ...]]] = []

        for track in tracks:
            path = self._track_path(track)
            if path is None or not path.is_file():
                missing.append(
                    TrackIssue(track, "Audio file is not available on disk.")
                )
                continue

            try:
                read_audio_metadata(path)
            except (OSError, ValueError) as error:
                broken.append(TrackIssue(track, str(error)))
                continue

            try:
                content_hash = self._file_hash(path)
            except OSError as error:
                broken.append(TrackIssue(track, str(error)))
                continue
            hash_groups.setdefault(content_hash, []).append(track)

            try:
                fingerprints.append((track, self._acoustic_fingerprint(path)))
            except ImportError as error:
                unavailable.append(
                    TrackIssue(
                        track,
                        f"Acoustic fingerprint unavailable: {error}",
                    )
                )
            except (OSError, RuntimeError, ValueError) as error:
                broken.append(
                    TrackIssue(
                        track,
                        f"Audio decode check failed: {error}",
                    )
                )

        exact_groups = tuple(
            DuplicateGroup("Identical files", tuple(group))
            for group in hash_groups.values()
            if len(group) > 1
        )
        exact_pair_ids = {
            frozenset((first.id, second.id))
            for group in exact_groups
            for index, first in enumerate(group.tracks)
            for second in group.tracks[index + 1 :]
        }
        acoustic_groups = self._find_acoustic_duplicates(
            fingerprints,
            exact_pair_ids,
        )

        return LibraryHealthReport(
            checked_tracks=len(tracks),
            missing_files=tuple(missing),
            broken_audio=tuple(broken),
            exact_duplicates=exact_groups,
            acoustic_duplicates=acoustic_groups,
            fingerprint_unavailable=tuple(unavailable),
        )

    @staticmethod
    def _track_path(track: Track) -> Path | None:
        if not track.local_path:
            return None
        return Path(track.local_path).expanduser()

    @staticmethod
    def _file_hash(path: Path) -> str:
        hasher = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                hasher.update(chunk)
        return hasher.hexdigest()

    @staticmethod
    def _acoustic_fingerprint(path: Path) -> tuple[float, ...]:
        """Return a codec-independent signature from decoded audio.

        CENS chroma is designed to be insensitive to dynamics and moderate
        encoding artifacts.  Combining its average and variation avoids
        treating tracks in the same key as copies of each other.
        """

        import librosa
        import numpy as np

        samples, sample_rate = librosa.load(
            str(path),
            sr=11_025,
            mono=True,
            duration=90.0,
        )
        if len(samples) < sample_rate * 3:
            raise ValueError("audio is shorter than three seconds")

        samples, _ = librosa.effects.trim(samples, top_db=40)
        if len(samples) < sample_rate * 3:
            raise ValueError("audio contains no usable signal")

        chroma = librosa.feature.chroma_cens(
            y=samples,
            sr=sample_rate,
            hop_length=2_048,
        )
        if chroma.size == 0:
            raise ValueError("no acoustic features could be extracted")

        average = np.mean(chroma, axis=1)
        variation = np.std(chroma, axis=1)
        signature = np.concatenate((average, variation)).astype(float)
        norm = float(np.linalg.norm(signature))
        if norm == 0:
            raise ValueError("empty acoustic signature")
        return tuple(float(value / norm) for value in signature)

    @staticmethod
    def _find_acoustic_duplicates(
        fingerprints: list[tuple[Track, tuple[float, ...]]],
        exact_pair_ids: set[frozenset[str]],
    ) -> tuple[DuplicateGroup, ...]:
        candidates: list[DuplicateGroup] = []
        for index, (first_track, first_signature) in enumerate(fingerprints):
            for second_track, second_signature in fingerprints[index + 1 :]:
                if frozenset((first_track.id, second_track.id)) in exact_pair_ids:
                    continue
                if not LibraryHealthService._durations_are_close(
                    first_track,
                    second_track,
                ):
                    continue
                similarity = sum(
                    left * right
                    for left, right in zip(
                        first_signature,
                        second_signature,
                        strict=True,
                    )
                )
                # A strict threshold is intentional: the result is a review
                # list, not an automatic deletion tool.
                if similarity >= 0.985:
                    candidates.append(
                        DuplicateGroup(
                            "Same recording (acoustic fingerprint)",
                            (first_track, second_track),
                            similarity,
                        )
                    )
        return tuple(candidates)

    @staticmethod
    def _durations_are_close(first: Track, second: Track) -> bool:
        if first.duration_ms is None or second.duration_ms is None:
            return True
        return abs(first.duration_ms - second.duration_ms) <= 3_000


class LibraryBackupService:
    """Create full ZIP snapshots and portable JSON database exports."""

    def __init__(self, store: MusicStore) -> None:
        self.store = store

    def create_zip_backup(self, destination: Path) -> BackupSummary:
        ensure_storage_directories()
        destination = destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self._export_payload()

        with zipfile.ZipFile(
            destination,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "format": ZIP_BACKUP_FORMAT,
                        "version": BACKUP_VERSION,
                        "created_at": datetime.now(UTC).isoformat(),
                        "includes": "database, audio, covers, analysis",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
            archive.writestr(
                "library.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            for file_path in DATA_DIR.rglob("*"):
                if not file_path.is_file() or file_path.resolve() == destination:
                    continue
                archive.write(
                    file_path,
                    Path("data") / file_path.relative_to(DATA_DIR),
                )

        return self._summary(destination, payload, includes_audio=True)

    def export_json(self, destination: Path) -> BackupSummary:
        destination = destination.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = self._export_payload()
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self._summary(destination, payload, includes_audio=False)

    def restore_zip_backup(self, source: Path) -> None:
        """Replace ``DATA_DIR`` from a validated Musefy ZIP snapshot.

        The caller must first close database connections and ask the user for
        confirmation.  Extraction is staged beside the data directory so a
        malformed archive never partially overwrites the active library.
        """

        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"Backup does not exist: {source}")

        staging_root = Path(
            tempfile.mkdtemp(prefix="musefy-restore-", dir=DATA_DIR.parent)
        )
        try:
            with zipfile.ZipFile(source) as archive:
                manifest = self._read_zip_manifest(archive)
                if manifest.get("format") != ZIP_BACKUP_FORMAT:
                    raise ValueError("This ZIP is not a Musefy backup.")

                for member in archive.infolist():
                    target = (staging_root / member.filename).resolve()
                    if not target.is_relative_to(staging_root.resolve()):
                        raise ValueError("Backup contains an unsafe path.")
                    archive.extract(member, staging_root)

            restored_data = staging_root / "data"
            if not (restored_data / "music.db").is_file():
                raise ValueError("Backup does not contain a library database.")

            if DATA_DIR.exists():
                shutil.rmtree(DATA_DIR)
            shutil.move(str(restored_data), str(DATA_DIR))
            ensure_storage_directories()
        finally:
            shutil.rmtree(staging_root, ignore_errors=True)

    def _export_payload(self) -> dict[str, Any]:
        return {
            "format": JSON_EXPORT_FORMAT,
            "version": BACKUP_VERSION,
            "exported_at": datetime.now(UTC).isoformat(),
            "users": [self._user_to_dict(user) for user in self.store.list_users()],
            "tracks": [self._track_to_dict(track) for track in self.store.list_tracks()],
            "playlists": [
                self._playlist_to_dict(playlist)
                for playlist in self.store.list_playlists()
            ],
            "playlist_entries": [
                self._entry_to_dict(entry)
                for playlist in self.store.list_playlists()
                for entry in self.store.list_playlist_entries(playlist.id)
            ],
            "interactions": [
                self._interaction_to_dict(interaction)
                for interaction in self.store.list_interactions()
            ],
        }

    @staticmethod
    def _summary(
        path: Path,
        payload: dict[str, Any],
        *,
        includes_audio: bool,
    ) -> BackupSummary:
        return BackupSummary(
            path=path,
            track_count=len(payload["tracks"]),
            playlist_count=len(payload["playlists"]),
            interaction_count=len(payload["interactions"]),
            includes_audio=includes_audio,
        )

    @staticmethod
    def _read_zip_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
        try:
            return json.loads(archive.read("manifest.json"))
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Backup manifest is missing or invalid.") from error

    @staticmethod
    def _timestamp(value: datetime) -> str:
        return value.astimezone(UTC).isoformat()

    @classmethod
    def _track_to_dict(cls, track: Track) -> dict[str, Any]:
        return {
            "id": track.id,
            "title": track.title,
            "artist": track.artist,
            "created_at": cls._timestamp(track.created_at),
            "genres": list(track.genres),
            "detected_genres": [asdict(genre) for genre in track.detected_genres],
            "track_embedding": list(track.track_embedding or ()),
            "mood": (
                {"valence": track.mood.valence, "arousal": track.mood.arousal}
                if track.mood is not None
                else None
            ),
            "mood_tags": [list(item) for item in track.mood_tags],
            "mood_profiles": [list(item) for item in track.mood_profiles],
            "mood_analysis_version": track.mood_analysis_version,
            "duration_ms": track.duration_ms,
            "source": track.source,
            "source_id": track.source_id,
            "source_url": track.source_url,
            "local_path": track.local_path,
            "cover_path": track.cover_path,
        }

    @classmethod
    def _user_to_dict(cls, user: User) -> dict[str, Any]:
        return {
            "id": user.id,
            "display_name": user.display_name,
            "created_at": cls._timestamp(user.created_at),
        }

    @classmethod
    def _playlist_to_dict(cls, playlist: Playlist) -> dict[str, Any]:
        return {
            "id": playlist.id,
            "name": playlist.name,
            "cover_path": playlist.cover_path,
            "created_at": cls._timestamp(playlist.created_at),
        }

    @staticmethod
    def _entry_to_dict(entry: PlaylistEntry) -> dict[str, Any]:
        return asdict(entry)

    @classmethod
    def _interaction_to_dict(cls, interaction: Interaction) -> dict[str, Any]:
        return {
            "user_id": interaction.user_id,
            "track_id": interaction.track_id,
            "interaction_type": interaction.interaction_type.value,
            "mood_context": interaction.mood_context,
            "recommendation_session_id": (
                interaction.recommendation_session_id
            ),
            "created_at": cls._timestamp(interaction.created_at),
        }
