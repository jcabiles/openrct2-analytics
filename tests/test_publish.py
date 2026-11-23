"""Publish flow: lock refusals, the stand-in park rule, the WAL barrier and step order."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest.publish import main, publish
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from tests.publish_standin import (
    StandinOptions,
    add_registry_model,
    build_standin,
    read_stamp,
    write_stamped,
)
from tests.test_contracts import write_data

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "rehearsal"
SAMPLE_V1 = SAMPLE / "v1"
WRITE_OPEN = "import duckdb, sys; duckdb.connect(sys.argv[1])"
WAIT_SECONDS = 30
Build = Callable[[Path, Path, Path], None]

pytestmark = pytest.mark.usefixtures("landing_root")


def error_line(output: str) -> str:
    """Return the single error line, ignoring an optional rotation status line."""
    rotation_prefix = "no interrupted rotation: "
    if output.startswith(rotation_prefix):
        _, separator, output = output.partition("\n")
        assert separator == "\n"
    assert output.endswith("\n")
    assert output.count("\n") == 1
    return output[:-1]


def land_sample(root: Path, data_set: str) -> Path:
    """Copy the committed sample's Parquet and feed into the data set's landing folders."""
    v1 = root / data_set / "parquet" / "v1"
    shutil.copytree(SAMPLE_V1, v1)
    shutil.copytree(SAMPLE / "registry" / "v1", root / data_set / "registry" / "v1")
    return v1


def standin(data_set: str, *, options: StandinOptions | None = None, version: str = "v") -> Build:
    """Return the dbt stand-in plus the current registry model node a real dbt manifest carries."""
    inner = build_standin(data_set, options=options, version=version)

    def build(candidate_dir: Path, candidate_file: Path, snapshot_dir: Path) -> None:
        inner(candidate_dir, candidate_file, snapshot_dir)
        add_registry_model(candidate_dir, candidate_file.stem)

    return build


def project_for(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def published_file(project: Path, name: str = "rehearsal") -> Path:
    return project / "warehouse" / f"{name}.duckdb"


def candidate_folders(project: Path) -> list[Path]:
    return sorted((project / "warehouse" / "candidate").glob("run-*"))


@pytest.mark.parametrize(
    "held_step", ["candidate-created", "wal-checked", "renamed", "candidate-removed"]
)
def test_second_publisher_is_refused_at_the_lock_while_first_is_held(
    tmp_path: Path, landing_root: Path, held_step: str
) -> None:
    """A8: B is refused at the lock, creates no candidate folder, and A's stamp is published."""
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    write_stamped(published_file(project), "before")
    reached = threading.Event()
    release = threading.Event()

    def hold(step: str) -> None:
        if step == held_step:
            reached.set()
            assert release.wait(WAIT_SECONDS)

    def run_a() -> None:
        publish(
            "rehearsal",
            run_id="run-a",
            build=standin("rehearsal", version="from-a"),
            on_step=hold,
            project_dir=project,
        )

    pool = ThreadPoolExecutor(max_workers=1)
    publisher_a = pool.submit(run_a)
    try:
        assert reached.wait(WAIT_SECONDS)
        before = candidate_folders(project)
        with pytest.raises(PublishRefused) as refused:
            publish(
                "rehearsal",
                run_id="run-b",
                build=standin("rehearsal", version="from-b"),
                project_dir=project,
            )
        assert refused.value.reason == "lock-taken"
        assert candidate_folders(project) == before
        assert not (project / "warehouse" / "candidate" / "run-run-b").exists()
    finally:
        release.set()
        pool.shutdown()

    publisher_a.result()
    assert read_stamp(published_file(project)) == "from-a"
    assert not (project / "warehouse" / "rehearsal.lock").exists()
    assert candidate_folders(project) == []


def test_company_publish_of_rehearsal_park_fails_unregistered_park(
    tmp_path: Path, landing_root: Path
) -> None:
    """A9: the park registered for another data set is refused, published file unchanged."""
    land_sample(landing_root, "company")
    project = project_for(tmp_path)
    write_stamped(published_file(project, "company"), "before")
    build = standin(
        "company", options=StandinOptions(registered_data_set="rehearsal"), version="new"
    )

    with pytest.raises(PublishFailed) as failed:
        publish("company", build=build, project_dir=project)

    assert failed.value.reason == "unregistered-park"
    assert read_stamp(published_file(project, "company")) == "before"
    assert candidate_folders(project) == []


def replace_landing_at_built(v1: Path) -> Callable[[str], None]:
    def swap(step: str) -> None:
        if step == "built":
            for parquet in v1.glob("*.parquet"):
                parquet.write_bytes(b"not parquet")

    return swap


