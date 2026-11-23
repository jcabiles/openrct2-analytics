"""Makefile tests for how delete-company-data takes its variables."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.test_makefile import MAKEFILE, make_n


def test_delete_variables_reject_dollars_and_environment() -> None:
    for variable in ("PARK", "SESSION", "CONFIRM"):
        result = make_n("delete-company-data", f"{variable}=a$(shell touch unsafe)")
        assert result.returncode != 0
        assert "dollar sign" in result.stderr
        result = make_n("delete-company-data", env_extra={variable: "value"})
        assert result.returncode != 0
        assert "command line" in result.stderr


def test_delete_values_reach_command_as_single_literal_arguments(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    uv.chmod(0o755)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PARK", "SESSION", "CONFIRM", "MAKEFLAGS", "MAKELEVEL"}
    }
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    value = "a; 'quoted' \"double\" words"
    for variable in ("PARK", "SESSION", "CONFIRM"):
        result = subprocess.run(
            ["make", "--no-print-directory", "delete-company-data", f"{variable}={value}"],
            cwd=MAKEFILE.parent,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "run",
            "python",
            "-m",
            "openrct2_analytics.ingest.delete_data",
            f"--{variable.lower()}={value}",
        ]


def test_delete_empty_values_reach_command_as_empty_arguments(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
    uv.chmod(0o755)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PARK", "SESSION", "CONFIRM", "MAKEFLAGS", "MAKELEVEL"}
    }
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    for variable in ("PARK", "SESSION", "CONFIRM"):
        result = subprocess.run(
            ["make", "--no-print-directory", "delete-company-data", f"{variable}="],
            cwd=MAKEFILE.parent,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == [
            "run",
            "python",
            "-m",
            "openrct2_analytics.ingest.delete_data",
            f"--{variable.lower()}=",
        ]

    result = subprocess.run(
        ["make", "--no-print-directory", "delete-company-data"],
        cwd=MAKEFILE.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "run",
        "python",
        "-m",
        "openrct2_analytics.ingest.delete_data",
    ]
