"""The benchmark's sample mode: three chained sessions converted into the sample folder.

The chain runs end to end: each session loads the save the previous one wrote, reports that
save's ID in its ``session_start``, and the three sessions convert into the sample folder
beside its README. Every ``bench.run`` also checks that each line the stand-in sent landed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openrct2_analytics.ingest.bench_actions import ACTION_HELPER_FILE
from openrct2_analytics.ingest.bench_sample import _report, combine_raw
from openrct2_analytics.ingest.bench_setup import (
    AUTOSAVE_NEVER,
    SAVE_HELPER_FILE,
    config_ini,
)
from openrct2_analytics.ingest.convert import ConvertResult, convert
from tests.test_bench_run import FIXTURE_BYTES, BenchHarness, make_bench
from tests.test_convert import event, query

README = "# Rehearsal extract\n\nKept by every conversion.\n"


@pytest.fixture(name="bench")
def bench_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> BenchHarness:
    made = make_bench(tmp_path, monkeypatch)
    made.sample_dir.mkdir()
    (made.sample_dir / "README.md").write_text(README, encoding="utf-8")
    return made


def test_each_session_loads_a_copy_of_the_save_the_previous_session_wrote(
    bench: BenchHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.plan({"save": True})

    code = bench.run(sample=True)

    sessions = [bench.folder(f"sample-session-{n}") for n in (1, 2, 3)]
    saves = [s.save_dir / f"bench-sample-session-{n}.park" for n, s in enumerate(sessions, 1)]
    loaded = [s.save_dir / "bench-park.park" for s in sessions]
    assert loaded[0].read_bytes() == FIXTURE_BYTES
    assert loaded[1].read_bytes() == saves[0].read_bytes() == FIXTURE_BYTES + b"+standin-1"
    assert loaded[2].read_bytes() == saves[1].read_bytes()
    assert all(save.is_file() for save in saves)  # copied, never moved
    assert [argv[1] for argv in bench.launch_argvs()] == [str(path) for path in loaded]  # type: ignore[index]
    for number, session in enumerate(sessions, start=1):
        helper = (session.user_data / "plugin" / SAVE_HELPER_FILE).read_text(encoding="utf-8")
        assert not (session.user_data / "plugin" / ACTION_HELPER_FILE).exists()
        assert f'var SAVE_FILENAME = "bench-sample-session-{number}";' in helper
        assert "var SAVE_AFTER_DAYS = 3;" in helper
        config = (session.user_data / "config.ini").read_text(encoding="utf-8")
        assert config == config_ini(bench.game_path, AUTOSAVE_NEVER)
    assert bench.fixture.read_bytes() == FIXTURE_BYTES
    assert len(list((bench.bench_dir / "sample-raw" / "v1").glob("events-*.jsonl"))) == 3

    out = capsys.readouterr().out
    assert code == 0
    assert "Converted 3 sessions into the sample folder" in out
    assert sorted(path.name for path in bench.sample_dir.iterdir()) == ["README.md", "audit", "v1"]
    assert (bench.sample_dir / "README.md").read_text(encoding="utf-8") == README
    written = bench.sample_dir / "v1" / "save_written.parquet"
    assert query(written, "SELECT session_id, save_id FROM '{p}' ORDER BY 1") == [
        (f"standin-{n}", f"save-standin-{n}") for n in (1, 2, 3)
    ]
    # Each session reports the save the previous session wrote; the first loaded the fixture.
    starts = bench.sample_dir / "v1" / "session_start.parquet"
    lineage = "SELECT session_id, loaded_save_id, loaded_save_session_id FROM '{p}' ORDER BY 1"
    assert query(starts, lineage) == [
        ("standin-1", None, None),
        ("standin-2", "save-standin-1", "standin-1"),
        ("standin-3", "save-standin-2", "standin-2"),
    ]
    for private in bench.private_texts():
        assert private not in out


def test_a_session_that_never_saves_times_out_and_stops_the_chain(
    bench: BenchHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.plan({})

    assert bench.run(sample=True, seconds_per_day=0.5, startup_seconds=2.0) == 1

    assert len(bench.launch_argvs()) == 1
    assert "Sample session 1 failed: timed out after 3.5 s" in capsys.readouterr().out
    assert not (bench.bench_dir / "sample-raw").exists()
    assert sorted(path.name for path in bench.sample_dir.iterdir()) == ["README.md"]


def test_a_session_waits_until_its_save_is_finished_and_saves_park_whatever_it_loaded(
    bench: BenchHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # save_written lands first, then the save is written in chunks over about 1 s.
    other_park = bench.fixture.with_suffix(".sv6")
    other_park.write_bytes(FIXTURE_BYTES)
    monkeypatch.setenv("OPENRCT2_BENCH_PARK", str(other_park))
    bench.plan({"slow_save": True})

    assert bench.run(sample=True) == 0

    sessions = [bench.folder(f"sample-session-{n}") for n in (1, 2, 3)]
    assert (sessions[0].save_dir / "bench-park.sv6").read_bytes() == FIXTURE_BYTES
    finished = sessions[0].save_dir / "bench-sample-session-1.park"
    assert finished.read_bytes() == FIXTURE_BYTES + b"+standin-1"
    assert (sessions[1].save_dir / "bench-park.park").read_bytes() == finished.read_bytes()
    second = (sessions[1].save_dir / "bench-sample-session-2.park").read_bytes()
    assert second == FIXTURE_BYTES + b"+standin-1+standin-2"
    assert (sessions[2].save_dir / "bench-park.park").read_bytes() == second


def test_a_session_that_changes_the_fixture_fails_the_sample(
    bench: BenchHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    bench.plan({"save": True, "touch": str(bench.fixture)})

    assert bench.run(sample=True) == 1

    assert len(bench.launch_argvs()) == 1
    out = capsys.readouterr().out
    assert "Sample session 1 failed: fixture changed during the run." in out
    assert not (bench.bench_dir / "sample-raw").exists()
    assert sorted(path.name for path in bench.sample_dir.iterdir()) == ["README.md"]


def test_the_sessions_convert_together_and_the_readme_stays(tmp_path: Path) -> None:
    raw_dirs = []
    for number in (1, 2, 3):
        raw = tmp_path / f"session-{number}" / "raw"
        (raw / "v1").mkdir(parents=True)
        lines = [event(f"s{number}", seq) for seq in (1, 2)]
        # The listener names files by date, so all three sessions share one name.
        (raw / "v1" / "events-2026-10-01.jsonl").write_text("\n".join(lines) + "\n")
        raw_dirs.append(raw)
    (raw_dirs[1] / "malformed-2026-10-01.jsonl").write_text(json.dumps({"line": "x"}) + "\n")
    sample = tmp_path / "sample"
    (sample / "v1").mkdir(parents=True)
    (sample / "v1" / "stale.parquet").write_bytes(b"old")
    (sample / "README.md").write_text(README, encoding="utf-8")
    before = [path.read_bytes() for raw in raw_dirs for path in sorted(raw.rglob("*.jsonl"))]

    combine_raw(raw_dirs, tmp_path / "combined")
    result = convert(tmp_path / "combined", sample)

    assert result.ok and result.malformed_lines == 1
    assert result.row_counts["park_snapshot"] == 6
    audit = sample / "audit" / "seq_audit.parquet"
    assert query(audit, "SELECT session_id, row_count FROM '{p}' ORDER BY 1") == [
        ("s1", 2),
        ("s2", 2),
        ("s3", 2),
    ]
    assert (sample / "README.md").read_text(encoding="utf-8") == README
    assert not (sample / "v1" / "stale.parquet").exists()  # v1 is replaced as a whole
    assert [path.read_bytes() for raw in raw_dirs for path in sorted(raw.rglob("*.jsonl"))] == (
        before
    )


def test_a_sample_with_malformed_lines_fails_and_says_it_was_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = ConvertResult(malformed_lines=1, row_counts={"session_start": 3})

    assert _report(result, tmp_path) == 1

    out = capsys.readouterr().out
    assert "1 malformed line(s) in malformed-*.jsonl were not converted." in out
    assert "The sample was written but holds malformed lines" in out


def test_a_clean_sample_reports_the_counts_and_succeeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _report(ConvertResult(row_counts={"session_start": 3}), tmp_path) == 0

    out = capsys.readouterr().out
    assert "(session_start=3)" in out
    assert "Converted 3 sessions into the sample folder." in out
