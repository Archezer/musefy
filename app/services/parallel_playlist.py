"""Shared bounded-concurrency helpers for playlist imports."""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

from app.domain.models import Track

DEFAULT_PLAYLIST_IMPORT_WORKERS = 6
MAX_PLAYLIST_IMPORT_WORKERS = 16

CandidateT = TypeVar("CandidateT")


def parallel_playlist_import(
    candidates: Sequence[CandidateT],
    import_one: Callable[[CandidateT], Track],
    *,
    max_workers: int = DEFAULT_PLAYLIST_IMPORT_WORKERS,
    on_progress: Callable[[int, int], None] | None = None,
    on_track_imported: Callable[[CandidateT, Track], None] | None = None,
) -> tuple[
    tuple[Track, ...],
    tuple[tuple[CandidateT, str], ...],
    tuple[tuple[CandidateT, Track], ...],
]:
    """Import playlist items concurrently while preserving source order.

    Network/download work runs in the pool.  Completion callbacks are
    consumed by the caller's thread, so UI signal emission is never performed
    by arbitrary worker threads.  A bounded pool keeps a large playlist from
    creating one connection per track.
    """

    total = len(candidates)
    if total == 0:
        return (), (), ()

    if not 1 <= max_workers <= MAX_PLAYLIST_IMPORT_WORKERS:
        raise ValueError(
            "max_workers must be between 1 and "
            f"{MAX_PLAYLIST_IMPORT_WORKERS}"
        )

    def import_one_safe(
        index: int,
        candidate: CandidateT,
    ) -> tuple[int, CandidateT, Track | None, str | None]:
        try:
            return index, candidate, import_one(candidate), None
        except (OSError, RuntimeError, ValueError) as error:
            return index, candidate, None, str(error)

    imported_by_index: dict[int, tuple[CandidateT, Track]] = {}
    failed_by_index: dict[int, tuple[CandidateT, str]] = {}

    with ThreadPoolExecutor(
        max_workers=min(max_workers, total),
        thread_name_prefix="musefy-download",
    ) as executor:
        futures = {
            executor.submit(import_one_safe, index, candidate): index
            for index, candidate in enumerate(candidates)
        }

        for completed, future in enumerate(as_completed(futures), start=1):
            index, candidate, track, error = future.result()
            if track is not None:
                imported_by_index[index] = (candidate, track)
                if on_track_imported is not None:
                    on_track_imported(candidate, track)
            else:
                failed_by_index[index] = (
                    candidate,
                    error or "Playlist track import failed.",
                )

            if on_progress is not None:
                on_progress(completed, total)

    imported_candidates = tuple(
        imported_by_index[index]
        for index in range(total)
        if index in imported_by_index
    )
    failed = tuple(
        failed_by_index[index]
        for index in range(total)
        if index in failed_by_index
    )

    return (
        tuple(track for _, track in imported_candidates),
        failed,
        imported_candidates,
    )
