"""Behavioral tests for scripts/check_metric_catalog_shape.py.

The skip decision is tested as a pure function. Two tests run the script, with real dbt, on a
temporary copy of the dbt project. They skip only when the script itself printed the skip line,
which needs `CI` unset, so a sandbox crash fails them in CI.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import check_metric_catalog_shape as shape

REPO = Path(__file__).resolve().parent.parent
OUTPUT = "Encountered an error:\nPermissionError: [Errno 13] os.sysconf('SC_SEM_NSEMS_MAX')\n"
PRIMARY_ENTITY_LINE = "    primary_entity: park_month\n"
VALIDATOR = "dbt_semantic_interfaces.validations.semantic_manifest_validator"
# Runs ahead of the script's parse code: any process pool raises, and a thread pool prints the
# module that created it, so the parse passes only if dbt's validator got a thread pool.
POOL_GUARD = """
import concurrent.futures
import sys


class NoProcessPool:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("a process pool was created")


class ReportingThreadPool(concurrent.futures.ThreadPoolExecutor):
    def __init__(self, *args, **kwargs):
        print("thread pool for", sys._getframe(1).f_globals["__name__"])
        super().__init__(*args, **kwargs)


concurrent.futures.ProcessPoolExecutor = NoProcessPool
concurrent.futures.ThreadPoolExecutor = ReportingThreadPool
"""


def test_both_markers_with_ci_unset_skip_and_exit_zero() -> None:
    assert shape.decide(1, OUTPUT, None) == shape.Decision(0, shape.SKIP_LINE)
    assert shape.decide(1, OUTPUT, "") == shape.Decision(0, shape.SKIP_LINE)
    assert shape.SKIP_LINE == (
        "skipped: sandbox process-pool limit; allowed only while CI is unset"
    )


def test_both_markers_with_ci_set_refuse_the_skip_and_keep_the_error_text() -> None:
    decision = shape.decide(1, OUTPUT, "true")

    assert decision.exit_code == 1
    assert "PermissionError" in decision.message
    assert decision.message != shape.SKIP_LINE


@pytest.mark.parametrize("ci", [None, "true"])
def test_one_marker_alone_fails_whatever_ci_says(ci: str | None) -> None:
    for output in ("PermissionError: no", "SC_SEM_NSEMS_MAX only"):
        assert shape.decide(1, output, ci).exit_code == 1


@pytest.mark.parametrize("ci", [None, "true"])
def test_an_unrelated_failure_fails_whatever_ci_says(ci: str | None) -> None:
    decision = shape.decide(1, "Semantic Manifest validation failed.", ci)

    assert decision == shape.Decision(1, "Semantic Manifest validation failed.")


def test_a_clean_parse_exits_zero() -> None:
    assert shape.decide(0, "", "true").exit_code == 0


def copy_project(root: Path) -> None:
    for name in shape.COPIED:
        source = REPO / name
        if source.is_dir():
            shutil.copytree(source, root / name)
        else:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, root / name)
    (root / "metrics").mkdir()
    for path in sorted((REPO / "metrics").glob("*.yml")):
        shutil.copy2(path, root / "metrics" / path.name)


def run_or_skip(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = shape.main([str(root)])
    captured = capsys.readouterr()
    text = captured.out + captured.err
    if shape.SKIP_LINE in text:
        # WEAKENED-OK: sandbox semaphore crash; the skip refuses when CI is set
        pytest.skip("dbt's process pool is blocked here and CI is unset")
    return code, text


def test_the_committed_catalog_passes_dbt_parse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy_project(tmp_path)

    code, text = run_or_skip(tmp_path, capsys)

    assert code == 0, text


def test_a_deleted_primary_entity_fails_dbt_parse(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    copy_project(tmp_path)
    holders = [
        path
        for path in sorted((tmp_path / "metrics").glob("*.yml"))
        if PRIMARY_ENTITY_LINE in path.read_text(encoding="utf-8")
    ]
    assert holders
    catalog = holders[0]
    text = catalog.read_text(encoding="utf-8")
    catalog.write_text(text.replace(PRIMARY_ENTITY_LINE, "", 1), encoding="utf-8")

    code, output = run_or_skip(tmp_path, capsys)

    assert code != 0
    assert "primary entity" in output


def test_a_missing_catalog_exits_one(tmp_path: Path) -> None:
    assert shape.main([str(tmp_path)]) == 1


def test_an_empty_metrics_folder_exits_one_with_its_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "metrics").mkdir()

    code = shape.main([str(tmp_path)])

    assert code == 1
    assert capsys.readouterr().err == "metrics/: no catalog file\n"


def test_every_catalog_file_is_copied_into_the_project_without_running_dbt(
    tmp_path: Path,
) -> None:
    root, work = tmp_path / "root", tmp_path / "work"
    (root / "metrics").mkdir(parents=True)
    work.mkdir()
    for stem in ("first", "second"):
        (root / "metrics" / f"{stem}.yml").write_text(
            "semantic_models: []\nmetrics: []\n", encoding="utf-8"
        )

    shape.build_project(root, work)

    assert (work / "models" / "metric_catalog_first.yml").is_file()
    assert (work / "models" / "metric_catalog_second.yml").is_file()


def test_dbt_parse_runs_its_validator_on_a_thread_pool_never_a_process_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shape.build_project(REPO, tmp_path)
    monkeypatch.setattr(shape, "PARSE_WITH_THREADS", POOL_GUARD + shape.PARSE_WITH_THREADS)

    code, output = shape.run_parse(tmp_path)

    assert code == 0, output
    assert f"thread pool for {VALIDATOR}" in output
