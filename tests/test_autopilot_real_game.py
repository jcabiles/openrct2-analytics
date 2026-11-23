"""The autopilot year on the real game, run by hand (spec section 8, "Real game, by hand").

Skipped unless ``OPENRCT2_AUTOPILOT_REAL_GAME=1``; ``make check`` never starts the game. It needs
the benchmark settings (``OPENRCT2_BINARY``, ``OPENRCT2_GAME_PATH``, ``OPENRCT2_BENCH_PARK``,
the benchmark fixture that starts on 6 March of game year 9), found without exports from the
settings file and the game's own ``config.ini`` (read before the user folder is swapped); every
folder it writes is under pytest's temporary folder, and the player's OpenRCT2 folder is
replaced by a temporary one.

Step 1 lands a managed session: it plays a copy of the fixture to 1 March of game year 10 with
the save watcher, lands the capture into temporary company folders and runs the convert, report
and backup that ``make play`` runs after a quit. Step 2 registers that park as company, plants
one managed day of a second park in the same company year, and runs ``main`` with ``READY`` to
1 March of game year 11. It asserts R15: the stop day and October's statement, a clean ``seq``
audit, the contract check, the ready phrase on the label row and, from a dbt build of
``int_sessions__lineage``, step 2's session kept as the child of step 1's save with the same
``park_id``. About two game years at speed 8: a few minutes.
"""

from __future__ import annotations

import os
import platform
import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.autopilot_run import run_autopilot
from openrct2_analytics.ingest.autopilot_year import main
from openrct2_analytics.ingest.bench_setup import game_version
from openrct2_analytics.ingest.capture import REPO_ROOT
from openrct2_analytics.ingest.capture_session import convert_and_report
from openrct2_analytics.ingest.contracts import check_all
from openrct2_analytics.ingest.convert import convert
from openrct2_analytics.ingest.play_mode_feed import ready_phrase
from openrct2_analytics.ingest.save_backup import BackupPlan
from openrct2_analytics.ingest.save_watch import watch_folders
from tests.autopilot_fixtures import plant_registry
from tests.conftest import REAL_GAME_FLAG, settings_for_real_run
from tests.test_dbt_environments import COPIED, dbt

# WEAKENED-OK: the real-game test runs only by hand (spec R13)
pytestmark = pytest.mark.skipif(
    os.environ.get(REAL_GAME_FLAG) != "1",
    reason="the real game runs only by hand: set OPENRCT2_AUTOPILOT_REAL_GAME=1",
)

FIXTURE_YEAR = 9  # the benchmark fixture starts on 6 March of game year 9 (docs/FINDINGS.md)
PLANNED_TO_MARCH = 240  # 6 March to 1 March of the next game year


def query(path: Path, sql: str) -> list[tuple[object, ...]]:
    with duckdb.connect(":memory:") as connection:
        return connection.execute(sql.format(p=path)).fetchall()


def land_managed_session(work: Path, company: Path) -> None:
    """Copy step 1's raw and record files into the company folders, as ``make play`` writes them."""
    for kind in ("raw", "save_files"):
        target = company / kind / "v1"
        target.mkdir(parents=True, exist_ok=True)
        for path in sorted((work / kind / "v1").glob("*.jsonl")):
            shutil.copyfile(path, target / path.name)


def plant_second_park_day(parquet: Path, park_id: str) -> None:
    """Add one managed day of ``park-b`` (game year 9, after 1 March) beside step 1's rows.

    A managed day needs its session's ``save_written`` (company_years.py:68-70): the save row
    is step 1's last one, so its ``seq`` is at or above the planted snapshot's. The planted rows
    are a day older than the real ones: a copy with the same ``emitted_at`` and ``received_at``
    would share the real save's record and leave both unpaired (save_pairing.py:160-169).
    """
    for table, where in (
        ("park_snapshot", "game_month > 0"),
        ("session_start", "true"),
        ("save_written", "true ORDER BY seq DESC"),
    ):
        path = parquet / "v1" / f"{table}.parquet"
        staged = path.with_suffix(".tmp")
        query(
            path,
            f"COPY (SELECT * FROM '{{p}}' UNION ALL (SELECT * REPLACE ('park-b' AS park_id, "
            f"'sess-b' AS session_id, 'sess-b-' || seq AS event_id, "
            f"emitted_at - INTERVAL 1 DAY AS emitted_at, "
            f"received_at - INTERVAL 1 DAY AS received_at) FROM '{{p}}' "
            f"WHERE park_id = '{park_id}' AND {where} LIMIT 1)) TO '{staged}' (FORMAT PARQUET)",
        )
        staged.replace(path)


