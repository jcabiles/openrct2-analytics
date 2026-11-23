"""The Makefile's gate wiring, read from the real Makefile."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parent.parent / "Makefile"
NEW_TARGETS = [
    "delete-company-data",
    "real-play-check",
    "go-live",
    "listen",
    "convert",
    "contracts",
    "transform",
    "pipeline",
    "capture-data",
    "play",
    "launcher",
    "capture-rehearsal",
    "register-parks",
    "play-status",
    "unfiled",
    "after-play",
    "auto-file",
    "autopilot-parks",
    "results",
    "publish",
    "rollback",
    "bench",
    "bench-sample",
    "site-export",
    "site-company",
    "autopilot-year",
    "autopilot-real-test",
]


def phony_targets() -> set[str]:
    match = re.search(r"^\.PHONY:(.*)$", MAKEFILE.read_text(encoding="utf-8"), re.MULTILINE)
    assert match, "the Makefile has no .PHONY line"
    return set(match.group(1).split())


def recipe(target: str) -> str:
    """The recipe lines of `target`, joined, with line continuations folded."""
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith("\t"):
            break
        body.append(line.strip().rstrip("\\").strip())
    return " ".join(part for part in body if part)


def make_n(*args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run `make -n` with MAKEFLAGS, MAKELEVEL and DATA_SET cleared from the environment."""
    env = {k: v for k, v in os.environ.items() if k not in {"MAKEFLAGS", "MAKELEVEL", "DATA_SET"}}
    env.update(env_extra or {})
    return subprocess.run(
        ["make", "-n", *args],
        cwd=MAKEFILE.parent,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_new_targets_are_phony() -> None:
    assert set(NEW_TARGETS) <= phony_targets()


def test_check_runs_plugin_tests_then_contracts_on_the_sample_before_dbt_parse() -> None:
    steps = recipe("check")
    plugin = steps.index("node --test plugin/test/*.test.mjs")
    contracts = steps.index("openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal")
    dbt_parse = steps.index("dbt parse")

    assert plugin < contracts < dbt_parse


def test_check_runs_the_feed_check_on_the_sample_right_after_the_sample_contract_check() -> None:
    steps = recipe("check")
    pair = (
        "openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal && "
        "${RUN}python -m openrct2_analytics.ingest.registry_feed "
        "--data-root data/sample/rehearsal && "
        "${RUN}python -m openrct2_analytics.ingest.save_files "
        "--data-root data/sample/rehearsal && "
        "${RUN}python -m openrct2_analytics.ingest.play_mode_feed "
        "--data-root data/sample/rehearsal && "
        "${RUN}python scripts/generate_dbt_sources.py --check"
    )

    assert pair.replace("${RUN}", "$${RUN}") in steps


def test_check_runs_the_catalog_validator_after_docs_and_the_shape_check_before_dbt_parse() -> None:
    steps = recipe("check")
    docs = steps.index("scripts/check_docs.py")
    validator = steps.index("scripts/check_metric_catalog.py")
    mypy = steps.index("mypy")
    contracts = steps.index("openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal")
    shape = steps.index("scripts/check_metric_catalog_shape.py")
    dbt_parse = steps.index("dbt parse")

    assert docs < validator < mypy
    assert contracts < shape < dbt_parse


def test_check_builds_the_ci_target_in_a_temporary_folder_and_lints_inside_it() -> None:
    steps = recipe("check")
    folder = steps.index('mktemp -d "$${TMPDIR:-/tmp}/openrct2-ci.XXXXXX"')
    trap = steps.index("""trap 'rm -rf "$${dir:?}"' EXIT""")
    export = steps.index('export OPENRCT2_CI_DIR="$$dir"')
    guard = steps.index('warehouse_guard --root "$$dir" "$$dir/ci.duckdb" && $${RUN}dbt parse')
    build = steps.index("${RUN}dbt build")
    lint = steps.index("${RUN}sqlfluff lint models tests/dbt )")
    secrets = steps.index("detect-secrets-hook")

    assert folder < trap < export < guard < build < lint < secrets
    assert "mkdir -p warehouse" not in steps
    for command in ("dbt parse", "dbt build"):
        line = steps[steps.index(command) :].split("&&")[0]
        assert "--target ci" in line
        assert '--target-path "$$dir/target" --log-path "$$dir/logs"' in line
        assert "parquet_root: data/sample/rehearsal" in line
    assert "target = ci" in (MAKEFILE.parent / ".sqlfluff").read_text(encoding="utf-8")


def test_check_runs_the_dbt_checks_after_the_sample_contracts_and_before_the_shape_check() -> None:
    steps = recipe("check")
    contracts = steps.index("openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal")
    sources = steps.index("scripts/generate_dbt_sources.py --check")
    rules = steps.index("scripts/check_dbt_rules.py")
    breaking = steps.index("scripts/check_contract_breaking.py")
    shape = steps.index("scripts/check_metric_catalog_shape.py")

    assert contracts < sources < rules < breaking < shape


def test_check_builds_a_zero_row_extract_after_the_sample_build_and_before_the_lint() -> None:
    steps = recipe("check")
    sample_build = steps.index("dbt build")
    extract = steps.index('ingest.empty_extract --out-dir "$$dir/empty"')
    empty_build = steps.index("dbt build", extract)
    lint = steps.index("sqlfluff lint")

    assert sample_build < extract < empty_build < lint
    sample_line = steps[sample_build:].split("&&")[0]
    empty_line = steps[empty_build:].split("&&")[0]
    assert "parquet_root: data/sample/rehearsal" in sample_line
    assert '--vars "{parquet_root: $$dir/empty}"' in empty_line
    assert "data/sample/rehearsal" not in empty_line
    assert "--target ci" in empty_line
    assert '--target-path "$$dir/target" --log-path "$$dir/logs"' in empty_line


def test_check_builds_docs_then_checks_exposures_between_column_check_and_lint() -> None:
    steps = recipe("check")
    extract = steps.index('ingest.empty_extract --out-dir "$$dir/empty"')
    empty_build = steps.index("dbt build", extract)
    columns = steps.index("check_model_columns.py")
    docs = steps.index("dbt docs generate")
    exposures = steps.index("check_exposures.py")
    lint = steps.index("sqlfluff lint")

    assert empty_build < columns < docs < exposures < lint
    assert 'check_exposures.py "$$dir/target/manifest.json" && ' in steps
    docs_line = steps[docs:].split("&&")[0]
    assert "--target ci" in docs_line
    assert '--target-path "$$dir/target" --log-path "$$dir/logs"' in docs_line
    assert '--vars "{parquet_root: $$dir/empty}"' in docs_line


def test_check_runs_cleaning_rule_counts_after_exposures_and_before_lint() -> None:
    steps = recipe("check")
    extract = steps.index('ingest.empty_extract --out-dir "$$dir/empty"')
    empty_build = steps.index("dbt build", extract)
    exposures = steps.index("check_exposures.py")
    counts = steps.index("check_cleaning_rule_counts.py")
    lint = steps.index("sqlfluff lint")

    assert empty_build < exposures < counts < lint
    counts_line = steps[counts:].split("&&")[0]
    assert '"$$dir/target/manifest.json" "$$dir/ci.duckdb"' in counts_line
    # `&&`, not `;`: inside the subshell `set -e` is off, so `;` lets a failing check fall through.
    assert (
        'check_cleaning_rule_counts.py "$$dir/target/manifest.json" "$$dir/ci.duckdb" && ' in steps
    )
    assert "$${RUN}python scripts/check_cleaning_rule_counts.py " in steps


def test_no_recipe_puts_a_space_between_the_fallback_folder_and_the_tool() -> None:
    # `RUN=".venv/bin/"` then `$$RUN python` runs the folder; the tool must follow directly.
    assert "$$RUN " not in MAKEFILE.read_text(encoding="utf-8")


def test_pipeline_runs_convert_then_contracts_then_transform_as_separate_lines() -> None:
    # One recipe line per step: make stops at the first failing line, and -j cannot reorder them.
    assert recipe("pipeline") == "$(MAKE) convert $(MAKE) contracts $(MAKE) transform"
    steps = "\t$(MAKE) convert\n\t$(MAKE) contracts\n\t$(MAKE) transform\n"
    assert steps in MAKEFILE.read_text(encoding="utf-8")


def test_capture_data_runs_the_capture_module_through_run() -> None:
    # No --port and no other test seam: the real plugin sends only to 127.0.0.1:8765.
    assert recipe("capture-data") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.capture '
        "$(if $(DATA_SET),--data-set $(DATA_SET))"
    )


