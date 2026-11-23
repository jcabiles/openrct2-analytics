"""Auto-file after an autopilot year while an earlier park is also waiting (spec R10).

Each case starts from the same planted play: ``park-b`` is the autopilot park (a registered
company park holding the one session missing from the record file) and ``park-a`` is an earlier
park whose session was recorded before the play. Each case changes one thing, the earlier park's
registration or the answer. Expected texts are copied from ``auto_file.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openrct2_analytics.ingest import register_parks
from openrct2_analytics.ingest import registry_feed as feed_module
from tests.auto_file_support import NO_WAREHOUSE_LINE, Asked, _before, _register, _run, _sessions
from tests.auto_file_support import data as data  # noqa: F401  (pytest fixture)
from tests.test_after_play import _tree
from tests.test_auto_file import EARLIER_A, NOT_NOW_A, RERUN_COMPANY


def _plant(data: Path, tmp_path: Path, *, earlier_registered: bool) -> None:
    """Plant the earlier park and the autopilot park; the earlier one is a sandbox park if filed."""
    _sessions(data, [("s1", "park-a", "Alpha"), ("s2", "park-b", "Beta")])
    _before(tmp_path, ["s1"])
    if earlier_registered:
        feed = data / "company" / "registry" / "v1"
        feed.mkdir(parents=True)
        header = ",".join(feed_module.HEADER)
        (feed / "park_registry_2026-10-18_01.csv").write_text(
            f"{header}\npark-a,2000,3,company,{register_parks.NOTE},2026-10-18\n"
            "park-b,2000,3,company,,2026-10-18\n",
            encoding="utf-8",
        )
    else:
        _register(data, "park-b", practice=False)


def test_a_registered_earlier_park_is_not_asked_and_both_keep_their_registration(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, tmp_path, earlier_registered=True)
    code, asked, filed = _run(tmp_path, "company")
    assert code == 0
    assert asked.prompts == []
    assert filed.calls == [["--data-set", "company", "--parks", "park-a:practice,park-b:company"]]
    assert capsys.readouterr().out == ""


N3_NO_WAREHOUSE = (
    "auto-file: the play is filed, but the note about the previous company park could not be "
    "shown (warehouse/dev/dev.duckdb does not exist).\n"
)


@pytest.mark.parametrize(
    "scenario",
    [
        ("1", "company", "company park, start year 2001", ["--start-year", "2001"]),
        ("2", "practice", "a sandbox park", []),
    ],
)
def test_an_unregistered_earlier_park_is_filed_with_its_answer(
    data: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    scenario: tuple[str, str, str, list[str]],
) -> None:
    answer, shown_as, line, year = scenario
    _plant(data, tmp_path, earlier_registered=False)
    code, asked, filed = _run(tmp_path, "company", asked=Asked([answer]))
    assert code == 0
    assert asked.prompts == [EARLIER_A]
    assert filed.calls == [
        ["--data-set", "company", "--parks", f"park-a:{shown_as},park-b:company", *year]
    ]
    assert (
        capsys.readouterr().out
        == f"auto-file: park Alpha (first played Oct 1) is new; registering it as {line}.\n"
        + (NO_WAREHOUSE_LINE + N3_NO_WAREHOUSE if answer == "1" else "")
    )


def test_dont_file_now_for_the_earlier_park_files_nothing_not_even_the_autopilot_park(
    data: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _plant(data, tmp_path, earlier_registered=False)
    before = _tree(tmp_path)
    code, asked, filed = _run(tmp_path, "company", asked=Asked(["3"]))
    assert code == 2
    assert asked.prompts == [EARLIER_A]
    assert filed.calls == []
    assert _tree(tmp_path) == before
    assert capsys.readouterr().out == NOT_NOW_A + RERUN_COMPANY