def test_replacing_landing_at_built_keeps_a_failing_publish_failing(
    tmp_path: Path, landing_root: Path
) -> None:
    """A9: the build reads the snapshot, so a landing swap cannot rescue a refused park."""
    v1 = land_sample(landing_root, "company")
    project = project_for(tmp_path)
    write_stamped(published_file(project, "company"), "before")
    build = standin("company", options=StandinOptions(registered_data_set="rehearsal"))

    with pytest.raises(PublishFailed) as failed:
        publish("company", build=build, on_step=replace_landing_at_built(v1), project_dir=project)

    assert failed.value.reason == "unregistered-park"
    assert read_stamp(published_file(project, "company")) == "before"


def test_replacing_landing_at_built_keeps_a_passing_publish_passing(
    tmp_path: Path, landing_root: Path
) -> None:
    """A9: a landing swap after the snapshot cannot break a publish that would pass."""
    v1 = land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)

    publish(
        "rehearsal",
        build=standin("rehearsal", version="fresh"),
        on_step=replace_landing_at_built(v1),
        project_dir=project,
    )

    assert read_stamp(published_file(project)) == "fresh"


def test_write_open_of_published_file_fails_at_wal_checked_and_leaves_no_wal(
    tmp_path: Path, landing_root: Path
) -> None:
    """A12: a separate process cannot open the published file for writing at the barrier."""
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    build = standin("rehearsal", version="first")
    publish("rehearsal", build=build, project_dir=project)
    outcomes: list[subprocess.CompletedProcess[str]] = []

    def barrier(step: str) -> None:
        if step == "wal-checked":
            outcomes.append(
                subprocess.run(
                    [sys.executable, "-c", WRITE_OPEN, str(published_file(project))],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=WAIT_SECONDS,
                )
            )

    publish(
        "rehearsal",
        build=standin("rehearsal", version="second"),
        on_step=barrier,
        project_dir=project,
    )

    assert len(outcomes) == 1
    assert outcomes[0].returncode != 0
    assert list((project / "warehouse").rglob("*.wal")) == []
    assert read_stamp(published_file(project)) == "second"


def test_interrupted_rotation_rule_runs_after_locked_and_before_candidate_created(
    tmp_path: Path, landing_root: Path
) -> None:
    """The ADR 0017 rule finishes the leftover between the two named steps.

    The steps run in the order ARCHITECTURE.md's publish section gives.
    """
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    published = published_file(project)
    write_stamped(published, "before")
    leftover = project / "warehouse" / "previous" / "rehearsal.duckdb.new"
    leftover.parent.mkdir(parents=True)
    os.link(published, leftover)
    steps: list[str] = []
    leftover_seen: dict[str, bool] = {}

    def observe(step: str) -> None:
        steps.append(step)
        leftover_seen[step] = leftover.exists()

    publish(
        "rehearsal",
        build=standin("rehearsal", version="after"),
        on_step=observe,
        project_dir=project,
    )

    assert leftover_seen["locked"] is True
    assert leftover_seen["candidate-created"] is False
    assert steps == [
        "locked",
        "candidate-created",
        "landing-locked",
        "snapshot-taken",
        "built",
        "audited",
        "wal-checked",
        "previous-linked",
        "renamed",
        "previous-rotated",
        "candidate-removed",
    ]


def test_main_publishes_and_returns_zero(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)

    result = main(
        ["--data-set", "rehearsal"],
        build=standin("rehearsal"),
        project_dir=project,
    )

    assert result == 0
    assert capsys.readouterr().out == (
        f"no interrupted rotation: "
        f"{project / 'warehouse' / 'previous' / 'rehearsal.duckdb.new'} does not exist\n"
        "published warehouse/rehearsal.duckdb: 3 tables, 3 rows; no earlier file kept\n"
    )
    assert published_file(project).is_file()


def test_second_main_publish_reports_rotated_file(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)

    first_result = main(
        ["--data-set", "rehearsal"], build=standin("rehearsal"), project_dir=project
    )
    assert first_result == 0
    capsys.readouterr()

    result = main(
        ["--data-set", "rehearsal"],
        build=standin("rehearsal", version="second"),
        project_dir=project,
    )

    assert result == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "published warehouse/rehearsal.duckdb: 3 tables, 3 rows; "
        "kept warehouse/previous/rehearsal.duckdb for one rollback"
    )


def test_main_rolls_back_and_prints_step_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = project_for(tmp_path)
    write_stamped(published_file(project), "current")
    previous_file = project / "warehouse" / "previous" / "rehearsal.duckdb"
    write_stamped(previous_file, "previous")

    result = main(["--data-set", "rehearsal", "--rollback"], project_dir=project)

    assert result == 0
    assert capsys.readouterr().out == (
        f"no interrupted rotation: "
        f"{project / 'warehouse' / 'previous' / 'rehearsal.duckdb.new'} does not exist\n"
    )
    assert read_stamp(published_file(project)) == "previous"