def test_capture_rehearsal_runs_its_module_through_run() -> None:
    assert recipe("capture-rehearsal") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.rehearsal_capture '
        "$(if $(DATA_SET),--data-set $(DATA_SET))"
    )


def test_register_parks_runs_its_module_through_run() -> None:
    assert recipe("register-parks") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.register_parks '
        "$(if $(DATA_SET),--data-set $(DATA_SET)) $(if $(PRACTICE),--practice) "
        '$${PARKS+--parks="$$PARKS"} $${START_YEAR+--start-year="$$START_YEAR"}'
    )


def test_play_status_and_after_play_run_their_modules_through_run() -> None:
    assert recipe("play-status") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.play_status '
        "$(if $(DATA_SET),--data-set $(DATA_SET))"
    )
    assert recipe("after-play") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.after_play '
        '$(if $(DATA_SET),--data-set $(DATA_SET)) $${PARKS+--parks="$$PARKS"} '
        '$${START_YEAR+--start-year="$$START_YEAR"}'
    )


def test_results_runs_its_module_through_run() -> None:
    assert recipe("results") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.results '
        "$(if $(DATA_SET),--data-set $(DATA_SET)) $(if $(PUBLISHED),--published)"
    )


def test_bench_targets_run_the_bench_module_through_run() -> None:
    # No port or other test seam: the real plugin sends only to 127.0.0.1:8765.
    prefix = (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.bench_run'
    )
    assert recipe("bench") == prefix
    assert recipe("bench-sample") == prefix + " --sample"


