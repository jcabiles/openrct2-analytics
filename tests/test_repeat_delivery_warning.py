"""The repeat-delivery warning: a payload that differs between deliveries warns and is stored.

Real dbt runs in a temporary project copy. The repeat deliveries are planted directly in Parquet,
never through the converter: the converter exits non-zero on a repeated `seq`, so a repeat delivery
cannot reach staging through `make pipeline` without a `seq` violation (R7, "Reachability",
of the removed staging spec, `git show 6eafb6d:docs/ai-dlc/specs/staging-models.md`).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import duckdb

from tests.test_dbt_environments import SAMPLE, dbt, project  # noqa: F401  (project is a fixture)

TEST_PREFIX = "repeat_delivery_payload_differs"
# dbt cuts the stored table's name to 63 characters.
STORED_PREFIX = "repeat_delivery_payload_differ"
FIXTURE_SQL = """select
    event_id,
    guests_in_park
from {{ source('landing', 'park_snapshot') }}
"""
# Applied the way the event-type staging models apply it: model level, with the model's source.
FIXTURE_YAML = """version: 2

models:
  - name: stg_repeat_fixture
    data_tests:
      - repeat_delivery_payload_differs:
          arguments:
            source_relation: source('landing', 'park_snapshot')
"""


@dataclass(frozen=True)
class Planted:
    """The two event ids planted into a Parquet file: one repeat that differs, one that does not."""

    differing: str
    identical: str


def plant_repeats(
    parquet_root: Path,
    event_type: str,
    changed_column: str,
    change_expression: str = "+ 1",
) -> Planted:
    """Copy the sample into parquet_root and add two repeat deliveries to one event type's file.

    Both repeats get a new received_at, _raw_file and _raw_line, as any second delivery would. The
    first also gets a different value in changed_column; the second differs in nothing else.
    """
    shutil.copytree(SAMPLE / "v1", parquet_root / "v1")
    path = parquet_root / "v1" / f"{event_type}.parquet"
    with duckdb.connect() as con:
        con.execute(f"create table deliveries as select * from read_parquet('{path}')")
        if event_type == "weather_change":
            con.execute(
                """insert into deliveries values (
                    1, 'weather_change', '0.5.0', 'kpark1', 's1', 'weather.jsonl', 1,
                    8, 's1-8', 2, 3, 4, 8000,
                    '2026-09-30 23:30:00+00'::timestamptz,
                    '2026-09-30 23:31:00+00'::timestamptz,
                    'Rain', 'Sunny', 'Storm', 18
                ), (
                    1, 'weather_change', '0.5.0', 'kpark1', 's1', 'weather.jsonl', 2,
                    9, 's1-9', 2, 3, 4, 9000,
                    '2026-09-30 23:32:00+00'::timestamptz,
                    '2026-09-30 23:33:00+00'::timestamptz,
                    'Fog', 'Rain', 'Storm', 17
                )"""
            )
        ids = [
            row[0]
            for row in con.execute(
                f"select event_id from deliveries where {changed_column} is not null "
                "order by event_id limit 2"
            ).fetchall()
        ]
        assert len(ids) == 2, f"{event_type} needs two events with a {changed_column}"
        planted = Planted(differing=ids[0], identical=ids[1])
        repeat = (
            "received_at + interval 1 second as received_at, "
            "_raw_file || '.again' as _raw_file, "
            "_raw_line + 1000000 as _raw_line"
        )
        for event_id, change in (
            (
                planted.differing,
                f", {changed_column} {change_expression} as {changed_column}",
            ),
            (planted.identical, ""),
        ):
            con.execute(
                f"insert into deliveries select * replace ({repeat}{change}) "
                "from deliveries where event_id = ?",
                [event_id],
            )
        con.execute(f"copy deliveries to '{path}' (format parquet)")
    return Planted(*ids)


def build(work: Path, select: str, parquet_root: Path, ci_dir: Path) -> str:
    """Build one model and its tests on the ci target; return dbt's output."""
    ci_dir.mkdir()
    done = dbt(
        work,
        "build",
        "--target",
        "ci",
        "--select",
        select,
        "--indirect-selection",
        "buildable",
        "--vars",
        f"{{parquet_root: {parquet_root}}}",
        env={"OPENRCT2_CI_DIR": str(ci_dir)},
        parquet=False,
        registry=False,
    )
    assert done.returncode == 0, done.stdout
    return done.stdout


