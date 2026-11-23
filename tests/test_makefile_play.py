"""The `play` and `launcher` targets and the launcher's command file, read from the real files."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from tests.test_makefile import MAKEFILE, recipe


def test_play_runs_the_capture_module_with_open_game() -> None:
    assert recipe("play") == (
        '@set -e; if command -v uv >/dev/null 2>&1; then RUN="uv run "; '
        'else RUN=".venv/bin/"; fi; $${RUN}python -m openrct2_analytics.ingest.capture '
        "$(if $(DATA_SET),--data-set $(DATA_SET)) --open-game"
    )


def test_launcher_compiles_into_a_temp_folder_before_replacing_the_app() -> None:
    body = recipe("launcher")
    compiled = body.index("osacompile -o")
    assert body.index('mktemp -d "$$apps/') < compiled < body.index('rm -rf "$$app"')
    assert body.index('rm -rf "$$app"') < body.index('mv "$$build/OpenRCT2 Enterprise.app"')
    assert 'file="$$(pwd -P)/launcher/play-company.command"' in body  # the path is never shell text
    assert "open -a Terminal" in body
    assert "tell application" not in body  # scripting Terminal needs an Automation permission


def test_launcher_takes_the_game_icon_and_is_signed_again_before_it_is_moved_in() -> None:
    body = recipe("launcher")
    copied = body.index('cp "$$icon" "$$contents/Resources/applet.icns"')
    assert body.index("osacompile -o") < copied < body.index("codesign --force --sign -")
    signed = body.index("codesign --force --sign -")
    assert signed < body.index('mv "$$build/OpenRCT2 Enterprise.app"')
    # Without this, macOS shows the script icon from the compiled asset catalog.
    assert 'rm -f "$$contents/Resources/Assets.car"' in body


def test_the_launcher_command_file_is_executable_and_holds_no_machine_path() -> None:
    command = MAKEFILE.parent / "launcher" / "play-company.command"
    text = command.read_text(encoding="utf-8")
    assert os.access(command, os.X_OK)
    assert text.startswith("#!/bin/zsh -l\n")
    assert "/Users/" not in text and "/home/" not in text and "~" not in text
    assert 'cd "${0:A:h}/.."' in text
    assert "direnv exec . make play DATA_SET=company" in text
    assert "Press Return to close this window." in text


QUESTION = (
    "Where should this play count?\n"
    "1. Company — counts toward the company's results\n"
    "2. Sandbox — saved, but kept out of the company's results (a company park stays company)\n"
    "3. Run autopilot on a finished park — the game plays one company year by itself "
    "(up to about two hours), then it is filed\n"
)
COMMAND = MAKEFILE.parent / "launcher" / "play-company.command"


def launcher_env(
    tmp_path: Path,
    *,
    play_exit: int = 0,
    record_exit: int = 0,
    unfiled: tuple[str, ...] = (),
    exits: dict[str, int] | None = None,
) -> dict[str, str]:
    """Write the fake commands under `tmp_path/bin`; return the child environment that finds them.

    `unfiled` holds the planted output of each `make unfiled` call, in turn (empty by default).
    `exits` sets `unfiled`, `convert` and `offer_file` (the first `COUNT_AS` call, the one made
    during the offer) exit codes; each is 0 when absent. The environment variables `PARKS_JSON`,
    `PARKS_EXIT`, `AUTOPILOT_EXIT` and `FILE_EXIT` steer `autopilot-parks`, `autopilot-year` and the
    `COUNT_AS` filing; `FILE_EXIT` applies to every `COUNT_AS` call but the first (the offer call,
    which only `offer_file` steers). `RECORD_EXIT` also steers the `RECORD=yes` step.
    """
    exits = exits or {}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    for number, output in enumerate(unfiled, start=1):
        (tmp_path / f"unfiled-{number}").write_text(output, encoding="utf-8")
    log = tmp_path / "calls.log"
    (bin_dir / "direnv").write_text(
        '#!/bin/sh\nif [ "$1" = exec ]; then shift 2; exec "$@"; fi\n', encoding="utf-8"
    )
    (bin_dir / "make").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$CALL_LOG"\n'
        # Real make reports every failing recipe as exit 2, whatever the program's own code.
        'printf \'%s\\n\' "$@" >> "$ARGS_LOG"\n'
        'case "$1" in autopilot-parks) echo Resolved >&2; printf \'%s\\n\' "$PARKS_JSON"\n'
        '  [ "$PARKS_EXIT" = 0 ] || exit 2;; esac\n'
        'case "$1" in autopilot-year) echo "autopilot-year started"\n'
        '  [ "$AUTOPILOT_EXIT" = 0 ] || exit 2;; esac\n'
        'case "$1" in play) [ "$PLAY_EXIT" = 0 ] || exit 2;; esac\n'
        'case "$*" in *RECORD=yes*) [ "$RECORD_EXIT" = 0 ] || exit 2;; esac\n'
        'case "$1" in convert) [ "$CONVERT_EXIT" = 0 ] || exit 2;; esac\n'
        'case "$1" in unfiled)\n'
        '  n=$(cat "$RUN_DIR/unfiled-count" 2>/dev/null || echo 0); n=$((n + 1))\n'
        '  echo "$n" > "$RUN_DIR/unfiled-count"\n'
        '  [ "$UNFILED_EXIT" = 0 ] || exit 2\n'
        '  cat "$RUN_DIR/unfiled-$n" 2>/dev/null;;\n'
        "esac\n"
        'case "$*" in *COUNT_AS=*)\n'
        '  n=$(cat "$RUN_DIR/count-as" 2>/dev/null || echo 0); n=$((n + 1))\n'
        '  echo "$n" > "$RUN_DIR/count-as"\n'
        '  [ "$n" != 1 ] || [ "$OFFER_FILE_EXIT" = 0 ] || exit 2\n'
        '  [ "$n" = 1 ] || [ "$FILE_EXIT" = 0 ] || exit 2;;\n'
        "esac\n",
        encoding="utf-8",
    )
    # Drops `-i` like the real tool's wrapper role, then runs the rest so the fake make still logs.
    (bin_dir / "caffeinate").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" >> "$CAFFEINATE_LOG"\n'
        'if [ "$1" = -i ]; then shift; fi\nexec "$@"\n',
        encoding="utf-8",
    )
    # The dashboard answers its ping, so no server starts; opening the page is logged, not done.
    (bin_dir / "curl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "open").write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$OPEN_LOG"\n', encoding="utf-8"
    )
    for fake in bin_dir.iterdir():
        fake.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin",
        "PYTHONPATH": str(MAKEFILE.parent / "src"),
        "CALL_LOG": str(log),
        "ARGS_LOG": str(tmp_path / "args.log"),
        "CAFFEINATE_LOG": str(tmp_path / "caffeinate.log"),
        "PARKS_JSON": '{"data_set": "company", "parks": []}',
        "PARKS_EXIT": "0",
        "AUTOPILOT_EXIT": "0",
        "FILE_EXIT": "0",
        "OPEN_LOG": str(tmp_path / "open.log"),
        "PLAY_EXIT": str(play_exit),
        "RECORD_EXIT": str(record_exit),
        "RUN_DIR": str(tmp_path),
        "UNFILED_EXIT": str(exits.get("unfiled", 0)),
        "CONVERT_EXIT": str(exits.get("convert", 0)),
        "OFFER_FILE_EXIT": str(exits.get("offer_file", 0)),
    }


def run_launcher(  # noqa: PLR0913  (one keyword per fake the launcher tests steer)
    tmp_path: Path,
    answers: str,
    *,
    play_exit: int = 0,
    record_exit: int = 0,
    unfiled: tuple[str, ...] = (),
    exits: dict[str, int] | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Run the real command file with the fake commands first on PATH; return the `make` calls.

    `env` is merged over the fakes' environment, so a test can set `PARKS_JSON`, `FILE_EXIT` etc.
    """
    child_env = {
        **launcher_env(
            tmp_path, play_exit=play_exit, record_exit=record_exit, unfiled=unfiled, exits=exits
        ),
        **(env or {}),
    }
    result = subprocess.run(
        ["zsh", str(COMMAND)],
        input=answers,
        env=child_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    log = tmp_path / "calls.log"
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result, calls


def test_the_fakes_shadow_the_real_commands(tmp_path: Path) -> None:
    env = launcher_env(tmp_path)
    assert env["PATH"].split(":")[:2] == [str(tmp_path / "bin"), str(Path(sys.executable).parent)]
    for name in ("make", "caffeinate", "direnv", "curl", "open"):
        found = subprocess.run(
            ["zsh", "-c", f"command -v {name}"],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout.strip()
        assert found == str(tmp_path / "bin" / name)


def test_the_launcher_asks_the_question_and_answer_1_files_as_company(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "1\n\n")
    assert QUESTION in result.stdout
    assert result.stdout.count("Where should this play count?") == 1
    assert calls == [
        "unfiled DATA_SET=company",
        "auto-file DATA_SET=company RECORD=yes",
        "play DATA_SET=company",
        "auto-file DATA_SET=company COUNT_AS=company",
    ]
    assert result.returncode == 0


def test_answer_2_runs_record_then_play_then_files_as_practice(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "2\n\n")
    assert calls == [
        "unfiled DATA_SET=company",
        "auto-file DATA_SET=company RECORD=yes",
        "play DATA_SET=company",
        "auto-file DATA_SET=company COUNT_AS=practice",
    ]
    assert result.returncode == 0


def test_a_bad_answer_asks_again(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "4\n\nyes\n2\n\n")
    assert result.stdout.count(QUESTION) == 4
    assert calls[-1] == "auto-file DATA_SET=company COUNT_AS=practice"


RERUN = (
    "This play was not filed. If the report above names a seq problem, do not file it; "
    "otherwise run: make auto-file DATA_SET=company COUNT_AS="
)


def test_a_failed_play_prints_the_rerun_line_and_does_not_file(tmp_path: Path) -> None:
    for code in (1, 2):
        result, calls = run_launcher(tmp_path / str(code), "2\n\n", play_exit=code)
        assert f"{RERUN}practice\n" in result.stdout
        assert calls == [
            "unfiled DATA_SET=company",
            "auto-file DATA_SET=company RECORD=yes",
            "play DATA_SET=company",
        ]
        assert result.returncode == 2  # make's own code for any failed recipe


def test_a_failed_play_names_the_company_choice_in_the_rerun_line(tmp_path: Path) -> None:
    result, _ = run_launcher(tmp_path, "1\n\n", play_exit=1)
    assert f"{RERUN}company\n" in result.stdout


def test_a_clean_play_prints_no_rerun_line(tmp_path: Path) -> None:
    result, _ = run_launcher(tmp_path, "2\n\n")
    assert "not filed" not in result.stdout


def test_the_dashboard_opens_only_after_the_play_is_filed(tmp_path: Path) -> None:
    run_launcher(tmp_path / "clean", "1\n\n")
    opened = (tmp_path / "clean" / "open.log").read_text(encoding="utf-8")
    assert opened == "http://127.0.0.1:8780/\n"
    run_launcher(tmp_path / "failed", "1\n\n", play_exit=1)
    assert not (tmp_path / "failed" / "open.log").exists()


def test_a_failed_record_step_stops_before_play_and_says_so(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "2\n\n", record_exit=1)
    assert calls == ["unfiled DATA_SET=company", "auto-file DATA_SET=company RECORD=yes"]
    assert (
        "The game was not opened: noting the earlier recordings failed (see above). "
        "Nothing was played or filed.\n"
    ) in result.stdout
    assert result.returncode == 2


def test_end_of_input_at_the_question_stops_without_running_anything(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "")
    assert calls == ["unfiled DATA_SET=company"]
    assert "No answer was read. Nothing was changed.\n" in result.stdout
    assert result.returncode == 130


UNFILED = "unfiled DATA_SET=company"
RECORD = "auto-file DATA_SET=company RECORD=yes"
FILE_WAITING = "auto-file DATA_SET=company COUNT_AS=company"
PLAY = "play DATA_SET=company"
LIST = "Play waiting to be filed:\n- Park 1 (1): 1 converted session(s) not filed yet\n"
UNCONVERTED = "Play waiting to be filed:\n- Park 1 (1): 1 recording(s) never converted\n"
FAILED_AUDIT = (
    "Play waiting to be filed:\n"
    "- Park 1 (1): session s1 failed its seq audit, so it is not offered for filing\n"
    "Nothing is offered while a session that failed its seq audit is waiting, "
    "because filing files every waiting session.\n"
)
BACKSLASH_PARK = "- C:\\new Park (p1): 1 converted session(s)\n"
OFFER = "File the waiting play now, before this play?\n1. Yes — file it first\n2. No — go on\n"
NOT_FILED = "The waiting play was not filed.\n"
NOT_FILED_SEE_ABOVE = "The waiting play was not filed (see above).\n"
RERUN_LINE = (
    "Any rerun command above is not needed: the waiting play is offered again "
    "the next time this app starts\n"
)


def test_nothing_waiting_prints_only_the_question(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "1\n\n", unfiled=("",))
    assert result.stdout.startswith(QUESTION)
    assert result.stdout.count("Where should this play count?") == 1
    assert "File the waiting play" not in result.stdout
    assert calls[0] == UNFILED
    assert calls.count(UNFILED) == 1


def test_a_waiting_converted_session_accepted_is_filed_before_the_play(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "1\n1\n\n", unfiled=("offer\n" + LIST,))
    assert result.stdout.startswith(LIST + OFFER + QUESTION)
    assert calls == [UNFILED, RECORD, FILE_WAITING, RECORD, PLAY, FILE_WAITING]
    assert "was not filed" not in result.stdout
    assert result.returncode == 0


def test_a_waiting_converted_session_declined_goes_on_to_the_play(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "2\n2\n\n", unfiled=("offer\n" + LIST,))
    assert result.stdout.startswith(LIST + OFFER + QUESTION)
    assert calls == [
        UNFILED,
        RECORD,
        PLAY,
        "auto-file DATA_SET=company COUNT_AS=practice",
    ]
    assert result.returncode == 0


def test_an_unconverted_recording_accepted_is_converted_then_listed_again(tmp_path: Path) -> None:
    # Convert exits 2 here, as it does when any old session failed its audit: its code is not used.
    result, calls = run_launcher(
        tmp_path,
        "1\n1\n\n",
        unfiled=("offer-after-convert\n" + UNCONVERTED, "offer\n" + LIST),
        exits={"convert": 2},
    )
    assert calls == [
        UNFILED,
        "convert DATA_SET=company",
        UNFILED,
        RECORD,
        FILE_WAITING,
        RECORD,
        PLAY,
        FILE_WAITING,
    ]
    assert result.stdout.startswith(UNCONVERTED + OFFER + QUESTION)
    assert "was not filed" not in result.stdout
    assert result.returncode == 0


def test_a_backslash_in_a_park_line_is_printed_as_written(tmp_path: Path) -> None:
    list_text = "Play waiting to be filed:\n" + BACKSLASH_PARK
    result, _ = run_launcher(tmp_path, "2\n2\n\n", unfiled=("offer\n" + list_text,))
    assert "- C:\\new Park (p1): 1 converted session(s)\n" in result.stdout


def test_a_backslash_in_a_second_list_park_line_is_printed_as_written(tmp_path: Path) -> None:
    list_text = "Play waiting to be filed:\n" + BACKSLASH_PARK
    result, _ = run_launcher(
        tmp_path,
        "1\n2\n\n",
        unfiled=("offer-after-convert\n" + UNCONVERTED, "no-offer\n" + list_text),
    )
    assert result.stdout.count("- C:\\new Park (p1): 1 converted session(s)\n") == 1


def test_a_no_offer_list_names_the_failed_session_and_offers_nothing(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "2\n\n", unfiled=("no-offer\n" + FAILED_AUDIT,))
    assert result.stdout.startswith(FAILED_AUDIT + QUESTION)
    assert "File the waiting play" not in result.stdout
    assert calls == [
        UNFILED,
        RECORD,
        PLAY,
        "auto-file DATA_SET=company COUNT_AS=practice",
    ]


def test_a_second_list_that_is_not_an_offer_files_nothing_and_goes_to_the_question(
    tmp_path: Path,
) -> None:
    result, calls = run_launcher(
        tmp_path,
        "1\n2\n\n",
        unfiled=("offer-after-convert\n" + UNCONVERTED, "no-offer\n" + FAILED_AUDIT),
    )
    assert result.stdout.startswith(UNCONVERTED + OFFER + FAILED_AUDIT + NOT_FILED + QUESTION)
    assert calls == [
        UNFILED,
        "convert DATA_SET=company",
        UNFILED,
        RECORD,
        PLAY,
        "auto-file DATA_SET=company COUNT_AS=practice",
    ]


def test_a_second_list_that_still_needs_a_convert_files_nothing(tmp_path: Path) -> None:
    result, calls = run_launcher(
        tmp_path,
        "1\n2\n\n",
        unfiled=("offer-after-convert\n" + UNCONVERTED, "offer-after-convert\n" + UNCONVERTED),
    )
    assert result.stdout.startswith(UNCONVERTED + OFFER + UNCONVERTED + NOT_FILED + QUESTION)
    assert calls == [
        UNFILED,
        "convert DATA_SET=company",
        UNFILED,
        RECORD,
        PLAY,
        "auto-file DATA_SET=company COUNT_AS=practice",
    ]


def test_a_failed_record_inside_the_offer_does_not_file(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "1\n", unfiled=("offer\n" + LIST,), record_exit=2)
    assert result.stdout.startswith(LIST + OFFER + NOT_FILED_SEE_ABOVE + RERUN_LINE + QUESTION)
    assert calls == [UNFILED, RECORD]


def test_a_refused_filing_prints_both_not_filed_lines_then_the_question(tmp_path: Path) -> None:
    result, calls = run_launcher(
        tmp_path, "1\n2\n\n", unfiled=("offer\n" + LIST,), exits={"offer_file": 2}
    )
    assert result.stdout.startswith(LIST + OFFER + NOT_FILED_SEE_ABOVE + RERUN_LINE + QUESTION)
    assert calls[:3] == [UNFILED, RECORD, FILE_WAITING]
    assert calls[3:] == [RECORD, PLAY, "auto-file DATA_SET=company COUNT_AS=practice"]


def test_a_failed_unfiled_check_says_so_and_goes_to_the_question(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "2\n\n", exits={"unfiled": 2})
    assert result.stdout.startswith("Waiting play could not be checked (see above).\n" + QUESTION)
    assert "File the waiting play" not in result.stdout
    assert calls == [UNFILED, RECORD, PLAY, "auto-file DATA_SET=company COUNT_AS=practice"]


def test_a_bad_answer_at_the_offer_asks_it_again(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\nyes\n2\n2\n\n", unfiled=("offer\n" + LIST,))
    assert result.stdout.count(OFFER) == 3
    assert result.stdout.count(QUESTION) == 1
    assert calls == [UNFILED, RECORD, PLAY, "auto-file DATA_SET=company COUNT_AS=practice"]


def test_end_of_input_at_the_offer_stops_without_filing_or_asking(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "", unfiled=("offer\n" + LIST,))
    assert calls == [UNFILED]
    assert "No answer was read. Nothing was changed.\n" in result.stdout
    assert "Where should this play count?" not in result.stdout
    assert result.returncode == 130


def test_file_exit_fails_the_filing_after_the_play_not_the_offer_call(tmp_path: Path) -> None:
    result, calls = run_launcher(
        tmp_path, "1\n2\n\n", unfiled=("offer\n" + LIST,), env={"FILE_EXIT": "2"}
    )
    assert calls == [
        UNFILED,
        RECORD,
        FILE_WAITING,
        RECORD,
        PLAY,
        "auto-file DATA_SET=company COUNT_AS=practice",
    ]
    assert NOT_FILED_SEE_ABOVE not in result.stdout  # the offer call exited 0
    assert result.returncode == 2  # the second COUNT_AS call exited 2
    assert not (tmp_path / "open.log").exists()  # a failed filing opens no dashboard


def test_parks_json_reaches_the_parks_fake(tmp_path: Path) -> None:
    listing = '{"data_set": "company", "parks": [{"park_id": "p1"}]}'
    child = {**launcher_env(tmp_path), "PARKS_JSON": listing}
    shown = subprocess.run(
        ["zsh", "-c", "make autopilot-parks DATA_SET=company"],
        env=child,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert shown.stdout == listing + "\n"


def test_autopilot_exit_makes_the_year_fake_print_its_marker_and_exit_2(tmp_path: Path) -> None:
    child = {**launcher_env(tmp_path), "AUTOPILOT_EXIT": "2"}
    ran = subprocess.run(
        ["zsh", "-c", "make autopilot-year DATA_SET=company PARK=p1"],
        env=child,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert ran.stdout == "autopilot-year started\n"
    assert ran.returncode == 2
