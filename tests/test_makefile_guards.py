"""The PRACTICE, PARKS, PUBLISHED, PARK and READY guards, and the label checker wiring."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tests.test_makefile import MAKEFILE, make_n, recipe


def run_recipe(tmp_path: Path, target: str, *args: str) -> list[str]:
    """Run the real recipe of `target` with a stand-in Python; return the argv it received."""
    stand_in = tmp_path / ".venv" / "bin" / "python"
    stand_in.parent.mkdir(parents=True)
    stand_in.write_text('#!/bin/sh\nprintf \'%s\\n\' "$@" > "$ARGV_FILE"\n', encoding="utf-8")
    stand_in.chmod(0o755)
    argv_file = tmp_path / "argv.txt"
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MAKELEVEL", "DATA_SET"}}
    # A PATH without uv makes the recipe pick the stand-in under .venv/bin.
    env.update({"PATH": "/usr/bin:/bin", "ARGV_FILE": str(argv_file)})
    result = subprocess.run(
        ["make", "-f", str(MAKEFILE), target, "DATA_SET=company", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return argv_file.read_text(encoding="utf-8").splitlines()


def test_practice_and_published_reach_their_module_only_as_flags() -> None:
    practice = make_n("register-parks", "DATA_SET=company", "PRACTICE=yes")
    assert practice.returncode == 0, practice.stderr
    assert "ingest.register_parks --data-set company --practice" in practice.stdout
    plain = make_n("register-parks", "DATA_SET=company")
    assert "--practice" not in plain.stdout
    published = make_n("results", "DATA_SET=company", "PUBLISHED=yes")
    assert published.returncode == 0, published.stderr
    assert "ingest.results --data-set company --published" in published.stdout
    assert "--published" not in make_n("results", "DATA_SET=company").stdout


def test_practice_and_published_are_refused_from_the_environment_or_with_a_bad_value() -> None:
    for target, name in (("register-parks", "PRACTICE"), ("results", "PUBLISHED")):
        for value in ("yes", ""):
            result = make_n(target, "DATA_SET=company", env_extra={name: value})
            assert result.returncode != 0, (target, value)
            assert name in result.stderr
            assert "python -m" not in result.stdout
        for value in ("no", "true", "yes; touch y", "Yes"):
            result = make_n(target, "DATA_SET=company", f"{name}={value}")
            assert result.returncode != 0, (target, value)
            assert name in result.stderr
            assert "python -m" not in result.stdout


def test_an_exported_practice_or_published_does_not_stop_other_targets() -> None:
    for target in ("convert", "results", "register-parks"):
        for name in ("PRACTICE", "PUBLISHED"):
            if (target, name) in (("results", "PUBLISHED"), ("register-parks", "PRACTICE")):
                continue
            result = make_n(target, "DATA_SET=company", env_extra={name: "yes"})
            assert result.returncode == 0, (target, name, result.stderr)


def test_parks_reaches_its_module_only_from_the_command_line() -> None:
    for target, module in (
        ("register-parks", "ingest.register_parks"),
        ("after-play", "ingest.after_play"),
    ):
        listed = make_n(target, "DATA_SET=company", "PARKS=a:company,b:practice")
        assert listed.returncode == 0, listed.stderr
        assert f"{module} --data-set company" in listed.stdout
        assert '${PARKS+--parks="$PARKS"}' in listed.stdout
        result = make_n(target, "DATA_SET=company", env_extra={"PARKS": "a:company"})
        assert result.returncode != 0, target
        assert "PARKS" in result.stderr and "command line" in result.stderr
        result = make_n(target, "DATA_SET=company", "PARKS=a$(shell touch unsafe)")
        assert result.returncode != 0, target
        assert "dollar sign" in result.stderr


def test_an_empty_parks_on_the_command_line_is_accepted() -> None:
    # The module treats the empty list as no list; the Makefile must not refuse it first.
    for target in ("register-parks", "after-play"):
        result = make_n(target, "DATA_SET=company", "PARKS=")
        assert result.returncode == 0, (target, result.stderr)


def test_an_exported_parks_does_not_stop_other_targets() -> None:
    for target in ("convert", "results", "play-status", "unfiled"):
        result = make_n(target, "DATA_SET=company", env_extra={"PARKS": "a:company"})
        assert result.returncode == 0, (target, result.stderr)


def test_start_year_part_is_in_both_recipes() -> None:
    for target, module in (
        ("register-parks", "ingest.register_parks"),
        ("after-play", "ingest.after_play"),
    ):
        listed = make_n(target, "DATA_SET=company", "START_YEAR=2001")
        assert listed.returncode == 0, listed.stderr
        assert f"{module} --data-set company" in listed.stdout
        assert '${START_YEAR+--start-year="$START_YEAR"}' in listed.stdout


def test_start_year_reaches_the_register_parks_module_as_its_own_arguments(
    tmp_path: Path,
) -> None:
    argv = run_recipe(tmp_path, "register-parks", "START_YEAR=2005")
    assert argv == [
        "-m",
        "openrct2_analytics.ingest.register_parks",
        "--data-set",
        "company",
        "--start-year=2005",
    ]


def test_start_year_reaches_the_after_play_module_as_its_own_arguments(tmp_path: Path) -> None:
    argv = run_recipe(tmp_path, "after-play", "START_YEAR=2005")
    assert argv == [
        "-m",
        "openrct2_analytics.ingest.after_play",
        "--data-set",
        "company",
        "--start-year=2005",
    ]


def test_no_start_year_flag_reaches_the_module_when_none_is_given(tmp_path: Path) -> None:
    for target in ("register-parks", "after-play"):
        assert not any(a.startswith("--start-year") for a in run_recipe(tmp_path / target, target))


def test_parks_reaches_the_register_parks_module_as_its_own_arguments(tmp_path: Path) -> None:
    argv = run_recipe(tmp_path, "register-parks", "PARKS=a:company,b:practice")
    assert argv[-1] == "--parks=a:company,b:practice"


def test_parks_reaches_the_after_play_module_as_its_own_arguments(tmp_path: Path) -> None:
    argv = run_recipe(tmp_path, "after-play", "PARKS=a:company,b:practice")
    assert argv[-1] == "--parks=a:company,b:practice"


def test_no_parks_flag_reaches_the_module_when_none_is_given(tmp_path: Path) -> None:
    for target in ("register-parks", "after-play"):
        assert not any(a.startswith("--parks") for a in run_recipe(tmp_path / target, target))


def test_an_exported_start_year_is_refused() -> None:
    for target in ("register-parks", "after-play"):
        result = make_n(target, "DATA_SET=company", env_extra={"START_YEAR": "2001"})
        assert result.returncode != 0, target
        assert "START_YEAR must be given on the command line" in result.stderr
        assert "python -m" not in result.stdout


def test_a_start_year_with_a_dollar_sign_is_refused() -> None:
    for target in ("register-parks", "after-play"):
        result = make_n(target, "DATA_SET=company", "START_YEAR=20$(shell true)")
        assert result.returncode != 0, target
        assert "START_YEAR must not contain a dollar sign" in result.stderr


def test_an_empty_start_year_on_the_command_line_is_accepted() -> None:
    # Python checks the digits; the Makefile must not refuse an empty value first.
    for target in ("register-parks", "after-play"):
        result = make_n(target, "DATA_SET=company", "START_YEAR=")
        assert result.returncode == 0, (target, result.stderr)


def test_an_exported_start_year_does_not_stop_other_targets() -> None:
    for target in ("convert", "results", "play-status", "unfiled"):
        result = make_n(target, "DATA_SET=company", env_extra={"START_YEAR": "2001"})
        assert result.returncode == 0, (target, result.stderr)


def test_autopilot_year_runs_its_module_with_the_given_park_and_ready_phrase() -> None:
    result = make_n("autopilot-year", "DATA_SET=company", "PARK=park-1", "READY=park-1 is ready")
    assert result.returncode == 0, result.stderr
    assert "ingest.autopilot_year --data-set company" in result.stdout
    assert '${PARK+--park="$PARK"}' in result.stdout
    assert '${READY+--ready="$READY"}' in result.stdout


def test_autopilot_year_refuses_an_exported_data_set() -> None:
    result = make_n("autopilot-year", "PARK=p1", env_extra={"DATA_SET": "company"})
    assert result.returncode != 0
    assert "DATA_SET must be given on the command line" in result.stderr
    assert "python -m" not in result.stdout


def test_autopilot_year_refuses_an_exported_park() -> None:
    result = make_n("autopilot-year", "DATA_SET=company", env_extra={"PARK": "p1"})
    assert result.returncode != 0
    assert "PARK must be given on the command line" in result.stderr
    assert "python -m" not in result.stdout


def test_autopilot_year_refuses_an_exported_ready() -> None:
    result = make_n(
        "autopilot-year", "DATA_SET=company", "PARK=p1", env_extra={"READY": "p1 is ready"}
    )
    assert result.returncode != 0
    assert "READY must be given on the command line" in result.stderr
    assert "python -m" not in result.stdout


def test_autopilot_year_refuses_a_park_with_a_dollar_sign() -> None:
    result = make_n("autopilot-year", "DATA_SET=company", "PARK=p$(shell touch unsafe)")
    assert result.returncode != 0
    assert "dollar sign" in result.stderr


def test_autopilot_year_refuses_a_ready_phrase_with_a_dollar_sign() -> None:
    result = make_n("autopilot-year", "DATA_SET=company", "PARK=p1", "READY=x$(shell touch unsafe)")
    assert result.returncode != 0
    assert "dollar sign" in result.stderr


def test_an_exported_park_or_ready_does_not_stop_other_targets() -> None:
    for name in ("PARK", "READY"):
        result = make_n("convert", "DATA_SET=company", env_extra={name: "x"})
        assert result.returncode == 0, (name, result.stderr)


def test_check_runs_the_label_checker_on_the_sample() -> None:
    steps = recipe("check")
    expected = "openrct2_analytics.ingest.play_mode_feed --data-root data/sample/rehearsal"
    assert expected in steps


def test_contracts_runs_the_label_checker_after_the_save_file_check() -> None:
    out = make_n("contracts", "DATA_SET=rehearsal").stdout
    save = out.index("python -m openrct2_analytics.ingest.save_files --data-set rehearsal")
    labels = out.index("python -m openrct2_analytics.ingest.play_mode_feed --data-set rehearsal")
    assert save < labels


def test_transform_runs_the_label_checker_after_the_registry_check_and_before_the_build() -> None:
    out = make_n("transform", "DATA_SET=rehearsal").stdout
    feed = out.index("python -m openrct2_analytics.ingest.registry_feed --data-set rehearsal")
    labels = out.index("python -m openrct2_analytics.ingest.play_mode_feed --data-set rehearsal")
    build = out.index("dbt build")
    assert feed < labels < build


def test_transform_joins_the_label_check_to_the_build_with_and_for_its_data_set() -> None:
    out = make_n("transform", "DATA_SET=company").stdout
    assert "play_mode_feed --data-set company && " in out


def test_contracts_label_check_is_not_joined_with_or() -> None:
    out = make_n("contracts", "DATA_SET=company").stdout
    labels = out.index("play_mode_feed --data-set company")
    assert "||" not in out[out.index("save_files") :]
    assert "||" not in out[:labels]


def test_auto_file_and_autopilot_parks_run_their_modules_through_run() -> None:
    assert recipe("auto-file") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.auto_file '
        "$(if $(DATA_SET),--data-set $(DATA_SET)) $(if $(RECORD),--record) "
        '$${COUNT_AS+--count-as="$$COUNT_AS"}'
    )
    # No make echo: standard output holds only the program's JSON, as for play-status.
    assert recipe("autopilot-parks") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.autopilot_parks '
        "$(if $(DATA_SET),--data-set $(DATA_SET))"
    )


def test_auto_file_passes_exactly_the_record_or_count_as_flag(tmp_path: Path) -> None:
    record = run_recipe(tmp_path / "record", "auto-file", "RECORD=yes")
    assert record == [
        "-m",
        "openrct2_analytics.ingest.auto_file",
        "--data-set",
        "company",
        "--record",
    ]
    for choice in ("company", "practice"):
        argv = run_recipe(tmp_path / choice, "auto-file", f"COUNT_AS={choice}")
        assert argv == [
            "-m",
            "openrct2_analytics.ingest.auto_file",
            "--data-set",
            "company",
            f"--count-as={choice}",
        ]


def test_an_exported_count_as_or_record_is_refused() -> None:
    for name, value in (("COUNT_AS", "company"), ("RECORD", "yes")):
        result = make_n("auto-file", "DATA_SET=company", env_extra={name: value})
        assert result.returncode != 0, name
        assert f"{name} must be given on the command line" in result.stderr
        assert "python -m" not in result.stdout


def test_a_count_as_or_record_with_a_dollar_sign_is_refused() -> None:
    for name in ("COUNT_AS", "RECORD"):
        result = make_n("auto-file", "DATA_SET=company", f"{name}=a$(shell true)")
        assert result.returncode != 0, name
        assert f"{name} must not contain a dollar sign" in result.stderr
        assert "python -m" not in result.stdout


def test_an_exported_count_as_or_record_does_not_stop_other_targets() -> None:
    for target in ("convert", "results", "play-status", "autopilot-parks", "unfiled"):
        for name, value in (("COUNT_AS", "company"), ("RECORD", "yes")):
            result = make_n(target, "DATA_SET=company", env_extra={name: value})
            assert result.returncode == 0, (target, name, result.stderr)


def test_autopilot_parks_standard_output_is_only_the_programs_output(tmp_path: Path) -> None:
    stand_in = tmp_path / ".venv" / "bin" / "python"
    stand_in.parent.mkdir(parents=True)
    stand_in.write_text("#!/bin/sh\nprintf '{\"parks\": []}'\n", encoding="utf-8")
    stand_in.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MAKELEVEL", "DATA_SET"}}
    env["PATH"] = "/usr/bin:/bin"
    result = subprocess.run(
        ["make", "-f", str(MAKEFILE), "autopilot-parks", "DATA_SET=company"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == '{"parks": []}'


def test_unfiled_runs_its_module_through_run() -> None:
    assert recipe("unfiled") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.unfiled '
        "$(if $(DATA_SET),--data-set $(DATA_SET))"
    )


def test_unfiled_standard_output_is_only_the_programs_output(tmp_path: Path) -> None:
    stand_in = tmp_path / ".venv" / "bin" / "python"
    stand_in.parent.mkdir(parents=True)
    stand_in.write_text("#!/bin/sh\nprintf 'park-1\\n'\n", encoding="utf-8")
    stand_in.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MAKELEVEL", "DATA_SET"}}
    env["PATH"] = "/usr/bin:/bin"
    result = subprocess.run(
        ["make", "-f", str(MAKEFILE), "unfiled", "DATA_SET=company"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "park-1\n"


def test_record_other_than_yes_is_refused() -> None:
    result = make_n("auto-file", "DATA_SET=company", "RECORD=no")
    assert result.returncode != 0
    assert "RECORD must be empty or exactly yes" in result.stderr
    assert "python -m" not in result.stdout