def warning_results(work: Path) -> list[dict[str, object]]:
    """The run results of the repeat-delivery test in the last build."""
    results = json.loads((work / "target" / "run_results.json").read_text(encoding="utf-8"))
    return [
        r
        for r in results["results"]
        if r["unique_id"].startswith(f"test.openrct2_analytics.{TEST_PREFIX}")
    ]


def warning_result_for_source(
    results: list[dict[str, object]], event_type: str
) -> dict[str, object]:
    """Return the repeat-delivery test result whose identifier names its source."""
    matches = [r for r in results if event_type in str(r["unique_id"])]
    assert len(matches) == 1, matches
    return matches[0]


def stored_rows(ci_dir: Path, result: dict[str, object] | None = None) -> list[tuple[str, int]]:
    """The rows the test stored: one (event_id, versions seen) per flagged event.

    With a result, read the table that result stored; without one, require exactly one table.
    """
    with duckdb.connect(str(ci_dir / "ci.duckdb"), read_only=True) as con:
        tables = con.execute(
            "select table_schema, table_name from information_schema.tables "
            f"where table_name like '{STORED_PREFIX}%'"
        ).fetchall()
        if result is not None:
            stored_table = str(result["relation_name"]).rsplit(".", 1)[-1].strip('"')
            tables = [row for row in tables if row[1] == stored_table]
        assert len(tables) == 1, tables
        schema, table = tables[0]
        rows = con.execute(
            f'select event_id, versions_seen from "{schema}"."{table}" order by event_id'
        ).fetchall()
    return [(str(event_id), int(versions)) for event_id, versions in rows]


def test_plugin_stats_repeat_warns_through_stg_envelope(
    project: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    planted = plant_repeats(tmp_path / "parquet", "plugin_stats", "callbacks")
    output = build(project, "stg_envelope", tmp_path / "parquet", tmp_path / "ci")

    results = warning_results(project)
    assert len(results) == 2
    result = warning_result_for_source(results, "plugin_stats")
    assert result["status"] == "warn", output
    assert result["failures"] == 1
    assert stored_rows(tmp_path / "ci", result) == [(planted.differing, 2)]


def test_emitted_at_repeat_warns_through_stg_envelope(
    project: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    planted = plant_repeats(
        tmp_path / "parquet",
        "plugin_stats",
        "emitted_at",
        "+ interval 1 second",
    )
    output = build(project, "stg_envelope", tmp_path / "parquet", tmp_path / "ci")

    results = warning_results(project)
    assert len(results) == 2
    result = warning_result_for_source(results, "plugin_stats")
    assert result["status"] == "warn", output
    assert result["failures"] == 1
    assert stored_rows(tmp_path / "ci", result) == [(planted.differing, 2)]


def test_event_type_repeat_warns_through_a_model_yaml(
    project: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    staging = project / "models" / "staging"
    (staging / "stg_repeat_fixture.sql").write_text(FIXTURE_SQL, encoding="utf-8")
    (staging / "stg_repeat_fixture.yml").write_text(FIXTURE_YAML, encoding="utf-8")
    planted = plant_repeats(tmp_path / "parquet", "park_snapshot", "guests_in_park")
    output = build(project, "stg_repeat_fixture", tmp_path / "parquet", tmp_path / "ci")

    results = warning_results(project)
    assert len(results) == 1
    result = warning_result_for_source(results, "park_snapshot")
    assert result["status"] == "warn", output
    assert result["failures"] == 1
    assert stored_rows(tmp_path / "ci") == [(planted.differing, 2)]


def test_envelope_repeat_warns_for_weather_change(
    project: Path,  # noqa: F811
    tmp_path: Path,
) -> None:
    planted = plant_repeats(tmp_path / "parquet", "weather_change", "weather", "|| ' changed'")
    output = build(project, "stg_envelope", tmp_path / "parquet", tmp_path / "ci")

    results = warning_results(project)
    assert len(results) == 2
    result = warning_result_for_source(results, "weather_change")
    assert result["status"] == "warn", output
    assert result["failures"] == 1
    assert stored_rows(tmp_path / "ci", result) == [(planted.differing, 2)]
