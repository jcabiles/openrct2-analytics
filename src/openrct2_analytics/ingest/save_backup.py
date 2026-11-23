"""Back up each park's last recorded save, and warn before play when a save changed unrecorded.

After a healthy company capture, each park's last paired save of the run is copied to a
never-overwritten archive under ``OPENRCT2_BACKUP_DIR`` (default ``local/park-backups``) and to the
game's save folder as ``<park name>-last-plugin-save-YYYY-MM-DD.park``. A dated copy counts as this
command's own only while its bytes equal one of that park's archive copies: only then is it
replaced or recommended, so a file the player saved into is never overwritten or offered as a
clean restore point. Before play, any ``.park`` file that changed after its last paired write is
named, with the park's newest own copy. Decision record: ADR 0048 in ``docs/adr/``.
"""

from __future__ import annotations

import filecmp
import os
import shutil
import stat
import tempfile
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from openrct2_analytics.ingest.park_label import park_names as park_names
from openrct2_analytics.ingest.save_files import read_records, read_save_written
from openrct2_analytics.ingest.save_pairing import (
    RunPairing,
    SaveFileRecord,
    SaveJudgment,
    SavePair,
    StartCheck,
    judge_saves,
)

BACKUP_MARK = "-last-plugin-save-"
PARK_SUFFIX = ".park"
BACKUP_DATA_SET = "company"
FINE_DATA = "The recorded data is fine; only the backup copy failed."
EPOCH = datetime.fromtimestamp(0, UTC)
ARCHIVE_TIME_FORMAT = "%Y-%m-%d-%H%M%S"  # the time at the end of an archive copy's name
_MILLISECOND = timedelta(milliseconds=1)


class BackupFailed(Exception):
    """Raised when one copy cannot be made safely; the message says why."""


@dataclass(frozen=True)
class BackupPlan:
    """Where one run's backup copies come from and go.

    Attributes:
        watched: The run's watched folders by kind, as the watcher used them.
        game_save_dir: The game's own save folder, which receives the dated copy.
        archive_dir: The archive root; each park gets its own folder under it.
        parquet_dir: The converted Parquet, for the park names.
        replace_own_copy: When False, an existing same-day dated copy is never replaced, not even
            this command's own; a copy named to the second is written beside it.
    """

    watched: dict[str, Path]
    game_save_dir: Path
    archive_dir: Path
    parquet_dir: Path
    replace_own_copy: bool = True


def file_label(park_name: str | None, park_id: str) -> str:
    """The park name made safe for a file name; the ``park_id`` when there is no name."""
    for text in (park_name or "", park_id):
        cleaned = "".join(
            "_" if ch in "/:\\" or unicodedata.category(ch) == "Cc" else ch for ch in text
        )
        if cleaned.startswith("."):
            cleaned = "_" + cleaned[1:]
        if cleaned.strip():
            return cleaned
    return "_"


def archive_files(park_archive: Path) -> list[Path]:
    """The park's archive copies (regular ``.park`` files), sorted by full name."""
    try:
        return sorted(
            Path(entry.path)
            for entry in os.scandir(park_archive)
            if entry.name.endswith(PARK_SUFFIX) and entry.is_file(follow_symlinks=False)
        )
    except FileNotFoundError:
        return []


def is_own_copy(path: Path, park_archive: Path) -> bool:
    """True when ``path`` is a regular file whose bytes equal one of the park's archive copies."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    return any(
        proof.stat().st_size == info.st_size and filecmp.cmp(path, proof, shallow=False)
        for proof in archive_files(park_archive)
    )


def newest_own_copy(game_save_dir: Path, label: str, park_archive: Path) -> str | None:
    """The file name of the park's newest dated copy that is still its own, or None."""
    prefix = f"{label}{BACKUP_MARK}"
    try:
        names = [
            entry.name
            for entry in os.scandir(game_save_dir)
            if entry.name.startswith(prefix) and entry.name.endswith(PARK_SUFFIX)
        ]
    except FileNotFoundError:
        return None
    for name in sorted(names, reverse=True):
        if is_own_copy(game_save_dir / name, park_archive):
            return name
    return None


