"""The fallback line, the print order and the reader's own handling, after a successful filing.

Each fallback case plants one valid warehouse (or none) and changes one thing; the expected line is
a literal. The line is one plain line with a short fixed reason: no SQL, path, process ID or user
name from the database's own error text. Spec R15, R17 and the reader of R3.
"""

from __future__ import annotations

import builtins
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import TextIO

import duckdb
import pytest

from openrct2_analytics.ingest import lock, play_status, publish_audit, several_parks
from tests.auto_file_support import (
    BEFORE,
    NO_WAREHOUSE_LINE,
    _before,
    _dim_park,
    _run,
)
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_auto_file_answers import ALPHA_LINE, BETA_SANDBOX_LINE, Registering, _plant
from tests.test_auto_file_park_number import Watching, _files_cleared, _two_parks_filed

LOCKED_LINE = (
    "auto-file: the play is filed, but the park number could not be shown "
    "(the warehouse is locked by another program).\n"
)
OLD_BUILD_LINE = (
    "auto-file: the play is filed, but the park number could not be shown "
    "(the warehouse was built before park numbers).\n"
)
DAMAGED_LINE = (
    "auto-file: the play is filed, but the park number could not be shown "
    "(the warehouse could not be read).\n"
)
STDERR_LINE = "auto-file: the play is filed, but its last lines could not be written.\n"


def _fallback(data: Path, tmp_path: Path, out: str, line: str) -> None:
    """Assert the whole output: the two is-new lines, then exactly ``line``, plain and one line."""
    assert out == ALPHA_LINE + BETA_SANDBOX_LINE + line
    assert out.count("could not be shown") == 1
    assert "/" not in line
    assert str(tmp_path) not in out
    _files_cleared(tmp_path)


