"""Guards of the several-park chain that no other test pins: each case fails if its guard goes.

Covers the free-name refusal, a park that leaves the waiting list during the answers, the refusal
text when no park was shown, the printed lines of a Sandbox park on the chain, which answers are
stored and when the answers file is removed, a registered park that starts before 2000, a
``ConfigError`` after a landing and the singular game day. Expected texts are copied from the
spec's R4.2, R6, R7 and R8.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import auto_file
from tests.auto_file_support import (
    FIRST,
    SECOND,
    Asked,
    Filed,
    Registers,
    _before,
    _deliveries,
    _feed,
    _filed,
    _new,
    _run,
    _snapshots,
    _world,
)
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _tree
from tests.test_auto_file_answers import (
    ALPHA_LINE,
    ALPHA_SANDBOX_LINE,
    BETA_SANDBOX_LINE,
    RERUN,
    Registering,
    _registry,
    _two_new_parks,
)
from tests.test_auto_file_several_parks import ALPHA_ASKED
from tests.test_play_status import _warehouse
from tests.test_register_parks import _delivery
from tests.test_register_parks_start_year import World, plant

ANSWERS = Path("local") / "auto-file" / "answers.json"
THROWAWAY = "Throwaway practice park; not company data."


def test_exactly_one_free_delivery_name_refuses_two_company_parks(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    today = datetime.now(UTC).date().isoformat()
    for number in range(1, 99):
        _delivery(_feed(data), f"park_registry_{today}_{number:02}.csv", "other")
    before = _tree(tmp_path)
    registers = Registers()

    code, _, filed = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=registers)

    assert code == 2
    assert capsys.readouterr().out == (
        f"auto-file refused: no-free-name: Only 1 delivery names for {today} are free; need 2. "
        "Nothing was changed.\n"
    )
    assert registers.calls == []
    assert filed.calls == []
    assert len(_deliveries(data)) == 98
    assert not (tmp_path / ANSWERS).exists()
    assert _tree(tmp_path) == before


class LeavesTheList(Asked):
    """``Asked`` whose dev warehouse gains the first park's session after the last answer."""

    def __init__(self, answers: list[str], project: Path) -> None:
        super().__init__(answers)
        self.project = project

    def __call__(self, prompt: str) -> str:
        reply = super().__call__(prompt)
        if not self.answers:
            _warehouse(self.project, ["s1"])
        return reply


