"""The optional watch of ``bench_play``: the hook sees landed events and polls, never more."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from openrct2_analytics.ingest import bench_play
from openrct2_analytics.ingest.bench_setup import BenchSettings, RunFolder
from tests.test_capture import free_port

GAME_SCRIPT = """
import json, socket, sys, time
sock = socket.create_connection(("127.0.0.1", {port}))
for seq in (1, 2):
    event = {{"schema_version": 1, "event_type": "park_snapshot", "seq": seq}}
    sock.sendall((json.dumps(event) + "\\n").encode())
sock.sendall(b"not json\\n")
time.sleep(60)
"""


def event_line(**fields: object) -> bytes:
    return (
        json.dumps({"schema_version": 1, "event_type": "park_snapshot", **fields}) + "\n"
    ).encode()


class RecordingWatch:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self.ticks = 0

    def on_landed(self, event: dict[str, object]) -> None:
        self.events.append(event)

    def tick(self) -> None:
        self.ticks += 1


def make_bench(tmp_path: Path) -> tuple[bench_play.Bench, RunFolder, Path]:
    port = free_port()
    script = tmp_path / "game.py"
    script.write_text(GAME_SCRIPT.format(port=port), encoding="utf-8")
    binary = tmp_path / "game"
    binary.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding="utf-8")
    binary.chmod(0o755)
    settings = BenchSettings(binary, tmp_path / "park", tmp_path, tmp_path, tmp_path)
    options = bench_play.Options(
        listener_port=port, startup_seconds=30.0, stop_grace_seconds=5.0, game_port=free_port()
    )
    folder = RunFolder(tmp_path / "run")
    folder.raw.mkdir(parents=True)
    folder.user_data.mkdir(parents=True)
    bench = bench_play.Bench(settings, options, tmp_path / "plugin.js", "0" * 40, "stand-in")
    return bench, folder, tmp_path / "park-copy"


def two_snapshots(lander: bench_play.CountingLander) -> bool:
    return lander.count("park_snapshot") >= 2


def test_lander_without_a_hook_lands_and_counts_as_before(tmp_path: Path) -> None:
    lander = bench_play.CountingLander(tmp_path)

    assert lander.land(event_line(seq=1)) is True
    assert lander.count("park_snapshot") == 1


def test_lander_calls_the_hook_with_the_parsed_event_after_it_landed(tmp_path: Path) -> None:
    seen: list[dict[str, object]] = []
    lander = bench_play.CountingLander(tmp_path, seen.append)

    assert lander.land(event_line(seq=7)) is True

    assert [event["seq"] for event in seen] == [7]
    assert lander.count("park_snapshot") == 1


def test_lander_does_not_call_the_hook_for_a_malformed_line(tmp_path: Path) -> None:
    seen: list[dict[str, object]] = []
    lander = bench_play.CountingLander(tmp_path, seen.append)

    assert lander.land(b"not json\n") is False

    assert seen == []


def test_play_with_a_watch_reports_every_landed_event_and_polls(tmp_path: Path) -> None:
    bench, folder, park_copy = make_bench(tmp_path)
    watch = RecordingWatch()

    problem = bench_play.play(bench, folder, park_copy, stop=two_snapshots, days=1, watch=watch)

    assert problem is None
    assert [event["seq"] for event in watch.events] == [1, 2]  # the malformed line is not seen
    assert watch.ticks >= 1


def test_play_without_a_watch_runs_as_before(tmp_path: Path) -> None:
    bench, folder, park_copy = make_bench(tmp_path)

    problem = bench_play.play(bench, folder, park_copy, stop=two_snapshots, days=1)

    assert problem is None
    landed = [
        line
        for path in folder.raw.rglob("events-*.jsonl")
        for line in path.read_text().splitlines()
    ]
    assert len(landed) == 2


def test_lander_does_not_call_the_hook_for_a_parsable_line_the_listener_rejects(
    tmp_path: Path,
) -> None:
    seen: list[dict[str, object]] = []
    lander = bench_play.CountingLander(tmp_path, seen.append)

    assert lander.land(event_line(seq=1, schema_version=0)) is False

    assert seen == []
    assert lander.count("park_snapshot") == 0


def test_lander_calls_the_hook_only_once_the_line_is_on_disk(tmp_path: Path) -> None:
    on_disk_when_called: list[int] = []

    def hook(event: dict[str, object]) -> None:
        on_disk_when_called.append(
            sum(len(path.read_text().splitlines()) for path in tmp_path.rglob("*.jsonl"))
        )

    lander = bench_play.CountingLander(tmp_path, hook)

    assert lander.land(event_line(seq=1)) is True

    assert on_disk_when_called == [1]
