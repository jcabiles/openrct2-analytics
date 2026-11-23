"""Read-only attribution and byte-preserving plans for company deletion."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest import park_label, play_mode_feed
from openrct2_analytics.ingest.publish_errors import PublishRefused
from openrct2_analytics.ingest.registry_feed import FILE_GLOB as REGISTRY_GLOB


def raw_lines(content: bytes) -> list[bytes]:
    """Split on newline bytes only, keeping terminators, so the pieces rejoin to the original.

    The converter reads text with universal newlines, so it also ends a line at a lone carriage
    return. A CRLF line counts once in both; a lone CR is not a break here and is one in the
    converter, so counts differ for such a file.
    """
    parts = content.split(b"\n")
    lines = [part + b"\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


@dataclass(frozen=True)
class Scope:
    """The scope confirmed by a phrase, independent of its eventual file list."""

    park: str | None = None
    session: str | None = None

    @property
    def phrase(self) -> str:
        """Return the exact confirmation phrase."""
        if self.park is not None:
            return f"delete company park {self.park}"
        if self.session is not None:
            return f"delete company session {self.session}"
        return "delete all company data"

    @property
    def named(self) -> bool:
        """Whether raw attribution is required."""
        return self.park is not None or self.session is not None


@dataclass
class Change:
    """An original snapshot and its replacement; None means remove the file."""

    path: Path
    original: bytes
    kept: bytes | None
    sessions: dict[str, int] = field(default_factory=dict)
    unattributed: int = 0

    @property
    def digest(self) -> str:
        """Return the archived snapshot's SHA-256."""
        return hashlib.sha256(self.original).hexdigest()

    @property
    def removed_lines(self) -> int:
        """Return the number of physical lines absent from the replacement."""
        kept = b"" if self.kept is None else self.kept
        return len(raw_lines(self.original)) - len(raw_lines(kept))


@dataclass
class Plan:
    """All mutations and warnings in one authoritative snapshot."""

    scope: Scope
    changes: list[Change] = field(default_factory=list)
    derived: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    live: str | None = None
    parks: list[str] = field(default_factory=list)


def _event(line: bytes) -> dict[str, object] | None:
    try:
        value = json.loads(line)
    except (ValueError, UnicodeError, RecursionError):
        # Unreadable lines are counted and kept or removed whole, never a reason to stop.
        return None
    return value if isinstance(value, dict) else None


def session_id(line: bytes) -> str | None:
    """Return the line's string session_id, or None when it has no readable one."""
    session = (_event(line) or {}).get("session_id")
    return session if isinstance(session, str) else None


def attribution(line: bytes) -> tuple[str, str] | None:
    """Read string identifiers, retaining every malformed/unattributable line."""
    park = (_event(line) or {}).get("park_id")
    session = session_id(line)
    return (park, session) if isinstance(park, str) and session is not None else None


def removal_change(path: Path, original: bytes) -> Change:
    """Plan removal of a whole raw event file, counting lines per session for the preview."""
    counts: Counter[str] = Counter()
    unreadable = 0
    for line in raw_lines(original):
        session = session_id(line)
        if session is None:
            unreadable += 1
        else:
            counts[session] += 1
    return Change(path, original, None, dict(counts), unreadable)


def csv_records(content: bytes) -> list[tuple[list[str], bytes]]:
    """Parse CSV records while retaining original physical bytes, including quoted newlines."""
    lines = content.splitlines(keepends=True)
    # utf-8-sig on the header only: a byte-order mark must not hide the park_id column.
    text = [line.decode("utf-8-sig" if i == 0 else "utf-8") for i, line in enumerate(lines)]
    reader = csv.reader(text, strict=True)
    records = []
    start = 0
    for row in reader:
        records.append((row, b"".join(lines[start : reader.line_num])))
        start = reader.line_num
    return records


def _csv_change(path: Path, column: str, value: str) -> Change | None:
    """Plan the removal of every row of a delivery whose ``column`` equals ``value``."""
    original = path.read_bytes()
    records = csv_records(original)
    if not records or column not in records[0][0]:
        return None
    index = records[0][0].index(column)
    kept = [raw for row, raw in records[1:] if len(row) <= index or row[index] != value]
    if len(kept) == len(records) - 1:
        return None
    return Change(path, original, records[0][1] + b"".join(kept) if kept else None)


def _selected(scope: Scope, parks: dict[str, set[str]], deliveries: list[Change]) -> set[str]:
    selected = {
        session for session, ids in parks.items() if session == scope.session or scope.park in ids
    }
    if not selected and not deliveries:
        kind, value = ("park", scope.park) if scope.park is not None else ("session", scope.session)
        raise PublishRefused("unknown-id", f"no company data carries {kind} {value!r}")
    for session in selected:
        if len(parks[session]) > 1:
            raise PublishRefused(
                "mixed-session", f"session {session!r} carries {sorted(parks[session])!r}"
            )
    return selected


def _raw_change(path: Path, original: bytes, selected: set[str]) -> Change:
    kept = []
    counts: Counter[str] = Counter()
    unattributed = 0
    for line in raw_lines(original):
        ids = attribution(line)
        if ids is not None and ids[1] in selected:
            counts[ids[1]] += 1
        else:
            kept.append(line)
            unattributed += ids is None
    return Change(path, original, b"".join(kept) or None, dict(counts), unattributed)


