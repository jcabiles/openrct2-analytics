"""Tests for publish error exit codes and output."""

from openrct2_analytics.ingest.publish_errors import (
    PublishFailed,
    PublishRefused,
    exit_code,
    format_line,
)


def test_refusal_exit_code_is_two() -> None:
    assert exit_code(PublishRefused("locked", "another publish is running")) == 2


def test_failure_exit_code_is_one() -> None:
    assert exit_code(PublishFailed("write", "could not replace the published file")) == 1


def test_refusal_line() -> None:
    assert format_line(PublishRefused("locked", "another publish is running")) == (
        "publish refused: locked: another publish is running"
    )


def test_failure_line() -> None:
    assert format_line(PublishFailed("write", "could not replace the published file")) == (
        "publish failed: write: could not replace the published file"
    )


def test_failure_line_includes_notes_on_one_line() -> None:
    error = PublishFailed("write", "could not replace the published file")
    error.add_note("cleanup failed\nfor staging file")

    line = format_line(error)

    assert line.endswith("; cleanup failed for staging file")
    assert "\n" not in line
