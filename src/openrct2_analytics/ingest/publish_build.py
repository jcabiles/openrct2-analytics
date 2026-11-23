"""Build a candidate warehouse with dbt."""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused
from openrct2_analytics.ingest.publish_prepare import guard_path

_DBT_OUTPUT_LINES = 10
_DBT_OUTPUT_MAX_CHARS = 1000
_DBT_FAILING_TESTS_MAX = 10
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_DBT_TEST_RESULT = re.compile(r"(?:^|\s)Failure in (?:unit_)?test ([^\s(]+) \(")


def _dbt_failure_detail(returncode: int, stdout: str, stderr: str) -> str:
    stdout_lines = [line for line in stdout.splitlines() if line.strip()][-_DBT_OUTPUT_LINES:]
    stderr_lines = [line for line in stderr.splitlines() if line.strip()][-_DBT_OUTPUT_LINES:]
    appended_output = " | ".join([*stdout_lines, *stderr_lines])
    tail = appended_output[-_DBT_OUTPUT_MAX_CHARS:]
    failing_tests = list(dict.fromkeys(_DBT_TEST_RESULT.findall(_ANSI_ESCAPE.sub("", stdout))))
    if failing_tests:
        listed_tests = failing_tests[:_DBT_FAILING_TESTS_MAX]
        test_summary = f"failing tests: {', '.join(listed_tests)}"
        remaining_tests = len(failing_tests) - len(listed_tests)
        if remaining_tests:
            test_summary += f" and {remaining_tests} more"
        return f"dbt exited with code {returncode}: {test_summary} | {tail}"
    return f"dbt exited with code {returncode}: {tail}"


def run_dbt_build(  # noqa: PLR0913, PLR0917  # step API is fixed by the publish specification
    project_dir: Path,
    name: str,
    run_id: str,
    candidate_dir: Path,
    candidate_file: Path,
    snapshot_dir: Path,
    on_step: Callable[[str], None],
    dbt_argv: tuple[str, ...] = ("dbt",),
) -> None:
    """Build the candidate warehouse and report completion through ``on_step``.

    Args:
        project_dir: The dbt project folder and subprocess working directory.
        name: The dbt target name.
        run_id: The publish run ID passed to dbt's environment.
        candidate_dir: The isolated folder for this candidate build.
        candidate_file: The DuckDB file dbt will build.
        snapshot_dir: The copied Parquet snapshot dbt will read.
        on_step: Called with ``built`` only after dbt succeeds.
        dbt_argv: Executable and leading arguments, replaceable by a test stand-in.

    Raises:
        PublishFailed: If the candidate file is an unsafe warehouse path, or if dbt cannot
            start, exits unsuccessfully, or writes no candidate file.
    """
    try:
        guard_path(
            candidate_file,
            root=project_dir / "warehouse",
            project_dir=project_dir,
        )
    except PublishRefused as error:
        # Step 6 runs after the lock is taken, so an unsafe candidate fails the run (exit 1).
        raise PublishFailed(error.reason, error.detail) from error

    command = [
        *dbt_argv,
        "build",
        "--profiles-dir",
        ".",
        "--target",
        name,
        "--target-path",
        str(candidate_dir / "target"),
        "--log-path",
        str(candidate_dir / "logs"),
        "--vars",
        f"{{parquet_root: '{snapshot_dir.resolve()}',"
        f" registry_root: '{snapshot_dir.resolve() / 'registry'}'}}",
    ]
    environment = {**os.environ, "OPENRCT2_PUBLISH_RUN_ID": run_id}
    try:
        result = subprocess.run(  # noqa: S603  # argument list, never a shell command
            command,
            cwd=project_dir,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise PublishFailed("dbt", f"could not start dbt: {exc}") from exc
    if result.returncode != 0:
        raise PublishFailed(
            "dbt",
            _dbt_failure_detail(result.returncode, result.stdout, result.stderr),
        )
    if not candidate_file.is_file():
        raise PublishFailed(
            "dbt",
            f"dbt exited 0 but wrote no warehouse file at {candidate_file}",
        )
    on_step("built")
