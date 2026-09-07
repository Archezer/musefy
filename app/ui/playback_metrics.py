"""Pure playback threshold helpers used by the desktop player."""

COMPLETION_THRESHOLD_PERCENT = 80


def reached_completion_threshold(
    position_ms: int,
    duration_ms: int,
) -> bool:
    """Return whether a track position is at or beyond the 80% threshold."""

    return (
        duration_ms > 0
        and position_ms >= 0
        and position_ms * 100 >= duration_ms * COMPLETION_THRESHOLD_PERCENT
    )
