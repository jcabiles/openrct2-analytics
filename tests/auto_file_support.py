"""Fakes and planting helpers for the auto-file tests; after-play is a recording fake.

Moved out of ``tests/test_auto_file.py`` so the single-park and several-park test files share them.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, tzinfo
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import (
    after_play,
    auto_file,
    lock,
    play_status,
    register_parks,
    several_parks,
)
from openrct2_analytics.ingest import registry_feed as feed_module
from tests.autopilot_fixtures import event_row, plant_park_snapshot
from tests.test_after_play import _copy
from tests.test_register_parks import _rows
from tests.test_register_parks_start_year import World

# What a successful filing that registered a company park ends with when no warehouse was built.
NO_WAREHOUSE_LINE = (
    "auto-file: the play is filed, but the park number could not be shown (no warehouse file).\n"
)
BEFORE = Path("local") / "auto-file" / "converted-before.json"
# Opened first, though its park ID sorts after the second park's.
FIRST, SECOND = "park-b", "park-a"


class Asked:
    """The ``ask`` seam: replays answers (or raises one) and records every prompt."""

    def __init__(
        self, answers: Sequence[str | BaseException] = (), log: list[str] | None = None
    ) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []
        self.log = log if log is not None else []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.log.append("ask")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class Filed:
    """The ``file_with`` seam: records each argument list and ``registrations_landed``."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[list[str]] = []
        self.landed: list[bool] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        project_dir: Path,
        registrations_landed: bool = False,
        registered: list[str] | None = None,
    ) -> int:
        self.calls.append(list(argv))
        self.landed.append(registrations_landed)
        if registered is not None:
            # Like after-play, report the listed parks that no delivery holds yet, as written.
            options = dict(zip(argv[::2], argv[1::2], strict=True))
            feed = play_status.registry_feed_dir("company", project_dir)
            held = register_parks.registered_parks(feed)
            registered.extend(
                park for park in register_parks.parse_parks(options["--parks"]) if park not in held
            )
        return self.code


class AfterPlayWithOutsideRegistration(Filed):
    """The real after-play, preceded by another filing run that registers ``park-a``."""

    def __init__(self, *, outside: bool) -> None:
        super().__init__()
        self.outside = outside

    def __call__(
        self,
        argv: Sequence[str],
        *,
        project_dir: Path,
        registrations_landed: bool = False,
        registered: list[str] | None = None,
    ) -> int:
        if self.outside:
            register_parks.register(
                project_dir, datetime.now(UTC).date(), False, parks={"park-a": False}
            )
        return after_play.main(
            argv,
            project_dir=project_dir,
            registrations_landed=registrations_landed,
            registered=registered,
        )


def _sessions(data: Path, rows: list[tuple[str, str, str]]) -> None:
    """Write (session, park, park name) rows as converted session_start, oldest first."""
    query = " UNION ALL ".join(
        f"SELECT '{session}' AS session_id, '{park}' AS park_id, '{name}' AS park_name, "
        f"1 AS game_year, "
        f"TIMESTAMPTZ '2026-10-{day:02} 10:00:00+00' AS emitted_at"
        for day, (session, park, name) in enumerate(rows, start=1)
    )
    _copy(data / "company" / "parquet" / "v1" / "session_start.parquet", query)


def _snapshots(data: Path, days: dict[str, list[tuple[int, int, int]]]) -> None:
    """Write one converted park_snapshot row per (park, game date); a date may repeat."""
    rows = [
        event_row(seq, park_id=park, session_id="snapshots", game_date=date)
        for seq, (park, date) in enumerate(
            ((park, date) for park, dates in days.items() for date in dates), start=1
        )
    ]
    plant_park_snapshot(data / "company" / "parquet", rows)


def _register(data: Path, park: str, *, practice: bool) -> None:
    feed = data / "company" / "registry" / "v1"
    feed.mkdir(parents=True)
    note = register_parks.NOTE if practice else ""
    (feed / "park_registry_2026-10-18_01.csv").write_text(
        f"{','.join(feed_module.HEADER)}\n{park},2000,3,company,{note},2026-10-18\n",
        encoding="utf-8",
    )


def _dim_park(
    project: Path, rows: list[tuple[str, int | None, int]], *, number_column: bool = True
) -> Path:
    """Plant (park, number, year) rows in ``marts.dim_park`` of the development warehouse.

    The table and schema are created when absent and kept when present, so ``plant_park_years``
    may have written the file first; a park already in the table has its number and year updated.
    ``number_column=False`` plants the table as a warehouse built before ``park_number`` had it.
    """
    path = project / "warehouse" / "dev" / "dev.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = "park_id VARCHAR, company_start_year INTEGER"
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS marts")
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS marts.dim_park ({columns}"
            f"{', park_number INTEGER' * number_column})"
        )
        for park, number, year in rows:
            values = {
                "company_start_year": year,
                **({"park_number": number} if number_column else {}),
            }
            found = connection.execute(
                "SELECT count(*) FROM marts.dim_park WHERE park_id = ?", [park]
            ).fetchone()
            if found and found[0]:
                assignments = ", ".join(f"{column} = ?" for column in values)
                connection.execute(
                    f"UPDATE marts.dim_park SET {assignments} WHERE park_id = ?",
                    [*values.values(), park],
                )
            else:
                marks = ", ".join("?" * (len(values) + 1))
                connection.execute(
                    f"INSERT INTO marts.dim_park (park_id, {', '.join(values)}) VALUES ({marks})",
                    [park, *values.values()],
                )
    return path