def _index(files: dict[Path, bytes]) -> tuple[dict[str, set[str]], dict[str, tuple[str, str]]]:
    parks: dict[str, set[str]] = defaultdict(set)
    latest: dict[str, tuple[str, str]] = {}
    for path, original in files.items():
        for line in raw_lines(original):
            ids = attribution(line)
            if ids is not None:
                parks[ids[1]].add(ids[0])
                received = (_event(line) or {}).get("received_at")
                # The file name breaks ties and orders lines without received_at. It cannot order
                # sessions alone: an autopilot file sorts before the managed file of its date.
                stamp = (received if isinstance(received, str) else "", path.name)
                latest[ids[1]] = max(latest.get(ids[1], ("", "")), stamp)
    return parks, latest


def _refuse_ready_phrase_session(session: str, company: Path) -> None:
    """Refuse a delete that would leave a park's first autopilot row without the ready phrase.

    The label check needs each park's first autopilot row (in delivery order) to carry the
    phrase, so such a delete would fail the check after files changed.
    """
    labels = play_mode_feed.read_labels(company / "registry")
    label = labels.get(session)
    if label is None or label.play_mode != play_mode_feed.AUTOPILOT:
        return
    others = [
        key
        for key, other in labels.items()
        if other.play_mode == play_mode_feed.AUTOPILOT
        and other.park_id == label.park_id
        and key != session
    ]
    if others and labels[others[0]].ready_confirmation != play_mode_feed.ready_phrase(
        label.park_id
    ):
        raise PublishRefused(
            "ready-phrase-row",
            f"session {session} holds the ready phrase of park {label.park_id}; delete the other "
            f"autopilot sessions of that park first, one at a time with SESSION=<id> "
            f"({', '.join(others)}), or the whole park with PARK={label.park_id}",
        )


def _selected_parks(scope: Scope, parks: dict[str, set[str]]) -> list[str]:
    """The park IDs the scope selects: the named park, or each park of the named session."""
    if scope.park is not None:
        return [scope.park]
    return sorted(parks.get(scope.session or "", ()))


def named_plan(scope: Scope, company: Path) -> Plan:
    """Find the named ID, reject mixed sessions, and build byte-exact replacements."""
    if scope.park == "" or scope.session == "":
        raise PublishRefused("unknown-id", "empty ID ''")
    files = {
        path: path.read_bytes() for path in sorted((company / "raw").glob("v*/events-*.jsonl"))
    }
    parks, days = _index(files)
    deliveries = []
    for pattern, column, value in (
        (REGISTRY_GLOB, "park_id", scope.park),
        (play_mode_feed.FILE_GLOB, "park_id", scope.park),
        (play_mode_feed.FILE_GLOB, "session_id", scope.session),
    ):
        if value is not None:
            deliveries += [
                change
                for path in sorted((company / "registry/v1").glob(pattern))
                if (change := _csv_change(path, column, value)) is not None
            ]
    selected = _selected(scope, parks, deliveries)
    if scope.session is not None:
        _refuse_ready_phrase_session(scope.session, company)
    plan = Plan(scope, parks=_selected_parks(scope, parks))
    for path, original in files.items():
        change = _raw_change(path, original, selected)
        plan.notes.append(f"{path}: {change.unattributed} unattributed lines kept")
        if change.sessions:
            plan.changes.append(change)
    plan.changes.extend(deliveries)
    for path in sorted((company / "raw").rglob("malformed-*.jsonl")):
        plan.notes.append(f"{path}: {len(raw_lines(path.read_bytes()))} malformed lines kept")
    for session in sorted(selected):
        if any(
            other not in selected and parks[session] & ids and days[other] > days[session]
            for other, ids in parks.items()
        ):
            plan.notes.append(
                f"session {session!r} is not its park's latest: missing days of a closed month "
                "fail the missing-day test in make pipeline by design; later sessions that "
                "loaded its saves may become orphans; replay the save"
            )
    return plan


def _print_parks(plan: Plan, company: Path) -> None:
    """Print ``park <id>: <label>`` for each selected park; the ID alone when names fail."""
    if not plan.parks:
        return
    try:
        landing = LandingDirs(raw=company / "raw", parquet=company / "parquet")
        names = park_label.labels(park_label.park_facts(landing))
    except (duckdb.Error, OSError, ValueError) as error:
        # Deliberate: a name is a courtesy, so the preview, its counts and the confirmation still
        # print; each park shows by ID and one line says why.
        for park in plan.parks:
            print(f"park {park}: {park}")
        print(f"park names could not be read: {error}; parks are shown by ID.")
        return
    for park in plan.parks:
        print(f"park {park}: {park_label.label_of(names, park)}")


def print_plan(plan: Plan, company: Path) -> None:
    """Print every changed file, counts, rebuild warning, and confirmation phrase."""
    print(f"scope: park={plan.scope.park!r}, session={plan.scope.session!r}")
    _print_parks(plan, company)
    for change in plan.changes:
        action = "rewrite" if change.kept is not None else "remove"
        print(
            f"archive and {action}: {change.path}; {change.removed_lines} lines removed "
            f"of {len(raw_lines(change.original))}"
        )
        for session, count in change.sessions.items():
            print(f"  session {session!r}: {count} lines removed")
        if change.kept is None and change.unattributed:
            print(f"  {change.unattributed} lines removed without a readable session_id")
    for path in plan.derived:
        print(f"remove derived: {path}")
    for note in plan.notes:
        print(note)
    if plan.live is not None:
        print(
            "only rebuildable files removed, including the published warehouse "
            "and its rollback copy"
        )
        print(f"raw captures and registry deliveries kept (live since {plan.live})")
    print("the dev warehouse may still hold company rows; the next `make transform` rebuilds it")
    if plan.scope.named:
        print("run `make pipeline DATA_SET=company` to rebuild")
    print(f"confirmation: {plan.scope.phrase!r}")
