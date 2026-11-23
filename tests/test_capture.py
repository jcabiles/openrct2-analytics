"""The capture command, run as a child process against temp folders and a stand-in game.

The stand-in game is a sleeping Python child; the stand-in game check tests its PID with
signal 0 and exits 0 (running), 1 (not running) or 3 (cannot tell), by pgrep's contract.
The test plays the plugin's part over a real socket.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics.ingest import capture, capture_session
from openrct2_analytics.ingest import plugin_install as pi
from openrct2_analytics.ingest.game_check import GameState
from openrct2_analytics.ingest.listener import Lander
from tests.test_convert import event
from tests.test_convert_event_types import START_PAYLOAD, typed_event

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_BYTES = b'registerPlugin({name: "openrct2-analytics"}); // stand-in build\n'
READY = "Open OpenRCT2 now"
CHECK_CODE = """
import os, sys
from pathlib import Path
pid_file = Path(sys.argv[1])
if not pid_file.exists():
    sys.exit(1)
try:
    os.kill(int(pid_file.read_text()), 0)
except ProcessLookupError:
    sys.exit(1)
except OSError:
    sys.exit(3)
"""


class Folders:
    """The temp folders one test points the command at."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.user = root / "user"
        self.data = root / "data"
        self.raw = self.data / "rehearsal" / "raw"
        self.parquet = self.data / "rehearsal" / "parquet"
        self.capture = root / "capture"
        self.pid_file = root / "game.pid"
        self.plugin_file = root / "build" / "openrct2-analytics.js"
        self.installed = pi.install_path(self.user)
        self.record = pi.record_path(self.capture)

    def env(self) -> dict[str, str]:
        clean = {k: v for k, v in os.environ.items() if not k.startswith("OPENRCT2_")}
        return {
            **clean,
            "OPENRCT2_USER_DIR": str(self.user),
            "OPENRCT2_DATA_DIR": str(self.data),
            "OPENRCT2_CAPTURE_DIR": str(self.capture),
            "OPENRCT2_BACKUP_DIR": str(self.root / "backups"),
            "PYTHONUNBUFFERED": "1",
        }

    def check_args(self) -> list[str]:
        return [sys.executable, "-c", CHECK_CODE, str(self.pid_file)]


class Command:
    """The capture command as a child process; a thread collects its merged output."""

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self.process = process
        self.lines: list[str] = []
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.append(line.rstrip("\n"))

    @property
    def output(self) -> str:
        return "\n".join(self.lines)

    def wait_for(self, text: str, timeout: float = 30) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if text in self.output:
                return
            if self.process.poll() is not None:
                self._reader.join(timeout=5)
                break
            time.sleep(0.02)
        assert text in self.output, f"{text!r} never printed; output:\n{self.output}"

    def finish(self, timeout: float = 60) -> int:
        code = self.process.wait(timeout=timeout)
        self._reader.join(timeout=5)
        return code


Start = Callable[..., Command]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def plugin_line(session: str, seq: int) -> str:
    """One event as the plugin sends it: no received_at, which the listener adds."""
    if seq == 1:
        payload = {**START_PAYLOAD, "headless": False}
        doc = json.loads(typed_event(session, seq, "session_start", payload))
    else:
        doc = json.loads(event(session, seq, "plugin_stats" if seq % 2 else "park_snapshot"))
    del doc["received_at"]
    return json.dumps(doc)


def plugin_lines(session: str, seqs: Sequence[int] = (1, 2, 3)) -> list[str]:
    return [plugin_line(session, seq) for seq in seqs]


def play(port: int, lines: Sequence[str]) -> None:
    """Send lines as the plugin does, then disconnect."""
    with socket.create_connection(("127.0.0.1", port)) as client:
        client.sendall("".join(line + "\n" for line in lines).encode("utf-8"))


def command_argv(folders: Folders, port: int, check: list[str] | None = None) -> list[str]:
    return [
        sys.executable,
        "-m",
        "openrct2_analytics.ingest.capture",
        "--data-set",
        "rehearsal",
        "--game-check-command",
        shlex.join(check or folders.check_args()),
        "--port",
        str(port),
        "--plugin-file",
        str(folders.plugin_file),
        "--poll-seconds",
        "0.05",
    ]


class Game:
    """The stand-in game: a sleeping child whose PID is written where the check reads it."""

    def __init__(self, pid_file: Path) -> None:
        sleeper = [sys.executable, "-c", "import time; time.sleep(300)"]
        self.process = subprocess.Popen(sleeper, text=True)
        pid_file.write_text(str(self.process.pid))

    def quit(self) -> None:
        self.process.terminate()
        self.process.wait(timeout=10)  # reaped, so signal 0 no longer finds it


