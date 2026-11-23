"""The benchmark's sample mode (``make bench-sample``): three chained sessions into the sample.

``bench_run`` refuses or prepares the invocation, then calls ``run_sample``. Session 1 loads a
copy of the fixture; sessions 2 and 3 load a copy of the save the previous session wrote (the
file is copied, never moved). Each session runs with autosave off and the save helper in its
own plugin folder, and stops once its save has landed. The three raw folders are then
converted together into the sample folder; the converter replaces only ``v1/`` and
``audit/`` there, so the folder's README stays.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Sequence
from pathlib import Path

from openrct2_analytics.ingest.bench_judge import FIXTURE_CHANGED
from openrct2_analytics.ingest.bench_play import Bench, CountingLander, play
from openrct2_analytics.ingest.bench_setup import (
    AUTOSAVE_NEVER,
    RunFolder,
    RunInputs,
    file_sha1,
    make_run_folder,
    save_helper,
)
from openrct2_analytics.ingest.capture import EXIT_OK, EXIT_PROBLEM, say
from openrct2_analytics.ingest.contracts import LANDING_FOLDER
from openrct2_analytics.ingest.convert import ConvertResult, NoInputError, convert, report_lines

SAMPLE_SESSIONS = 3
SAMPLE_RAW = "sample-raw"
SAVE_SUFFIX = ".park"  # OpenRCT2 0.5.5 always saves a .park file, whatever it loaded
# The save is finished once 3 polls this far apart see one size (the committed sample's method).
SAVE_POLL_SECONDS = 0.2
SAVE_STABLE_POLLS = 3


def session_name(session: int) -> str:
    """The folder of one sample session, relative to the work folder."""
    return f"sample-session-{session}"


def reserved_names() -> list[str]:
    """What sample mode writes in the work folder; a leftover of any of them refuses."""
    return [session_name(n) for n in range(1, SAMPLE_SESSIONS + 1)] + [SAMPLE_RAW]


class SaveLanded:
    """The stop condition of a sample session: its save has landed and is finished.

    The plugin sends ``save_written`` from inside the save hook, before the game writes the
    file, so the file must also exist and keep one size across ``SAVE_STABLE_POLLS`` polls
    ``SAVE_POLL_SECONDS`` apart.

    Args:
        save_file: Where the game writes the session's save.
    """

    def __init__(self, save_file: Path) -> None:
        self.save_file = save_file
        self._sizes: list[int] = []
        self._next_poll = 0.0

    def __call__(self, lander: CountingLander) -> bool:
        """Poll the save; True once it has landed and its size has stopped changing."""
        if lander.count("save_written") < 1 or not self.save_file.is_file():
            return False
        now = time.monotonic()
        if now < self._next_poll:
            return False
        self._next_poll = now + SAVE_POLL_SECONDS
        self._sizes.append(self.save_file.stat().st_size)
        last = self._sizes[-SAVE_STABLE_POLLS:]
        return len(last) == SAVE_STABLE_POLLS and len(set(last)) == 1


def _session(bench: Bench, session: int, park_in: Path) -> tuple[Path, str | None]:
    """Run one chained session; return its save file and None, or why it failed."""
    folder = RunFolder(bench.settings.bench_dir / session_name(session))
    save_name = f"bench-sample-session-{session}"
    helper = save_helper(save_name, bench.options.sample_days)
    inputs = RunInputs(park_in, bench.built, bench.settings.game_path, AUTOSAVE_NEVER, helper)
    park_copy = make_run_folder(folder, inputs)
    save_file = folder.save_dir / f"{save_name}{SAVE_SUFFIX}"
    stop = SaveLanded(save_file)
    problem = play(bench, folder, park_copy, stop=stop, days=bench.options.sample_days)
    if problem is None and file_sha1(bench.settings.park) != bench.fixture_sha1:
        problem = FIXTURE_CHANGED
    return save_file, problem


def combine_raw(raw_dirs: Sequence[Path], combined: Path) -> None:
    """Copy each session's raw files into one raw folder, renamed so no two collide.

    The listener names files by UTC date, so sessions on one day share names. The session
    raw folders are only read.
    """
    (combined / LANDING_FOLDER).mkdir(parents=True)
    for number, raw in enumerate(raw_dirs, start=1):
        for path in sorted((raw / LANDING_FOLDER).glob("events-*.jsonl")):
            shutil.copyfile(path, combined / LANDING_FOLDER / f"{path.stem}-session-{number}.jsonl")
        for path in sorted(raw.glob("malformed-*.jsonl")):
            shutil.copyfile(path, combined / f"{path.stem}-session-{number}.jsonl")


def _report(result: ConvertResult, out_dir: Path) -> int:
    """Print the conversion report; return 0 only for a clean audit and no malformed line."""
    for line in report_lines(result, out_dir):
        say(line)
    if result.schema_errors:
        say("The converter failed; the committed sample is unchanged.")
        return EXIT_PROBLEM
    if result.seq_violations:
        say("The sample was written but fails the seq audit.")
        return EXIT_PROBLEM
    if result.malformed_lines:
        say("The sample was written but holds malformed lines; a plugin run must have none.")
        return EXIT_PROBLEM
    say(f"Converted {SAMPLE_SESSIONS} sessions into the sample folder.")
    return EXIT_OK


def run_sample(bench: Bench) -> int:
    """Run the three chained sessions and convert them; return 0 when the sample was rebuilt."""
    park_in = bench.settings.park
    raw_dirs: list[Path] = []
    for session in range(1, SAMPLE_SESSIONS + 1):
        say(f"Sample session {session} in {session_name(session)}.")
        park_in, problem = _session(bench, session, park_in)
        if problem is not None:
            say(f"Sample session {session} failed: {problem}. No sample was converted.")
            return EXIT_PROBLEM
        raw_dirs.append(RunFolder(bench.settings.bench_dir / session_name(session)).raw)
    combined = bench.settings.bench_dir / SAMPLE_RAW
    combine_raw(raw_dirs, combined)
    try:
        result = convert(combined, bench.options.sample_dir)
    except NoInputError:
        say("The converter found no event; the committed sample is unchanged.")
        return EXIT_PROBLEM
    return _report(result, bench.options.sample_dir)
