"""Watch the game's save folders and append one record per created or changed ``.park`` file.

Polls the ``save``, ``save/autosave`` and parent folders of the user folder, plus the game's
remembered save folder from ``config.ini`` when it names a new one, once per poll interval
(stdlib only). The first scan takes a baseline and writes a ``start`` record per
``.park`` file; later scans write ``created`` and ``modified`` records to
``<landing>/v1/save_file_observation_<UTC date>.jsonl`` (spec R1 to R9). Records hold a base
name, never a path. The watcher shares no object or lock with the listener's ``Lander`` and
writes none of its files. Requirement numbers such as R12 refer to
docs/ai-dlc/specs/save-file-watcher.md.
"""

from __future__ import annotations

import configparser
import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openrct2_analytics.ingest.listener import Clock, format_received_at, utc_now
from openrct2_analytics.ingest.save_pairing import (
    RECORD_FILE_PREFIX,
    RECORD_FILE_SUFFIX,
    RECORD_FOLDER,
    SaveFileRecord,
    WatcherError,
)

JOIN_LIMIT_SECONDS = 5.0
_SUFFIX = ".park"
REMEMBERED_KIND = "remembered"
_TAIL = "watching the save, autosave and user folders only."
NO_REMEMBERED_NOTE = f"Note: config.ini names no remembered save folder; {_TAIL}"
_MACOS_PRIVACY = (
    " On macOS, allow the terminal under System Settings, Privacy & Security, "
    "Files and Folders (or Full Disk Access), then run the capture again."
)
_FileStat = tuple[int, int]  # (modified time in nanoseconds, size in bytes)


def watch_folders(user_dir: Path) -> dict[str, Path]:
    """Return the three watched folders by kind (spec R1); nothing is read."""
    return {
        "save": user_dir / "save",
        "autosave": user_dir / "save" / "autosave",
        "parent": user_dir,
    }


def remembered_folder(user_dir: Path) -> tuple[Path | None, str | None]:
    """Return the folder to watch as ``remembered`` (or None) and the one line to print (or None).

    Reads ``last_game_directory`` under ``[general]`` of ``user_dir/config.ini`` once. Nothing
    here raises for a bad ``config.ini`` or a bad folder: an optional feature never blocks a
    capture, so the problem is returned as the note to print (spec R1 to R6).
    """
    configured = _configured_folder(user_dir)
    if isinstance(configured, str):
        return None, configured
    folder, shown = configured
    if any(_same_folder(folder, default) for default in watch_folders(user_dir).values()):
        return None, None  # already watched under its own kind (spec R3)
    note = _unreadable_note(folder, shown)
    if note is not None:
        return None, note
    # realpath, not Path.resolve, to match _same_folder.
    if Path(os.path.realpath(folder)).is_relative_to(Path(os.path.realpath(user_dir))):
        return folder, None
    return folder, (
        f"Warning: the game's remembered save folder {shown} is outside the OpenRCT2 user "
        "folder; watching it too."
    )


def _configured_folder(user_dir: Path) -> tuple[Path, str] | str:
    """Read the folder named in ``config.ini``.

    Returns the folder with the value as ``config.ini`` gives it (after quote stripping), or the
    note to print when there is no usable folder.
    """
    try:
        text = (user_dir / "config.ini").read_text(encoding="utf-8-sig")
        # "%" in a path is not a format; a default section named "\x00" (no file can write it)
        # keeps [DEFAULT] an ordinary section, so no value is inherited into [general].
        parser = configparser.ConfigParser(interpolation=None, default_section="\x00")
        parser.read_string(text)
    except FileNotFoundError:
        # A game that never wrote a config.ini has no remembered folder (spec R2).
        return NO_REMEMBERED_NOTE
    except (OSError, UnicodeDecodeError, configparser.Error) as exc:
        # Unreadable, a folder, not UTF-8 or malformed: shown in the note, not swallowed (R2b).
        return f"Note: config.ini could not be read ({type(exc).__name__}: {exc}); {_TAIL}"
    value = parser.get("general", "last_game_directory", fallback="")
    if value.startswith('"') and value.endswith('"') and value != '"':
        value = value[1:-1]
    if not value:
        return NO_REMEMBERED_NOTE
    if "\x00" in value:
        return f"Note: config.ini's remembered save folder {value!r} is not a usable path; {_TAIL}"
    folder = Path(value)
    if not folder.is_absolute():
        return f"Note: config.ini's remembered save folder {value} is not an absolute path; {_TAIL}"
    return folder, value


