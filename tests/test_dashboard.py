"""The local company dashboard: rebuild on page load, banner, the five pages and the server."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Unpack

import duckdb
import pytest

from openrct2_analytics.ingest import capture_session, dashboard, register_parks
from tests.test_dashboard_data import Options, make_warehouse

BANNER = "Local dashboard from the working copy (warehouse/dev/dev.duckdb)"
SMOKE = dashboard.PROJECT_DIR / "tests" / "dashboard_smoke.mjs"
APP = dashboard.PROJECT_DIR / "src" / "openrct2_analytics" / "dashboard" / "app"


def _project(tmp_path: Path, **warehouse: Unpack[Options]) -> Path:
    """A project whose development warehouse is the fixture warehouse."""
    project = tmp_path / "project"
    dev = project / dashboard.DEV_WAREHOUSE
    dev.parent.mkdir(parents=True)
    make_warehouse(dev, **warehouse)
    return project


def _touch(path: Path) -> None:
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def _ready(tmp_path: Path, **warehouse: Unpack[Options]) -> dashboard.Dashboard:
    board = dashboard.Dashboard(_project(tmp_path, **warehouse))
    board.start()
    return board


def test_a_data_set_other_than_company_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert dashboard.main(["--data-set", "rehearsal"], project_dir=tmp_path) == 2
    assert capsys.readouterr().out == (
        "dashboard refused: the dashboard shows company data only, not rehearsal. "
        "Nothing was changed.\n"
    )
    assert not (tmp_path / "local").exists()


def test_every_page_shows_the_banner_right_after_body(tmp_path: Path) -> None:
    board = _ready(tmp_path)
    board.refresh()

    for name in dashboard.PAGES:
        code, body = board.page(name)
        page = body.decode()
        assert code == 200, (name, board.problem)
        assert BANNER in page, name
        assert page.index("role='status'") > page.index("<body"), name
        assert page.count("role='status'") == 1, name
    assert board.current is not None
    assert not (board.current.folder / "warehouse.duckdb").exists()


def test_the_data_file_holds_the_figures_and_their_time(tmp_path: Path) -> None:
    board = _ready(tmp_path)
    board.refresh()
    assert board.current is not None

    text = (board.current.site / dashboard.DATA_FILE).read_text()

    prefix = "window.DASHBOARD = "
    assert text.startswith(prefix) and text.endswith(";\n")
    figures = json.loads(text[len(prefix) : -2])
    assert figures["as_of"] == board.current.source_time.strftime("%Y-%m-%d %H:%M")
    assert figures["parks"] == [
        {
            "id": "p1",
            "name": "Alpha Park",
            "sandbox": False,
            "game_years": {
                "2001": {"game_year": 1, "from_month": 3},
                "2002": {"game_year": 2, "from_month": 3},
            },
        }
    ]
    assert len(figures["scopes"]["all"]["months"]) == 16


def test_an_unchanged_warehouse_is_not_rebuilt_and_a_changed_one_is(tmp_path: Path) -> None:
    board = _ready(tmp_path)
    board.refresh()
    first = board.current
    board.refresh()
    assert board.current is first

    _touch(board.project / dashboard.DEV_WAREHOUSE)
    board.refresh()

    assert first is not None and board.current is not first
    assert not first.folder.exists()
    assert len(list(board.root.glob("build-*"))) == 1


def test_a_failed_rebuild_keeps_the_last_build_and_names_the_failure(tmp_path: Path) -> None:
    board = _ready(tmp_path)
    board.refresh()
    good = board.current
    warehouse = board.project / dashboard.DEV_WAREHOUSE
    connection = duckdb.connect(str(warehouse))
    connection.execute("drop table marts.fct_ride_day")
    connection.close()
    _touch(warehouse)

    board.refresh()
    board.refresh()

    assert board.current is good
    code, body = board.page("finance.html")
    page = body.decode()
    assert code == 200
    assert (
        "The figures below are the last good build. Not updated: the rebuild failed: "
        "Catalog Error: Table with name fct_ride_day does not exist!"
    ) in page
    assert len(list(board.root.glob("build-*"))) == 1


def test_a_warehouse_being_written_is_not_copied(tmp_path: Path) -> None:
    board = _ready(tmp_path)
    wal = board.project / "warehouse" / "dev" / "dev.duckdb.wal"
    wal.write_text("")

    board.refresh()

    assert board.current is None
    assert list(board.root.glob("build-*")) == []
    code, body = board.page("executive.html")
    assert code == 503
    assert "warehouse/dev/dev.duckdb is being built" in body.decode()
    wal.unlink()
    board.refresh()
    assert board.current is not None and board.problem is None


def test_a_missing_warehouse_names_the_command(tmp_path: Path) -> None:
    board = _ready(tmp_path)
    (board.project / dashboard.DEV_WAREHOUSE).unlink()

    board.refresh()

    assert board.current is None
    assert (
        "Not updated: warehouse/dev/dev.duckdb is missing; run make after-play DATA_SET=company."
        in board.page("executive.html")[1].decode()
    )


@pytest.mark.parametrize("practice", [True, False])
def test_a_practice_park_is_named_only_when_present(tmp_path: Path, practice: bool) -> None:
    notes = ("", register_parks.NOTE if practice else "")
    board = _ready(tmp_path, parks=(("p1", "Alpha Park"), ("p2", "Beta Park")), notes=notes)
    board.refresh()

    page = board.page("executive.html")[1].decode()

    warning = (
        "Sandbox park p2 (first-played date unavailable) is left out of the All parks figures "
        "unless Sandbox parks are included; remove it with make delete-company-data PARK=p2."
    )
    assert (warning in page) is practice


@pytest.mark.parametrize("data_set", ["rehearsal", "company"])
def test_another_data_set_is_named_only_when_present(tmp_path: Path, data_set: str) -> None:
    board = _ready(tmp_path, data_set=data_set)
    board.refresh()

    page = board.page("executive.html")[1].decode()

    warning = "data, not only company data;"
    assert (warning in page) is (data_set == "rehearsal")


def _smoke(
    tmp_path: Path, park: str | None = None, reduced: bool = False, **warehouse: Unpack[Options]
) -> dict[str, dict[str, Any]]:
    """Run the five pages' scripts over the fixture's data file and return what they say."""
    board = _ready(tmp_path, **warehouse)
    board.refresh()
    assert board.current is not None, board.problem
    site = board.current.site
    result = subprocess.run(
        ["node", str(SMOKE), str(site), str(site / dashboard.DATA_FILE)]
        + (["--reduced"] if reduced else [])
        + ([f"--park={park}"] if park else []),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def test_the_pages_compare_years_when_there_are_several(tmp_path: Path) -> None:
    pages = _smoke(tmp_path)

    assert pages["executive"]["finding"].startswith(
        "2002 closed with $1.8K operating profit, 50% more than 2001."
    )
    assert "There is no earlier year to compare." not in pages["executive"]["text"]


def test_the_pages_render_one_year_and_say_there_is_no_comparison(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, years=(2001,))

    assert sorted(pages) == ["attractions", "executive", "finance", "operations", "pricing"]
    assert "There is no earlier year to compare." in pages["executive"]["finding"]
    assert (
        "was the first season, so there is no year before it to compare"
        in (pages["executive"]["text"])
    )


TWO_PARKS: Options = {
    "parks": (("p1", "Alpha Park"), ("p2", "Beta Park")),
    "game_years": ((1, 2), (None, 7)),
    "starts": (3, 6),
}


def test_one_chosen_park_names_its_game_year_without_a_prefix(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, park="p2", **TWO_PARKS)

    assert pages["executive"]["opened_note"] == "Company year 2002 = game year 7"


def test_an_unknown_park_shows_every_park_in_the_note(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, park="nope", **TWO_PARKS)

    assert pages["executive"]["opened_note"] == (
        "Alpha Park: Company year 2002 = game year 2\nBeta Park: Company year 2002 = game year 7"
    )


def test_every_park_is_named_in_the_note_when_none_is_chosen(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, **TWO_PARKS)

    assert pages["executive"]["opened_note"] == (
        "Alpha Park: Company year 2002 = game year 2\nBeta Park: Company year 2002 = game year 7"
    )


def test_the_note_follows_the_chosen_year_and_leaves_a_closed_park_blank(tmp_path: Path) -> None:
    note = _smoke(tmp_path, **TWO_PARKS)["executive"]["year_note"]

    assert note == "Alpha Park: Company year 2001 = game year 1\nBeta Park:"
    assert "game year 0" not in note
    assert "\u2013" not in note


def test_one_chosen_park_names_the_chosen_earlier_year(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, park="p1", **TWO_PARKS)

    assert pages["executive"]["year_note"] == "Company year 2001 = game year 1"


def test_a_shown_month_with_no_mapping_leaves_the_one_park_note_blank(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, game_years=((None, 2),))

    assert pages["executive"]["year_note"] == ""
    assert pages["executive"]["opened_note"] == "Company year 2002 = game year 2"


def test_the_note_keeps_one_line_per_park(tmp_path: Path) -> None:
    page = (APP / "executive.html").read_text()
    note = _smoke(tmp_path, **TWO_PARKS)["executive"]["year_note"]

    assert 'id="gameYears" style="white-space:pre-line"' in page
    assert note.split("\n") == ["Alpha Park: Company year 2001 = game year 1", "Beta Park:"]


def test_the_pages_see_reduced_motion_when_the_flag_is_given(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, reduced=True)

    assert sorted(pages) == ["attractions", "executive", "finance", "operations", "pricing"]
    assert [page["reduced_motion"] for page in pages.values()] == [True] * 5


def test_the_pages_do_not_see_reduced_motion_without_the_flag(tmp_path: Path) -> None:
    pages = _smoke(tmp_path)

    assert [page["reduced_motion"] for page in pages.values()] == [False] * 5


def test_the_note_follows_the_shown_month(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, **TWO_PARKS)

    assert (
        pages["executive"]["month_note"]
        == "Alpha Park: Company year 2002 = game year 2\nBeta Park:"
    )


def test_the_only_park_names_its_game_year_without_a_prefix(tmp_path: Path) -> None:
    pages = _smoke(tmp_path, years=(2001,))

    assert pages["executive"]["opened_note"] == "Company year 2001 = game year 1"


def test_the_note_element_is_in_the_executive_page_once() -> None:
    page = (APP / "executive.html").read_text()

    assert page.count('id="gameYears"') == 1


@pytest.fixture
def served(tmp_path: Path) -> Iterator[str]:
    server = dashboard.serve(_project(tmp_path), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{dashboard.HOST}:{server.server_port}"
    server.shutdown()
    server.server_close()


def _get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_the_server_answers_the_ping_every_page_and_the_data(served: str) -> None:
    assert _get(served + dashboard.PING_PATH) == (200, dashboard.PING_BODY)
    for path in ("/", *(f"/{page}" for page in dashboard.PAGES)):
        code, body = _get(served + path)
        assert code == 200, path
        assert BANNER.encode() in body, path
    assert _get(served + "/")[1] == _get(served + "/executive.html")[1]
    for path in ("/data.js", "/app.css", "/shared.js"):
        assert _get(served + path)[0] == 200, path
    assert _get(served + "/data.js")[1].startswith(b"window.DASHBOARD = ")
    assert _get(served + "/warehouse.duckdb")[0] == 404


def test_a_busy_port_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as busy:
        busy.bind((dashboard.HOST, 0))
        busy.listen()
        port = busy.getsockname()[1]
        code = dashboard.main(
            ["--data-set", "company", "--port", str(port)], project_dir=_project(tmp_path)
        )
    assert code == 2
    assert capsys.readouterr().out == (
        f"dashboard refused: port {port} is in use; is the dashboard already running?. "
        "Nothing was changed.\n"
    )


def _never_bind(project: Path, port: int) -> dashboard._Server:
    raise AssertionError(f"the dashboard tried to bind port {port}")


def test_the_dashboard_never_takes_the_port_the_plugin_sends_to(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The network is the external here: a failed refusal must not hold the real recorder port.
    monkeypatch.setattr(dashboard, "serve", _never_bind)
    launcher = (dashboard.PROJECT_DIR / "launcher" / "play-company.command").read_text()

    assert dashboard.DEFAULT_PORT != capture_session.PLUGIN_PORT == 8765
    assert f"dashboard_port={dashboard.DEFAULT_PORT}\n" in launcher
    code = dashboard.main(["--data-set", "company", "--port", "8765"], project_dir=tmp_path)
    assert code == 2
    assert capsys.readouterr().out == (
        "dashboard refused: port 8765 belongs to the game's recorder; use another port. "
        "Nothing was changed.\n"
    )
    assert not (tmp_path / "local").exists()


def _start_server(project: Path, *extra: str) -> tuple[subprocess.Popen[str], str]:
    """Start the dashboard as a real process on a free port; return it and its address."""
    code = (
        "import sys; from pathlib import Path; from openrct2_analytics.ingest import dashboard; "
        "sys.exit(dashboard.main(['--data-set', 'company', '--port', '0', *sys.argv[2:]], "
        "project_dir=Path(sys.argv[1])))"
    )
    env = {**os.environ, "PYTHONPATH": str(dashboard.PROJECT_DIR / "src")}
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(project), *extra],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    assert line.startswith("dashboard: serving "), line
    return process, line.split("serving ")[1].strip().rstrip("/")


@pytest.mark.parametrize(("extra", "survives"), [(("--detach",), True), ((), False)])
def test_only_a_detached_server_outlives_a_hangup(
    tmp_path: Path, extra: tuple[str, ...], survives: bool
) -> None:
    process, address = _start_server(tmp_path, *extra)
    try:
        process.send_signal(signal.SIGHUP)
        if survives:
            assert _get(address + dashboard.PING_PATH) == (200, dashboard.PING_BODY)
            assert process.poll() is None
        else:
            assert process.wait(timeout=10) == -signal.SIGHUP
    finally:
        process.kill()
        process.wait()


def test_a_refused_second_server_leaves_the_running_one_intact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    server = dashboard.serve(project, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://{dashboard.HOST}:{server.server_port}"
    try:
        assert _get(address + "/")[0] == 200
        built = list((project / dashboard.ROOT).glob("build-*"))

        code = dashboard.main(
            ["--data-set", "company", "--port", str(server.server_port)], project_dir=project
        )

        assert code == 2
        assert "is in use" in capsys.readouterr().out
        assert built and all(folder.is_dir() for folder in built)
        assert _get(address + "/")[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_the_launcher_starts_a_detached_server() -> None:
    launcher = (dashboard.PROJECT_DIR / "launcher" / "play-company.command").read_text()

    assert "DASHBOARD_DETACH=1" in launcher
