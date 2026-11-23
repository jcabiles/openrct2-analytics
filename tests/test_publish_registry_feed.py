"""Publish flow over the park registry feed: the audit as second line, the live feed untouched."""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest import registry_feed
from openrct2_analytics.ingest.publish import publish
from openrct2_analytics.ingest.publish_audit import audit_candidate
from openrct2_analytics.ingest.publish_errors import PublishFailed
from tests.publish_standin import StandinOptions, add_registry_model, build_standin
from tests.test_publish import land_sample, project_for, standin
from tests.test_publish_dbt import data_root, project_copy
from tests.two_park_support import FIRST_PARK

FEED_HEADER = "park_id,company_start_year,game_year_origin,data_set,note,delivered_on\n"
SAMPLE_PARK = FIRST_PARK


def feed_bytes(feed: Path) -> dict[str, str]:
    """Return a content hash for every file under the feed folder."""
    return {
        path.relative_to(feed).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(feed.rglob("*"))
        if path.is_file()
    }


def write_delivery(feed_v1: Path, name: str, rows: str) -> Path:
    path = feed_v1 / name
    path.write_text(FEED_HEADER + rows, encoding="utf-8")
    return path


def test_company_registry_audit_names_a_park_outside_the_registry(
    tmp_path: Path, landing_root: Path
) -> None:
    """The audit's check reads the current registry model and names the unregistered park."""
    land_sample(landing_root, "company")

    with pytest.raises(PublishFailed) as failure:
        publish(
            "company",
            run_id="standin-company",
            build=standin("company", options=StandinOptions(unregistered_park=True)),
            project_dir=project_for(tmp_path),
        )

    assert failure.value.reason == "unregistered-park"
    assert "unregistered park_id value(s): park-unregistered" in failure.value.detail


def test_registry_manifest_without_a_current_model_fails_unregistered_park(tmp_path: Path) -> None:
    candidate_dir = tmp_path / "candidate"
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    candidate_file = candidate_dir / "warehouse.duckdb"
    build_standin("company")(candidate_dir, candidate_file, snapshot_dir)
    add_registry_model(candidate_dir, "warehouse", kind="history")

    with pytest.raises(PublishFailed) as failure:
        audit_candidate(candidate_file, candidate_dir, "company", tmp_path, on_step=lambda _: None)

    assert failure.value.reason == "unregistered-park"
    assert "park_registry: current" in failure.value.detail


@pytest.mark.parametrize(
    ("kind", "table"),
    [("history", "int_park_registry__history"), ("staging", "stg_park_registry")],
)
def test_registry_relations_other_than_current_do_not_count_as_park_rows(
    tmp_path: Path, kind: str, table: str
) -> None:
    """Park ids held only by a registry relation leave the candidate with no park."""
    candidate_dir = tmp_path / "candidate"
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    candidate_file = candidate_dir / "warehouse.duckdb"
    options = StandinOptions(include_keyed_model=False, empty_park_session=True)
    build_standin("company", options=options)(candidate_dir, candidate_file, snapshot_dir)
    add_registry_model(candidate_dir, "warehouse")
    add_registry_model(candidate_dir, "warehouse", kind=kind)
    connection = duckdb.connect(str(candidate_file))
    try:
        connection.execute(f"CREATE TABLE main.{table} (park_id VARCHAR)")
        connection.execute(f"INSERT INTO main.{table} VALUES ('park-in-registry')")
    finally:
        connection.close()

    with pytest.raises(PublishFailed) as failure:
        audit_candidate(candidate_file, candidate_dir, "company", tmp_path, on_step=lambda _: None)

    assert failure.value.reason == "no-park"


def test_company_registry_real_publish_with_a_park_missing_from_the_feed_fails_at_the_dbt_step(
    tmp_path: Path,
) -> None:
    """A company feed that registers only another park fails the company-year check in dbt."""
    project, _landing = project_copy(tmp_path, "company")
    feed_v1 = project / "data" / "company" / "registry" / "v1"
    for delivery in feed_v1.glob("*.csv"):
        delivery.unlink()
    write_delivery(
        feed_v1,
        "park_registry_2026-10-10_01.csv",
        "other-park,2000,9,company,n,2026-10-10\n",
    )

    with data_root(project), pytest.raises(PublishFailed) as failure:
        publish("company", run_id="real-missing-park", project_dir=project)

    assert failure.value.reason == "dbt"
    assert "assert_every_park_year_has_a_company_year" in failure.value.detail
    assert not (project / "warehouse" / "company.duckdb").is_file()


def test_company_delivery_landed_after_the_snapshot_does_not_reach_the_registry_build(
    tmp_path: Path,
) -> None:
    """A company-labelled delivery appended to the live feed mid-publish is not built."""
    project, _landing = project_copy(tmp_path, "rehearsal")
    live_v1 = project / "data" / "rehearsal" / "registry" / "v1"
    assert live_v1.is_relative_to(tmp_path)

    def land_delivery(step: str) -> None:
        if step == "snapshot-taken":
            write_delivery(
                live_v1,
                "park_registry_2026-10-11_01.csv",
                f"{SAMPLE_PARK},2000,9,company,Landed mid-publish.,2026-10-11\n",
            )

    with data_root(project):
        publish("rehearsal", run_id="real-mid-publish", on_step=land_delivery, project_dir=project)

    assert (project / "warehouse" / "rehearsal.duckdb").is_file()
    assert (live_v1 / "park_registry_2026-10-11_01.csv").is_file()