def test_a_park_removed_from_the_waiting_list_after_the_last_answer_is_refused(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    registers = Registers()

    code, _, filed = _run(
        tmp_path, "company", asked=LeavesTheList(["1", "2"], tmp_path), register=registers
    )

    assert code == 2
    assert capsys.readouterr().out == (
        "auto-file refused: waiting-list: the waiting parks changed while you were answering "
        f"(added: none; removed: {FIRST}). Nothing was changed.\n"
    )
    assert registers.calls == []
    assert filed.calls == []
    assert not _feed(data).exists()
    assert not (tmp_path / ANSWERS).exists()


def test_a_refusal_before_any_park_is_shown_reads_no_registry(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", "")

    code = auto_file.main(
        ["--data-set", "rehearsal", "--count-as", "company"],
        project_dir=tmp_path,
        ask=Asked(),
        file_with=Filed(),
        is_terminal=lambda: True,
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == (
        "auto-file refused: data-set: auto-file files company plays only; got rehearsal. "
        "Nothing was changed.\n"
    )
    assert "Traceback" not in captured.out + captured.err


def test_a_sandbox_park_opened_first_and_two_company_parks_print_their_lines(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    world: World = {
        "sessions": [
            ("park-a", "s1", (1, 0, 1), 0),
            ("park-b", "s2", (1, 0, 1), 1),
            ("park-c", "s3", (1, 0, 1), 2),
        ],
        "days": [],
        "saves": [],
        "registry": [],
        "labels": [],
    }
    plant(data, world)
    _before(tmp_path, [])
    registers = Registers()

    code, _, filed = _run(tmp_path, "company", asked=Asked(["4", "2", "3"]), register=registers)

    assert code == 0
    assert capsys.readouterr().out == (
        "auto-file: park park-a (first played Nov 12) is new; registering it as a sandbox park.\n"
        "auto-file: park park-b (first played Nov 12) is new; registering it as company park, "
        "start year 2000.\n"
        "auto-file: park park-c (first played Nov 12) is new; registering it as company park, "
        "start year 2001.\n"
        "auto-file: the play is filed, but the park number could not be shown "
        "(no warehouse file).\n"
        "auto-file: the play is filed, but the note about the previous company park could not be "
        "shown (warehouse/dev/dev.duckdb does not exist).\n"
    )
    assert registers.calls == [
        ({"park-a": True}, None),
        ({"park-b": False}, None),
        ({"park-c": False}, 2001),
    ]
    assert _deliveries(data) == [
        [("park-a", "2000", "1", THROWAWAY)],
        [("park-b", "2000", "1", "")],
        [("park-c", "2001", "1", "")],
    ]
    assert filed.landed == [True]


BUSY = "after-play refused: warehouse-busy: Another command is writing warehouse/dev/dev.duckdb."
REFUSED = BUSY + " Nothing was changed.\n"
EARLIER_E = (
    "Park park-e (first played Nov 12) from an earlier play is waiting. Where should it count?\n"
    "1. Company\n2. Sandbox\n3. Don't file now\n"
)
SANDBOX_E = (
    "auto-file: park park-e (first played Nov 12) is new; registering it as a sandbox park.\n"
)
SANDBOX_N = (
    "auto-file: park park-n (first played Nov 12) is new; registering it as a sandbox park.\n"
)
COMPANY_N = (
    "auto-file: park park-n (first played Nov 12) is new; registering it as company park, start "
    "year 2001.\n"
)
REGISTERED = ("park-0", 2000, 1, "company", "", "2026-11-12")
CONFIG_ERROR = ConfigError("Two landing folders are one folder")


def _earlier_world(data: Path, tmp_path: Path) -> None:
    """Park-0 is registered, park-e waits from an earlier play, park-n is this play's new park."""
    sessions = [("park-0", "s0", (1, 0, 1), 0), ("park-e", "se", (1, 0, 1), 1)]
    sessions.append(("park-n", "sn", (1, 0, 1), 2))
    days = [("park-0", "s0", 2, (1, 0, 2))]
    saves = [("park-0", "s0", 3, (1, 0, 2))]
    plant(
        data,
        {
            "sessions": sessions,
            "days": days,
            "saves": saves,
            "registry": [REGISTERED],
            "labels": [],
        },
    )
    _before(tmp_path, ["s0", "se"])


def test_a_rerun_after_a_refusal_that_landed_nothing_files_the_new_park_as_count_as(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _earlier_world(data, tmp_path)
    code, _, _ = _run(
        tmp_path,
        "company",
        asked=Asked(["2"]),
        filed=Registering(2, prints=REFUSED[:-1], only=set()),
    )
    assert code == 2
    assert capsys.readouterr().out == SANDBOX_E + COMPANY_N + REFUSED
    assert not (tmp_path / ANSWERS).exists()

    # The rerun starts as Sandbox: the new park takes it, and the earlier park is asked again.
    code, asked, _ = _run(tmp_path, "practice", asked=Asked(["2"]), filed=Registering(0))

    assert code == 0
    assert asked.prompts == [EARLIER_E]
    assert capsys.readouterr().out == SANDBOX_E + SANDBOX_N
    assert _deliveries(data)[1:] == [
        [("park-e", "2000", "1", THROWAWAY), ("park-n", "2000", "1", THROWAWAY)]
    ]


def test_a_refused_answer_is_asked_again_on_the_rerun(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _two_new_parks(data, tmp_path)
    refusal = "after-play refused: start-year-origin: it broke. Nothing was changed."
    refused = Registering(2, prints=refusal, only=set())
    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]), filed=refused)
    assert code == 2
    assert capsys.readouterr().out == ALPHA_LINE + BETA_SANDBOX_LINE + refusal + "\n"
    assert not (tmp_path / ANSWERS).exists()

    # The player answers the other way round; no stored answer is left to win.
    code, asked, filed = _run(tmp_path, "company", asked=Asked(["3", "2"]))

    assert code == 0
    assert len(asked.prompts) == 2
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:practice,park-b:company"]]
    assert capsys.readouterr().out == (
        ALPHA_SANDBOX_LINE
        + "auto-file: park Beta (first played Oct 2) is new; registering it as company park, "
        "start year 2000.\n"
        "auto-file: the play is filed, but the park number could not be shown "
        "(no warehouse file).\n"
    )


def test_only_answers_to_questions_are_stored_and_kept_after_a_landing(
    data: Path, tmp_path: Path
) -> None:
    _earlier_world(data, tmp_path)

    code, _, _ = _run(
        tmp_path, "company", asked=Asked(["2"]), filed=Registering(1, only={"park-n"})
    )

    assert code == 1
    # park-0 (a kept registration) and park-n (taken from COUNT_AS) were not asked about.
    stored = json.loads((tmp_path / ANSWERS).read_text(encoding="utf-8"))
    assert stored == {"park-e": "practice"}
    assert set(_registry(tmp_path)) == {"park-0", "park-n"}


def test_an_unreadable_answers_file_asks_about_the_one_park_left(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sessions = [("park-0", "s0", (1, 0, 1), 0), ("park-n", "sn", (1, 0, 1), 2)]
    plant(
        data,
        {"sessions": sessions, "days": [], "saves": [], "registry": [REGISTERED], "labels": []},
    )
    _before(tmp_path, ["s0"])
    (tmp_path / ANSWERS).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / ANSWERS).write_text("{not json", encoding="utf-8")

    code, asked, filed = _run(tmp_path, "company", asked=Asked(["2"]))

    assert code == 0
    assert asked.prompts == [EARLIER_E.replace("park-e", "park-n")]
    assert capsys.readouterr().out == (
        "auto-file: answers.json could not be read; asking again.\n" + SANDBOX_N
    )
    assert filed.calls == [["--data-set", "company", "--parks", "park-0:company,park-n:practice"]]


@pytest.mark.parametrize("landed", [True, False])
def test_a_config_error_reports_what_landed(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], landed: bool
) -> None:
    plant(data, _world())
    _before(tmp_path, [])
    # The landing paths are read again for each registration, so the error can come on the second
    # one, after the first park landed, or on the first one, before anything landed.
    registers = Registers(park=SECOND if landed else FIRST, raises=CONFIG_ERROR)

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=registers)

    out = capsys.readouterr().out
    if landed:
        failed = f"auto-file failed: data-set: {CONFIG_ERROR}.\n"
        assert (code, out) == (
            1,
            _new(FIRST, 2000) + _new(SECOND, 2002) + failed + _filed((FIRST, 2000)) + RERUN,
        )
        assert set(_registry(tmp_path)) == {FIRST}
    else:
        refused = f"auto-file refused: data-set: {CONFIG_ERROR}. Nothing was changed.\n"
        assert (code, out) == (2, _new(FIRST, 2000) + _new(SECOND, 2002) + refused)
        assert not _deliveries(data)


@pytest.mark.parametrize("registered", [True, False])
def test_a_company_park_after_a_registered_one_takes_its_year_even_when_it_is_2000(
    data: Path, tmp_path: Path, registered: bool
) -> None:
    sessions = [("park-a", "sa", (1, 0, 1), 1), ("park-b", "sb", (1, 0, 1), 2)]
    registry = []
    if registered:
        # Registered at 1999 with no managed day, park-0 plans park-a for 2000, not 2001.
        sessions.insert(0, ("park-0", "s0", (1, 0, 1), 0))
        registry = [("park-0", 1999, 1, "company", "", "2026-11-12")]
    plant(data, {"sessions": sessions, "days": [], "saves": [], "registry": registry, "labels": []})
    _before(tmp_path, ["s0"])
    registers = Registers()

    code, _, _ = _run(tmp_path, "company", asked=Asked(["1", "2"]), register=registers)

    assert code == 0
    assert registers.calls == [
        ({"park-a": False}, 2000 if registered else None),
        ({"park-b": False}, 2001),
    ]
    assert _deliveries(data)[-2:] == [[("park-a", "2000", "1", "")], [("park-b", "2001", "1", "")]]


def test_one_game_day_is_worded_in_the_singular(data: Path, tmp_path: Path) -> None:
    _two_new_parks(data, tmp_path)
    _snapshots(data, {"park-a": [(10, 8, 1)]})

    code, asked, _ = _run(tmp_path, "company", asked=Asked(["1", "3"]))

    assert code == 0
    assert asked.prompts[0] == ALPHA_ASKED.replace("3 game days", "1 game day")
