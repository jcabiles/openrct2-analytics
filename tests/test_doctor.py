"""Behavioral tests for scripts/doctor.py on fake virtual environments built in a temp folder."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from doctor import main, scan_record_files

# The Makefile wiring tests read this folder's Makefile; a planted-break run points it at a copy.
REPO_ROOT = Path(os.environ.get("DOCTOR_TEST_ROOT", Path(__file__).resolve().parent.parent))
PASSING_PROGRAM = "#!/bin/sh\nexit 0\n"


def write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def add_package(site: Path, name: str, present: list[str], absent: list[str]) -> Path:
    """Install a fake package: write the `present` files and list all of them in RECORD."""
    for rel in present:
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text("x", encoding="utf-8")
    info = site / f"{name}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    rows = [f"{rel},," for rel in [*present, *absent]] + [f"{info.name}/RECORD,,"]
    (info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return info


def make_venv(root: Path, home: Path | None = None) -> Path:
    """Build a fake `.venv` with passing python and dbt stubs and an empty site-packages."""
    venv = root / ".venv"
    (venv / "bin").mkdir(parents=True)
    write_executable(venv / "bin" / "python", PASSING_PROGRAM)
    write_executable(venv / "bin" / "dbt", PASSING_PROGRAM)
    home = home or root / "managed" / "cpython-3.12" / "bin"
    (venv / "pyvenv.cfg").write_text(f"home = {home}\nversion = 3.12\n", encoding="utf-8")
    site = venv / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    return site


def run_doctor(root: Path) -> int:
    return main(["--root", str(root), "--managed-dir", str(root / "managed")])


def test_missing_record_file_is_reported_and_exits_non_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = make_venv(tmp_path)
    add_package(site, "goodpkg", ["goodpkg/__init__.py"], [])
    add_package(site, "brokenpkg", ["brokenpkg/__init__.py"], ["brokenpkg/core.py"])

    assert scan_record_files(site).missing == {"brokenpkg-1.0.dist-info": ["brokenpkg/core.py"]}
    assert run_doctor(tmp_path) == 1
    err = capsys.readouterr().err
    assert "brokenpkg/core.py" in err
    assert "goodpkg" not in err
    assert "rm -rf .venv && make setup" in err
    assert "uv sync" in err


def test_healthy_environment_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    site = make_venv(tmp_path)
    add_package(site, "goodpkg", ["goodpkg/__init__.py"], [])

    assert run_doctor(tmp_path) == 0
    assert "doctor: took" in capsys.readouterr().out


def test_bytecode_entries_are_ignored(tmp_path: Path) -> None:
    site = make_venv(tmp_path)
    add_package(
        site,
        "pkg",
        ["pkg/__init__.py"],
        ["pkg/__pycache__/__init__.cpython-312.pyc", "pkg/stale.pyc"],
    )

    assert scan_record_files(site).missing == {}
    assert run_doctor(tmp_path) == 0


def test_home_outside_managed_folder_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_venv(tmp_path, home=tmp_path / "elsewhere" / "bin")

    assert run_doctor(tmp_path) == 1
    err = capsys.readouterr().err
    assert "not inside uv's managed folder" in err
    assert "rm -rf .venv && make setup" in err


def test_missing_venv_python_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_doctor(tmp_path) == 1
    assert ".venv/bin/python" in capsys.readouterr().err


def test_missing_pyvenv_cfg_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_venv(tmp_path)
    (tmp_path / ".venv" / "pyvenv.cfg").unlink()

    assert run_doctor(tmp_path) == 1
    assert "pyvenv.cfg is missing" in capsys.readouterr().err


def test_missing_pyvenv_cfg_fails_without_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "no-tools"))
    make_venv(tmp_path)
    (tmp_path / ".venv" / "pyvenv.cfg").unlink()

    assert main(["--root", str(tmp_path)]) == 1
    assert "pyvenv.cfg is missing" in capsys.readouterr().err


def test_missing_site_packages_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    site = make_venv(tmp_path)
    site.rmdir()

    assert run_doctor(tmp_path) == 1
    assert "no site-packages folder" in capsys.readouterr().err


def test_dist_info_without_record_is_unverifiable_not_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = make_venv(tmp_path)
    info = add_package(site, "norecord", ["norecord/__init__.py"], [])
    (info / "RECORD").unlink()

    assert run_doctor(tmp_path) == 0
    assert "cannot verify: norecord-1.0.dist-info" in capsys.readouterr().out


def test_dist_info_without_record_and_without_code_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = make_venv(tmp_path)
    info = add_package(site, "gone", [], [])
    (info / "RECORD").unlink()

    assert run_doctor(tmp_path) == 1
    assert "gone-1.0.dist-info" in capsys.readouterr().err


def test_dist_info_without_metadata_does_not_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = make_venv(tmp_path)
    nometa = add_package(site, "nometa", ["nometa/__init__.py"], ["nometa/core.py"])
    (nometa / "METADATA").unlink()
    add_package(site, "other", ["other/__init__.py"], ["other/core.py"])

    assert run_doctor(tmp_path) == 1
    err = capsys.readouterr().err
    assert "nometa/core.py" in err
    assert "other/core.py" in err


def test_egg_info_install_is_unverifiable_not_failed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = make_venv(tmp_path)
    (site / "legacy.py").write_text("x", encoding="utf-8")
    (site / "legacy-1.0.egg-info").mkdir()

    assert run_doctor(tmp_path) == 0
    assert "cannot verify: legacy-1.0.egg-info" in capsys.readouterr().out


def test_uv_absent_skips_the_managed_check_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "no-tools"))
    make_venv(tmp_path, home=Path("/usr/lib/python3.12"))

    assert main(["--root", str(tmp_path)]) == 0
    assert "skipped: uv is not on PATH" in capsys.readouterr().out


def test_managed_folder_is_asked_of_uv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    write_executable(tools / "uv", f"#!/bin/sh\necho {tmp_path / 'managed'}\n")
    monkeypatch.setenv("PATH", str(tools))
    make_venv(tmp_path)
    assert main(["--root", str(tmp_path)]) == 0

    (tmp_path / ".venv" / "pyvenv.cfg").write_text("home = /elsewhere/bin\n", encoding="utf-8")
    assert main(["--root", str(tmp_path)]) == 1
    assert "not inside uv's managed folder" in capsys.readouterr().err


def test_failing_uv_python_dir_has_its_own_message_not_the_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    write_executable(tools / "uv", "#!/bin/sh\necho no such command >&2\nexit 2\n")
    monkeypatch.setenv("PATH", str(tools))
    make_venv(tmp_path)

    assert main(["--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "`uv python dir` exited 2: no such command" in err
    assert "rm -rf" not in err


def test_missing_dbt_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_venv(tmp_path)
    (tmp_path / ".venv" / "bin" / "dbt").unlink()

    assert run_doctor(tmp_path) == 1
    assert "bin/dbt is missing" in capsys.readouterr().err


def test_non_executable_dbt_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_venv(tmp_path)
    (tmp_path / ".venv" / "bin" / "dbt").chmod(0o644)

    assert run_doctor(tmp_path) == 1
    assert "bin/dbt is not executable" in capsys.readouterr().err


def test_python_that_cannot_launch_is_reported_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_venv(tmp_path)
    write_executable(tmp_path / ".venv" / "bin" / "python", "#!/nonexistent/interpreter\n")

    assert run_doctor(tmp_path) == 1
    err = capsys.readouterr().err
    assert "cannot be launched" in err
    assert "rm -rf .venv && make setup" in err


def test_failed_import_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_venv(tmp_path)
    write_executable(
        tmp_path / ".venv" / "bin" / "python", "#!/bin/sh\necho ModuleNotFoundError >&2\nexit 1\n"
    )

    assert run_doctor(tmp_path) == 1
    assert "ModuleNotFoundError" in capsys.readouterr().err


def test_unreadable_entry_is_a_note_not_damage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = make_venv(tmp_path)
    add_package(site, "certs", ["certs/data/cacert.pem"], [])
    locked = site / "certs" / "data"
    locked.chmod(0o000)
    try:
        code = run_doctor(tmp_path)
    finally:
        locked.chmod(0o755)

    out = capsys.readouterr()
    assert code == 0
    assert "present but unreadable here: certs-1.0.dist-info" in out.out
    assert "rm -rf" not in out.err


def test_long_lists_are_summarized_and_capped(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    site = make_venv(tmp_path)
    add_package(site, "big", ["big/__init__.py"], [f"big/m{i:02d}.py" for i in range(12)])

    assert run_doctor(tmp_path) == 1
    err = capsys.readouterr().err
    assert err.index("1 package(s) with 12 missing file(s)") < err.index("big/m00.py")
    assert "big-1.0.dist-info: 12 missing" in err
    assert err.count("big/m") == 5
    assert "and 7 more" in err
    assert err.index("and 7 more") < err.index("Repair:")


def dry_run(target: str) -> str:
    result = subprocess.run(
        ["make", "-n", "-C", str(REPO_ROOT), target],
        capture_output=True,
        text=True,
        check=True,
        env={k: v for k, v in os.environ.items() if k != "MAKEFLAGS"},
    )
    return result.stdout


@pytest.mark.parametrize("target", ["setup", "check"])
def test_make_target_runs_the_doctor(target: str) -> None:
    assert "scripts/doctor.py" in dry_run(target)
