"""Behavioral tests for the autopilot menu helper: JSON in, tab-separated lines out."""

from __future__ import annotations

import copy
import io
import json
import select
import signal
import subprocess
import sys
from collections.abc import Mapping

import pytest

from openrct2_analytics.ingest import autopilot_menu
from openrct2_analytics.ingest.play_mode_feed import ready_phrase

PARK = {
    "park_id": "p-b",
    "park_name": "Beta Park",
    "park_label": "Beta Park (first played Nov 13)",
    "newest_backup": {"file": "x.park", "modified_at": "2026-11-01T00:00:00Z"},
    "source_problem": None,
    "needs_ready": False,
}
OTHER = {**PARK, "park_id": "p-a", "park_label": "Alpha Park (first played Nov 12)"}


def run(
    payload: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    code = autopilot_menu.main()
    out, err = capsys.readouterr()
    return code, out, err


def one(park: Mapping[str, object], mp: pytest.MonkeyPatch, cs: pytest.CaptureFixture[str]) -> str:
    code, out, _ = run({"data_set": "company", "parks": [park]}, mp, cs)
    assert code == 0
    return out


def test_two_parks_keep_input_order(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = run({"parks": [PARK, OTHER]}, monkeypatch, capsys)
    assert code == 0
    assert out == (
        "p-b\tBeta Park (first played Nov 13)\t-\t-\np-a\tAlpha Park (first played Nov 12)\t-\t-\n"
    )


def test_a_park_with_a_source_problem(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = one({**PARK, "source_problem": "no backup"}, monkeypatch, capsys)
    assert out == "p-b\tBeta Park (first played Nov 13)\tno backup\t-\n"


def test_needs_ready_true_ends_with_the_sentence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = one({**PARK, "needs_ready": True}, monkeypatch, capsys)
    assert out == f"p-b\tBeta Park (first played Nov 13)\t-\t{ready_phrase('p-b')}\n"


def test_needs_ready_false_ends_with_dash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert one(PARK, monkeypatch, capsys).endswith("\t-\n")


def test_field_two_is_the_label(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = one(
        {**PARK, "park_name": "Other Name", "park_label": "Label (Nov 1)"}, monkeypatch, capsys
    )
    assert out == "p-b\tLabel (Nov 1)\t-\t-\n"


def test_missing_label_is_refused(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    park = {k: v for k, v in PARK.items() if k != "park_label"}
    code, out, err = run({"parks": [park]}, monkeypatch, capsys)
    assert (code, out) == (1, "")
    assert err == "autopilot_menu: input is not the park list: a park entry has no 'park_label'\n"


@pytest.mark.parametrize("label", [None, 5, "", "   "], ids=["null", "number", "empty", "blank"])
def test_blank_label_is_refused(
    label: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run({"parks": [{**PARK, "park_label": label}]}, monkeypatch, capsys)
    assert (code, out) == (1, "")
    assert (
        err == "autopilot_menu: input is not the park list: park_label is not a non-empty string\n"
    )


def test_an_empty_source_problem_prints_dash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        one({**PARK, "source_problem": ""}, monkeypatch, capsys)
        == "p-b\tBeta Park (first played Nov 13)\t-\t-\n"
    )


@pytest.mark.parametrize("char", ["\t", "\r", "\n"], ids=["tab", "carriage-return", "line-feed"])
def test_a_control_character_in_a_name_becomes_a_space(
    char: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = one({**PARK, "park_label": f"Beta{char}Park"}, monkeypatch, capsys)
    assert out == "p-b\tBeta Park\t-\t-\n"
    assert len(out.rstrip("\n").split("\t")) == 4


def test_an_empty_list_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run({"parks": []}, monkeypatch, capsys) == (0, "", "")


def test_an_extra_top_level_key_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = run({"parks": [PARK]}, monkeypatch, capsys)
    assert run({"parks": [PARK], "extra": 1}, monkeypatch, capsys) == base


def test_an_extra_park_key_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    base = run({"parks": [PARK]}, monkeypatch, capsys)
    assert run({"parks": [{**PARK, "extra": "x"}]}, monkeypatch, capsys) == base


def test_invalid_json_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run("{not json", monkeypatch, capsys)
    assert (code, out) == (1, "")
    assert err


@pytest.mark.parametrize("key", ["park_id", "park_label", "source_problem", "needs_ready"])
def test_a_park_missing_a_key_exits_1(
    key: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    park = copy.deepcopy(PARK)
    del park[key]
    code, out, err = run({"parks": [OTHER, park]}, monkeypatch, capsys)
    assert (code, out) == (1, "")
    assert err.startswith("autopilot_menu: input is not the park list:")


def _four_fields(out: str) -> list[str]:
    fields = out.rstrip("\n").split("\t")
    assert len(fields) == 4
    return fields


def test_a_tab_in_park_id_becomes_a_space(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = one({**PARK, "park_id": "p\tb"}, monkeypatch, capsys)
    assert out == "p b\tBeta Park (first played Nov 13)\t-\t-\n"
    _four_fields(out)


def test_a_tab_in_park_id_becomes_a_space_in_the_sentence(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = one({**PARK, "park_id": "p\tb", "needs_ready": True}, monkeypatch, capsys)
    sentence = ready_phrase("p\tb").replace("\t", " ")
    assert out == f"p b\tBeta Park (first played Nov 13)\t-\t{sentence}\n"
    _four_fields(out)


def test_a_line_feed_in_source_problem_becomes_a_space(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = one({**PARK, "source_problem": "no\nbackup"}, monkeypatch, capsys)
    assert out == "p-b\tBeta Park (first played Nov 13)\tno backup\t-\n"
    _four_fields(out)


def test_an_interrupt_exits_130(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(_stream: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr(json, "load", interrupted)
    assert run({"parks": [PARK]}, monkeypatch, capsys)[:2] == (130, "")


def _invalid_utf8(mp: pytest.MonkeyPatch) -> None:
    mp.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"\xff\xfe"), encoding="utf-8"))


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"parks": {}},
        {"parks": ["x"]},
        {"parks": [{**PARK, "park_id": ""}]},
        {"parks": [{**PARK, "park_id": 7}]},
        {"parks": [{**PARK, "park_label": 5}]},
        {"parks": [{**PARK, "source_problem": 5}]},
        {"parks": [{**PARK, "needs_ready": "true"}]},
        "[" * 100000,
    ],
    ids=[
        "top-level-not-object",
        "parks-not-list",
        "park-not-object",
        "park-id-empty",
        "park-id-not-string",
        "label-number",
        "problem-number",
        "needs-ready-string",
        "deep-nesting",
    ],
)
def test_input_not_in_the_documented_shape_exits_1(
    payload: object, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run(payload, monkeypatch, capsys)
    assert (code, out) == (1, "")
    assert err.startswith("autopilot_menu: input is not the park list:")
    assert "Traceback" not in err


def test_invalid_utf8_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _invalid_utf8(monkeypatch)
    code = autopilot_menu.main()
    out, err = capsys.readouterr()
    assert (code, out) == (1, "")
    assert err.startswith("autopilot_menu: input is not the park list:")
    assert "Traceback" not in err


def test_a_spaces_only_source_problem_prints_dash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    out = one({**PARK, "source_problem": "   "}, monkeypatch, capsys)
    assert out == "p-b\tBeta Park (first played Nov 13)\t-\t-\n"


def test_newest_backup_is_not_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    park = {k: v for k, v in PARK.items() if k != "newest_backup"}
    assert one(park, monkeypatch, capsys) == one(PARK, monkeypatch, capsys)


def test_an_unknown_argument_exits_2() -> None:
    done = subprocess.run(
        [sys.executable, "-B", "-m", "openrct2_analytics.ingest.autopilot_menu", "--bogus"],
        input="{}",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert (done.returncode, done.stdout) == (2, "")
    assert done.stderr.startswith("usage:")
    assert "unrecognized arguments: --bogus" in done.stderr


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP], ids=["sigterm", "sighup"])
def test_a_signal_exits_130(sig: signal.Signals) -> None:
    with subprocess.Popen(
        [sys.executable, "-B", "-u", "-c", _READY_THEN_RUN],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as proc:
        assert proc.stderr is not None and proc.stdin is not None
        if not select.select([proc.stderr], [], [], 10)[0]:
            proc.kill()
            pytest.fail("the helper never installed its signal handlers")
        assert proc.stderr.readline() == "ready\n"
        proc.send_signal(sig)
        out, _ = proc.communicate(timeout=60)
    assert (proc.returncode, out) == (130, "")


_READY_THEN_RUN = (
    "import sys\n"
    "from openrct2_analytics.ingest import autopilot_menu, lock\n"
    "real = lock.set_signal_handlers\n"
    "def ready(handler):\n"
    "    real(handler)\n"
    "    print('ready', file=sys.stderr, flush=True)\n"
    "lock.set_signal_handlers = ready\n"
    "sys.exit(autopilot_menu.main([]))\n"
)