def choose(run: RunPairing) -> tuple[list[SavePair], list[str]]:
    """Each park's last paired save of the run, and a line for each park that is skipped.

    A park is skipped when a later write in this run may hold newer, unrecorded play: a write of
    the chosen file, or an unpaired write of any file paired with that park in this run.
    """
    last: dict[str, SavePair] = {}
    for pair in sorted(run.pairs, key=lambda p: (p.row.emitted_at, p.row.event_id)):
        last[pair.row.park_id] = pair
    chosen: list[SavePair] = []
    skipped: list[str] = []
    for park_id, pair in sorted(last.items()):
        park_files = {p.record.key for p in run.pairs if p.row.park_id == park_id}
        newer = [
            r
            for r in (*(p.record for p in run.pairs), *run.unpaired)
            if r.modified_at > pair.record.modified_at
            and (r.key == pair.record.key or (r in run.unpaired and r.key in park_files))
        ]
        if newer:
            skipped.append(
                f"No backup made for park {park_id}: {newer[0].file_name} was written after its "
                "last recorded save, so newer unrecorded play may exist; the previous backup was "
                "kept."
            )
        else:
            chosen.append(pair)
    return chosen, skipped


def milliseconds(moment: datetime) -> int:
    """Whole milliseconds from the epoch to ``moment``, as the watcher cuts a record's time."""
    return (moment - EPOCH) // _MILLISECOND


def _matches(path: Path, record: SaveFileRecord) -> bool:
    """True when the file still has the recorded size and modified time (to the millisecond)."""
    info = path.lstat()
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_size == record.size_bytes
        and info.st_mtime_ns // 1_000_000 == milliseconds(record.modified_at)
    )


def copy_checked(
    source: Path, record: SaveFileRecord, target: Path, *, replace: bool = False
) -> None:
    """Copy ``source`` to ``target`` through a temporary file, checking the source before and after.

    The temporary file has no ``.park`` suffix, so the game never lists a half-written copy.
    Without ``replace`` an existing target is never replaced; the caller decides when it may be.

    Raises:
        BackupFailed: if the source changed, or (without ``replace``) the target exists.
        OSError: if a read or write fails.
    """
    if not _matches(source, record):
        raise BackupFailed(f"{source.name} changed after it was recorded")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".backup-", suffix=".tmp")
    staged = Path(temporary)
    try:
        with os.fdopen(handle, "wb") as out, source.open("rb") as src:
            shutil.copyfileobj(src, out)
            out.flush()
            os.fsync(out.fileno())
        if not _matches(source, record) or staged.stat().st_size != record.size_bytes:
            raise BackupFailed(f"{source.name} changed while it was copied")
        if replace:
            os.replace(staged, target)
        else:
            try:
                os.link(staged, target)  # fails when the target exists, unlike a rename
            except FileExistsError as exc:
                raise BackupFailed(f"{target} already exists; it was left alone") from exc
    finally:
        staged.unlink(missing_ok=True)


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except FileNotFoundError:
        return False


def _game_copy(
    source: Path,
    record: SaveFileRecord,
    *,
    daily: Path,
    park_archive: Path,
    ended: datetime,
    replace_own_copy: bool,
) -> str:
    """Write the game-folder copy and return the report text naming it.

    The day's copy is replaced only while it is still this park's own copy. Otherwise (the player
    saved into it, or another park of the same name owns it), or when ``replace_own_copy`` is False,
    a copy named to the second is written beside it, so no player file is ever overwritten.
    """
    if _same_file(source, daily):
        return f"save/{daily.name} (it already was that file, so it was kept as is)"
    try:
        info = daily.lstat()
    except FileNotFoundError:
        copy_checked(source, record, daily)
        return f"save/{daily.name}"
    if replace_own_copy and stat.S_ISREG(info.st_mode) and is_own_copy(daily, park_archive):
        copy_checked(source, record, daily, replace=True)
        return f"save/{daily.name}"
    timed = daily.with_name(f"{daily.stem}-{ended:%H%M%S}{PARK_SUFFIX}")
    copy_checked(source, record, timed)
    reason = "was changed by play, so it was left alone" if replace_own_copy else "was left alone"
    return f"save/{timed.name} ({daily.name} {reason})"


def _archive_inside_watched(plan: BackupPlan) -> str | None:
    archive_root = Path(os.path.realpath(plan.archive_dir))
    for folder in plan.watched.values():
        if archive_root.is_relative_to(os.path.realpath(folder)):
            return (
                f"Backup FAILED: the archive folder {plan.archive_dir} is inside the watched save "
                f"folder {folder}; set OPENRCT2_BACKUP_DIR elsewhere. {FINE_DATA}"
            )
    return None