def test_check_turns_a_signal_into_an_exit_so_dash_removes_the_ci_folder() -> None:
    # dash runs no EXIT trap on a signal; `exit 130` makes the signal a normal exit.
    steps = recipe("check")
    exit_trap = steps.index("""trap 'rm -rf "$${dir:?}"' EXIT""")
    signal_trap = steps.index("trap 'exit 130' INT HUP TERM")
    dbt_parse = steps.index("dbt parse")

    assert exit_trap < signal_trap < dbt_parse


def test_check_keeps_dbt_target_inside_the_ci_folder() -> None:
    steps = recipe("check")
    block = steps[steps.index("( dir=$$(mktemp") :]
    assert 'export OPENRCT2_CI_DIR="$$dir"' in block
    assert 'export DBT_TARGET_PATH="$$dir/target"' in block
    assert block.index('export DBT_TARGET_PATH="$$dir/target"') < block.index("sqlfluff lint")


def test_data_set_from_the_environment_is_refused_by_data_set_targets() -> None:
    for target in (
        "listen",
        "capture-data",
        "play",
        "capture-rehearsal",
        "register-parks",
        "play-status",
        "unfiled",
        "after-play",
        "auto-file",
        "autopilot-parks",
        "results",
        "real-play-check",
        "convert",
        "contracts",
        "transform",
        "pipeline",
        "publish",
        "rollback",
    ):
        for value in ("rehearsal", ""):
            result = make_n(target, env_extra={"DATA_SET": value})
            assert result.returncode != 0, (target, value)
            assert "DATA_SET" in result.stderr


def test_data_set_other_than_the_two_names_is_refused_on_the_command_line() -> None:
    for value in ("x; touch y", "other", "rehearsal company", "Rehearsal"):
        result = make_n("listen", f"DATA_SET={value}")
        assert result.returncode != 0, value
        assert "DATA_SET" in result.stderr


