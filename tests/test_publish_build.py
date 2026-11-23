"""The publish dbt build command, exercised through a stand-in executable."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from openrct2_analytics.ingest.publish_build import run_dbt_build
from openrct2_analytics.ingest.publish_errors import PublishFailed, exit_code


def _build_paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    project_dir = tmp_path / "project"
    candidate_dir = project_dir / "warehouse" / "candidate" / "run-test-id"
    candidate_dir.mkdir(parents=True)
    candidate_file = candidate_dir / "rehearsal.duckdb"
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    return project_dir, candidate_dir, candidate_file, snapshot_dir


def _stand_in(
    tmp_path: Path,
    record: Path,
    exit_code: int = 0,
    *,
    stdout: str = "",
    stderr: str = "",
    warehouse_file: Path | None = None,
) -> tuple[str, ...]:
    script = tmp_path / "dbt-stand-in.py"
    record_literal = json.dumps(str(record))
    warehouse_write = (
        f"Path({json.dumps(str(warehouse_file))}).touch()\n" if warehouse_file is not None else ""
    )
    script.write_text(
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({record_literal}).write_text(json.dumps({{\n"
        "    'argv': sys.argv[1:],\n"
        "    'cwd': os.getcwd(),\n"
        "    'run_id': os.environ.get('OPENRCT2_PUBLISH_RUN_ID'),\n"
        "    'inherited': os.environ.get('PUBLISH_BUILD_INHERITED_TEST'),\n"
        "}), encoding='utf-8')\n" + warehouse_write + f"sys.stdout.write({json.dumps(stdout)})\n"
        f"sys.stderr.write({json.dumps(stderr)})\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    return sys.executable, str(script)


def test_runs_exact_dbt_command_and_calls_built_after_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir, candidate_dir, candidate_file, snapshot_dir = _build_paths(tmp_path)
    record = tmp_path / "record.json"
    steps: list[str] = []
    monkeypatch.setenv("PUBLISH_BUILD_INHERITED_TEST", "preserved")

    def record_step(step: str) -> None:
        assert record.is_file()
        steps.append(step)

    run_dbt_build(
        project_dir,
        "rehearsal",
        "publish-run-7",
        candidate_dir,
        candidate_file,
        snapshot_dir,
        record_step,
        _stand_in(tmp_path, record, warehouse_file=candidate_file),
    )

    result: dict[str, object] = json.loads(record.read_text(encoding="utf-8"))
    assert result == {
        "argv": [
            "build",
            "--profiles-dir",
            ".",
            "--target",
            "rehearsal",
            "--target-path",
            str(candidate_dir / "target"),
            "--log-path",
            str(candidate_dir / "logs"),
            "--vars",
            f"{{parquet_root: '{snapshot_dir.resolve()}',"
            f" registry_root: '{snapshot_dir.resolve() / 'registry'}'}}",
        ],
        "cwd": str(project_dir),
        "run_id": "publish-run-7",
        "inherited": "preserved",
    }
    assert steps == ["built"]


def test_registry_root_variable_points_at_the_snapshot_feed_copy(tmp_path: Path) -> None:
    """dbt receives the feed copy's folder beside the Parquet folder."""
    project_dir, candidate_dir, candidate_file, snapshot_dir = _build_paths(tmp_path)
    record = tmp_path / "record.json"

    run_dbt_build(
        project_dir,
        "rehearsal",
        "publish-run-7",
        candidate_dir,
        candidate_file,
        snapshot_dir,
        lambda _step: None,
        _stand_in(tmp_path, record, warehouse_file=candidate_file),
    )

    argv: list[str] = json.loads(record.read_text(encoding="utf-8"))["argv"]
    variables = argv[argv.index("--vars") + 1]
    assert f"registry_root: '{snapshot_dir.resolve() / 'registry'}'" in variables


def test_zero_exit_without_candidate_file_fails_as_dbt(tmp_path: Path) -> None:
    project_dir, candidate_dir, candidate_file, snapshot_dir = _build_paths(tmp_path)
    record = tmp_path / "record.json"
    steps: list[str] = []

    with pytest.raises(PublishFailed) as raised:
        run_dbt_build(
            project_dir,
            "rehearsal",
            "publish-run-11",
            candidate_dir,
            candidate_file,
            snapshot_dir,
            steps.append,
            _stand_in(tmp_path, record),
        )

    assert raised.value.reason == "dbt"
    assert str(candidate_file) in raised.value.detail
    assert steps == []
    assert record.is_file()