def back_up(judgment: SaveJudgment, plan: BackupPlan, ended: datetime) -> tuple[list[str], bool]:
    """Copy each park's last recorded save; return the report lines and False when a copy failed.

    ``ended`` is the local time the run ended; it dates the game-folder copy and the archive copy.
    The archive copy and the game-folder copy are attempted independently.
    """
    chosen, lines = choose(judgment.this_run)
    if not chosen and not lines:
        return ["Backup: no recorded save in this run, so no backup was made."], True
    refusal = _archive_inside_watched(plan)
    if refusal is not None:
        return [refusal], False
    names = park_names(plan.parquet_dir)
    ok = True
    for pair in chosen:
        park_id, record = pair.row.park_id, pair.record
        label = file_label(names.get(park_id), park_id)
        source = plan.watched[record.folder_kind] / f"{record.file_name}{PARK_SUFFIX}"
        if not source.exists():
            lines.append(
                f"No backup made for {label}: its last recorded save {record.file_name} no longer "
                "exists (the game deletes old autosaves); the previous backup was kept."
            )
            continue
        park_archive = plan.archive_dir / file_label(None, park_id)
        archive = park_archive / f"{label}-{ended:{ARCHIVE_TIME_FORMAT}}{PARK_SUFFIX}"
        daily = plan.game_save_dir / f"{label}{BACKUP_MARK}{ended:%Y-%m-%d}{PARK_SUFFIX}"
        archived = shown = None
        try:
            copy_checked(source, record, archive)
            archived = str(archive)
        except (BackupFailed, OSError) as exc:
            lines.append(f"Backup FAILED for {label}'s archive copy: {exc}. {FINE_DATA}")
        try:
            shown = _game_copy(
                source,
                record,
                daily=daily,
                park_archive=park_archive,
                ended=ended,
                replace_own_copy=plan.replace_own_copy,
            )
        except (BackupFailed, OSError) as exc:
            lines.append(f"Backup FAILED for {label}'s game-folder copy: {exc}. {FINE_DATA}")
        if archived is None or shown is None:
            ok = False
            continue
        lines.append(
            f"Backup: {label}'s last recorded save ({record.file_name}) copied to {shown}; "
            f"archive copy {archived}."
        )
    return lines, ok


def _advice(label: str, game_save_dir: Path, park_archive: Path) -> str:
    newest = newest_own_copy(game_save_dir, label, park_archive)
    if newest is not None:
        return f"load {newest} instead"
    archived = archive_files(park_archive)
    if archived:
        return f"copy {archived[-1]} into the game's save folder and load it"
    return f"no backup copy of {label} exists yet"


def warning_lines(
    checks: Sequence[StartCheck],
    names: dict[str, str | None],
    game_save_dir: Path,
    archive_dir: Path,
) -> list[str]:
    """One line per save file that may hold unrecorded play, with the park's own copy to load.

    A file warns when it differs from its last paired write (a later write whose save event was
    lost included), or when it is a dated copy that is no longer its park's own copy. A dated copy
    that still equals an archive copy never warns: this command replaced it, not the player.
    """
    labels = {pid: file_label(name, pid) for pid, name in names.items()}
    lines: list[str] = []
    for check in checks:
        shown = f"{check.start.file_name}{PARK_SUFFIX}"
        path = game_save_dir / shown
        if BACKUP_MARK in check.start.file_name and check.start.folder_kind == "save":
            label = check.start.file_name.split(BACKUP_MARK)[0]
            parks = sorted(pid for pid, lab in labels.items() if lab == label)
            if any(is_own_copy(path, archive_dir / file_label(None, pid)) for pid in parks):
                continue
            if check.outcome in ("none", "changed") and len(parks) == 1:
                advice = _advice(label, game_save_dir, archive_dir / file_label(None, parks[0]))
                lines.append(
                    f"Warning: {shown} was saved over while nothing was recording; {advice}."
                )
                continue
        last = check.last_pair
        if (
            check.outcome not in ("changed", "lost")
            or last is None
            or last.record.modified_at == check.start.modified_at
        ):
            continue
        park_id = last.row.park_id
        advice = _advice(
            labels.get(park_id, file_label(None, park_id)),
            game_save_dir,
            archive_dir / file_label(None, park_id),
        )
        lines.append(f"Warning: {shown} changed after the last recorded save; {advice}.")
    return lines


def warn_before_play(
    save_dir: Path, parquet_dir: Path, started: datetime, *, game_save_dir: Path, archive_dir: Path
) -> list[str]:
    """The pre-play warning lines for this run's ``start`` records; never stops the run."""
    try:
        records, unreadable = read_records(save_dir, started)
        judgment = judge_saves(
            records,
            read_save_written(parquet_dir),
            started,
            unreadable=unreadable,
            watcher_error=None,
        )
        names = park_names(parquet_dir)
        return warning_lines(judgment.start_checks, names, game_save_dir, archive_dir)
    except (OSError, duckdb.Error) as exc:
        # The warning is advice; the same check runs again in the report after the game quits.
        return [f"Could not check the save files before play: {type(exc).__name__}: {exc}"]