def test_the_gate_and_other_targets_ignore_data_set() -> None:
    for target in ("check", "setup", "fix", "lock", "bench", "bench-sample", "launcher"):
        for env in ({"DATA_SET": "company"}, {"DATA_SET": ""}, {"DATA_SET": "x; touch y"}):
            result = make_n(target, env_extra=env)
            assert result.returncode == 0, (target, env, result.stderr)


def test_data_set_reaches_the_module_from_the_command_line() -> None:
    capture = make_n("capture-data", "DATA_SET=rehearsal")
    assert capture.returncode == 0
    assert "python -m openrct2_analytics.ingest.capture --data-set rehearsal" in capture.stdout
    bare = make_n("capture-data")
    assert bare.returncode == 0
    assert "--data-set" not in bare.stdout
    publish = make_n("publish", "DATA_SET=company")
    assert "python -m openrct2_analytics.ingest.publish --data-set company" in publish.stdout
    rollback = make_n("rollback", "DATA_SET=company")
    assert (
        "python -m openrct2_analytics.ingest.publish --rollback --data-set company"
        in rollback.stdout
    )


def test_each_data_set_target_passes_the_data_set_to_its_module() -> None:
    for target, module in (
        ("listen", "ingest.listener"),
        ("convert", "ingest.convert"),
        ("contracts", "ingest.contracts"),
        ("capture-data", "ingest.capture"),
        ("play", "ingest.capture"),
        ("capture-rehearsal", "ingest.rehearsal_capture"),
        ("register-parks", "ingest.register_parks"),
        ("play-status", "ingest.play_status"),
        ("unfiled", "ingest.unfiled"),
        ("after-play", "ingest.after_play"),
        ("auto-file", "ingest.auto_file"),
        ("autopilot-parks", "ingest.autopilot_parks"),
        ("results", "ingest.results"),
        ("real-play-check", "ingest.real_play_check"),
    ):
        out = make_n(target, "DATA_SET=rehearsal").stdout
        assert f"openrct2_analytics.{module} --data-set rehearsal" in out
    transform = make_n("transform", "DATA_SET=rehearsal").stdout
    assert "landing_dirs(sys.argv[1])" in transform
    pipeline = make_n("pipeline", "DATA_SET=rehearsal").stdout
    assert "ingest.convert --data-set rehearsal" in pipeline
    assert "ingest.contracts --data-set rehearsal" in pipeline
    assert "landing_dirs(sys.argv[1])" in pipeline


def test_contracts_runs_the_feed_check_after_the_event_check() -> None:
    out = make_n("contracts", "DATA_SET=rehearsal").stdout
    events = out.index("openrct2_analytics.ingest.contracts --data-set rehearsal")
    feed = out.index("python -m openrct2_analytics.ingest.registry_feed --data-set rehearsal")
    save = out.index("python -m openrct2_analytics.ingest.save_files --data-set rehearsal")

    assert events < feed < save


def test_transform_checks_the_feed_then_guards_the_dev_path_then_builds_with_both_roots() -> None:
    out = make_n("transform", "DATA_SET=rehearsal").stdout
    resolve = out.index("registry_dir(sys.argv[1])")
    feed = out.index("python -m openrct2_analytics.ingest.registry_feed --data-set rehearsal")
    guard = out.index("warehouse_guard --root warehouse warehouse/dev/dev.duckdb")
    mkdir = out.index("mkdir -p warehouse/dev")
    build = out.index("dbt build --profiles-dir . --target dev --vars ")

    assert resolve < feed < guard < mkdir < build
    assert "{parquet_root: '$ROOT', registry_root: '$REG'}" in out[build:]


def test_setup_creates_the_dev_warehouse_folder() -> None:
    assert "mkdir -p warehouse/dev" in make_n("setup").stdout


def test_setup_installs_npm_packages_without_install_scripts() -> None:
    assert "npm ci --ignore-scripts" in make_n("setup").stdout