@pytest.fixture(name="folders")
def folders_fixture(tmp_path: Path) -> Folders:
    made = Folders(tmp_path)
    (made.user / "plugin").mkdir(parents=True)
    (made.user / "save").mkdir()
    made.plugin_file.parent.mkdir()
    made.plugin_file.write_bytes(PLUGIN_BYTES)
    return made


@pytest.fixture(name="children")
def children_fixture() -> Iterator[list[subprocess.Popen[str]]]:
    """Every child a test starts; any still running at the end is killed and reaped."""
    started: list[subprocess.Popen[str]] = []
    yield started
    for child in started:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)


@pytest.fixture(name="start")
def start_fixture(folders: Folders, children: list[subprocess.Popen[str]]) -> Start:
    def start_command(port: int, check: list[str] | None = None) -> Command:
        process = subprocess.Popen(
            command_argv(folders, port, check),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=folders.env(),
        )
        children.append(process)
        return Command(process)

    return start_command


@pytest.fixture(name="game")
def game_fixture(folders: Folders, children: list[subprocess.Popen[str]]) -> Callable[[], Game]:
    def start_game() -> Game:
        made = Game(folders.pid_file)
        children.append(made.process)
        return made

    return start_game


def session_to_quit(start: Start, game: Callable[[], Game], lines: Sequence[str]) -> Command:
    """Start the command, open the game, send the lines, quit the game."""
    port = free_port()
    command = start(port)
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    play(port, lines)
    command.wait_for("events arriving")
    running.quit()
    return command


# ---- a session with a stand-in game ----


