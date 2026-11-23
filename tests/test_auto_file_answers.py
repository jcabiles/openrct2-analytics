"""Auto-file on today's path: stored answers, the already-filed report, the extra caught errors.

The ``Registering`` fake really registers the parks it is given through ``register_parks.register``
(a plain recording fake writes no registry row, so it can never show a landed park), then fails as
told. Each case starts from one valid play and changes one thing. Expected texts are copied from
the spec's R7, R8 and R10.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics.ingest import auto_file, lock, play_status, register_parks
from openrct2_analytics.ingest.auto_file_state import write_json
from tests.auto_file_support import (
    NO_WAREHOUSE_LINE,
    Asked,
    Filed,
    _before,
    _register,
    _run,
    _sessions,
)
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _copy
from tests.test_auto_file_several_parks import ALPHA_ASKED, BETA_ASKED, TWO_PARKS
from tests.test_play_status import _warehouse

ANSWERS = Path("local") / "auto-file" / "answers.json"
ALPHA_LINE = (
    "auto-file: park Alpha (first played Oct 1) is new; registering it as company park, start year "
    "2000.\n"
)
BETA_SANDBOX_LINE = (
    "auto-file: park Beta (first played Oct 2) is new; registering it as a sandbox park.\n"
)
ALPHA_SANDBOX_LINE = (
    "auto-file: park Alpha (first played Oct 1) is new; registering it as a sandbox park.\n"
)
BOTH_FILED = (
    "auto-file: already registered by this run: park Alpha (first played Oct 1) as company park, "
    "start year 2000; park Beta (first played Oct 2) as a sandbox park.\n"
)
RERUN = (
    "To file the rest, run: make auto-file DATA_SET=company COUNT_AS=company "
    "(run it here; the launcher starts a new play)\n"
)
AFTER_PLAY_STOPPED = "auto-file: after-play stopped, and these parks are already registered.\n"
LOCK_TEXT = "landing.lock is held ('pid 1'); see ARCHITECTURE.md \"Stale locks\""
# Kept here because one test patches the module attribute the fake would otherwise call.
REAL_REGISTERED_PARKS = register_parks.registered_parks
BAD_BYTE = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
BAD_BYTE_TEXT = "'utf-8' codec can't decode byte 0xff in position 0: invalid start byte"


class Registering(Filed):
    """The ``file_with`` seam that registers the listed waiting parks for real, then fails.

    ``only`` limits the parks it registers; ``then`` is raised after registering; ``prints`` is a
    line after-play would print; ``code`` is the exit code returned when nothing is raised.
    """

    def __init__(
        self,
        code: int = 0,
        *,
        then: BaseException | None = None,
        prints: str = "",
        only: set[str] | None = None,
    ) -> None:
        super().__init__(code)
        self.then = then
        self.prints = prints
        self.only = only

    def __call__(
        self,
        argv: Sequence[str],
        *,
        project_dir: Path,
        registrations_landed: bool = False,
        registered: list[str] | None = None,
    ) -> int:
        self.calls.append(list(argv))
        options = dict(zip(argv[::2], argv[1::2], strict=True))
        listed = register_parks.parse_parks(options["--parks"])
        held = REAL_REGISTERED_PARKS(play_status.registry_feed_dir("company", project_dir))
        pending = {
            park: flag
            for park, flag in listed.items()
            if park not in held and (self.only is None or park in self.only)
        }
        if pending:
            year = int(options["--start-year"]) if "--start-year" in options else None
            register_parks.register(
                project_dir, datetime.now(UTC).date(), False, parks=pending, start_year=year
            )
            if registered is not None:
                registered.extend(pending)
        if self.prints:
            print(self.prints)
        if self.then is not None:
            raise self.then
        return self.code


def _plant(data: Path, rows: list[tuple[str, str, str]]) -> None:
    """Write converted session_start rows and the matching seq audit, so parks can register."""
    _sessions(data, rows)
    query = " UNION ALL ".join(
        f"SELECT '{park}' AS park_id, '{session}' AS session_id, 1 AS park_count, 0 AS missing, "
        "0 AS duplicates, 1 AS first_seq, 1 AS last_seq, 1 AS row_count"
        for session, park, _ in rows
    )
    _copy(data / "company" / "parquet" / "audit" / "seq_audit.parquet", query)


def _feed(tmp_path: Path) -> Path:
    return play_status.registry_feed_dir("company", tmp_path)


def _registry(tmp_path: Path) -> dict[str, tuple[str, bool]]:
    return register_parks.registered_parks(_feed(tmp_path))


def _stored(tmp_path: Path) -> dict[str, str]:
    result: dict[str, str] = json.loads((tmp_path / ANSWERS).read_text(encoding="utf-8"))
    return result


def _plant_answers(tmp_path: Path, text: str) -> None:
    (tmp_path / ANSWERS).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ANSWERS).write_text(text, encoding="utf-8")


def _two_new_parks(data: Path, tmp_path: Path) -> None:
    _plant(data, TWO_PARKS)
    _before(tmp_path, [])


@pytest.mark.parametrize(
    "scenario",
    [
        (
            Registering(then=OSError("boom")),
            "auto-file failed: io: boom.\n" + BOTH_FILED + RERUN,
            1,
        ),
        (
            Registering(then=KeyboardInterrupt()),
            "auto-file interrupted.\n" + BOTH_FILED + RERUN,
            130,
        ),
        (Registering(1), AFTER_PLAY_STOPPED + BOTH_FILED + RERUN, 1),
        (
            Registering(2, prints="after-play refused: contracts: it broke"),
            "after-play refused: contracts: it broke\n" + AFTER_PLAY_STOPPED + BOTH_FILED + RERUN,
            1,
        ),
        (
            Registering(then=lock.LockTaken(Path("landing.lock"), "pid 1")),
            f"auto-file failed: lock-taken: {LOCK_TEXT}.\n" + BOTH_FILED + RERUN,
            1,
        ),
        (
            Registering(then=register_parks.CheckFailed("bad row")),
            "auto-file failed: check-failed: bad row.\n" + BOTH_FILED + RERUN,
            1,
        ),
    ],
    ids=["oserror", "interrupt", "exit-1", "exit-2", "lock-taken", "check-failed"],
)
def test_a_failure_after_the_first_registration_names_the_filed_parks(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[Registering, str, int],
) -> None:
    fake, report, expected = scenario
    _two_new_parks(data, tmp_path)
    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=fake)
    out = capsys.readouterr().out
    assert code == expected
    assert out == ALPHA_LINE + BETA_SANDBOX_LINE + report
    assert "Nothing was changed" not in out
    assert _registry(tmp_path) == {"park-a": ("company", False), "park-b": ("company", True)}


@pytest.mark.parametrize(
    "scenario",
    [
        (
            lock.LockTaken(Path("landing.lock"), "pid 1"),
            f"auto-file refused: lock-taken: {LOCK_TEXT}. Nothing was changed.\n",
            2,
        ),
        (
            register_parks.CheckFailed("bad row"),
            "auto-file failed: check-failed: bad row\n",
            1,
        ),
        (csv.Error("bad csv"), "auto-file failed: io: bad csv\n", 1),
        (BAD_BYTE, f"auto-file failed: io: {BAD_BYTE_TEXT}\n", 1),
        (OSError("disk full"), "auto-file failed: io: disk full\n", 1),
        (KeyboardInterrupt(), "auto-file interrupted. Nothing was changed.\n", 130),
    ],
    ids=["lock-taken", "check-failed", "csv-error", "unicode", "oserror", "interrupt"],
)
def test_an_error_before_any_park_landed_keeps_the_plain_text(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[BaseException, str, int],
) -> None:
    error, text, expected = scenario
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    fake = Registering(then=error, only=set())
    code, _, _ = _run(tmp_path, "company", filed=fake)
    assert code == expected
    assert capsys.readouterr().out == ALPHA_LINE + text
    assert _registry(tmp_path) == {}


@pytest.mark.parametrize(
    "scenario",
    [
        (OSError("boom"), "auto-file failed: io: boom.\n", 1),
        (KeyboardInterrupt(), "auto-file interrupted.\n", 130),
    ],
    ids=["oserror", "interrupt"],
)
def test_the_failure_read_falls_back_when_the_registry_cannot_be_read(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[BaseException, str, int],
) -> None:
    error, first, expected = scenario
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    fake = Registering(then=error, only=set())

    def read(feed: Path) -> dict[str, tuple[str, bool]]:
        # The reads before the call (the start of the run) work; the read after the failure breaks.
        if fake.calls:
            raise register_parks.Refused("registry-feed", "the registry feed is broken")
        return REAL_REGISTERED_PARKS(feed)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(register_parks, "registered_parks", read)
        code, _, _ = _run(tmp_path, "company", filed=fake)
    out = capsys.readouterr().out
    assert code == expected
    assert out == (
        ALPHA_LINE
        + first
        + "auto-file: could not read the registry; run make auto-file DATA_SET=company "
        "COUNT_AS=company and it will report what is registered\n"
        "auto-file: it was registering: park Alpha (first played Oct 1) as company park, start "
        "year 2000.\n"
    )
    assert "Nothing was changed" not in out


def test_a_mixed_play_failing_after_registration_reruns_without_a_conflict_question(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_new_parks(data, tmp_path)
    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=Registering(1))
    assert code == 1
    assert capsys.readouterr().out == (
        ALPHA_LINE + BETA_SANDBOX_LINE + AFTER_PLAY_STOPPED + BOTH_FILED + RERUN
    )
    assert _stored(tmp_path) == {"park-a": "company", "park-b": "practice"}
    deliveries = sorted(_feed(tmp_path).glob("park_registry_*.csv"))

    code, asked, filed = _run(tmp_path, "company", filed=Registering())

    assert code == 0
    assert asked.prompts == []
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:company,park-b:practice"]]
    assert capsys.readouterr().out == ""
    assert sorted(_feed(tmp_path).glob("park_registry_*.csv")) == deliveries
    assert not (tmp_path / ANSWERS).exists()


def test_rerun_keeps_a_stored_sandbox_choice_without_a_conflict_question(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_new_parks(data, tmp_path)
    # Alpha is answered Sandbox and registers; Beta (answered Opened second) is not registered.
    first = Registering(then=OSError("park 2 failed"), only={"park-a"})
    code, _, _ = _run(tmp_path, "company", asked=Asked(["3", "2"]), filed=first)
    assert code == 1
    assert capsys.readouterr().out == (
        ALPHA_SANDBOX_LINE
        + "auto-file: park Beta (first played Oct 2) is new; registering it as company park, "
        "start year 2000.\n"
        "auto-file failed: io: park 2 failed.\n"
        "auto-file: already registered by this run: park Alpha (first played Oct 1) as a sandbox "
        "park.\n" + RERUN
    )
    assert _registry(tmp_path) == {"park-a": ("company", True)}

    code, asked, filed = _run(tmp_path, "company", filed=Registering())

    assert code == 0
    assert asked.prompts == []
    assert filed.calls == [
        [
            "--data-set",
            "company",
            "--parks",
            "park-a:practice,park-b:company",
        ]
    ]
    assert _registry(tmp_path) == {"park-a": ("company", True), "park-b": ("company", False)}


def test_an_unreadable_answers_file_is_ignored_with_one_line(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, TWO_PARKS)
    _before(tmp_path, [])
    _plant_answers(tmp_path, "{not json")
    code, asked, filed = _run(tmp_path, "company", asked=Asked(["1", "3"]))
    assert code == 0
    assert asked.prompts == [ALPHA_ASKED.replace("3 game days", "0 game days"), BETA_ASKED]
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:company,park-b:practice"]]
    assert capsys.readouterr().out == (
        "auto-file: answers.json could not be read; asking again.\n"
        + ALPHA_LINE
        + BETA_SANDBOX_LINE
        + NO_WAREHOUSE_LINE
    )


def test_a_run_that_asked_no_per_park_question_writes_no_answers_file(
    data: Path, tmp_path: Path
) -> None:
    _plant(data, [("s1", "park-a", "Alpha")])
    _before(tmp_path, [])
    code, asked, filed = _run(tmp_path, "company", filed=Filed(1))
    assert code == 1
    assert asked.prompts == []
    assert len(filed.calls) == 1
    assert not (tmp_path / ANSWERS).exists()


def _exit_0(data: Path, tmp_path: Path) -> int:
    _plant(data, TWO_PARKS)
    _before(tmp_path, [])
    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]))
    return code


def _nothing_waiting(data: Path, tmp_path: Path) -> int:
    _plant(data, [("s1", "park-a", "Alpha")])
    _warehouse(tmp_path, ["s1"])
    _plant_answers(tmp_path, json.dumps({"park-a": "company"}))
    code, _, _ = _run(tmp_path, "company")
    return code


def _record(data: Path, tmp_path: Path) -> int:
    _plant_answers(tmp_path, json.dumps({"park-a": "company"}))
    return auto_file.main(["--data-set", "company", "--record"], project_dir=tmp_path)


@pytest.mark.parametrize("path", [_exit_0, _nothing_waiting, _record])
def test_answers_file_is_removed_after_success_and_by_record(
    data: Path, tmp_path: Path, path: object
) -> None:
    assert path(data, tmp_path) == 0  # type: ignore[operator]
    assert not (tmp_path / ANSWERS).exists()


def test_answers_file_is_removed_after_an_after_play_refusal_that_changed_nothing(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_new_parks(data, tmp_path)
    refusal = "after-play refused: contracts: it broke. Nothing was changed."
    fake = Registering(2, prints=refusal, only=set())
    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=fake)
    assert code == 2
    assert capsys.readouterr().out == ALPHA_LINE + BETA_SANDBOX_LINE + refusal + "\n"
    # Nothing landed, so the rerun asks again (a deliberate change from keeping the answers).
    assert not (tmp_path / ANSWERS).exists()


def test_the_answers_file_is_written_through_a_rename(tmp_path: Path) -> None:
    _plant_answers(tmp_path, '{"park-a": "company"}\n')
    target = tmp_path / ANSWERS

    def broken(self: Path, destination: Path) -> Path:
        raise OSError("disk full")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "replace", broken)
        with pytest.raises(OSError, match="disk full"):
            write_json(target, {"park-a": "practice"})

    assert target.read_text(encoding="utf-8") == '{"park-a": "company"}\n'

    write_json(target, {"park-a": "practice"})

    assert target.read_text(encoding="utf-8") == '{"park-a": "practice"}\n'
    assert sorted(path.name for path in target.parent.iterdir()) == ["answers.json"]


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
    ids=["sandbox-registered-company-stored", "company-registered-sandbox-stored"],
)
def test_a_stored_answer_unequal_to_the_registration_still_asks_the_conflict(
    data: Path, tmp_path: Path, scenario: tuple[bool, str, str]
) -> None:
    registered_practice, count_as, prompt = scenario
    _plant(data, [("s1", "park-a", "Alpha")])
    _register(data, "park-a", practice=registered_practice)
    _before(tmp_path, [])
    # The stored answer is the one the registration does not hold.
    _plant_answers(
        tmp_path, json.dumps({"park-a": "company" if registered_practice else "practice"})
    )

    code, asked, filed = _run(tmp_path, count_as, asked=Asked(["1"]))

    assert code == 0
    assert asked.prompts == [prompt]
    kept = "practice" if registered_practice else "company"
    assert filed.calls == [["--data-set", "company", "--parks", f"park-a:{kept}"]]


def test_a_second_interrupt_while_the_end_lines_print_exits_130_without_a_traceback(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_new_parks(data, tmp_path)
    real_print = print

    def interrupted(*args: object, **kwargs: object) -> None:
        if args and str(args[0]).startswith("auto-file: after-play stopped"):
            raise KeyboardInterrupt
        real_print(*args, **kwargs)  # type: ignore[call-overload]

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(auto_file, "print", interrupted, raising=False)
        code, _, _ = _run(
            tmp_path,
            "company",
            asked=Asked(["1", "3"]),
            filed=Registering(1),
        )

    captured = capsys.readouterr()
    assert code == 130
    assert captured.out == ALPHA_LINE + BETA_SANDBOX_LINE + AFTER_PLAY_STOPPED[:0]
    assert "Traceback" not in captured.out + captured.err
    assert _registry(tmp_path) == {"park-a": ("company", False), "park-b": ("company", True)}
