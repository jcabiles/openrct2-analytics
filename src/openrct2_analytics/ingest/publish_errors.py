"""Errors and command output for publishing a warehouse."""

from __future__ import annotations


class PublishRefused(Exception):
    """Raised when a publish request is refused before it can run.

    Args:
        reason: Short machine-readable refusal reason.
        detail: Human-readable explanation of the refusal.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(reason, detail)
        self.reason = reason
        self.detail = detail


class PublishFailed(Exception):
    """Raised when a publish operation starts but fails.

    Args:
        reason: Short machine-readable failure reason.
        detail: Human-readable explanation of the failure.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(reason, detail)
        self.reason = reason
        self.detail = detail


def exit_code(exc: PublishRefused | PublishFailed) -> int:
    """Return the process exit code for a publish error.

    Args:
        exc: The refusal or failure to map to an exit code.

    Returns:
        ``2`` for a refusal and ``1`` for a failure.
    """
    if isinstance(exc, PublishRefused):
        return 2
    return 1


def format_line(exc: PublishRefused | PublishFailed) -> str:
    """Format the one-line message for a publish error.

    Args:
        exc: The refusal or failure to format.

    Returns:
        The error kind, reason, and detail on one line.
    """
    prefix = "publish refused" if isinstance(exc, PublishRefused) else "publish failed"
    line = f"{prefix}: {exc.reason}: {exc.detail}"
    notes = getattr(exc, "__notes__", ())
    if notes:
        formatted_notes = (
            note.replace("\r\n", " ").replace("\r", " ").replace("\n", " ") for note in notes
        )
        line += "; " + "; ".join(formatted_notes)
    return line
