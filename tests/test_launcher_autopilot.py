"""The launcher's third answer and its park menu, run through the real command file with fakes."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from openrct2_analytics.ingest.play_mode_feed import READY_SUFFIX, ready_phrase
from tests.test_makefile_play import COMMAND, LIST, QUESTION, run_launcher

READY: dict[str, object] = {
    "park_id": "pk-1",
    "park_name": "Alpha Park",
    "park_label": "Alpha Park (first played Nov 12)",
    "source_problem": None,
    "needs_ready": False,
}
BLOCKED: dict[str, object] = {
    "park_id": "pk-2",
    "park_name": "Beta Park",
    "park_label": "Beta Park (first played Nov 13)",
    "source_problem": "no proven backup",
    "needs_ready": True,
}
PARKS_CALL = "autopilot-parks DATA_SET=company"
UNFILED = "unfiled DATA_SET=company"
LIST_HEAD = "Which park should autopilot run?\n"
BACK = "0. Back to the first question\n"
LIST_ONE = (
    f"{LIST_HEAD}1. Alpha Park (first played Nov 12)\n"
    f"Not ready: Beta Park (first played Nov 13): no proven backup\n{BACK}"
)
R6 = (
    "The park list could not be read; see the messages above. To try again, choose 3 again, "
    "or run: make autopilot-parks DATA_SET=company\n"
)
RECORD = "auto-file DATA_SET=company RECORD=yes"
YEAR = "autopilot-year DATA_SET=company PARK=pk-1"
FILING = "auto-file DATA_SET=company COUNT_AS=company"
SENTENCE_HEAD = (
    "This is the first autopilot run for Beta Park (first played Nov 13). "
    "To confirm that it is ready, "
    "type this sentence exactly:\n"
)
STEP2 = (
    "Autopilot did not start; see the messages above. No autopilot run was started. "
    "Once the cause is fixed, open the launcher and choose 3 again.\n"
)
NOTICE = (
    "This can take up to about two hours. Keep this window open until it says it finished. "
    "The Mac is kept from idle sleep while it runs; do not close the lid.\n"
)
STOP = (
    "Autopilot did not finish every step; see the messages above. If they say nothing was "
    "written or company data was not touched, or make stopped with a line starting with ***, "
    "nothing needs filing; fix the cause and choose 3 again. Otherwise, unless they name a seq "
    "problem, do not choose 3 again; file with: "
    "make auto-file DATA_SET=company COUNT_AS=company\n"
)
EVERY_PARK = (
    "That command files every waiting park, including an earlier registered park, and may ask "
    "about other waiting parks by name.\n"
)
FILING_FAILED = (
    "Filing did not complete; see the messages above. To try again, run: "
    "make auto-file DATA_SET=company COUNT_AS=company\n"
)
SEQ_WARNING = "If the report above names a seq problem, do not file it.\n"
OPEN_URL = "http://127.0.0.1:8780/\n"
EOF_TEXT = "No answer was read. Nothing was changed.\n"


def parks_env(*parks: dict[str, object]) -> dict[str, str]:
    return {"PARKS_JSON": json.dumps({"data_set": "company", "parks": list(parks)})}


def test_ready_parks_are_numbered_and_a_source_problem_is_shown(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n2\n0\n2\n\n", env=parks_env(READY, BLOCKED))
    assert result.stdout.count(LIST_ONE) == 2
    assert "1. Beta Park" not in result.stdout
    assert calls.count(PARKS_CALL) == 1
    assert not any(call.startswith("autopilot-year") for call in calls)


def test_a_nameless_park_is_listed_by_the_label_with_its_id_in_place_of_the_name(
    tmp_path: Path,
) -> None:
    # park_label.py labels(): a park with no name and a first-played time gets
    # "<park ID> (first played <Mon D>)"; one with no name and no time gets the bare park ID.
    nameless = {**READY, "park_name": None, "park_label": "pk-1 (first played Nov 12)"}
    blank = {**BLOCKED, "park_name": "", "park_label": "pk-2"}
    result, _ = run_launcher(tmp_path, "3\n0\n2\n\n", env=parks_env(nameless, blank))
    expected = (
        f"{LIST_HEAD}1. pk-1 (first played Nov 12)\nNot ready: pk-2: no proven backup\n{BACK}"
    )
    assert expected in result.stdout
    assert result.stdout.count("pk-1 (first played Nov 12)") == 1
    assert "pk-1 (pk-1)" not in result.stdout
    assert "pk-2 (pk-2)" not in result.stdout
    assert "pk-2 (first played" not in result.stdout


def test_choosing_a_park_runs_autopilot_year_for_it(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n1\n\n", env=parks_env(BLOCKED, READY))
    assert calls == [UNFILED, PARKS_CALL, RECORD, YEAR, FILING]
    assert result.returncode == 0


def test_a_very_long_number_prints_the_list_again(tmp_path: Path) -> None:
    result, calls = run_launcher(
        tmp_path, "3\n99999999999999999999\n0\n2\n\n", env=parks_env(READY)
    )
    assert result.stdout.count(f"{LIST_HEAD}1. Alpha Park (first played Nov 12)\n{BACK}") == 2
    assert result.stdout.count(QUESTION) == 2
    assert not any(call.startswith("autopilot-year") for call in calls)


def test_a_park_name_with_odd_characters_is_shown_as_typed(tmp_path: Path) -> None:
    odd = {**READY, "park_label": "My Park 100% $HOME \\n \\ (first played Nov 12)"}
    result, _ = run_launcher(tmp_path, "3\n0\n2\n\n", env=parks_env(odd))
    assert "\n1. My Park 100% $HOME \\n \\ (first played Nov 12)\n" in result.stdout


def test_cancelling_returns_to_the_question(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n0\n2\n\n", env=parks_env(READY))
    assert calls == [
        UNFILED,
        PARKS_CALL,
        "auto-file DATA_SET=company RECORD=yes",
        "play DATA_SET=company",
        "auto-file DATA_SET=company COUNT_AS=practice",
    ]
    assert result.stdout.count(QUESTION) == 2
    assert result.returncode == 0


def test_an_empty_list_says_why_and_asks_again(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n2\n\n", env=parks_env())
    sentence = "No company park is registered yet, so autopilot has no park to run.\n"
    assert f"{sentence}{QUESTION}" in result.stdout
    assert result.stdout.count(QUESTION) == 2
    assert not any(call.startswith("autopilot-year") for call in calls)


def test_no_ready_park_prints_each_reason_and_asks_again(tmp_path: Path) -> None:
    other = {
        **BLOCKED,
        "park_id": "pk-3",
        "park_label": "Gamma Park (first played Nov 14)",
        "source_problem": "stale",
    }
    result, calls = run_launcher(tmp_path, "3\n2\n\n", env=parks_env(BLOCKED, other))
    printed = (
        "No park can run autopilot now:\n"
        "Not ready: Beta Park (first played Nov 13): no proven backup\n"
        "Not ready: Gamma Park (first played Nov 14): stale\n"
    )
    assert f"{printed}{QUESTION}" in result.stdout
    assert LIST_HEAD not in result.stdout
    assert not any(call.startswith("autopilot-year") for call in calls)


def test_a_failed_park_list_returns_to_the_question(tmp_path: Path) -> None:
    failed, failed_calls = run_launcher(
        tmp_path / "make", "3\n2\n\n", env={**parks_env(READY), "PARKS_EXIT": "2"}
    )
    assert f"{R6}{QUESTION}" in failed.stdout
    assert failed.stdout.count(QUESTION) == 2
    assert failed_calls[-1] == "auto-file DATA_SET=company COUNT_AS=practice"
    # The fake prints text that is not JSON and exits 0, so the helper is what fails.
    bad, _ = run_launcher(tmp_path / "helper", "3\n2\n\n", env={"PARKS_JSON": "not json"})
    assert f"{R6}{QUESTION}" in bad.stdout
    assert bad.stdout.count(QUESTION) == 2


def test_end_of_input_at_the_park_list_exits_130(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n", env=parks_env(READY))
    assert result.returncode == 130
    assert result.stdout.endswith(
        f"{LIST_HEAD}1. Alpha Park (first played Nov 12)\n{BACK}\n{EOF_TEXT}"
    )
    assert not any(call.startswith("autopilot-year") for call in calls)


BLOCKED_READY: dict[str, object] = {
    **READY,
    "park_label": "Beta Park (first played Nov 13)",
    "needs_ready": True,
}


def test_a_first_run_shows_the_sentence_and_passes_what_was_typed(tmp_path: Path) -> None:
    sentence = ready_phrase("pk-1")
    result, calls = run_launcher(
        tmp_path / "exact", f"3\n1\n{sentence}\n\n", env=parks_env(BLOCKED_READY)
    )
    assert f"{SENTENCE_HEAD}{sentence}\n" in result.stdout
    args = (tmp_path / "exact" / "args.log").read_text(encoding="utf-8").splitlines()
    assert f"READY={sentence}" in args
    assert calls[-2] == f"{YEAR} READY={sentence}"
    spaced, _ = run_launcher(
        tmp_path / "spaced", f"3\n1\n   {sentence}   \n\n", env=parks_env(BLOCKED_READY)
    )
    spaced_args = (tmp_path / "spaced" / "args.log").read_text(encoding="utf-8").splitlines()
    assert f"READY={sentence}" in spaced_args
    assert spaced.returncode == 0


def test_a_later_run_asks_no_sentence(tmp_path: Path) -> None:
    result, _ = run_launcher(tmp_path, "3\n1\n\n", env=parks_env(READY))
    assert "type this sentence exactly" not in result.stdout
    args = (tmp_path / "args.log").read_text(encoding="utf-8").splitlines()
    assert not any(arg.startswith("READY=") for arg in args)


def test_the_launcher_does_not_hold_the_sentence() -> None:
    assert READY_SUFFIX not in COMMAND.read_text(encoding="utf-8")


def test_end_of_input_at_the_sentence_exits_130(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n1\n", env=parks_env(BLOCKED_READY))
    assert result.returncode == 130
    assert result.stdout.endswith(f"{SENTENCE_HEAD}{ready_phrase('pk-1')}\n\n{EOF_TEXT}")
    assert not any(call.startswith(("autopilot-year", "auto-file")) for call in calls)


def test_a_successful_autopilot_year_is_filed_and_the_dashboard_opens(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n1\n\n", env=parks_env(READY))
    assert calls == [UNFILED, PARKS_CALL, RECORD, YEAR, FILING]
    assert (tmp_path / "open.log").read_text(encoding="utf-8") == OPEN_URL
    assert result.returncode == 0


def test_a_failed_record_step_does_not_start_autopilot(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n1\n\n", record_exit=1, env=parks_env(READY))
    assert calls == [UNFILED, PARKS_CALL, RECORD]
    assert not (tmp_path / "open.log").exists()
    assert STEP2 in result.stdout
    assert NOTICE not in result.stdout
    assert result.returncode == 2


def test_the_dashboard_open_does_not_change_the_exit_status(tmp_path: Path) -> None:
    fake_dir = tmp_path / "fake-open"
    fake_dir.mkdir()
    fake = fake_dir / "open"
    fake.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$OPEN_LOG"\nexit 1\n', encoding="utf-8")
    fake.chmod(0o755)
    run_dir = tmp_path / "run"
    path = f"{fake_dir}:{run_dir / 'bin'}:{Path(sys.executable).parent}:/usr/bin:/bin"
    result, calls = run_launcher(run_dir, "3\n1\n\n", env={**parks_env(READY), "PATH": path})
    assert calls[-1] == FILING
    assert (run_dir / "open.log").read_text(encoding="utf-8") == OPEN_URL
    assert result.returncode == 0


@pytest.mark.parametrize("year_exit", ["1", "2"])
def test_a_failed_autopilot_year_prints_the_stop_line_and_the_rerun_command(
    tmp_path: Path, year_exit: str
) -> None:
    result, calls = run_launcher(
        tmp_path, "3\n1\n\n", env={**parks_env(READY), "AUTOPILOT_EXIT": year_exit}
    )
    assert f"{STOP}{EVERY_PARK}" in result.stdout
    assert calls[-1] == YEAR
    assert not (tmp_path / "open.log").exists()
    assert result.returncode == 2
    assert "was not filed" not in result.stdout and "harmless" not in result.stdout


def test_a_failed_filing_after_autopilot_prints_the_rerun_line(tmp_path: Path) -> None:
    # The fake fails the first COUNT_AS call (its offer_file code); no offer is made here.
    result, calls = run_launcher(
        tmp_path, "3\n1\n\n", exits={"offer_file": 1}, env=parks_env(READY)
    )
    assert f"{FILING_FAILED}{EVERY_PARK}{SEQ_WARNING}" in result.stdout
    assert calls[-1] == FILING
    assert not (tmp_path / "open.log").exists()
    assert result.returncode == 2
    assert "was not filed" not in result.stdout and "harmless" not in result.stdout


def test_the_long_run_notice_is_printed_before_autopilot_year(tmp_path: Path) -> None:
    result, _ = run_launcher(tmp_path, "3\n1\n\n", env=parks_env(READY))
    assert result.stdout.index(NOTICE) < result.stdout.index("autopilot-year started")


def test_autopilot_year_runs_under_caffeinate(tmp_path: Path) -> None:
    sentence = ready_phrase("pk-1")
    base = ["-i", "make", "autopilot-year", "DATA_SET=company", "PARK=pk-1"]
    later, _ = run_launcher(tmp_path / "later", "3\n1\n\n", env=parks_env(READY))
    log = (tmp_path / "later" / "caffeinate.log").read_text(encoding="utf-8").splitlines()
    assert log == base
    first, _ = run_launcher(
        tmp_path / "first", f"3\n1\n{sentence}\n\n", env=parks_env(BLOCKED_READY)
    )
    log = (tmp_path / "first" / "caffeinate.log").read_text(encoding="utf-8").splitlines()
    assert log == [*base, f"READY={sentence}"]
    assert later.returncode == first.returncode == 0


DASHBOARD_START = "dashboard-start"
TYPED = "a  \"b\" 'c' $HOME \\ `d` end"


def dashboard_down_env(fake_dir: Path, run_dir: Path) -> dict[str, str]:
    """Fakes for a dashboard that is not running: `curl` fails until the fake `nohup` has run.

    The fake `nohup` writes `dashboard-start` into the same log the fake `make` writes and starts
    nothing, so one log holds the order of the start and the `make` calls. The launcher starts the
    server in the background, so a fake `direnv` waits (up to 5 s) for that write before it runs the
    record step: a start that comes late or never then shows in the log, with no race.
    """
    fake_dir.mkdir()
    (fake_dir / "curl").write_text(
        '#!/bin/sh\n[ -e "$RUN_DIR/dashboard-started" ]\n', encoding="utf-8"
    )
    (fake_dir / "nohup").write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' {DASHBOARD_START} >> \"$CALL_LOG\"\n"
        'touch "$RUN_DIR/dashboard-started"\n',
        encoding="utf-8",
    )
    (fake_dir / "direnv").write_text(
        "#!/bin/sh\n"
        'case "$*" in *RECORD=yes*) for _ in $(seq 50); do\n'
        '  [ -e "$RUN_DIR/dashboard-started" ] && break; sleep 0.1; done;; esac\n'
        'if [ "$1" = exec ]; then shift 2; exec "$@"; fi\n',
        encoding="utf-8",
    )
    for fake in fake_dir.iterdir():
        fake.chmod(0o755)
    return {"PATH": f"{fake_dir}:{run_dir / 'bin'}:{Path(sys.executable).parent}:/usr/bin:/bin"}


def test_the_dashboard_starts_after_the_sentence_and_before_the_record_step(
    tmp_path: Path,
) -> None:
    sentence = ready_phrase("pk-1")
    run_dir = tmp_path / "run"
    env = {**parks_env(BLOCKED_READY), **dashboard_down_env(tmp_path / "fake", run_dir)}
    result, calls = run_launcher(run_dir, f"3\n1\n{sentence}\n\n", env=env)
    assert calls == [
        UNFILED,
        PARKS_CALL,
        DASHBOARD_START,
        RECORD,
        f"{YEAR} READY={sentence}",
        FILING,
    ]
    assert result.returncode == 0
    # The start comes after the sentence is read: input that ends at the sentence starts nothing.
    ended_dir = tmp_path / "ended"
    ended_env = {**parks_env(BLOCKED_READY), **dashboard_down_env(tmp_path / "fake2", ended_dir)}
    ended, ended_calls = run_launcher(ended_dir, "3\n1\n", env=ended_env)
    assert ended.returncode == 130
    assert ended_calls == [UNFILED, PARKS_CALL]


def test_the_typed_text_is_passed_as_one_ready_argument(tmp_path: Path) -> None:
    assert ready_phrase("pk-1") != TYPED
    result, calls = run_launcher(tmp_path, f"3\n1\n{TYPED}\n\n", env=parks_env(BLOCKED_READY))
    args = (tmp_path / "args.log").read_text(encoding="utf-8").splitlines()
    assert [arg for arg in args if arg.startswith("READY=")] == [f"READY={TYPED}"]
    assert args.count("PARK=pk-1") == 1
    assert calls[-2] == f"{YEAR} READY={TYPED}"
    caffeinate = (tmp_path / "caffeinate.log").read_text(encoding="utf-8").splitlines()
    assert caffeinate[-1] == f"READY={TYPED}"
    assert result.returncode == 0


def test_a_failed_filing_after_an_offered_filing_prints_the_rerun_line(tmp_path: Path) -> None:
    # Answer 1 files the planted waiting play (the first COUNT_AS call, exit 0); the filing after
    # autopilot is the second COUNT_AS call, which FILE_EXIT fails.
    result, calls = run_launcher(
        tmp_path,
        "1\n3\n1\n\n",
        unfiled=("offer\n" + LIST,),
        env={**parks_env(READY), "FILE_EXIT": "1"},
    )
    assert calls == [UNFILED, RECORD, FILING, PARKS_CALL, RECORD, YEAR, FILING]
    assert f"{FILING_FAILED}{EVERY_PARK}{SEQ_WARNING}" in result.stdout
    assert "The waiting play was not filed" not in result.stdout
    assert not (tmp_path / "open.log").exists()
    assert result.returncode == 2


ODD = "\\n \\c 50% \\"


def test_a_first_run_header_prints_an_odd_park_name_as_typed(tmp_path: Path) -> None:
    odd = {**BLOCKED_READY, "park_label": f"Odd {ODD} (first played Nov 13)"}
    sentence = ready_phrase("pk-1")
    result, _ = run_launcher(tmp_path, f"3\n1\n{sentence}\n\n", env=parks_env(odd))
    header = (
        f"This is the first autopilot run for Odd {ODD} (first played Nov 13). "
        "To confirm that it is ready, type this sentence exactly:\n"
    )
    assert f"{header}{sentence}\n" in result.stdout


def test_the_second_ready_park_is_the_one_that_runs(tmp_path: Path) -> None:
    later = {
        **READY,
        "park_id": "pk-3",
        "park_label": "Gamma Park (first played Nov 14)",
        "needs_ready": True,
    }
    sentence = ready_phrase("pk-3")
    result, calls = run_launcher(
        tmp_path, f"3\n2\n{sentence}\n\n", env=parks_env(BLOCKED, READY, later)
    )
    assert calls[-2] == f"autopilot-year DATA_SET=company PARK=pk-3 READY={sentence}"
    assert calls.count(PARKS_CALL) == 1
    head = (
        "This is the first autopilot run for Gamma Park (first played Nov 14). "
        "To confirm that it is ready, "
    )
    assert f"{head}type this sentence exactly:\n{sentence}\n" in result.stdout
    assert ready_phrase("pk-1") not in result.stdout
    assert result.returncode == 0


def test_the_sentence_comes_from_the_helper_and_the_typed_text_is_unchanged(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    fake = fake_dir / "python"
    fake.write_text(
        "#!/bin/sh\nprintf 'pk-1\\tAlpha Park\\t-\\tZZ made-up sentence\\n'\n", encoding="utf-8"
    )
    fake.chmod(0o755)
    path = f"{fake_dir}:{run_dir / 'bin'}:{Path(sys.executable).parent}:/usr/bin:/bin"
    result, calls = run_launcher(
        run_dir, "3\n1\nwhat was typed\n\n", env={**parks_env(READY), "PATH": path}
    )
    assert "type this sentence exactly:\nZZ made-up sentence\n" in result.stdout
    assert calls[-2] == f"{YEAR} READY=what was typed"


@pytest.mark.parametrize("second_ready", [False, True])
def test_a_not_ready_line_with_odd_text_is_printed_as_typed(
    tmp_path: Path, second_ready: bool
) -> None:
    odd = {
        **BLOCKED,
        "park_label": f"Odd {ODD} (first played Nov 13)",
        "source_problem": f"bad {ODD}",
    }
    line = f"Not ready: Odd {ODD} (first played Nov 13): bad {ODD}\n"
    parks = (READY, odd) if second_ready else (odd,)
    result, _ = run_launcher(tmp_path, "3\n0\n2\n\n", env=parks_env(*parks))
    assert line in result.stdout
    if not second_ready:
        assert f"No park can run autopilot now:\n{line}{QUESTION}" in result.stdout


def test_arithmetic_and_padded_answers_print_the_list_again(tmp_path: Path) -> None:
    result, calls = run_launcher(tmp_path, "3\n1+0\nn\n01\n0\n2\n\n", env=parks_env(READY))
    assert result.stdout.count(f"{LIST_HEAD}1. Alpha Park (first played Nov 12)\n{BACK}") == 4
    assert not any(call.startswith("autopilot-year") for call in calls)


@pytest.mark.parametrize("choice", ["company", "practice"])
def test_the_dashboard_starts_before_the_record_step_for_a_play(
    tmp_path: Path, choice: str
) -> None:
    run_dir = tmp_path / "run"
    env = dashboard_down_env(tmp_path / "fake", run_dir)
    answer = "1" if choice == "company" else "2"
    result, calls = run_launcher(run_dir, f"{answer}\n\n", env=env)
    assert calls == [
        UNFILED,
        DASHBOARD_START,
        RECORD,
        "play DATA_SET=company",
        f"auto-file DATA_SET=company COUNT_AS={choice}",
    ]
    assert result.returncode == 0
