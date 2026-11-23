"""Turn DuckDB's interrupt error back into the interrupt that caused it."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from openrct2_analytics.ingest import lock


@contextmanager
def interrupt_as_signal() -> Iterator[None]:
    """Raise the interrupt itself when DuckDB turns it into ``RuntimeError('Query interrupted')``.

    A signal during a query runs the handler, which raises ``lock.Interrupted`` (or Python raises
    ``KeyboardInterrupt``); DuckDB then ends the query with that ``RuntimeError``, the interrupt as
    its ``__cause__``. Any other ``RuntimeError`` passes through unchanged.
    """
    try:
        yield
    except RuntimeError as error:
        cause = error.__cause__
        if str(error) == "Query interrupted" and isinstance(
            cause, lock.Interrupted | KeyboardInterrupt
        ):
            raise cause from None
        raise