def plant_park_years(
    project: Path,
    years: list[tuple[str, object, str, object, object, object]],
    names: dict[str, str],
    *,
    money_type: str = "DECIMAL(18,2)",
    year_type: str = "INTEGER",
) -> Path:
    """Plant ``marts.obt_park_year`` rows and ``marts.dim_park`` names in the development warehouse.

    Each year row is (park, company year, close status, operating profit, capital spending,
    interest costs); no year row creates no ``obt_park_year``. The names go into ``dim_park`` as
    the parent's reader expects: the table is created with ``park_name`` when absent, given it when
    it lacks it, and a planted park already in it has its name updated before a missing one is
    inserted (null number and year), so no park gets two rows.
    """
    path = project / "warehouse" / "dev" / "dev.duckdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS marts")
        if years:
            connection.execute(
                f"CREATE TABLE marts.obt_park_year (park_id VARCHAR, company_year {year_type}, "
                f"close_status VARCHAR, operating_profit {money_type}, "
                f"capital_spending {money_type}, interest_costs {money_type})"
            )
            connection.executemany(
                "INSERT INTO marts.obt_park_year VALUES (?, ?, ?, ?, ?, ?)", years
            )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS marts.dim_park (park_id VARCHAR, park_number INTEGER, "
            "company_start_year INTEGER, park_name VARCHAR)"
        )
        connection.execute("ALTER TABLE marts.dim_park ADD COLUMN IF NOT EXISTS park_name VARCHAR")
        for park, name in names.items():
            connection.execute(
                "UPDATE marts.dim_park SET park_name = ? WHERE park_id = ?", [name, park]
            )
            connection.execute(
                "INSERT INTO marts.dim_park (park_id, park_name) "
                "SELECT ?, ? WHERE NOT EXISTS (SELECT 1 FROM marts.dim_park WHERE park_id = ?)",
                [park, name, park],
            )
    return path


def _before(project: Path, ids: list[str]) -> None:
    path = project / BEFORE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ids), encoding="utf-8")


@pytest.fixture
def data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fixed_local_zone: Callable[[tzinfo], None]
) -> Path:
    fixed_local_zone(UTC)
    root = tmp_path / "data"
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(root))
    return root


def _run(
    project: Path,
    count_as: str,
    *,
    asked: Asked | None = None,
    filed: Filed | None = None,
    terminal: bool = True,
    register: several_parks.RegisterWith = register_parks.register,
) -> tuple[int, Asked, Filed]:
    asked = asked or Asked()
    filed = filed or Filed()
    code = auto_file.main(
        ["--data-set", "company", "--count-as", count_as],
        project_dir=project,
        ask=asked,
        file_with=filed,
        is_terminal=lambda: terminal,
        register_with=register,
    )
    return code, asked, filed


# The several-park chain: its fixture, expected lines and the ``register_with`` wrapper.


def _world(first: str = FIRST, second: str = SECOND, *, origin: int = 1) -> World:
    """Two new parks: ``first`` played and saved into game year 2 (company years 2000 and 2001),
    ``second`` opened two hours later in game year ``origin``."""
    return {
        "sessions": [(first, "s1", (1, 0, 1), 0), (second, "s2", (origin, 0, 1), 2)],
        "days": [
            (first, "s1", 2, (1, 0, 2)),
            (first, "s1", 3, (1, 7, 31)),
            (first, "s1", 4, (2, 0, 20)),
        ],
        "saves": [(first, "s1", 5, (2, 0, 20))],
        "registry": [],
        "labels": [],
    }


def _new(park: str, year: int) -> str:
    how = f"company park, start year {year}"
    return f"auto-file: park {park} (first played Nov 12) is new; registering it as {how}.\n"


def _filed(*parks: tuple[str, int]) -> str:
    named = "; ".join(
        f"park {park} (first played Nov 12) as company park, start year {year}"
        for park, year in parks
    )
    return f"auto-file: already registered by this run: {named}.\n"


def _feed(data: Path) -> Path:
    return data / "company" / "registry" / "v1"


def _lock_path(data: Path) -> Path:
    return data / "company" / "parquet.lock"


def _deliveries(data: Path) -> list[list[tuple[str, str, str, str]]]:
    """Each written delivery's (park, start year, origin, note) rows, in file name order."""
    return [
        [
            (row["park_id"], row["company_start_year"], row["game_year_origin"], row["note"])
            for row in _rows(path)
        ]
        for path in sorted(_feed(data).glob("park_registry_*.csv"))
    ]


class Registers:
    """The ``register_with`` seam: the real ``register``, failing as told for park ``park``.

    ``raises`` is raised instead of registering it; ``locked`` holds the landing lock during its
    call; ``after`` runs once it registered.
    """

    def __init__(
        self,
        log: list[str] | None = None,
        *,
        park: str | None = None,
        raises: BaseException | None = None,
        locked: Path | None = None,
        after: Callable[[], object] | None = None,
    ) -> None:
        self.log = log if log is not None else []
        self.park = park
        self.raises = raises
        self.locked = locked
        self.after = after
        self.calls: list[tuple[dict[str, bool], int | None]] = []

    def __call__(
        self,
        project_dir: Path,
        today: date,
        practice: bool,
        *,
        parks: dict[str, bool] | None = None,
        start_year: int | None = None,
    ) -> str:
        assert parks is not None
        self.log.append("register")
        self.calls.append((dict(parks), start_year))
        told = self.park in parks
        if told and self.raises is not None:
            raise self.raises
        if told and self.locked is not None:
            with lock.hold_lock(self.locked, "test holder"):
                return register_parks.register(
                    project_dir, today, practice, parks=parks, start_year=start_year
                )
        name = register_parks.register(
            project_dir, today, practice, parks=parks, start_year=start_year
        )
        if told and self.after is not None:
            self.after()
        return name
