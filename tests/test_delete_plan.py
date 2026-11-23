"""Scoped attribution, warnings, and exact retained record bytes."""

import json
from collections.abc import Callable
from datetime import timedelta, timezone, tzinfo
from pathlib import Path

import pytest

from openrct2_analytics.config import LandingDirs
from openrct2_analytics.ingest.delete_plan import Scope, named_plan, print_plan
from openrct2_analytics.ingest.publish_errors import PublishRefused
from tests.test_park_label import converted


def write(path: Path, data: bytes = b"payload\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def event(park: str, session: str, seq: int = 1) -> bytes:
    return (
        json.dumps(
            {
                "park_id": park,
                "session_id": session,
                "seq": seq,
                "event_id": f"{session}:{seq}",
                "event_type": "session_start",
                "schema_version": 1,
                "emitted_at": "2026-10-17T00:00:00Z",
                "game_year": 1,
                "game_month": 1,
                "game_day": 1,
            }
        )
        + "\n"
    ).encode()


def test_session_keeps_unattributed_bytes_and_warns_for_earlier_session(tmp_path: Path) -> None:
    company = tmp_path / "company"
    kept = b'not json\n{"park_id": "p"}\n' + event("p", "later")
    path = write(company / "raw/v1/events-2026-10-16.jsonl", event("p", "s") + kept)
    write(company / "raw/v1/events-2026-10-17.jsonl", event("p", "later", 2))
    malformed = write(company / "raw/malformed-a.jsonl")
    plan = named_plan(Scope(session="s"), company)
    assert [(c.path, c.kept, c.sessions, c.unattributed) for c in plan.changes] == [
        (path, kept, {"s": 1}, 2)
    ]
    assert any("replay the save" in note for note in plan.notes)
    assert any(str(malformed) in note and "1 malformed" in note for note in plan.notes)


def test_registry_only_park_and_multiline_reordered_records(tmp_path: Path) -> None:
    company = tmp_path / "company"
    header = b"note,data_set,park_id\r\n"
    kept = b'"a quoted\r\nnote",company,keep\r\n'
    path = write(
        company / "registry/v1/park_registry_2026-10-17_01.csv",
        header + b"bye,company,a.b\r\n" + kept,
    )
    plan = named_plan(Scope(park="a.b"), company)
    assert len(plan.changes) == 1
    assert plan.changes[0].path == path
    assert plan.changes[0].kept == header + kept
    assert plan.scope.phrase == "delete company park a.b"


def test_park_selects_each_of_its_sessions_across_day_files(tmp_path: Path) -> None:
    company = tmp_path / "company"
    first = write(company / "raw/v1/events-a.jsonl", event("p", "first"))
    second = write(company / "raw/v1/events-b.jsonl", event("p", "second") + event("keep", "other"))
    plan = named_plan(Scope(park="p"), company)
    assert [(change.path, change.kept, change.sessions) for change in plan.changes] == [
        (first, None, {"first": 1}),
        (second, event("keep", "other"), {"second": 1}),
    ]


@pytest.mark.parametrize("scope", [Scope(park="p"), Scope(session="s")])
def test_mixed_session_refused(tmp_path: Path, scope: Scope) -> None:
    write(tmp_path / "raw/v1/events-a.jsonl", event("p", "s") + event("q", "s", 2))
    with pytest.raises(PublishRefused, match="mixed-session"):
        named_plan(scope, tmp_path)


def test_registry_delivery_with_byte_order_mark_keeps_the_mark_and_other_rows(
    tmp_path: Path,
) -> None:
    company = tmp_path / "company"
    header = b"\xef\xbb\xbfpark_id,data_set\r\n"
    kept = b"b,company\r\n"
    path = write(
        company / "registry/v1/park_registry_2026-10-17_01.csv", header + b"a,company\r\n" + kept
    )
    plan = named_plan(Scope(park="a"), company)
    assert [(c.path, c.kept) for c in plan.changes] == [(path, header + kept)]


def test_carriage_return_inside_json_does_not_split_a_line(tmp_path: Path) -> None:
    company = tmp_path / "company"
    split = b'{"park_id": "p",\r "session_id": "s"}\n'
    kept = event("p", "other")
    path = write(company / "raw/v1/events-a.jsonl", split + kept)
    plan = named_plan(Scope(session="s"), company)
    assert [(c.path, c.kept, c.sessions, c.unattributed) for c in plan.changes] == [
        (path, kept, {"s": 1}, 0)
    ]
    assert plan.changes[0].removed_lines == 1


def _two_sessions(company: Path) -> None:
    write(company / "raw/v1/events-2026-10-16.jsonl", event("p", "first"))
    write(company / "raw/v1/events-2026-10-17.jsonl", event("p", "second", 2))


def test_no_latest_warning_when_every_later_session_is_in_scope(tmp_path: Path) -> None:
    company = tmp_path / "company"
    _two_sessions(company)
    plan = named_plan(Scope(park="p"), company)
    assert not any("replay the save" in note for note in plan.notes)


def test_latest_warning_when_a_later_session_remains(tmp_path: Path) -> None:
    company = tmp_path / "company"
    _two_sessions(company)
    plan = named_plan(Scope(session="first"), company)
    assert any("replay the save" in note for note in plan.notes)


def _named_park(tmp_path: Path, zone: Callable[[tzinfo], None]) -> Path:
    """One park ``p`` with session ``s``, named and timed in the converted Parquet and raw lines."""
    zone(timezone(timedelta(hours=-8)))
    company = tmp_path / "company"
    write(company / "raw/v1/events-a.jsonl", event("p", "s"))
    converted(
        LandingDirs(raw=company / "raw", parquet=company / "parquet"),
        [("p", "s", "Alpha Park", "2026-10-17T00:00:00Z")],
    )
    return company


def _preview(scope: Scope, company: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    print_plan(named_plan(scope, company), company)
    return capsys.readouterr().out.splitlines()


def test_preview_names_the_park_with_its_id(
    tmp_path: Path, fixed_local_zone: Callable[[tzinfo], None], capsys: pytest.CaptureFixture[str]
) -> None:
    company = _named_park(tmp_path, fixed_local_zone)

    lines = _preview(Scope(park="p"), company, capsys)

    assert lines[0] == "scope: park='p', session=None"
    assert lines[1] == "park p: Alpha Park (first played Oct 16)"
    assert lines[-1] == "confirmation: 'delete company park p'"


def test_session_preview_names_its_park(
    tmp_path: Path, fixed_local_zone: Callable[[tzinfo], None], capsys: pytest.CaptureFixture[str]
) -> None:
    company = _named_park(tmp_path, fixed_local_zone)

    lines = _preview(Scope(session="s"), company, capsys)

    assert lines[0] == "scope: park=None, session='s'"
    assert lines[1] == "park p: Alpha Park (first played Oct 16)"
    assert lines[-1] == "confirmation: 'delete company session s'"


def test_a_park_the_landing_files_do_not_know_prints_its_id_alone(
    tmp_path: Path, fixed_local_zone: Callable[[tzinfo], None], capsys: pytest.CaptureFixture[str]
) -> None:
    company = _named_park(tmp_path, fixed_local_zone)
    write(company / "registry/v1/park_registry_2026-10-17_01.csv", b"park_id\r\nq\r\n")

    lines = _preview(Scope(park="q"), company, capsys)

    assert lines[:2] == ["scope: park='q', session=None", "park q: q"]
    assert not any("could not be read" in line for line in lines)


def _bare_id_preview(lines: list[str]) -> None:
    # The error text may span lines, so the could-not-be-read sentence is checked whole.
    text = "\n".join(lines)
    assert lines[0] == "scope: park='p', session=None"
    assert lines[1] == "park p: p"
    assert lines[2].startswith("park names could not be read: ")
    assert "; parks are shown by ID.\n" in text
    assert lines[-1] == "confirmation: 'delete company park p'"


def test_preview_survives_a_raw_file_that_is_not_utf8(
    tmp_path: Path, fixed_local_zone: Callable[[tzinfo], None], capsys: pytest.CaptureFixture[str]
) -> None:
    company = _named_park(tmp_path, fixed_local_zone)
    write(company / "raw/v1/events-b.jsonl", b'{"session_id": "r1", "park_name": "Caf\xc3')

    _bare_id_preview(_preview(Scope(park="p"), company, capsys))


def test_preview_survives_an_unreadable_parquet(
    tmp_path: Path, fixed_local_zone: Callable[[tzinfo], None], capsys: pytest.CaptureFixture[str]
) -> None:
    company = _named_park(tmp_path, fixed_local_zone)
    write(company / "parquet/v1/session_start.parquet", b"not parquet")

    _bare_id_preview(_preview(Scope(park="p"), company, capsys))