def _unreadable_note(folder: Path, shown: str) -> str | None:
    """Probe the folder as the first scan would; the note to print when it cannot be read."""
    try:
        list_park_files(folder)
    except FileNotFoundError:
        return None  # kept: a drive not yet mounted is still where the game will save (R6)
    except OSError as exc:
        # Any other error would fail the first scan, so the folder is dropped here instead.
        note = (
            f"Note: the game's remembered save folder {shown} cannot be read "
            f"({type(exc).__name__}: {exc}); it is not watched."
        )
        return note + (_MACOS_PRIVACY if isinstance(exc, PermissionError) else "")
    return None


def _same_folder(first: Path, second: Path) -> bool:
    """True when both name one folder; ``samefile`` folds letter case, ``resolve`` cannot."""
    try:
        return os.path.samefile(first, second)
    except OSError:
        # One of them is missing or unreadable, so compare the spelled-out paths instead.
        # realpath, not Path.resolve: a symlink loop makes resolve() raise RuntimeError.
        return os.path.realpath(first) == os.path.realpath(second)


def list_park_files(folder: Path) -> dict[str, _FileStat]:
    """Return the folder's counted ``.park`` files by base name.

    Raises:
        OSError: if the folder cannot be listed or a file cannot be stat-ed;
            ``FileNotFoundError`` when the folder does not exist.
    """
    listing: dict[str, _FileStat] = {}
    for entry in list(os.scandir(folder)):
        if not entry.name.endswith(_SUFFIX) or entry.name == _SUFFIX:
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            stat = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            # The file vanished between listing and stat (an autosave rotation can remove it).
            continue
        listing[entry.name[: -len(_SUFFIX)]] = (stat.st_mtime_ns, stat.st_size)
    return listing


@dataclass(frozen=True)
class WatchStop:
    """What ``stop()`` found: the error (stored, or made from a flag) and the two flags."""

    error: WatcherError | None
    ended_early: bool
    join_timed_out: bool