@pytest.mark.parametrize("run_id", ["../", "/", ""])
def test_main_refuses_invalid_run_id_before_creating_warehouse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], run_id: str
) -> None:
    project = project_for(tmp_path)

    result = main(["--data-set", "rehearsal"], run_id=run_id, project_dir=project)

    assert result == 2
    assert capsys.readouterr().out == (
        f"publish refused: invalid-run-id: invalid run ID: {run_id!r}\n"
    )
    assert not (project / "warehouse").exists()


@pytest.mark.parametrize(
    "case",
    [
        ("rehearsal", StandinOptions(view=True), "views"),
        ("company", StandinOptions(registered_data_set="rehearsal"), "unregistered-park"),
    ],
)
def test_main_reports_candidate_failures(
    tmp_path: Path,
    landing_root: Path,
    capsys: pytest.CaptureFixture[str],
    case: tuple[str, StandinOptions, str],
) -> None:
    data_set, options, reason = case
    land_sample(landing_root, data_set)
    project = project_for(tmp_path)

    result = main(
        ["--data-set", data_set],
        build=standin(data_set, options=options),
        project_dir=project,
    )

    output = capsys.readouterr().out
    assert result == 1
    assert error_line(output).startswith(f"publish failed: {reason}: ")
    assert not (project / "warehouse" / f"{data_set}.lock").exists()
    assert candidate_folders(project) == []


def test_main_reports_contract_failure(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_data(
        landing_root / "rehearsal" / "parquet",
        "UPDATE snapshot SET park_id = NULL, cash_tenths = NULL",
    )
    project = project_for(tmp_path)

    result = main(
        ["--data-set", "rehearsal"],
        build=standin("rehearsal"),
        project_dir=project,
    )

    output = capsys.readouterr().out
    assert result == 1
    # WEAKENED-OK: partition and separator assert moved into error_line(),
    # which also asserts a single newline-terminated line
    assert error_line(output).startswith("publish failed: contracts: ")
    assert candidate_folders(project) == []


def test_main_reports_sequence_audit_failure(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1 = land_sample(landing_root, "rehearsal")
    source = next(v1.glob("*.parquet"))
    rewritten = source.with_suffix(".rewritten.parquet")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            f"COPY (SELECT * REPLACE (0 AS seq) FROM read_parquet('{source}')) "
            f"TO '{rewritten}' (FORMAT PARQUET)"
        )
    finally:
        connection.close()
    rewritten.replace(source)
    project = project_for(tmp_path)

    result = main(
        ["--data-set", "rehearsal"],
        build=standin("rehearsal"),
        project_dir=project,
    )

    assert result == 1
    assert error_line(capsys.readouterr().out).startswith("publish failed: seq-audit: ")
    assert candidate_folders(project) == []


def test_main_reports_unreadable_landing_folder(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    v1 = land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)
    v1.chmod(0)
    try:
        result = main(
            ["--data-set", "rehearsal"],
            build=standin("rehearsal"),
            project_dir=project,
        )
    finally:
        v1.chmod(0o755)

    assert result == 1
    assert error_line(capsys.readouterr().out).startswith("publish failed: snapshot: ")
    assert candidate_folders(project) == []


def test_main_reports_unsafe_warehouse_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = project_for(tmp_path)
    writable = tmp_path / "writable"
    writable.mkdir()
    (project / "warehouse").symlink_to(writable, target_is_directory=True)

    result = main(["--data-set", "rehearsal"], project_dir=project)

    assert result == 2
    assert capsys.readouterr().out.startswith("publish refused: unsafe-path: ")
    assert list(writable.iterdir()) == []


def test_main_reports_missing_manifest_and_missing_previous(
    tmp_path: Path, landing_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    land_sample(landing_root, "rehearsal")
    project = project_for(tmp_path)

    def remove_manifest(candidate_dir: Path, candidate_file: Path, snapshot_dir: Path) -> None:
        standin("rehearsal")(candidate_dir, candidate_file, snapshot_dir)
        (candidate_dir / "target" / "manifest.json").unlink()

    result = main(["--data-set", "rehearsal"], build=remove_manifest, project_dir=project)

    assert result == 1
    assert error_line(capsys.readouterr().out).startswith("publish failed: empty: ")
    assert candidate_folders(project) == []

    result = main(["--data-set", "rehearsal", "--rollback"], project_dir=project)

    assert result == 1
    assert error_line(capsys.readouterr().out).startswith("publish failed: no-previous: ")
    assert not (project / "warehouse" / "rehearsal.lock").exists()