def test_registry_feed_unchanged_by_the_feed_check_and_a_real_publish(tmp_path: Path) -> None:
    """Neither `make contracts`'s feed check nor a real publish writes to the live feed."""
    project, _landing = project_copy(tmp_path, "rehearsal")
    live = project / "data" / "rehearsal" / "registry"
    before = feed_bytes(live)
    assert before

    with data_root(project):
        assert registry_feed.main(["--data-set", "rehearsal"]) == 0
        publish("rehearsal", run_id="real-feed-unchanged", project_dir=project)

    assert feed_bytes(live) == before


def test_registry_landed_bad_file_fails_the_publish_naming_the_file(
    tmp_path: Path, landing_root: Path
) -> None:
    """A bad delivery that was landed in the feed refuses the publish and is named."""
    land_sample(landing_root, "company")
    bad = write_delivery(
        landing_root / "company" / "registry" / "v1",
        "park_registry_2026-10-11_01.csv",
        ",2000,9,company,,2026-10-11\n",
    )

    with pytest.raises(PublishFailed) as failure:
        publish(
            "company",
            run_id="standin-landed",
            build=standin("company"),
            project_dir=project_for(tmp_path),
        )

    assert failure.value.reason == "contracts"
    assert bad.name in failure.value.detail


def relabel_park(landing: Path, park_id: str) -> None:
    """Rewrite `park_id` to one value in every landed Parquet file that has the column."""
    connection = duckdb.connect()
    try:
        for path in sorted(landing.rglob("*.parquet")):
            source = path.as_posix()
            columns = connection.execute(
                "SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?))", [source]
            ).fetchall()
            if ("park_id",) not in columns:
                continue
            rewritten = path.with_suffix(".rewritten")
            connection.execute(
                "COPY (SELECT * REPLACE (? AS park_id) FROM read_parquet(?)) "
                f"TO '{rewritten.as_posix()}' (FORMAT parquet)",
                [park_id, source],
            )
            rewritten.replace(path)
    finally:
        connection.close()


def test_rehearsal_registry_real_publish_of_a_non_sample_park_publishes(tmp_path: Path) -> None:
    """A park other than the sample park, registered by the feed alone, publishes."""
    project, landing = project_copy(tmp_path, "rehearsal")
    other_park = "other-rehearsal-park"
    relabel_park(landing, other_park)
    live_v1 = project / "data" / "rehearsal" / "registry" / "v1"
    for delivery in live_v1.glob("*.csv"):
        delivery.unlink()
    write_delivery(
        live_v1,
        "park_registry_2026-10-10_01.csv",
        f"{other_park},2000,9,rehearsal,Non-sample park.,2026-10-10\n",
    )

    with data_root(project):
        publish("rehearsal", run_id="real-non-sample", project_dir=project)

    assert (project / "warehouse" / "rehearsal.duckdb").is_file()


LABEL_HEADER = "session_id,park_id,play_mode,ready_confirmation,data_set,delivered_on\n"
LABEL_NAME = "session_play_mode_2026-11-14_01.csv"


def write_label(landing_root: Path, row: str) -> Path:
    path = landing_root / "company" / "registry" / "v1" / LABEL_NAME
    path.write_text(LABEL_HEADER + row, encoding="utf-8")
    return path


def test_label_file_is_copied_into_the_snapshot_and_published(
    tmp_path: Path, landing_root: Path
) -> None:
    """A landed label file reaches the snapshot beside the registry delivery, byte for byte."""
    land_sample(landing_root, "company")
    label = write_label(landing_root, "s1,p,managed,,company,2026-11-14\n")
    copied: dict[str, bytes] = {}
    inner = standin("company")

    def build(candidate_dir: Path, candidate_file: Path, snapshot_dir: Path) -> None:
        for path in (snapshot_dir / "registry" / "v1").glob("session_play_mode_*.csv"):
            copied[path.name] = path.read_bytes()
        inner(candidate_dir, candidate_file, snapshot_dir)

    publish("company", run_id="standin-label", build=build, project_dir=project_for(tmp_path))

    assert copied[LABEL_NAME] == label.read_bytes()
    assert "session_play_mode_2026-11-13_01.csv" in copied


def test_landed_bad_label_file_fails_the_publish_naming_the_file(
    tmp_path: Path, landing_root: Path
) -> None:
    """A label row with an unknown play mode refuses the publish at the contract step."""
    land_sample(landing_root, "company")
    write_label(landing_root, "s1,p,robot,,company,2026-11-14\n")

    with pytest.raises(PublishFailed) as failure:
        publish(
            "company",
            run_id="standin-bad-label",
            build=standin("company"),
            project_dir=project_for(tmp_path),
        )

    assert failure.value.reason == "contracts"
    assert "play-mode feed:" in failure.value.detail


def test_label_row_of_another_data_set_fails_the_company_publish(
    tmp_path: Path, landing_root: Path
) -> None:
    """The publish names its data set to the label check; the candidate folder has no such name."""
    land_sample(landing_root, "company")
    write_label(landing_root, "s1,p,managed,,rehearsal,2026-11-14\n")

    with pytest.raises(PublishFailed) as failure:
        publish(
            "company",
            run_id="standin-other-set",
            build=standin("company"),
            project_dir=project_for(tmp_path),
        )

    assert failure.value.reason == "contracts"
    assert "play-mode feed:" in failure.value.detail
