"""Real-dbt publish acceptance checks in isolated project copies."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import shutil
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from check_metric_catalog_shape import COPIED
from openrct2_analytics.ingest.empty_extract import write_empty_extract
from openrct2_analytics.ingest.publish import main, publish
from openrct2_analytics.ingest.publish_audit import open_warehouse
from openrct2_analytics.ingest.publish_errors import PublishFailed

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "sample" / "rehearsal"


def project_copy(work: Path, data_set: str) -> tuple[Path, Path]:
    """Copy the dbt project and committed landing sample into an isolated folder."""
    project = work / "project"
    for name in COPIED:
        source = ROOT / name
        destination = project / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
    landing = project / "data" / data_set / "parquet"
    landing.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SAMPLE, landing)
    shutil.copytree(SAMPLE / "registry" / "v1", landing.parent / "registry" / "v1")
    return project, landing


def landing_bytes(landing: Path) -> dict[str, str]:
    """Return a content hash for every file in the landing folder."""
    return {
        path.relative_to(landing).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(landing.rglob("*"))
        if path.is_file()
    }


def quote_identifier(identifier: str) -> str:
    """Quote one DuckDB identifier for an inspection query."""
    return '"' + identifier.replace('"', '""') + '"'


@contextlib.contextmanager
def data_root(project: Path) -> Iterator[None]:
    """Point the publish flow at data inside the temporary project copy."""
    with pytest.MonkeyPatch.context() as patch:
        for name in tuple(os.environ):
            if name.startswith("OPENRCT2_"):
                patch.delenv(name)
        patch.setenv("OPENRCT2_DATA_DIR", str(project / "data"))
        yield


def add_non_main_model(project: Path) -> None:
    """Add a one-row model whose audit must use its schema-qualified relation name."""
    model_dir = project / "models" / "staging"
    (model_dir / "audit_probe.sql").write_text(
        "{{ config(schema='audit_probe') }}\nselect 1 as id\n", encoding="utf-8"
    )
    (model_dir / "audit_probe.yml").write_text(
        "version: 2\nmodels:\n  - name: audit_probe\n    meta:\n      expected_min_rows: 1\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def rehearsal_publish(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[Path, Path, dict[str, str], int]:
    """Run one real rehearsal publish, shared by the A11 and relation-name checks."""
    project, landing = project_copy(tmp_path_factory.mktemp("publish-rehearsal"), "rehearsal")
    add_non_main_model(project)
    before = landing_bytes(landing)
    output = io.StringIO()
    with data_root(project), contextlib.redirect_stdout(output):
        exit_code = main(["--data-set", "rehearsal"], run_id="real-rehearsal", project_dir=project)
    return project, landing, before, exit_code


def test_a11_real_rehearsal_publish_is_read_only_and_audited(
    rehearsal_publish: tuple[Path, Path, dict[str, str], int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A11: build, audit, publish, and open the committed rehearsal sample."""
    project, landing, before, exit_code = rehearsal_publish
    published = project / "warehouse" / "rehearsal.duckdb"

    assert exit_code == 0
    assert published.is_file()
    assert stat.S_IMODE(published.stat().st_mode) == 0o444
    assert landing_bytes(landing) == before
    assert list((project / "warehouse" / "candidate").iterdir()) == []
    assert not list(project.rglob("*.lock"))

    outside = tmp_path / "outside-project"
    outside.mkdir()
    monkeypatch.chdir(outside)
    connection = open_warehouse(published, project_dir=project)
    try:
        relations = connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog', 'system') "
            "ORDER BY table_schema, table_name"
        ).fetchall()
        assert relations
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_type = 'VIEW'"
        ).fetchone() == (0,)
        for schema, relation in relations:
            qualified = f"{quote_identifier(schema)}.{quote_identifier(relation)}"
            assert connection.execute(f"SELECT count(*) FROM {qualified}").fetchone() is not None
    finally:
        connection.close()


def test_audit_reads_expected_rows_through_non_main_relation_name(
    rehearsal_publish: tuple[Path, Path, dict[str, str], int],
) -> None:
    """A11 step 7: a model outside main is present after its relation-name audit."""
    project, _landing, _before, exit_code = rehearsal_publish
    assert exit_code == 0
    connection = open_warehouse(project / "warehouse" / "rehearsal.duckdb", project_dir=project)
    try:
        relation = connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_name = 'audit_probe' AND table_type = 'BASE TABLE'"
        ).fetchone()
        assert relation is not None
        schema, table = relation
        schema = str(schema)
        table = str(table)
        assert schema != "main"
        assert connection.execute(
            f"SELECT count(*) FROM {quote_identifier(schema)}.{quote_identifier(table)}"
        ).fetchone() == (1,)
    finally:
        connection.close()


def empty_parquet_copies(landing: Path) -> None:
    """Replace the copied Parquet files with the schema-preserving zero-row extract."""
    write_empty_extract(landing)


def test_a13_zero_row_real_publish_fails_empty_before_rename(
    tmp_path: Path,
) -> None:
    """A13: staging expected_min_rows keys reject a real zero-row build."""
    project, landing = project_copy(tmp_path, "rehearsal")
    empty_parquet_copies(landing)
    warehouse = project / "warehouse"
    warehouse.mkdir()
    published = warehouse / "rehearsal.duckdb"
    original = b"existing published file remains byte for byte unchanged"
    published.write_bytes(original)

    with data_root(project), pytest.raises(PublishFailed) as failure:
        publish("rehearsal", run_id="real-empty", project_dir=project)

    assert failure.value.reason == "empty"
    assert published.read_bytes() == original
    assert list((warehouse / "candidate").iterdir()) == []
    assert not list(project.rglob("*.lock"))


def test_a9_real_company_publish_of_a_rehearsal_feed_fails_at_the_dbt_step(
    tmp_path: Path,
) -> None:
    """A9: the committed feed labels its park rehearsal, so a company build fails in dbt."""
    project, _landing = project_copy(tmp_path, "company")
    published = project / "warehouse" / "company.duckdb"

    with data_root(project), pytest.raises(PublishFailed) as failure:
        publish("company", run_id="real-company", project_dir=project)

    assert failure.value.reason == "dbt"
    assert not published.is_file()
    assert list((project / "warehouse" / "candidate").iterdir()) == []
    assert not list(project.rglob("*.lock"))