def test_nonzero_exit_fails_with_code_and_does_not_call_built(tmp_path: Path) -> None:
    project_dir, candidate_dir, candidate_file, snapshot_dir = _build_paths(tmp_path)
    record = tmp_path / "record.json"
    steps: list[str] = []

    with pytest.raises(PublishFailed) as raised:
        run_dbt_build(
            project_dir,
            "rehearsal",
            "publish-run-8",
            candidate_dir,
            candidate_file,
            snapshot_dir,
            steps.append,
            _stand_in(
                tmp_path,
                record,
                exit_code=17,
                stdout="stdout model failure\n",
                stderr="stderr test failure\n",
            ),
        )

    assert raised.value.reason == "dbt"
    assert "17" in raised.value.detail
    assert "stdout model failure" in raised.value.detail
    assert "stderr test failure" in raised.value.detail
    assert "\n" not in raised.value.detail
    assert steps == []
    assert record.is_file()


def test_nonzero_exit_limits_appended_output_to_1000_characters(tmp_path: Path) -> None:
    project_dir, candidate_dir, candidate_file, snapshot_dir = _build_paths(tmp_path)
    record = tmp_path / "record.json"
    long_output = "".join(f"model failure {index}: {'x' * 120}\n" for index in range(20))

    with pytest.raises(PublishFailed) as raised:
        run_dbt_build(
            project_dir,
            "rehearsal",
            "publish-run-10",
            candidate_dir,
            candidate_file,
            snapshot_dir,
            lambda _: None,
            _stand_in(
                tmp_path,
                record,
                exit_code=17,
                stdout=long_output,
            ),
        )

    detail_prefix = "dbt exited with code 17: "
    assert raised.value.detail.startswith(detail_prefix)
    assert len(raised.value.detail.removeprefix(detail_prefix)) == 1000


def test_nonzero_exit_names_all_dbt_test_failures_before_the_1000_character_tail(
    tmp_path: Path,
) -> None:
    project_dir, candidate_dir, candidate_file, snapshot_dir = _build_paths(tmp_path)
    record = tmp_path / "record.json"
    tail = "x" * 1200
    stdout = (
        "Failure in test first_test (tests/dbt/first_test.sql)\n"
        "\x1b[31mFailure in unit_test second_test (models/second_test.yml)\x1b[0m\n"
        "Failure in model some_model (models/some_model.sql)\n"
        f"{tail}\n"
    )

    with pytest.raises(PublishFailed) as raised:
        run_dbt_build(
            project_dir,
            "rehearsal",
            "publish-run-12",
            candidate_dir,
            candidate_file,
            snapshot_dir,
            lambda _: None,
            _stand_in(tmp_path, record, exit_code=17, stdout=stdout),
        )

    detail = raised.value.detail
    assert "failing tests: first_test, second_test" in detail
    assert "some_model" not in detail
    assert detail.endswith(tail[-1000:])


def test_nonzero_exit_limits_failing_test_summary_to_10(tmp_path: Path) -> None:
    project_dir, candidate_dir, candidate_file, snapshot_dir = _build_paths(tmp_path)
    record = tmp_path / "record.json"
    stdout = (
        "".join(
            f"Failure in test test_{index:02} (tests/dbt/test_{index:02}.sql)\n"
            for index in range(15)
        )
        + "dbt diagnostic tail\n" * 10
    )

    with pytest.raises(PublishFailed) as raised:
        run_dbt_build(
            project_dir,
            "rehearsal",
            "publish-run-13",
            candidate_dir,
            candidate_file,
            snapshot_dir,
            lambda _: None,
            _stand_in(tmp_path, record, exit_code=17, stdout=stdout),
        )

    detail = raised.value.detail
    for index in range(10):
        assert f"test_{index:02}" in detail
    assert "test_10" not in detail
    assert "and 5 more" in detail


def test_symlink_candidate_is_refused_before_the_stand_in_runs(tmp_path: Path) -> None:
    project_dir, candidate_dir, candidate_file, snapshot_dir = _build_paths(tmp_path)
    target = tmp_path / "outside.duckdb"
    target.touch()
    candidate_file.symlink_to(target)
    record = tmp_path / "record.json"
    steps: list[str] = []

    with pytest.raises(PublishFailed) as raised:
        run_dbt_build(
            project_dir,
            "rehearsal",
            "publish-run-9",
            candidate_dir,
            candidate_file,
            snapshot_dir,
            steps.append,
            _stand_in(tmp_path, record),
        )

    assert raised.value.reason == "unsafe-path"
    assert exit_code(raised.value) == 1
    assert steps == []
    assert not record.exists()
