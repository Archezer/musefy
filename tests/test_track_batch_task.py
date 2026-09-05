from app.domain.models import Track
from app.ui.workers import TrackBatchTask


def test_track_batch_task_emits_small_progressive_batches() -> None:
    tracks = [
        Track(id=f"track-{index}", title=f"Track {index}", artist="Artist")
        for index in range(7)
    ]
    batches: list[tuple[int, int, tuple[Track, ...]]] = []
    finished: list[int] = []

    task = TrackBatchTask(
        tracks,
        start_index=0,
        generation=4,
        batch_size=3,
    )
    task.signals.batch_ready.connect(
        lambda generation, start_index, batch: batches.append(
            (generation, start_index, tuple(batch))
        )
    )
    task.signals.finished.connect(finished.append)

    task.run()

    assert [(generation, start_index, len(batch)) for generation, start_index, batch in batches] == [
        (4, 0, 3),
        (4, 3, 3),
        (4, 6, 1),
    ]
    assert finished == [4]