def test_two_game_years_continue_one_park_and_label_the_second_autopilot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, folder in (
        ("OPENRCT2_BENCH_DIR", "bench"),
        ("OPENRCT2_DATA_DIR", "data"),
        ("OPENRCT2_BACKUP_DIR", "archive"),
    ):
        (tmp_path / folder).mkdir()
        monkeypatch.setenv(name, str(tmp_path / folder))
    (tmp_path / "user").mkdir()
    company = tmp_path / "data" / "company"
    # The settings come from the real sources; the run gets the temporary user folder.
    settings = settings_for_real_run(platform.system(), monkeypatch, tmp_path / "user")
    print(f"game version: {game_version(settings.binary)}")  # noqa: T201

    # Step 1: a managed session from the fixture to 1 March of game year 10, landed as make play.
    built = pi.build_plugin(REPO_ROOT)
    work_name = f"managed-{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
    first = run_autopilot(
        settings,
        park_id="unchecked",  # the fixture's park ID is read from the capture below
        source=settings.park,
        work_name=work_name,
        g=FIXTURE_YEAR,
        loaded_save_id="",
        loaded_save_session_id="",
        built=built,
        planned_days=PLANNED_TO_MARCH,
    )
    assert first.reached_stop, first.problems
    land_managed_session(first.work_dir, company)
    parquet = company / "parquet"
    plan = BackupPlan(
        watch_folders(first.work_dir / "user-data"),
        tmp_path / "user" / "save",
        tmp_path / "archive",
        parquet,
    )
    (tmp_path / "user" / "save").mkdir()
    code = convert_and_report(
        company / "raw",
        parquet,
        company / "save_files",
        first.started,
        watch=first.watch,
        backup=plan,
    )
    assert code == 0
    ((park_id,),) = query(parquet / "v1" / "session_start.parquet", "SELECT park_id FROM '{p}'")
    assert isinstance(park_id, str)

    # Step 2: register the park, plant a second park's managed day in the same company year, run.
    plant_registry(
        company / "registry" / "v1",
        [
            (park_id, 2000, 1, "company", "", "2026-11-13"),
            # Game year 9 of park-b is company year 2009, the year park_id plays from game year 10.
            ("park-b", 2001, 1, "company", "", "2026-11-13"),
        ],
    )
    plant_second_park_day(parquet, park_id)
    phrase = ready_phrase(park_id)
    assert main(["--data-set", "company", "--park", park_id, "--ready", phrase]) == 0

    # R15: the stop day, October's statement, a clean seq audit and the contract check.
    tables = parquet / "v1"
    ((second,),) = query(
        tables / "session_start.parquet",
        f"SELECT session_id FROM '{{p}}' WHERE session_id <> '{first.session_id}' "
        f"AND park_id = '{park_id}'",
    )
    assert query(
        tables / "save_written.parquet",
        f"SELECT game_year, game_month, game_day FROM '{{p}}' WHERE session_id = '{second}'",
    ) == [(FIXTURE_YEAR + 2, 0, 1)]
    assert query(
        tables / "finance_month.parquet",
        "SELECT statement_year, statement_month FROM '{p}' "
        f"WHERE session_id = '{second}' AND statement_month = 7",
    ) == [(FIXTURE_YEAR + 1, 7)]
    assert query(
        tables / "park_snapshot.parquet",
        f"SELECT count(*) FROM '{{p}}' WHERE session_id = '{second}' "
        f"AND game_year = {FIXTURE_YEAR + 2} AND game_month > 0",
    ) == [(0,)]
    rebuilt = convert(company / "raw", tmp_path / "reconverted")
    assert rebuilt.ok and not rebuilt.seq_violations and rebuilt.malformed_lines == 0
    assert {name: lines for name, lines in check_all(parquet).items() if lines} == {}
    labels = (company / "registry" / "v1").glob("session_play_mode_*.csv")
    assert [f"{second},{park_id},autopilot,{phrase}," in path.read_text() for path in labels] == [
        True
    ]

    # The kept timeline: step 2's session is the child of step 1's save, with the same park.
    project = tmp_path / "project"
    for name in COPIED:
        source, target = REPO_ROOT / name, project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    done = dbt(
        project,
        "build",
        "--target",
        "ci",
        "--select",
        "+int_sessions__lineage",
        "--vars",
        f"{{parquet_root: {parquet}, registry_root: {company / 'registry'}}}",
        env={"OPENRCT2_CI_DIR": str(tmp_path)},
        parquet=False,
        registry=False,
    )
    assert done.returncode == 0, done.stdout
    with duckdb.connect(str(tmp_path / "ci.duckdb"), read_only=True) as connection:
        rows = connection.execute(
            "SELECT park_id, parent_session_id, is_on_kept_path FROM "
            "intermediate.int_sessions__lineage WHERE session_id = ?",
            [second],
        ).fetchall()
    assert rows == [(park_id, first.session_id, True)]
