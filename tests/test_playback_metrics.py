from app.ui.playback_metrics import reached_completion_threshold


def test_seek_to_eighty_percent_counts_as_completion_threshold() -> None:
    assert reached_completion_threshold(80_000, 100_000)
    assert reached_completion_threshold(95_000, 100_000)


def test_position_before_eighty_percent_does_not_count() -> None:
    assert not reached_completion_threshold(79_999, 100_000)
    assert not reached_completion_threshold(0, 0)