def test_ci_installs_npm_packages_without_install_scripts() -> None:
    workflow = MAKEFILE.parent / ".github/workflows/ci.yml"
    lines = [line.strip() for line in workflow.read_text(encoding="utf-8").splitlines()]

    assert "run: npm ci --ignore-scripts" in lines
    assert "run: npm ci" not in lines


def test_check_runs_the_export_check_site_build_and_page_check_after_the_sample_build() -> None:
    steps = recipe("check")
    sample_build = steps.index("dbt build")
    export = steps.index('showcase.export check --warehouse "$$dir/ci.duckdb"')
    site = steps.index('npm run --silent site:build -- --output="$$dir/site"')
    page = steps.index('showcase.page_check --site "$$dir/site" --served-dir site/_data')
    extract = steps.index("ingest.empty_extract")

    assert sample_build < export < site < page < extract

    gates = (
        '--vars "{parquet_root: data/sample/rehearsal}" && '
        "${RUN}python -m openrct2_analytics.showcase.export check "
        '--warehouse "$$dir/ci.duckdb" && '
        'npm run --silent site:build -- --output="$$dir/site" && '
        "${RUN}python -m openrct2_analytics.showcase.page_check "
        '--site "$$dir/site" --served-dir site/_data && '
        "${RUN}python -m openrct2_analytics.ingest.empty_extract "
        '--out-dir "$$dir/empty"'
    )

    assert gates.replace("${RUN}", "$${RUN}") in steps


def test_site_export_repeats_the_check_temporary_folder_lines_then_writes_the_export() -> None:
    def span(steps: str) -> str:
        start = steps.index("( dir=$$(mktemp")
        end = steps.index("dbt build")
        return steps[start : steps.index("&&", end) + 2]

    export = recipe("site-export")
    assert span(export) == span(recipe("check"))
    assert export.index("dbt build") < export.index(
        'showcase.export write --warehouse "$$dir/ci.duckdb" )'
    )
    goals = re.search(
        r"^DATA_SET_GOALS :=(.*)$", MAKEFILE.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert goals
    assert "site-export" not in goals.group(1).split()


def test_real_play_check_runs_its_module_with_data_set_and_session_through_run() -> None:
    assert recipe("real-play-check") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.real_play_check '
        '$(if $(DATA_SET),--data-set $(DATA_SET)) $${SESSION+--session="$$SESSION"}'
    )


def test_real_play_check_session_rejects_dollars_and_environment() -> None:
    result = make_n("real-play-check", "DATA_SET=company", "SESSION=a$(shell touch unsafe)")
    assert result.returncode != 0
    assert "dollar sign" in result.stderr
    result = make_n("real-play-check", "DATA_SET=company", env_extra={"SESSION": "value"})
    assert result.returncode != 0
    assert "SESSION" in result.stderr
    assert "command line" in result.stderr


def test_site_company_runs_its_module_with_data_set_through_run() -> None:
    assert recipe("site-company") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.site_company '
        "$(if $(DATA_SET),--data-set $(DATA_SET))"
    )


def test_site_company_dry_run_prints_the_module_and_data_set() -> None:
    result = make_n("site-company", "DATA_SET=company")
    assert result.returncode == 0
    assert "ingest.site_company --data-set company" in result.stdout


def test_site_company_refuses_an_exported_or_invalid_data_set() -> None:
    exported = make_n("site-company", env_extra={"DATA_SET": "company"})
    assert exported.returncode != 0
    assert "must be given on the command line" in exported.stderr
    invalid = make_n("site-company", "DATA_SET=bogus")
    assert invalid.returncode != 0
    assert "DATA_SET" in invalid.stderr


def test_autopilot_real_test_is_listed_in_help_and_outside_the_gate() -> None:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    line = next(item for item in lines if item.startswith("autopilot-real-test:"))
    assert line.startswith("autopilot-real-test: # Run the opt-in real-game autopilot test")
    assert "OPENRCT2_AUTOPILOT_REAL_GAME=1" in recipe("autopilot-real-test")
    assert "tests/test_autopilot_real_game.py" in recipe("autopilot-real-test")
    assert "autopilot-real-test" not in recipe("check")
