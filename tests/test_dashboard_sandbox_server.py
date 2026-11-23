"""The dashboard server names every Sandbox park the same way in the banner and the page script.

Every file is planted under ``tmp_path``; the labels come from ``park_label`` over the landing
files, never from the warehouse.
"""

from __future__ import annotations

import html
import http.client
import json
import os
import re
import threading
from collections.abc import Callable, Iterator
from datetime import timedelta, timezone, tzinfo
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import dashboard, dashboard_sandbox, park_label
from tests.dashboard_unfiled_support import PAGE, _board, _filed, _page
from tests.dashboard_unfiled_support import landing as landing  # noqa: F401  (pytest fixture)
from tests.test_dashboard import _project, _touch
from tests.test_dashboard_data import make_warehouse
from tests.test_dashboard_sandbox import ONLY_P1, R1
from tests.test_park_label import converted, raw

SCRIPT = "<script>window.DASHBOARD_LABELS"
ROWS: list[tuple[str, str, str | None, str]] = [
    ("s1", "a1", "Bumbly Bazaar", "2026-10-17T20:00:00Z"),
    ("s2", "a2", "Bumbly Bazaar", "2026-10-17T21:30:00Z"),
]
LABELS = {"s1": "Bumbly Bazaar (Oct 17, 12:00 pm)", "s2": "Bumbly Bazaar (Oct 17, 1:30 pm)"}
SENTENCE = (
    "Sandbox park {label} is left out of the All parks figures unless Sandbox parks are "
    "included; remove it with make delete-company-data PARK={park}."
)
FALLBACKS = {"s1": "s1 (first-played date unavailable)", "s2": "s2 (first-played date unavailable)"}
HINT = (
    "; the warehouse was built before Sandbox parks could be told apart: file the waiting "
    "play in the OpenRCT2 Enterprise app, or run make transform DATA_SET=company"
)


def _lines(page: str) -> list[str]:
    found = re.findall(r"<p style='margin:0.25em 0'>(.*?)</p>", page, flags=re.DOTALL)
    return [html.unescape(line) for line in found]


def _sandbox_lines(page: str) -> list[str]:
    return [line for line in _lines(page) if line.startswith("Sandbox park ")]


def _script_labels(page: str) -> dict[str, str]:
    """The object the served labels script assigns."""
    match = re.search(r"<script>window\.DASHBOARD_LABELS = (.*?);</script>", page)
    assert match is not None
    labels: dict[str, str] = json.loads(match.group(1))
    return labels


def _r1_board(
    tmp_path: Path,
    zone: Callable[[tzinfo], None],
    landing: LandingDirs,
    rows: list[tuple[str, str, str | None, str]] = ROWS,
    *,
    sandbox_name: str = "Bumbly Bazaar",
    sandbox_ids: tuple[str, str] = ("s1", "s2"),
) -> dashboard.Dashboard:
    """The R1 project (one company park, two Sandbox parks) with every session filed."""
    zone(timezone(timedelta(hours=-8)))
    parks = (("p1", "Alpha Park"), *((park, sandbox_name) for park in sandbox_ids))
    project = _project(tmp_path, parks=parks, notes=R1["notes"])
    _filed(project, *(session for _, session, _, _ in rows))
    converted(landing, rows)
    return _board(project)


