"""Auto-file with two or more new parks in one play: the per-park question, order check, cancel.

Each case plants converted ``session_start`` and ``park_snapshot`` Parquet, starts from a valid
play and changes one thing. Expected texts are copied from the spec's R1, R3 and R11.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from openrct2_analytics.ingest import several_parks, start_year
from tests.auto_file_support import (
    NO_WAREHOUSE_LINE,
    Asked,
    Filed,
    _before,
    _register,
    _run,
    _sessions,
    _snapshots,
)
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _copy, _tree
from tests.test_play_status import _warehouse

TWO_PARKS = [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")]
ALPHA_DAYS = [(10, 8, 1), (10, 8, 2), (10, 8, 2), (10, 8, 3)]
OPTIONS_OF_TWO = "1. Opened first\n2. Opened second\n3. Sandbox\n"
ALPHA_ASKED = (
    "Park Alpha (first played Oct 1), 3 game days played, is new in this play. Which is it?\n"
    + OPTIONS_OF_TWO
)
BETA_ASKED = (
    "Park Beta (first played Oct 2), 0 game days played, is new in this play. Which is it?\n"
    + OPTIONS_OF_TWO
)
INTERRUPTED = "auto-file interrupted. Nothing was changed.\n"


class LoggedFiled(Filed):
    """``Filed`` that also appends ``file`` to the log the ``Asked`` fake writes to."""

    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self.log = log

    def __call__(
        self,
        argv: Sequence[str],
        *,
        project_dir: Path,
        registrations_landed: bool = False,
        registered: list[str] | None = None,
    ) -> int:
        self.log.append("file")
        return super().__call__(
            argv,
            project_dir=project_dir,
            registrations_landed=registrations_landed,
            registered=registered,
        )


def _refusal(park: str, given: str, actual: str, count_as: str = "company") -> str:
    return (
        f"auto-file refused: order: Park {park} was answered as opened {given}, but its first "
        f"recorded session is the {actual} of this play's new parks. Nothing was changed.\n"
        f"To file it, run: make auto-file DATA_SET=company COUNT_AS={count_as}\n"
    )


@pytest.mark.parametrize("count_as", ["company", "practice"])
def test_two_new_parks_are_each_asked_with_days_played(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], count_as: str
) -> None:
    _sessions(data, TWO_PARKS)
    _snapshots(data, {"park-a": ALPHA_DAYS})
    _before(tmp_path, [])
    log: list[str] = []
    filed = LoggedFiled(log)

    code, asked, _ = _run(tmp_path, count_as, asked=Asked(["1", "3"], log), filed=filed)

    assert code == 0
    assert asked.prompts == [ALPHA_ASKED, BETA_ASKED]
    # No filing before the last answer, and one call after it.
    assert log == ["ask", "ask", "file"]
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:company,park-b:practice"]]
    assert capsys.readouterr().out == (
        "auto-file: park Alpha (first played Oct 1) is new; registering it as company park, start "
        "year 2000.\n"
        "auto-file: park Beta (first played Oct 2) is new; registering it as a sandbox park.\n"
        + NO_WAREHOUSE_LINE
    )


def test_an_answer_outside_the_options_repeats_the_question(data: Path, tmp_path: Path) -> None:
    _sessions(data, TWO_PARKS)
    _snapshots(data, {"park-a": ALPHA_DAYS})
    _before(tmp_path, [])
    code, asked, filed = _run(tmp_path, "company", asked=Asked(["0", "4", "1", "3"]))
    assert code == 0
    assert asked.prompts == [ALPHA_ASKED, ALPHA_ASKED, ALPHA_ASKED, BETA_ASKED]
    assert len(filed.calls) == 1


def test_a_park_with_no_snapshot_day_shows_zero_game_days(data: Path, tmp_path: Path) -> None:
    _sessions(data, TWO_PARKS)
    _before(tmp_path, [])
    _, asked, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]))
    assert asked.prompts == [
        ALPHA_ASKED.replace("3 game days", "0 game days"),
        BETA_ASKED,
    ]


@pytest.mark.parametrize(
    "scenario",
    [
        # A swapped pair: the first-opened park answered second.
        (["2", "1"], _refusal("Alpha (first played Oct 1)", "second", "first")),
        # A repeated rank: both answered first.
        (["1", "1"], _refusal("Beta (first played Oct 2)", "first", "second")),
    ],
)
def test_order_answers_that_do_not_match_are_refused_before_writing(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[list[str], str],
) -> None:
    answers, refusal = scenario
    _sessions(data, TWO_PARKS)
    _snapshots(data, {"park-a": ALPHA_DAYS})
    _before(tmp_path, [])
    before = _tree(tmp_path)
    code, _, filed = _run(tmp_path, "company", asked=Asked(answers))
    assert code == 2
    assert filed.calls == []
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == refusal


THREE_PARKS = [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta"), ("s3", "park-c", "Gamma")]


@pytest.mark.parametrize(
    "scenario",
    [
        # Alpha is Sandbox, Beta opened second, Gamma is Sandbox: the Sandbox park holds rank 1.
        (["4", "2", "4"], None),
        # Beta answered first, but the Sandbox park Alpha was opened before it.
        (["4", "1", "4"], _refusal("Beta (first played Oct 2)", "first", "second")),
    ],
)
def test_a_sandbox_park_counts_in_the_ranking(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[list[str], str | None],
) -> None:
    answers, refusal = scenario
    _sessions(data, THREE_PARKS)
    _before(tmp_path, [])
    code, _, filed = _run(tmp_path, "company", asked=Asked(answers))
    out = capsys.readouterr().out
    if refusal is None:
        assert code == 0
        assert filed.calls == [
            ["--data-set", "company", "--parks", "park-a:practice,park-b:company,park-c:practice"]
        ]
    else:
        assert code == 2
        assert filed.calls == []
        assert out == refusal


@pytest.mark.parametrize(
    "scenario",
    [
        # Beta is asked first but was opened second; Alpha (Sandbox) was opened first.
        (["2", "3"], None),
        (["1", "3"], _refusal("Beta (first played Oct 2)", "first", "second")),
    ],
)
def test_the_order_follows_first_sessions_not_the_order_asked(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[list[str], str | None],
) -> None:
    answers, refusal = scenario
    # Alpha's first session s0 is already in the warehouse, so only its later session s3 waits and
    # Beta (s2) is asked first, although Alpha's first session is the earlier one.
    _sessions(
        data, [("s0", "park-a", "Alpha"), ("s2", "park-b", "Beta"), ("s3", "park-a", "Alpha")]
    )
    _warehouse(tmp_path, ["s0"])
    _before(tmp_path, ["s0"])
    code, asked, filed = _run(tmp_path, "company", asked=Asked(answers))
    assert asked.prompts[0].startswith("Park Beta (first played Oct 2)")
    if refusal is None:
        assert code == 0
        assert filed.calls == [
            ["--data-set", "company", "--parks", "park-b:company,park-a:practice"]
        ]
    else:
        assert code == 2
        assert filed.calls == []
        assert capsys.readouterr().out == refusal


@pytest.mark.parametrize(
    "scenario",
    [
        ([], KeyboardInterrupt()),
        ([], EOFError()),
        (["1"], KeyboardInterrupt()),
        (["1"], EOFError()),
    ],
)
def test_cancelling_at_a_per_park_question_changes_nothing(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[list[str], BaseException],
) -> None:
    answered, stop = scenario
    _sessions(data, TWO_PARKS)
    _snapshots(data, {"park-a": ALPHA_DAYS})
    _before(tmp_path, [])
    before = _tree(tmp_path)
    code, asked, filed = _run(tmp_path, "company", asked=Asked([*answered, stop]))
    assert code == 130
    assert len(asked.prompts) == len(answered) + 1
    assert filed.calls == []
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == INTERRUPTED


def test_one_company_and_one_sandbox_new_park_file_in_one_after_play_run(
    data: Path, tmp_path: Path
) -> None:
    _sessions(data, TWO_PARKS)
    _snapshots(data, {"park-a": ALPHA_DAYS})
    _before(tmp_path, [])
    log: list[str] = []
    filed = LoggedFiled(log)
    code, _, _ = _run(tmp_path, "company", asked=Asked(["3", "2"], log), filed=filed)
    assert code == 0
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:practice,park-b:company"]]
    assert log == ["ask", "ask", "file"]


def test_one_new_park_is_not_asked_per_park(data: Path, tmp_path: Path) -> None:
    _sessions(data, TWO_PARKS)
    _before(tmp_path, ["s1"])
    # park-a is from an earlier play: only its own (earlier-play) question is asked.
    code, asked, filed = _run(tmp_path, "practice", asked=Asked(["2"]))
    assert code == 0
    assert asked.prompts == [
        "Park Alpha (first played Oct 1) from an earlier play is waiting. Where should it count?\n"
        "1. Company\n2. Sandbox\n3. Don't file now\n"
    ]
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:practice,park-b:practice"]]


NO_TERMINAL = (
    "auto-file refused: no-terminal: A question is needed, but standard input is not a "
    "terminal. Nothing was changed.\n"
    "To file it, run: make auto-file DATA_SET=company COUNT_AS=company\n"
)


def test_two_new_parks_with_no_terminal_are_refused_before_any_question(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, TWO_PARKS)
    _before(tmp_path, [])
    before = _tree(tmp_path)
    code, asked, filed = _run(tmp_path, "company", terminal=False)
    assert code == 2
    assert asked.prompts == []
    assert filed.calls == []
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == NO_TERMINAL


def test_a_registered_sandbox_park_of_this_play_does_not_make_the_new_park_asked(
    data: Path, tmp_path: Path
) -> None:
    _sessions(data, [("s1", "park-r", "Rho"), ("s2", "park-n", "Nu")])
    _register(data, "park-r", practice=True)
    _before(tmp_path, [])
    code, asked, filed = _run(tmp_path, "practice")
    assert code == 0
    assert asked.prompts == []
    assert filed.calls == [["--data-set", "company", "--parks", "park-r:practice,park-n:practice"]]


@pytest.mark.parametrize(
    ("number", "word"),
    [
        (1, "first"),
        (10, "tenth"),
        (11, "11th"),
        (12, "12th"),
        (13, "13th"),
        (21, "21st"),
        (22, "22nd"),
        (23, "23rd"),
        (101, "101st"),
        (111, "111th"),
    ],
)
def test_ordinal_is_english_for_every_number(number: int, word: str) -> None:
    assert several_parks.ordinal(number) == word


def test_a_park_with_no_session_start_row_is_named_in_the_error(data: Path, tmp_path: Path) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    with pytest.raises(ValueError, match=r"^Park Ghost \(park-g\) has no session_start row"):
        several_parks.check_order(
            data / "company" / "parquet",
            {"park-a": 1, "park-g": 2},
            {"park-a": "Alpha (park-a)", "park-g": "Ghost (park-g)"},
        )


def test_a_missing_session_start_row_exits_1_through_the_error_path(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _sessions(data, TWO_PARKS)
    _before(tmp_path, [])
    first = start_year.first_sessions
    monkeypatch.setattr(
        start_year,
        "first_sessions",
        lambda starts: [row for row in first(starts) if row[0] != "park-b"],
    )
    code, _, filed = _run(tmp_path, "company", asked=Asked(["1", "2"]))
    assert code == 1
    assert filed.calls == []
    assert capsys.readouterr().out == (
        "auto-file failed: io: Park Beta (park-b) has no session_start row to order it by\n"
    )


def test_three_same_named_new_parks_are_told_apart(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Two twins first played on Oct 1 at different times, the third on Oct 2 (local zone is UTC).
    starts = [
        ("s1", "park-a", 1, "10:00"),
        ("s2", "park-b", 1, "15:42"),
        ("s3", "park-c", 2, "10:00"),
    ]
    query = " UNION ALL ".join(
        f"SELECT '{session}' AS session_id, '{park}' AS park_id, 'Twin' AS park_name, "
        f"1 AS game_year, TIMESTAMPTZ '2026-10-{day:02} {clock}:00+00' "
        f"AS emitted_at"
        for session, park, day, clock in starts
    )
    _copy(data / "company" / "parquet" / "v1" / "session_start.parquet", query)
    _before(tmp_path, [])
    code, asked, filed = _run(tmp_path, "company", asked=Asked(["4", "4", "4"]))
    options = "1. Opened first\n2. Opened second\n3. Opened third\n4. Sandbox\n"
    labels = ["Twin (Oct 1, 10:00 am)", "Twin (Oct 1, 3:42 pm)", "Twin (first played Oct 2)"]
    assert code == 0
    assert asked.prompts == [
        f"Park {label}, 0 game days played, is new in this play. Which is it?\n{options}"
        for label in labels
    ]
    assert filed.calls == [
        ["--data-set", "company", "--parks", "park-a:practice,park-b:practice,park-c:practice"]
    ]
    assert capsys.readouterr().out == (
        "auto-file: park Twin (Oct 1, 10:00 am) is new; registering it as a sandbox park.\n"
        "auto-file: park Twin (Oct 1, 3:42 pm) is new; registering it as a sandbox park.\n"
        "auto-file: park Twin (first played Oct 2) is new; registering it as a sandbox park.\n"
    )