def test_no_warehouse_file_gives_one_plain_line_and_exit_0(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, filed = _two_parks_filed(data, tmp_path)

    assert code == 0
    assert filed.present == [True, True]
    _fallback(data, tmp_path, capsys.readouterr().out, NO_WAREHOUSE_LINE)


def test_a_held_lock_gives_one_plain_line_and_exit_0(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _dim_park(tmp_path, [("park-a", 1, 2000)])
    with ExitStack() as stack:
        code, filed = _two_parks_filed(data, tmp_path, Watching(stack, path))

    assert code == 0
    assert filed.present == [True, True]
    _fallback(data, tmp_path, capsys.readouterr().out, LOCKED_LINE)


def test_a_dim_park_without_park_number_gives_one_plain_line_and_exit_0(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _dim_park(tmp_path, [("park-a", None, 2000)], number_column=False)

    code, filed = _two_parks_filed(data, tmp_path)

    assert code == 0
    assert filed.present == [True, True]
    _fallback(data, tmp_path, capsys.readouterr().out, OLD_BUILD_LINE)


def test_a_missing_dim_park_table_gives_one_plain_line_and_exit_0(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _dim_park(tmp_path, [("park-a", 1, 2000)])
    with duckdb.connect(str(path)) as connection:
        connection.execute("DROP TABLE marts.dim_park")

    code, filed = _two_parks_filed(data, tmp_path)

    assert code == 0
    assert filed.present == [True, True]
    _fallback(data, tmp_path, capsys.readouterr().out, OLD_BUILD_LINE)


@pytest.mark.parametrize(
    "error", [PermissionError("/secret/path"), duckdb.IOException("damaged /secret/path")]
)
def test_any_other_read_error_gives_the_generic_reason_without_its_text(error: Exception) -> None:
    assert several_parks.unread_line(error) == DAMAGED_LINE.rstrip("\n")


def test_the_text_duckdb_gives_for_a_held_lock_is_the_locked_reason() -> None:
    error = duckdb.IOException(
        'IO Error: Could not set lock on file "w.duckdb": Conflicting lock is held in py (PID 1)'
    )

    assert several_parks.unread_line(error) == LOCKED_LINE.rstrip("\n")


def test_the_text_duckdb_gives_for_a_damaged_file_is_not_the_locked_reason() -> None:
    # "block" holds "lock", so a substring match on "lock" would call this file locked.
    error = duckdb.IOException(
        "IO Error: Failed to read a block at location 4096 of file w.duckdb: checksum mismatch"
    )

    assert several_parks.unread_line(error) == DAMAGED_LINE.rstrip("\n")


# R17: an interrupt while the lines print.


@pytest.mark.parametrize("interrupt", [KeyboardInterrupt, lock.Interrupted])
def test_an_interrupt_while_the_lines_print_ends_with_130_and_no_failure_report(
    interrupt: type[BaseException],
    *,
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])
    real_print = builtins.print

    def interrupted(*args: object, **kwargs: object) -> None:
        if "joins the company" in " ".join(str(arg) for arg in args):
            raise interrupt
        real_print(*args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(builtins, "print", interrupted)

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    captured = capsys.readouterr()
    assert code == 130
    assert captured.out == ALPHA_LINE
    for phrase in ("Nothing was changed", "already registered by this run", "To file the rest"):
        assert phrase not in captured.out
    assert "Traceback" not in captured.out + captured.err
    _files_cleared(tmp_path)


def test_a_broken_output_after_filing_ends_with_0_and_one_line_on_standard_error(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])

    class Broken:
        """Standard output whose write fails on the joins line, as a closed pipe does."""

        def __init__(self, inner: TextIO) -> None:
            self.inner = inner

        def write(self, text: str) -> int:
            if "joins the company" in text:
                raise BrokenPipeError
            return self.inner.write(text)

        def flush(self) -> None:
            self.inner.flush()

    monkeypatch.setattr(sys, "stdout", Broken(sys.stdout))

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == ALPHA_LINE
    assert captured.err == STDERR_LINE
    _files_cleared(tmp_path)


def test_the_lines_print_only_after_the_record_files_are_cleared(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    _dim_park(tmp_path, [("park-a", 1, 2000)])
    real_print = builtins.print
    record_present: list[bool] = []

    def noting(*args: object, **kwargs: object) -> None:
        if "joins the company" in " ".join(str(arg) for arg in args):
            record_present.append((tmp_path / BEFORE).exists())
        real_print(*args, **kwargs)  # type: ignore[call-overload]

    monkeypatch.setattr(builtins, "print", noting)

    code, _, _ = _run(tmp_path, "company", filed=Registering(0))

    assert code == 0
    assert record_present == [False]
    assert capsys.readouterr().out.endswith(
        "Alpha joins the company as Park 1, starting in company year 2000\n"
    )


# R3: the reader opens read-only and closes its connection.


def test_the_reader_opens_the_warehouse_read_only(tmp_path: Path) -> None:
    path = _dim_park(tmp_path, [("park-a", 1, 2000)])
    holder = duckdb.connect(str(path), read_only=True)
    try:
        found = play_status.dim_park_numbers(tmp_path, ["park-a"])
    finally:
        holder.close()

    assert found == {"park-a": (1, 2000)}


def test_the_reader_closes_its_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _dim_park(tmp_path, [("park-a", 1, 2000)])
    opened: list[duckdb.DuckDBPyConnection] = []
    real_open = publish_audit.open_warehouse

    def keeping(*args: object, **kwargs: object) -> duckdb.DuckDBPyConnection:
        connection = real_open(*args, **kwargs)  # type: ignore[arg-type]
        opened.append(connection)
        return connection

    monkeypatch.setattr(play_status, "open_warehouse", keeping)

    found = play_status.dim_park_numbers(tmp_path, ["park-a"])

    assert found == {"park-a": (1, 2000)}
    assert len(opened) == 1
    with duckdb.connect(str(path)) as writer:
        assert writer.execute("SELECT count(*) FROM marts.dim_park").fetchone() == (1,)


def test_a_closed_output_pipe_ends_the_process_with_0_not_120() -> None:
    # The write lands in the buffer; only the flush meets the closed pipe, as at interpreter exit.
    code = (
        "import sys\n"
        "from openrct2_analytics.ingest import several_parks\n"
        "sys.stdin.readline()\n"
        "sys.exit(several_parks.say(['Alpha joins the company as Park 1']))\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert child.stdin is not None
    assert child.stdout is not None
    child.stdout.close()
    child.stdin.write("go\n")
    child.stdin.close()

    err = child.stderr.read() if child.stderr else ""
    child.wait(timeout=60)

    assert child.returncode == 0
    assert err == STDERR_LINE
