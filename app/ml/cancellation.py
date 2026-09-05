from collections.abc import Callable

CancellationCheck = Callable[[], bool]


class AnalysisCancelled(Exception):
    """Raised when a running track analysis receives a shutdown request."""


def raise_if_cancelled(
    is_cancelled: CancellationCheck | None,
) -> None:
    if is_cancelled is not None and is_cancelled():
        raise AnalysisCancelled()