def test_1_plugin_is_installed_with_its_record_while_the_game_runs(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    port = free_port()
    command = start(port)
    command.wait_for(READY)
    assert f"Test run on port {port}: the real plugin sends only to 8765." in command.output
    running = game()
    command.wait_for("game seen")

    assert folders.installed.read_bytes() == PLUGIN_BYTES
    record = json.loads(folders.record.read_text(encoding="utf-8"))
    assert record["path"] == str(folders.installed)
    assert record["sha256"] == hashlib.sha256(PLUGIN_BYTES).hexdigest()
    assert not pi.temp_path(folders.user).exists()

    running.quit()
    assert command.finish() == 1  # no event landed in this run
    assert not folders.installed.exists()


def test_2_events_land_in_the_dated_file_and_a_second_run_appends(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    first = session_to_quit(start, game, plugin_lines("run-one"))
    assert first.finish() == 0, first.output
    [dated] = sorted((folders.raw / "v1").glob("events-*.jsonl"))
    before = dated.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["session_id"] for line in before] == ["run-one"] * 3
    assert all("received_at" in json.loads(line) for line in before)

    second = session_to_quit(start, game, plugin_lines("run-two"))
    assert second.finish() == 0, second.output

    after = dated.read_text(encoding="utf-8").splitlines()
    assert after[:3] == before
    assert [json.loads(line)["session_id"] for line in after[3:]] == ["run-two"] * 3
    assert "Sessions this run: 1" in second.output  # only this run's session is judged


def test_3_plugin_and_record_are_removed_when_the_game_quits_then_the_report_prints(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    command = session_to_quit(start, game, plugin_lines("quit-run"))

    assert command.finish() == 0, command.output
    assert not folders.installed.exists()
    assert not folders.record.exists()
    assert not pi.temp_path(folders.user).exists()
    out = command.output
    assert "The game has quit." in out
    assert "Events landed this run: 3 (park_snapshot 1, plugin_stats 1, session_start 1)" in out
    assert "Test Park, headless no" in out
    assert "seq 1 to 3; seq audit ok" in out
    report_end = out.index("Monthly statements (finance_month) received: 0")
    assert out.index("The plugin file was removed from") > report_end
    assert (folders.parquet / "audit" / "seq_audit.parquet").is_file()


def test_5_lines_typed_into_stdin_change_nothing(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    port = free_port()
    command = start(port)
    command.wait_for(READY)
    assert command.process.stdin is not None
    command.process.stdin.write("\n\nq\nexit\ny\nrm -rf /\n")
    command.process.stdin.flush()
    running = game()
    command.wait_for("game seen")
    time.sleep(0.3)  # several polls

    assert command.process.poll() is None
    assert folders.installed.read_bytes() == PLUGIN_BYTES

    play(port, plugin_lines("typed-at"))
    command.wait_for("events arriving")
    running.quit()
    assert command.finish() == 0, command.output
    assert not folders.installed.exists()


def test_12_a_quit_whose_plugin_removal_fails_exits_1_and_keeps_the_record(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    port = free_port()
    command = start(port)
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    plugin_folder = folders.installed.parent
    plugin_folder.chmod(0o555)  # the plugin file can no longer be unlinked
    try:
        play(port, plugin_lines("stuck-run"))
        command.wait_for("events arriving")
        running.quit()
        assert command.finish() == 1, command.output
    finally:
        plugin_folder.chmod(0o755)

    assert "Events landed this run: 3" in command.output  # the capture itself was clean
    assert "The plugin file was NOT removed" in command.output
    assert folders.installed.read_bytes() == PLUGIN_BYTES
    assert folders.record.exists()


def test_13_a_run_with_no_event_says_so_and_converts_nothing(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    command = start(free_port())
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    running.quit()

    assert command.finish() == 1, command.output
    assert command.lines.count("No event landed in this run.") == 1
    assert "Save pairing skipped: no event landed in this run." in command.output
    assert "The converter failed" not in command.output
    assert not folders.parquet.exists()
    assert not folders.installed.exists()


def test_the_watch_reports_cannot_tell_and_ends_only_after_running_then_not_running(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    G = GameState
    script = [G.NOT_RUNNING, G.UNKNOWN, G.UNKNOWN, G.RUNNING, G.UNKNOWN, G.RUNNING, G.NOT_RUNNING]
    answers = iter(script)

    capture_session._watch(lambda: next(answers), Lander(tmp_path), 0)

    out = capsys.readouterr().out.splitlines()
    assert out.count("Cannot tell whether the game is running; checking again.") == 2
    assert out.count("game seen") == 1
    assert out[-1] == "The game has quit."
    assert next(answers, None) is None  # every answer was used: no early quit


# ---- what this run is judged on ----


def test_a_seq_gap_in_this_run_exits_1_and_later_runs_only_warn(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    gap = session_to_quit(start, game, plugin_lines("gap-run", (1, 2, 4)))
    assert gap.finish() == 1, gap.output
    assert "seq audit FAILED (1 seq number(s) missing)" in gap.output
    assert "Save files" in gap.output  # the section prints before the exit decisions
    assert not folders.installed.exists()

    clean = session_to_quit(start, game, plugin_lines("clean-run"))

    assert clean.finish() == 0, clean.output
    assert "WARNING, earlier run: session gap-run: 1 seq number(s) missing" in clean.output


def test_a_converter_failure_prints_its_errors_not_a_report(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    mystery = json.loads(plugin_line("mystery-run", 2))
    mystery["event_type"] = "mystery"
    lines = [plugin_line("mystery-run", 1), json.dumps(mystery)]

    command = session_to_quit(start, game, lines)

    assert command.finish() == 1, command.output
    assert "The converter failed; no report was built from older Parquet." in command.output
    assert "Events landed this run" not in command.output
    assert "The plugin file was removed from" in command.output


def test_a_converter_that_raises_exits_1_and_still_says_what_happened_to_the_plugin(
    folders: Folders, start: Start, game: Callable[[], Game]
) -> None:
    taken = folders.parquet.with_name("parquet.lock")  # another conversion holds the lock
    taken.parent.mkdir(parents=True)
    taken.write_text("pid 4242 started earlier\n", encoding="utf-8")

    command = session_to_quit(start, game, plugin_lines("unsafe-out"))

    assert command.finish() == 1, command.output
    assert f"The converter failed: {taken} is held" in command.output
    assert "The plugin file was removed from" in command.output
    assert not folders.installed.exists()
    assert taken.is_file()  # the other holder's lock was left alone


# ---- what the real command builds, stamps and leaves out of git ----


def test_the_default_build_is_the_repos_plugin_dist_file() -> None:
    built = capture.REPO_ROOT / pi.BUILT_PLUGIN
    assert built == REPO_ROOT / "plugin" / "dist" / "openrct2-analytics.js"


def test_the_start_time_is_utc_when_the_local_time_zone_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    try:
        started = capture.start_time()
        gap = abs((datetime.now(UTC) - started).total_seconds())
    finally:
        monkeypatch.undo()
        time.tzset()

    assert started.utcoffset() is not None
    assert gap < 1


def test_the_install_record_is_ignored_by_git() -> None:
    record = f"data/capture/{pi.RECORD_FILE_NAME}"
    ignored = subprocess.run(["git", "check-ignore", "-q", record], cwd=REPO_ROOT, check=False)
    assert ignored.returncode == 0