def test_the_banner_and_the_data_name_the_same_sandbox_parks(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    board = _r1_board(tmp_path, fixed_local_zone, landing)

    page = _page(board)

    banner_ids = [re.search(r"PARK=(\S+)\.$", line) for line in _sandbox_lines(page)]
    assert all(banner_ids)
    assert board.current is not None
    text = (board.current.site / dashboard.DATA_FILE).read_text()
    figures = json.loads(text.removeprefix("window.DASHBOARD = ").removesuffix(";\n"))
    flagged = [park["id"] for park in figures["parks"] if park["sandbox"]]
    assert [m.group(1) for m in banner_ids if m] == flagged == ["s1", "s2"]


def test_the_labels_script_follows_the_banner(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    board = _r1_board(tmp_path, fixed_local_zone, landing)

    page = _page(board)

    assert page.index("role='status'") < page.index(SCRIPT)
    assert _script_labels(page) == LABELS
    assert _sandbox_lines(page) == [
        SENTENCE.format(label=LABELS["s1"], park="s1"),
        SENTENCE.format(label=LABELS["s2"], park="s2"),
    ]


def test_the_sandbox_sentences_follow_the_park_ids_not_the_build_order(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    # The data build lists parks by first company date, then ID: here s2 comes before s1.
    board = _r1_board(tmp_path, fixed_local_zone, landing, sandbox_ids=("s2", "s1"))

    page = _page(board)

    assert board.current is not None
    assert board.current.sandbox == ("s2", "s1")
    assert _sandbox_lines(page) == [
        SENTENCE.format(label=LABELS["s1"], park="s1"),
        SENTENCE.format(label=LABELS["s2"], park="s2"),
    ]
    assert list(_script_labels(page)) == ["s1", "s2"]


def test_a_park_name_cannot_close_the_labels_script(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    rows: list[tuple[str, str, str | None, str]] = [
        ("s1", "a1", "</script><b>x", "2026-10-17T20:00:00Z")
    ]
    board = _r1_board(tmp_path, fixed_local_zone, landing, rows, sandbox_name="</script><b>x")

    page = _page(board)

    assert "\\u003c/script>" in page
    start = page.index(SCRIPT)
    inside = page[start + len(SCRIPT) : page.index("</script>", start)]
    assert "<" not in inside
    assert _script_labels(page)["s1"] == "</script><b>x (first played Oct 17)"


def test_no_labels_script_without_a_sandbox_park(tmp_path: Path) -> None:
    board = _board(_project(tmp_path, **ONLY_P1))

    page = _page(board)

    assert "DASHBOARD_LABELS" not in page
    assert _sandbox_lines(page) == []


def test_a_new_session_updates_the_labels_without_a_rebuild(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    board = _r1_board(tmp_path, fixed_local_zone, landing)
    assert _script_labels(_page(board)) == LABELS
    built = board.current

    converted(landing, [*ROWS, ("s1", "a3", "Gamma Park", "2026-10-17T22:00:00Z")])

    page = _page(board)
    assert _script_labels(page) == {
        "s1": "Gamma Park (first played Oct 17)",
        "s2": "Bumbly Bazaar (first played Oct 17)",
    }
    assert board.current is built


def test_the_served_page_names_a_park_by_the_fallback_when_the_label_is_unavailable(
    tmp_path: Path,
    landing: LandingDirs,
    fixed_local_zone: Callable[[tzinfo], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _r1_board(tmp_path, fixed_local_zone, landing)
    calls: list[LandingDirs] = []

    def fail_the_read(landing_dirs: LandingDirs) -> object:
        calls.append(landing_dirs)
        raise OSError("planted")

    monkeypatch.setattr(park_label, "park_facts", fail_the_read)

    page = _page(board)

    assert len(calls) == 1

    assert _script_labels(page) == FALLBACKS
    assert _sandbox_lines(page) == [
        SENTENCE.format(label=FALLBACKS["s1"], park="s1"),
        SENTENCE.format(label=FALLBACKS["s2"], park="s2"),
    ]
    assert (
        "Park names could not be read: planted; Sandbox parks are shown by ID, "
        "first-played date unavailable." in _lines(page)
    )


def _without_park_number(path: Path) -> Path:
    """An old warehouse: ``dim_park`` has no ``park_number`` column."""
    with duckdb.connect(str(path)) as connection:
        connection.execute("alter table marts.dim_park drop column park_number")
    return path


def _banner_failure(page: str) -> str:
    (line,) = [line for line in _lines(page) if "the rebuild failed:" in line]
    return line


def test_a_warehouse_without_park_number_names_the_rebuild_step(tmp_path: Path) -> None:
    old = _without_park_number(make_warehouse(tmp_path / "old.duckdb", **R1))
    project = tmp_path / "project"
    dev = project / dashboard.DEV_WAREHOUSE
    dev.parent.mkdir(parents=True)

    # Cold start: no good build yet, so the page is a 503 holding the failure.
    os.replace(old, dev)
    board = _board(project)
    board.refresh()
    code, body = board.page(PAGE)
    cold = _banner_failure(body.decode())
    assert code == 503
    assert cold.startswith("Not updated: the rebuild failed: ")
    assert "park_number" in cold
    assert cold.endswith(HINT + ".")

    # A good build first, then the column-less warehouse swapped in: old figures, same line.
    os.replace(make_warehouse(tmp_path / "good.duckdb", **R1), dev)
    _touch(dev)
    board.refresh()
    good = board.current
    assert good is not None
    figures = (good.site / dashboard.DATA_FILE).read_text()
    assert board.problem is None
    os.replace(_without_park_number(make_warehouse(tmp_path / "old2.duckdb", **R1)), dev)
    _touch(dev)
    board.refresh()
    code, body = board.page(PAGE)
    kept = _banner_failure(body.decode())
    assert code == 200
    assert board.current is good
    assert (good.site / dashboard.DATA_FILE).read_text() == figures
    assert kept.startswith("The figures below are the last good build. Not updated: ")
    assert kept.endswith(HINT + ".")

    # A rebuilt warehouse with the column: new figures, no failure line.
    os.replace(make_warehouse(tmp_path / "new.duckdb", **R1), dev)
    _touch(dev)
    board.refresh()
    code, body = board.page(PAGE)
    assert code == 200
    assert board.current is not good
    assert "the rebuild failed" not in body.decode()
    assert board.problem is None


def test_another_rebuild_failure_carries_no_park_number_hint(tmp_path: Path) -> None:
    project = tmp_path / "project"
    dev = project / dashboard.DEV_WAREHOUSE
    dev.parent.mkdir(parents=True)
    make_warehouse(dev, **R1)
    with duckdb.connect(str(dev)) as connection:
        connection.execute("drop table marts.fct_ride_day")
    board = _board(project)

    board.refresh()
    code, body = board.page(PAGE)

    assert code == 503
    assert _banner_failure(body.decode()) == (
        "Not updated: the rebuild failed: Catalog Error: Table with name fct_ride_day does not "
        'exist!\nDid you mean "fct_park_day"?\n\nLINE 20:     from marts.fct_ride_day as '
        "ride_fact\n                  ^."
    )
    assert "the warehouse was built before Sandbox parks could be told apart" not in body.decode()


def test_label_of_park_gives_the_helper_label_or_the_fallback() -> None:
    assert dashboard_sandbox.label_of_park("s1", {"s1": "Bumbly Bazaar (first played Oct 17)"}) == (
        "Bumbly Bazaar (first played Oct 17)"
    )
    assert dashboard_sandbox.label_of_park("s2", {"s1": "x"}) == (
        "s2 (first-played date unavailable)"
    )


@pytest.mark.parametrize(
    "label",
    [
        pytest.param("s1", id="bare-id"),
        pytest.param("Bumbly Bazaar (s1)", id="name-and-id-no-time"),
    ],
)
def test_label_of_park_marks_a_label_with_no_first_played_date(label: str) -> None:
    assert dashboard_sandbox.label_of_park("s1", {"s1": label}) == (
        "s1 (first-played date unavailable)"
    )


def test_label_of_park_keeps_a_dated_label_that_ends_with_the_id() -> None:
    dated = "Bumbly Bazaar (Oct 17, 12:00 pm, s1)"

    assert dashboard_sandbox.label_of_park("s1", {"s1": dated}) == dated


def test_the_banner_and_script_mark_undated_sandbox_parks_and_keep_a_dated_one(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    # s1 has a start time (dated label); s2 has no start time, so park_label shows "<name> (s2)".
    rows: list[tuple[str, str, str | None, str]] = [
        ("s1", "a1", "Bumbly Bazaar", "2026-10-17T20:00:00Z")
    ]
    board = _r1_board(tmp_path, fixed_local_zone, landing, rows)
    raw(landing, "a2", "s2", "Zed Zoo", when=None)

    page = _page(board)

    assert _script_labels(page) == {
        "s1": "Bumbly Bazaar (first played Oct 17)",
        "s2": "s2 (first-played date unavailable)",
    }


def test_sandbox_sentences_name_each_park_with_its_label_and_delete_command() -> None:
    assert dashboard_sandbox.sandbox_sentences(["s1", "s2"], {"s1": "One (Oct 17)"}) == [
        "Sandbox park One (Oct 17) is left out of the All parks figures unless Sandbox parks are "
        "included; remove it with make delete-company-data PARK=s1.",
        "Sandbox park s2 (first-played date unavailable) is left out of the All parks figures "
        "unless Sandbox parks are included; remove it with make delete-company-data PARK=s2.",
    ]
    assert dashboard_sandbox.sandbox_sentences([], {"s1": "One"}) == []


def test_labels_script_escapes_every_angle_bracket() -> None:
    script = dashboard_sandbox.labels_script(["s1", "s2"], {"s1": "</script><b>x"})

    assert script == (
        '<script>window.DASHBOARD_LABELS = {"s1": "\\u003c/script>\\u003cb>x", '
        '"s2": "s2 (first-played date unavailable)"};</script>'
    )


def test_a_sandbox_refresh_reads_the_park_labels_once(
    tmp_path: Path,
    landing: LandingDirs,
    fixed_local_zone: Callable[[tzinfo], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _r1_board(tmp_path, fixed_local_zone, landing)
    real_facts = park_label.park_facts
    calls: list[LandingDirs] = []

    def counting(landing_dirs: LandingDirs) -> object:
        calls.append(landing_dirs)
        return real_facts(landing_dirs)

    monkeypatch.setattr(park_label, "park_facts", counting)

    page = _page(board)

    assert len(calls) == 1
    assert _script_labels(page) == LABELS


def _disagreeing_board(
    tmp_path: Path,
    landing: LandingDirs,
    zone: Callable[[tzinfo], None],
    change: str,
) -> dashboard.Dashboard:
    """The R1 project with one park's registry note and park number set against each other."""
    zone(timezone(timedelta(hours=-8)))
    project = _project(tmp_path, parks=R1["parks"], notes=R1["notes"])
    with duckdb.connect(str(project / dashboard.DEV_WAREHOUSE)) as connection:
        connection.execute(change)
    _filed(project, "a1", "a2")
    converted(landing, ROWS)
    return _board(project)


def test_the_banner_follows_the_data_build_not_the_registry_note(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    # s2 keeps the practice note but the build gives it a park number: not a Sandbox park.
    board = _disagreeing_board(
        tmp_path,
        landing,
        fixed_local_zone,
        "update marts.dim_park set park_number = 9 where park_id = 's2'",
    )

    page = _page(board)

    assert board.current is not None
    assert board.current.sandbox == ("s1",)
    assert _sandbox_lines(page) == [SENTENCE.format(label=LABELS["s1"], park="s1")]
    assert list(_script_labels(page)) == ["s1"]


def test_a_park_the_build_marks_sandbox_is_named_whatever_its_registry_note_says(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> None:
    # s1 has a null park number (Sandbox in the build) but its registry note is blank.
    board = _disagreeing_board(
        tmp_path,
        landing,
        fixed_local_zone,
        "update intermediate.int_park_registry__current set note = '' where park_id = 's1'",
    )

    page = _page(board)

    assert board.current is not None
    assert board.current.sandbox == ("s1", "s2")
    assert _sandbox_lines(page) == [
        SENTENCE.format(label=LABELS["s1"], park="s1"),
        SENTENCE.format(label=LABELS["s2"], park="s2"),
    ]


@pytest.fixture
def served_sandbox(
    tmp_path: Path, landing: LandingDirs, fixed_local_zone: Callable[[tzinfo], None]
) -> Iterator[str]:
    fixed_local_zone(timezone(timedelta(hours=-8)))
    project = _project(tmp_path, parks=R1["parks"], notes=R1["notes"])
    converted(landing, ROWS)
    server = dashboard.serve(project, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{dashboard.HOST}:{server.server_port}"
    server.shutdown()
    server.server_close()


def _raw_get(base: str, target: str) -> tuple[int, str]:
    """GET the request target as written, so no client rewrites its spelling."""
    connection = http.client.HTTPConnection(base.removeprefix("http://"), timeout=30)
    try:
        connection.request("GET", target)
        response = connection.getresponse()
        return response.status, response.read().decode()
    finally:
        connection.close()


def test_the_page_carries_the_labels_script_at_its_plain_path(served_sandbox: str) -> None:
    code, body = _raw_get(served_sandbox, "/executive.html")

    assert code == 200
    assert SCRIPT in body


def test_the_page_carries_the_labels_script_at_a_percent_encoded_path(
    served_sandbox: str,
) -> None:
    code, body = _raw_get(served_sandbox, "/%65xecutive.html")

    assert code == 200
    assert SCRIPT in body


def test_the_page_carries_the_labels_script_at_a_dot_segment_path(served_sandbox: str) -> None:
    code, body = _raw_get(served_sandbox, "/./executive.html")

    assert code == 200
    assert SCRIPT in body


def test_a_path_outside_the_app_folder_is_still_refused(served_sandbox: str) -> None:
    code, _ = _raw_get(served_sandbox, "/%2e%2e/%2e%2e/etc/passwd")

    assert code == 404