class SaveWatcher:
    """Scans the watched folders and appends records; building one reads and writes nothing.

    Args:
        folders: Watched folders by kind, from ``watch_folders``.
        landing_dir: Folder that receives ``v1/``; created on the first write.
        run_started_at: The capture run's start, copied into every record.
        poll_seconds: Time between scans.
        say: Prints one line (folder-gone, folder-back and error lines).
        clock: Returns the current time; tests pass a fixed or steppable one.
    """

    def __init__(
        self,
        folders: dict[str, Path],
        landing_dir: Path,
        run_started_at: datetime,
        poll_seconds: float,
        *,
        say: Callable[[str], None],
        clock: Clock = utc_now,
    ) -> None:
        self._folders = folders
        self._landing_dir = landing_dir
        self._run_started_at = run_started_at
        self._poll_seconds = poll_seconds
        self._say = say
        self._clock = clock
        self._known: dict[tuple[str, str], _FileStat] = {}
        self._seen_folders: set[str] = set()
        self._gone: set[str] = set()
        self._baselined = False
        self._thread: threading.Thread | None = None
        self._halt = threading.Event()
        self._stopped = False  # set by the thread only when it ended on purpose
        self._error: WatcherError | None = None

    def scan(self) -> None:
        """Scan every folder once and append a record per new or changed file.

        ``observed_at`` is read once before the folders are listed, so a file written mid-scan
        can carry a ``modified_at`` later than ``observed_at``.
        """
        now = self._clock()
        found: dict[tuple[str, str], _FileStat] = {}
        for kind, folder in self._folders.items():
            listing = self._list(kind, folder)
            if listing is None:
                # A vanished folder keeps its last-scan files, so its return is judged against them.
                found.update({key: stat for key, stat in self._known.items() if key[0] == kind})
            else:
                found.update({(kind, name): stat for name, stat in listing.items()})
        records = self._records(found, now)
        self._write(records, now)
        self._known = found
        self._baselined = True

    def start(self) -> None:
        """Run the first scan on this thread (an ``OSError`` propagates), then poll in a thread."""
        self.scan()
        self._thread = threading.Thread(target=self._run, name="save-watcher", daemon=True)
        self._thread.start()

    def stop(self, join_limit: float = JOIN_LIMIT_SECONDS) -> WatchStop:
        """End the thread after one final scan, waiting up to ``join_limit`` seconds for it.

        A never-started watcher is a no-op, including one whose thread was created but whose
        ``start()`` failed (joining such a thread raises).
        """
        if self._thread is None or self._thread.ident is None:
            return WatchStop(None, False, False)
        self._halt.set()
        self._thread.join(join_limit)
        timed_out = self._thread.is_alive()
        ended_early = not timed_out and not self._stopped
        error = self._error
        if error is None and (timed_out or ended_early):
            message = (
                f"watcher did not stop within {join_limit:g} s"
                if timed_out
                else "watcher thread ended early"
            )
            error = WatcherError(at=self._clock(), message=message)
        return WatchStop(error, ended_early, timed_out)

    def _run(self) -> None:
        while not self._halt.wait(self._poll_seconds):
            if not self._guarded_scan():
                break
        else:
            self._guarded_scan()  # the quit save can land just before the stop
        self._stopped = True

    def _guarded_scan(self) -> bool:
        """Scan; on an ``OSError`` store and print it and return False (others end the thread)."""
        try:
            self.scan()
        except OSError as exc:
            self._error = WatcherError(at=self._clock(), message=f"{type(exc).__name__}: {exc}")
            self._say(
                f"Save-file watcher stopped at {self._error.at.isoformat()}: {self._error.message}"
            )
            return False
        return True

    def _list(self, kind: str, folder: Path) -> dict[str, _FileStat] | None:
        """Return the folder's counted files, or None when it does not exist."""
        try:
            listing = list_park_files(folder)
        except FileNotFoundError:
            # A missing folder is waited for (spec D5, R7), not a failure.
            if kind in self._seen_folders and kind not in self._gone:
                self._gone.add(kind)
                self._say(f"{kind} save folder is gone; watching for it to return.")
            return None
        self._seen_folders.add(kind)
        if kind in self._gone:
            self._gone.discard(kind)
            self._say(f"{kind} save folder is back.")
        return listing

    def _records(
        self, found: dict[tuple[str, str], _FileStat], now: datetime
    ) -> list[SaveFileRecord]:
        records: list[SaveFileRecord] = []
        for (kind, name), (mtime_ns, size) in sorted(found.items()):
            before = self._known.get((kind, name))
            observation: str | None
            if not self._baselined:
                observation = "start"
            elif before is None:
                observation = "created"
            else:
                observation = "modified" if before != (mtime_ns, size) else None
            if observation is None:
                continue
            modified = datetime.fromtimestamp(0, UTC) + timedelta(microseconds=mtime_ns // 1000)
            records.append(
                SaveFileRecord(self._run_started_at, observation, name, kind, modified, size, now)
            )
        return records

    def _write(self, records: list[SaveFileRecord], now: datetime) -> None:
        if not records:
            return
        observed = format_received_at(now)
        name = f"{RECORD_FILE_PREFIX}{observed[:10]}{RECORD_FILE_SUFFIX}"
        path = self._landing_dir / RECORD_FOLDER / name
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = "".join(json.dumps(_fields(record)) + "\n" for record in records)
        with path.open("ab+") as handle:
            # A crash can leave a torn last line; end it so only that line is lost.
            handle.seek(0, os.SEEK_END)
            if handle.tell() > 0:
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    handle.write(b"\n")
            handle.write(lines.encode("utf-8"))


def _fields(record: SaveFileRecord) -> dict[str, object]:
    return {
        "run_started_at": format_received_at(record.run_started_at),
        "observation": record.observation,
        "file_name": record.file_name,
        "folder_kind": record.folder_kind,
        "modified_at": format_received_at(record.modified_at),
        "size_bytes": record.size_bytes,
        "observed_at": format_received_at(record.observed_at),
    }
