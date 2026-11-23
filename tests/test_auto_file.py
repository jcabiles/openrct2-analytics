"""Real Parquet and registry coverage for auto-file; after-play is a recording fake.

Each case starts from one waiting park per session, written as converted ``session_start``
Parquet, and changes one thing. Expected texts are copied from the spec's requirements R3 to R8.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openrct2_analytics.ingest import (
    after_play,
    auto_file,
    capture_session,
    lock,
    park_label,
    play_status,
)
from openrct2_analytics.ingest.convert import landing_lock_path
from tests.auto_file_support import (
    BEFORE,
    NO_WAREHOUSE_LINE,
    Asked,
    Filed,
    Registers,
    _before,
    _register,
    _run,
    _sessions,
)
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _tree
from tests.test_register_parks_start_year import park_one, plant

EARLIER_A = (
    "Park Alpha (first played Oct 1) from an earlier play is waiting. Where should it count?\n"
    "1. Company\n2. Sandbox\n3. Don't file now\n"
)
NOT_NOW_A = (
    "auto-file refused: not-now: Don't file now was chosen for park Alpha (first played Oct 1). "
    "Nothing was changed.\n"
)
RERUN_COMPANY = "To file it, run: make auto-file DATA_SET=company COUNT_AS=company\n"
MISSING = (
    "auto-file: local/auto-file/converted-before.json is missing, so no park counts as this "
    "play's; every unregistered park is asked about.\n"
)

N3_NO_WAREHOUSE = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown (warehouse/dev/dev.duckdb does not exist).\n"
)


def test_record_writes_the_sorted_converted_session_ids(data: Path, tmp_path: Path) -> None:
    _sessions(data, [("s2", "park-b", "Beta"), ("s1", "park-a", "Alpha"), ("s2", "park-c", "C")])
    _before(tmp_path, ["old"])
    code = auto_file.main(["--data-set", "company", "--record"], project_dir=tmp_path)
    assert code == 0
    assert json.loads((tmp_path / BEFORE).read_text(encoding="utf-8")) == ["s1", "s2"]


def test_record_also_lists_raw_sessions_never_converted(data: Path, tmp_path: Path) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    raw = data / "company" / "raw" / "v1"
    raw.mkdir(parents=True)
    (raw / "events-2026-11-14.jsonl").write_text(
        '{"session_id": "s1"}\n{"session_id": "s0"}\nnot json\n\n', encoding="utf-8"
    )
    assert auto_file.main(["--data-set", "company", "--record"], project_dir=tmp_path) == 0
    assert json.loads((tmp_path / BEFORE).read_text(encoding="utf-8")) == ["s0", "s1"]


def test_a_stopped_capture_converted_by_this_play_is_asked_about(
    data: Path, tmp_path: Path
) -> None:
    raw = data / "company" / "raw" / "v1"
    raw.mkdir(parents=True)
    (raw / "events-2026-11-14.jsonl").write_text('{"session_id": "s1"}\n', encoding="utf-8")
    assert auto_file.main(["--data-set", "company", "--record"], project_dir=tmp_path) == 0
    _sessions(data, [("s1", "park-a", "Alpha")])

    code, asked, filed = _run(tmp_path, "company", asked=Asked(["3"]))

    assert code == 2
    assert asked.prompts == [EARLIER_A]
    assert filed.calls == []


def test_earlier_play_question_names_the_first_played_day(data: Path, tmp_path: Path) -> None:
    _sessions(data, [("s0", "park-z", "Zed"), ("s1", "park-a", "Alpha")])
    _register(data, "park-z", practice=False)
    _before(tmp_path, ["s0", "s1"])

    code, asked, _ = _run(tmp_path, "company", asked=Asked(["3"]))

    assert code == 2
    assert asked.prompts == [
        "Park Alpha (first played Oct 2) from an earlier play is waiting. Where should it count?\n"
        "1. Company\n2. Sandbox\n3. Don't file now\n"
    ]


def test_park_label_read_error_stops_before_any_registration(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    raw = data / "company" / "raw" / "v1"
    raw.mkdir(parents=True)
    (raw / "events-2026-10-01.jsonl").write_bytes(b"\xff\n")
    registers = Registers()
    code, asked, filed = _run(tmp_path, "company", register=registers)

    assert code == 1
    assert capsys.readouterr().out == (
        "auto-file failed: io: 'utf-8' codec can't decode byte 0xff in position 0: "
        "invalid start byte\n"
    )
    assert (asked.prompts, filed.calls, registers.calls) == ([], [], [])


def test_park_label_read_hitting_an_unreadable_parquet_stops_before_any_registration(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    starts = data / "company" / "parquet" / "v1" / "session_start.parquet"
    status_read = after_play.check_can_start

    def spoil_after_the_status_read(data_set: str, project_dir: Path) -> play_status.PlayStatus:
        status = status_read(data_set, project_dir)
        starts.write_bytes(b"not a parquet file")
        return status

    monkeypatch.setattr(after_play, "check_can_start", spoil_after_the_status_read)
    registers = Registers()
    code, asked, filed = _run(tmp_path, "company", register=registers)

    assert code == 1
    assert capsys.readouterr().out.startswith("auto-file failed: io: ")
    assert (asked.prompts, filed.calls, registers.calls) == ([], [], [])


def test_the_converted_names_are_read_once(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sessions(data, [("s0", "park-z", "Zed"), ("s1", "park-a", "Alpha")])
    _register(data, "park-z", practice=False)
    _before(tmp_path, ["s0", "s1"])
    reads: list[Path] = []
    real = park_label.park_names

    def counted(parquet_dir: Path) -> dict[str, str | None]:
        reads.append(parquet_dir)
        return real(parquet_dir)

    monkeypatch.setattr(park_label, "park_names", counted)

    code, _, _ = _run(tmp_path, "company", asked=Asked(["3"]))

    assert code == 2
    assert len(reads) == 1


def test_record_with_nothing_converted_writes_an_empty_list(data: Path, tmp_path: Path) -> None:
    assert auto_file.main(["--data-set", "company", "--record"], project_dir=tmp_path) == 0
    assert json.loads((tmp_path / BEFORE).read_text(encoding="utf-8")) == []


@pytest.mark.parametrize(
    "args",
    [
        ["--data-set", "rehearsal", "--count-as", "company"],
        ["--data-set", "company"],
        ["--data-set", "company", "--record", "--count-as", "company"],
        ["--data-set", "company", "--count-as", "maybe"],
    ],
)
def test_bad_arguments_are_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], args: list[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    before = _tree(tmp_path)
    filed = Filed()
    assert auto_file.main(args, project_dir=tmp_path, file_with=filed) == 2
    assert _tree(tmp_path) == before
    assert filed.calls == []
    assert capsys.readouterr().out.startswith("auto-file refused: ")


def test_nothing_waiting(data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, asked, filed = _run(tmp_path, "company")
    assert code == 0
    assert capsys.readouterr().out == "auto-file: nothing is waiting to be filed.\n"
    assert asked.prompts == []
    assert filed.calls == []


@pytest.mark.parametrize(
    "scenario",
    [("company", "company park, start year 2000"), ("practice", "a sandbox park")],
)
def test_this_play_only_takes_count_as(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], scenario: tuple[str, str]
) -> None:
    count_as, shown = scenario
    _sessions(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    code, asked, filed = _run(tmp_path, count_as)
    assert code == 0
    assert asked.prompts == []
    # The first company park gets no --start-year.
    assert filed.calls == [["--data-set", "company", "--parks", f"park-a:{count_as}"]]
    assert capsys.readouterr().out == (
        f"auto-file: park Alpha (first played Oct 1) is new; registering it as {shown}.\n"
        + (NO_WAREHOUSE_LINE if count_as == "company" else "")
    )


@pytest.mark.parametrize("code", [0, 2])
def test_the_one_park_path_never_reports_landed_registrations(
    data: Path, tmp_path: Path, code: int
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])

    result, _, filed = _run(tmp_path, "company", filed=Filed(code))

    assert result == code
    assert filed.landed == [False]


def test_an_older_park_is_asked_and_an_invalid_answer_repeats(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s1"])
    log: list[str] = []
    monkeypatch.setattr(capture_session, "discard_typed_input", lambda: log.append("discard"))
    code, asked, filed = _run(tmp_path, "company", asked=Asked(["9", "2"], log))
    assert code == 0
    assert asked.prompts == [EARLIER_A, EARLIER_A]
    assert log == ["discard", "ask", "ask"]
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:practice,park-b:company"]]


@pytest.mark.parametrize("older", ["s1", "s2"])
def test_a_park_in_an_older_and_a_new_session_is_classified_once(
    data: Path, tmp_path: Path, older: str
) -> None:
    # Either session may come first in play_status order; the park is this play's either way.
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-a", "Alpha")])
    _before(tmp_path, [older])
    code, asked, filed = _run(tmp_path, "practice")
    assert code == 0
    assert asked.prompts == []
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:practice"]]


@pytest.mark.parametrize(
    "scenario",
    [
        (
            True,
            "company",
            "Park Alpha (first played Oct 1) is saved as Sandbox, but this play was started as "
            "Company.\n"
            "1. File it as Sandbox\n2. Don't file now\n",
        ),
        (
            False,
            "practice",
            "Park Alpha (first played Oct 1) is saved as Company, but this play was started as "
            "Sandbox.\n"
            "1. File it as Company\n2. Don't file now\n",
        ),
    ],
)
def test_conflict_answered_1_files_the_saved_choice(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[bool, str, str],
) -> None:
    saved_practice, count_as, prompt = scenario
    _sessions(data, [("s1", "park-a", "Alpha")])
    _register(data, "park-a", practice=saved_practice)
    _before(tmp_path, [])
    code, asked, filed = _run(tmp_path, count_as, asked=Asked(["1"]))
    assert code == 0
    assert asked.prompts == [prompt]
    saved = "practice" if saved_practice else "company"
    assert filed.calls == [["--data-set", "company", "--parks", f"park-a:{saved}"]]
    assert "is new" not in capsys.readouterr().out


def test_conflict_answered_2_files_nothing(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _register(data, "park-a", practice=True)
    _before(tmp_path, [])
    before = _tree(tmp_path)
    code, _, filed = _run(tmp_path, "company", asked=Asked(["2"]))
    assert code == 2
    assert filed.calls == []
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == NOT_NOW_A + RERUN_COMPANY


def test_a_registered_older_park_keeps_its_registration_unasked(data: Path, tmp_path: Path) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _register(data, "park-a", practice=True)
    _before(tmp_path, ["s1"])
    code, asked, filed = _run(tmp_path, "company")
    assert code == 0
    assert asked.prompts == []
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:practice,park-b:company"]]


def test_dont_file_now(data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s1"])
    before = _tree(tmp_path)
    code, asked, filed = _run(tmp_path, "company", asked=Asked(["3"]))
    assert code == 2
    assert asked.prompts == [EARLIER_A]
    assert filed.calls == []
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == NOT_NOW_A + RERUN_COMPANY


def test_a_second_company_park_is_given_its_start_year(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Park 1 is the registered company park; Park 2's session s2 is this play's.
    plant(data, park_one())
    _before(tmp_path, ["s1"])
    code, asked, filed = _run(tmp_path, "company")
    assert code == 0
    assert asked.prompts == []
    assert filed.calls == [
        [
            "--data-set",
            "company",
            "--parks",
            "park-1:company,park-2:company",
            "--start-year",
            "2001",
        ]
    ]
    assert capsys.readouterr().out == (
        "auto-file: park park-2 (first played Nov 12) is new; registering it as company park, "
        "start year 2001.\n" + NO_WAREHOUSE_LINE + N3_NO_WAREHOUSE
    )


def test_a_sandbox_park_after_a_company_park_gets_no_start_year(data: Path, tmp_path: Path) -> None:
    plant(data, park_one())
    _before(tmp_path, ["s1"])
    code, _, filed = _run(tmp_path, "practice")
    assert code == 0
    assert filed.calls == [["--data-set", "company", "--parks", "park-1:company,park-2:practice"]]


def test_r7_lines_name_each_park_about_to_be_registered(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s1"])
    code, _, _ = _run(tmp_path, "company", asked=Asked(["2"]))
    assert code == 0
    assert capsys.readouterr().out == (
        "auto-file: park Alpha (first played Oct 1) is new; registering it as a sandbox park.\n"
        "auto-file: park Beta (first played Oct 2) is new; registering it as company park, start "
        "year 2000.\n" + NO_WAREHOUSE_LINE
    )


def test_missing_before_file_asks_every_unregistered_park(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    code, asked, filed = _run(tmp_path, "practice", asked=Asked(["1"]))
    assert code == 0
    assert asked.prompts == [EARLIER_A]
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:company"]]
    assert capsys.readouterr().out.startswith(MISSING)


def test_unreadable_before_file_asks_every_unregistered_park(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    (tmp_path / BEFORE).parent.mkdir(parents=True)
    (tmp_path / BEFORE).write_text('{"s1": 1}', encoding="utf-8")
    code, asked, _ = _run(tmp_path, "practice", asked=Asked(["1"]))
    assert code == 0
    assert asked.prompts == [EARLIER_A]
    assert capsys.readouterr().out.startswith(
        "auto-file: local/auto-file/converted-before.json cannot be read (it is not a list of "
        "session IDs), so no park counts as this play's; every unregistered park is asked about.\n"
    )


def test_no_terminal_refuses_before_any_question(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s1"])
    before = _tree(tmp_path)
    code, asked, filed = _run(tmp_path, "company", terminal=False)
    assert code == 2
    assert asked.prompts == []
    assert filed.calls == []
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == (
        "auto-file refused: no-terminal: A question is needed, but standard input is not a "
        "terminal. Nothing was changed.\n" + RERUN_COMPANY
    )


def test_no_terminal_is_fine_when_no_question_is_needed(data: Path, tmp_path: Path) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    code, _, filed = _run(tmp_path, "company", terminal=False)
    assert code == 0
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:company"]]


@pytest.mark.parametrize("stop", [KeyboardInterrupt(), EOFError()])
def test_ctrl_c_or_end_of_input_changes_nothing(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], stop: BaseException
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s1"])
    before = _tree(tmp_path)
    code, _, filed = _run(tmp_path, "company", asked=Asked([stop]))
    assert code == 130
    assert filed.calls == []
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == "auto-file interrupted. Nothing was changed.\n"


def test_held_landing_lock_is_refused_before_any_question(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s1"])
    with lock.hold_lock(landing_lock_path(data / "company" / "parquet"), "test holder"):
        before = _tree(tmp_path)
        code, asked, filed = _run(tmp_path, "company", asked=Asked(["1"]))
        assert _tree(tmp_path) == before
    assert code == 2
    assert asked.prompts == []
    assert filed.calls == []
    assert capsys.readouterr().out.startswith("auto-file refused: lock-taken: ")


@pytest.mark.parametrize(("after_play_code", "kept"), [(1, True), (2, True), (0, False)])
def test_before_file_is_kept_after_a_failed_filing_and_removed_after_success(
    data: Path, tmp_path: Path, after_play_code: int, kept: bool
) -> None:
    _sessions(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    code, _, _ = _run(tmp_path, "company", filed=Filed(after_play_code))
    assert code == after_play_code
    assert (tmp_path / BEFORE).exists() is kept


def test_an_unconverted_raw_file_refuses_before_filing_and_keeps_the_before_file(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, park_one())
    _before(tmp_path, ["s1"])
    raw = data / "company" / "raw" / "v1"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "events-2026-11-15.jsonl").write_text('{"session_id": "s9"}\n', encoding="utf-8")

    code, asked, filed = _run(tmp_path, "company")

    assert code == 2
    assert asked.prompts == []
    assert filed.calls == []
    assert (tmp_path / BEFORE).is_file()
    assert capsys.readouterr().out == (
        "auto-file refused: not-converted: events-2026-11-15.jsonl holds a session that was "
        "never converted, so the latest managed year is unknown; run make convert "
        "DATA_SET=company first. Nothing was changed.\n"
    )
