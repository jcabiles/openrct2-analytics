"""Tests for the play-mode label feed: name shape, reader, ready phrase, checker and command line.

Every case builds CSV files in a temporary folder and runs the real contract check over them.
Expected texts are literals from docs/ai-dlc/specs/autopilot-year.md section 7.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.config import ConfigError
from openrct2_analytics.ingest import play_mode_feed, registry_feed
from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, load_reference_fields

HEADER = "session_id,park_id,play_mode,ready_confirmation,data_set,delivered_on"
PHRASE_A = "parka is profitable and its scenario challenge is complete"
PHRASE_B = "parkb is profitable and its scenario challenge is complete"
FIRST = "session_play_mode_2026-11-13_01.csv"
SECOND = "session_play_mode_2026-11-14_01.csv"
# Two parks, two deliveries: each park's first autopilot row has its phrase, a later one has none.
GOOD_FIRST = [
    f"s1,parka,autopilot,{PHRASE_A},rehearsal,2026-11-13",
    "s2,parkb,managed,,rehearsal,2026-11-13",
]
GOOD_SECOND = [
    "s3,parka,autopilot,,rehearsal,2026-11-14",
    f"s4,parkb,autopilot,{PHRASE_B},rehearsal,2026-11-14",
]
FAILED = ": failed (Actual custom_sql(session_play_mode) was {n}, expected = 0)"
RULE_PLAY_MODE = "test play_mode is managed or autopilot"
RULE_UNIQUE = "test session_id is unique across every delivery"
RULE_PHRASE = "test ready_confirmation is empty or exactly the park's ready phrase"
RULE_FIRST = (
    "test each park's first autopilot row, in file name then row order, carries the ready phrase"
)
RULE_DATA_SET = "test data_set equals the folder's data set and is rehearsal or company"
RULE_DELIVERED = "test delivered_on equals the date in the file name"
BAD_HEADER = (
    "{name}: header is not session_id,park_id,play_mode,ready_confirmation,data_set,delivered_on"
)
TWO_DATA_SETS = "rows name more than one data set: company, rehearsal"
BAD_NAME = "bad file name: {name} is not session_play_mode_YYYY-MM-DD_NN.csv"


def write_csv(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def deliver(root: Path, first: list[str], second: list[str]) -> Path:
    """Write the two deliveries under ``root/registry/v1`` and return the feed root."""
    write_csv(root / "registry" / "v1" / FIRST, [HEADER, *first])
    write_csv(root / "registry" / "v1" / SECOND, [HEADER, *second])
    return root / "registry"


def failed(rule: str, count: int = 1) -> str:
    return rule + FAILED.format(n=count)


def verdict(feed: Path, **kwargs: object) -> list[str]:
    """Return the check's problems without the overall-result line."""
    return [
        line
        for line in play_mode_feed.check_feed(feed, **kwargs)  # type: ignore[arg-type]
        if line != "test overall result: failed"
    ]


def test_fields_match_the_contract() -> None:
    fields = load_reference_fields(CONTRACTS_DIR / "reference")["session_play_mode"]
    assert [(f.name, f.logical, f.required) for f in fields] == [
        ("session_id", "string", True),
        ("park_id", "string", True),
        ("play_mode", "string", True),
        ("ready_confirmation", "string", False),
        ("data_set", "string", True),
        ("delivered_on", "date", True),
    ]
    assert tuple(HEADER.split(",")) == play_mode_feed.HEADER
    text = play_mode_feed.CONTRACT_PATH.read_text(encoding="utf-8")
    assert "\nversion: 1.0.0\n" in text


def test_ready_phrase_text() -> None:
    assert play_mode_feed.ready_phrase("parka") == PHRASE_A


@pytest.mark.parametrize(
    ("name", "accepted"),
    [
        ("session_play_mode_2026-11-13_01.csv", True),
        ("session_play_mode_2026-11-13_99.csv", True),
        ("session_play_mode_2026-11-13_00.csv", False),
        ("session_play_mode_2026-11-13_100.csv", False),
        ("session_play_mode_2026-11-13_1.csv", False),
        ("session_play_mode_2026-1-13_01.csv", False),
        ("session_play_mode_2026-11-13_01.csv.bak", False),
        ("park_registry_2026-11-13_01.csv", False),
    ],
)
def test_name_shape(name: str, accepted: bool) -> None:
    assert play_mode_feed.is_accepted_name(name) is accepted


def test_good_deliveries_pass(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    assert play_mode_feed.check_feed(feed, data_set="rehearsal") == []


def test_good_deliveries_pass_without_a_known_data_set(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    assert play_mode_feed.check_feed(feed) == []


# Each fault changes exactly one thing in the good deliveries.
FAULTS: dict[str, tuple[list[str], list[str], str]] = {
    "play_mode outside the two": (
        [GOOD_FIRST[0], "s2,parkb,robot,,rehearsal,2026-11-13"],
        GOOD_SECOND,
        failed(RULE_PLAY_MODE),
    ),
    "session_id repeated across two deliveries": (
        GOOD_FIRST,
        [GOOD_SECOND[0], f"s2,parkb,autopilot,{PHRASE_B},rehearsal,2026-11-14"],
        failed(RULE_UNIQUE),
    ),
    "ready_confirmation text wrong on a managed row": (
        [GOOD_FIRST[0], "s2,parkb,managed,parkb is ready,rehearsal,2026-11-13"],
        GOOD_SECOND,
        failed(RULE_PHRASE),
    ),
    "first autopilot row without the phrase": (
        ["s1,parka,autopilot,,rehearsal,2026-11-13", GOOD_FIRST[1]],
        GOOD_SECOND,
        failed(RULE_FIRST),
    ),
    "first autopilot row in delivery order is the later row of the earlier file": (
        [GOOD_FIRST[1], "s1,parka,autopilot,,rehearsal,2026-11-13"],
        [f"s3,parka,autopilot,{PHRASE_A},rehearsal,2026-11-14", GOOD_SECOND[1]],
        failed(RULE_FIRST),
    ),
    "data_set is not the folder's": (
        [GOOD_FIRST[0], "s2,parkb,managed,,company,2026-11-13"],
        GOOD_SECOND,
        failed(RULE_DATA_SET),
    ),
    "delivered_on differs from the file name date": (
        [GOOD_FIRST[0], "s2,parkb,managed,,rehearsal,2026-11-12"],
        GOOD_SECOND,
        failed(RULE_DELIVERED),
    ),
}


@pytest.mark.parametrize("fault", FAULTS)
def test_planted_fault_fails_with_its_rule(tmp_path: Path, fault: str) -> None:
    first, second, message = FAULTS[fault]
    feed = deliver(tmp_path, first, second)
    assert verdict(feed, data_set="rehearsal") == [message]


def test_the_other_parks_phrase_fails_both_phrase_rules(tmp_path: Path) -> None:
    first = [f"s1,parka,autopilot,{PHRASE_B},rehearsal,2026-11-13", GOOD_FIRST[1]]
    feed = deliver(tmp_path, first, GOOD_SECOND)
    assert verdict(feed, data_set="rehearsal") == [failed(RULE_PHRASE), failed(RULE_FIRST)]


def test_the_first_autopilot_row_is_first_by_file_name_not_by_write_order(tmp_path: Path) -> None:
    # The later-named file is written first and carries the phrase; the earlier-named one has none.
    write_csv(
        tmp_path / "registry" / "v1" / SECOND,
        [HEADER, f"s3,parka,autopilot,{PHRASE_A},rehearsal,2026-11-14"],
    )
    write_csv(
        tmp_path / "registry" / "v1" / FIRST, [HEADER, "s1,parka,autopilot,,rehearsal,2026-11-13"]
    )
    assert verdict(tmp_path / "registry", data_set="rehearsal") == [failed(RULE_FIRST)]


def missing(field: str, count: int = 1) -> str:
    return (
        f"test Check that field {field} has no missing values: failed "
        f"(Actual missing_count({field}) was {count}, expected = 0)"
    )


def test_a_missing_required_field_fails(tmp_path: Path) -> None:
    feed = deliver(tmp_path, [GOOD_FIRST[0], "s2,,managed,,rehearsal,2026-11-13"], GOOD_SECOND)
    assert verdict(feed, data_set="rehearsal") == [missing("park_id")]


def test_a_delivered_on_that_is_not_a_date_fails_required_and_the_name_date_rule(
    tmp_path: Path,
) -> None:
    feed = deliver(tmp_path, [GOOD_FIRST[0], "s2,parkb,managed,,rehearsal,soon"], GOOD_SECOND)
    assert verdict(feed, data_set="rehearsal") == [
        missing("delivered_on"),
        failed(RULE_DELIVERED),
    ]


@pytest.mark.parametrize(
    "name", ["session_play_mode_2026-11-13_00.csv", "session_play_mode_2026-11-13_100.csv"]
)
def test_refused_name_sequence_fails_with_its_name(tmp_path: Path, name: str) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    write_csv(feed / "v1" / name, [HEADER])
    assert verdict(feed, data_set="rehearsal") == [BAD_NAME.format(name=name)]


def test_malformed_date_in_the_name_fails_with_its_name(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    name = "session_play_mode_2026-1-13_01.csv"
    write_csv(feed / "v1" / name, [HEADER])
    assert verdict(feed, data_set="rehearsal") == [BAD_NAME.format(name=name)]


def test_missing_column_fails(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    write_csv(
        feed / "v1" / "session_play_mode_2026-11-15_01.csv", ["session_id,park_id", "s9,parka"]
    )
    problems = verdict(feed, data_set="rehearsal")
    assert missing("play_mode") in problems
    assert missing("data_set") in problems
    assert missing("delivered_on") in problems


def test_empty_folder_is_clean(tmp_path: Path) -> None:
    (tmp_path / "registry" / "v1").mkdir(parents=True)
    assert play_mode_feed.check_feed(tmp_path / "registry", data_set="rehearsal") == []
    assert play_mode_feed.check_feed(tmp_path / "missing", data_set="rehearsal") == []


def test_header_only_file_is_clean(tmp_path: Path) -> None:
    feed = tmp_path / "registry"
    write_csv(feed / "v1" / FIRST, [HEADER])
    assert play_mode_feed.check_feed(feed, data_set="rehearsal") == []


def test_a_clean_staged_file_passes_with_the_existing_deliveries(tmp_path: Path) -> None:
    feed = tmp_path / "registry"
    write_csv(feed / "v1" / FIRST, [HEADER, *GOOD_FIRST])
    staged = write_csv(tmp_path / "stage" / SECOND, [HEADER, *GOOD_SECOND])
    assert play_mode_feed.check_feed(feed, staged=[staged], data_set="rehearsal") == []


def test_a_staged_session_repeating_an_existing_one_fails(tmp_path: Path) -> None:
    feed = tmp_path / "registry"
    write_csv(feed / "v1" / FIRST, [HEADER, *GOOD_FIRST])
    staged = write_csv(
        tmp_path / "stage" / SECOND, [HEADER, f"s1,parkb,autopilot,{PHRASE_B},rehearsal,2026-11-14"]
    )
    assert verdict(feed, staged=[staged], data_set="rehearsal") == [failed(RULE_UNIQUE)]
    # The same staged file alone is clean: the failure comes from the existing delivery.
    assert (
        play_mode_feed.check_feed(tmp_path / "empty", staged=[staged], data_set="rehearsal") == []
    )


def test_a_staged_first_autopilot_row_is_judged_after_existing_deliveries(tmp_path: Path) -> None:
    # Park a already has its first autopilot row in the folder; the staged one needs no phrase.
    feed = tmp_path / "registry"
    write_csv(feed / "v1" / FIRST, [HEADER, *GOOD_FIRST])
    staged = write_csv(
        tmp_path / "stage" / SECOND, [HEADER, "s3,parka,autopilot,,rehearsal,2026-11-14"]
    )
    assert play_mode_feed.check_feed(feed, staged=[staged], data_set="rehearsal") == []
    # With no existing delivery the same staged row is park a's first and lacks the phrase.
    assert verdict(tmp_path / "empty", staged=[staged], data_set="rehearsal") == [
        failed(RULE_FIRST)
    ]


def test_a_staged_file_needs_its_final_name(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    leftover = write_csv(tmp_path / "stage" / f"{registry_feed.INCOMING}{SECOND}", [HEADER])
    odd = write_csv(tmp_path / "stage" / "session_play_mode_2026-11-15_00.csv", [HEADER])
    assert play_mode_feed.check_feed(feed, staged=[leftover, odd], data_set="rehearsal") == [
        f"staged file {leftover.name} does not have its final name",
        BAD_NAME.format(name=f"staged {odd.name}"),
    ]


def test_a_staged_file_cannot_reuse_a_delivered_name(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    staged = write_csv(tmp_path / "stage" / SECOND, [HEADER])
    assert play_mode_feed.check_feed(feed, staged=[staged], data_set="rehearsal") == [
        f"staged file {SECOND} is already delivered in {feed}"
    ]


def test_reader_maps_session_to_park_mode_and_confirmation(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    labels = play_mode_feed.read_labels(feed)
    assert set(labels) == {"s1", "s2", "s3", "s4"}
    assert labels["s1"] == play_mode_feed.PlayLabel("s1", "parka", "autopilot", PHRASE_A)
    assert labels["s2"] == play_mode_feed.PlayLabel("s2", "parkb", "managed", None)
    assert play_mode_feed.read_labels(tmp_path / "missing") == {}


def test_cli_data_root_clean_and_failed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "rehearsal"
    deliver(root, GOOD_FIRST, GOOD_SECOND)
    assert play_mode_feed.main(["--data-root", str(root)]) == 0
    assert capsys.readouterr().out == "The play-mode feed check passed.\n"
    write_csv(
        root / "registry" / "v1" / FIRST, [HEADER, "s1,parka,autopilot,,rehearsal,2026-11-13"]
    )
    assert play_mode_feed.main(["--data-root", str(root)]) == 1
    assert capsys.readouterr().out == (
        f"session_play_mode.odcs.yaml: test overall result: failed\n"
        f"session_play_mode.odcs.yaml: {failed(RULE_FIRST)}\n"
    )


def test_cli_data_root_named_for_a_data_set_judges_data_set(tmp_path: Path) -> None:
    root = tmp_path / "company"
    deliver(root, GOOD_FIRST, GOOD_SECOND)
    assert play_mode_feed.main(["--data-root", str(root)]) == 1


def test_cli_data_set_checks_the_data_sets_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    deliver(tmp_path / "rehearsal", GOOD_FIRST, GOOD_SECOND)
    assert play_mode_feed.main(["--data-set", "rehearsal"]) == 0
    assert capsys.readouterr().out == "The play-mode feed check passed.\n"
    assert play_mode_feed.main(["--data-set", "company"]) == 0
    deliver(tmp_path / "company", GOOD_FIRST, GOOD_SECOND)
    assert play_mode_feed.main(["--data-set", "company"]) == 1


def test_cli_data_set_alias_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path))
    (tmp_path / "rehearsal" / "registry").mkdir(parents=True)
    (tmp_path / "company").mkdir()
    (tmp_path / "company" / "registry").symlink_to(tmp_path / "rehearsal" / "registry")
    with pytest.raises(ConfigError):
        registry_feed.registry_dir("company")
    assert play_mode_feed.main(["--data-set", "company"]) == 2
    assert capsys.readouterr().out.endswith(". Nothing was checked.\n")


def test_cli_empty_folder_is_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert play_mode_feed.main(["--data-root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "The play-mode feed check passed.\n"


def test_data_set_outside_the_two_fails_even_when_the_folder_is_unknown(tmp_path: Path) -> None:
    feed = deliver(tmp_path, [GOOD_FIRST[0], "s2,parkb,managed,,staging,2026-11-13"], GOOD_SECOND)
    assert verdict(feed) == [
        "rows name more than one data set: rehearsal, staging",
        failed(RULE_DATA_SET),
    ]


def test_two_autopilot_rows_of_a_park_in_one_file_are_judged_in_row_order(tmp_path: Path) -> None:
    phrased = f"s1,parka,autopilot,{PHRASE_A},rehearsal,2026-11-13"
    bare = "s2,parka,autopilot,,rehearsal,2026-11-13"
    other = "s9,parkb,managed,,rehearsal,2026-11-14"
    feed = deliver(tmp_path / "good", [phrased, bare], [other])
    assert play_mode_feed.check_feed(feed, data_set="rehearsal") == []
    feed = deliver(tmp_path / "bad", [bare, phrased], [other])
    assert verdict(feed, data_set="rehearsal") == [failed(RULE_FIRST)]


def test_a_staged_file_named_earlier_than_a_delivery_has_the_first_autopilot_row(
    tmp_path: Path,
) -> None:
    feed = tmp_path / "registry"
    write_csv(feed / "v1" / SECOND, [HEADER, f"s3,parka,autopilot,{PHRASE_A},rehearsal,2026-11-14"])
    staged = write_csv(
        tmp_path / "stage" / FIRST, [HEADER, "s1,parka,autopilot,,rehearsal,2026-11-13"]
    )
    assert verdict(feed, staged=[staged], data_set="rehearsal") == [failed(RULE_FIRST)]


def test_the_contract_orders_the_first_autopilot_window_by_file_name_then_row_order() -> None:
    text = play_mode_feed.CONTRACT_PATH.read_text(encoding="utf-8")
    rule = re.search(r"description: each park's first autopilot row.*?mustBe", text, re.DOTALL)
    assert rule is not None
    assert "PARTITION BY park_id ORDER BY file_name, row_order" in rule.group(0)


def test_row_order_is_the_line_order_of_a_file(tmp_path: Path) -> None:
    lines = [f"s{n},parka,managed,,rehearsal,2026-11-13" for n in (5, 3, 4, 1, 2, 9)]
    path = write_csv(tmp_path / FIRST, [HEADER, *lines])
    view = play_mode_feed.VIEW_SQL.format(
        view="labels",
        suffix=play_mode_feed.READY_SUFFIX,
        date_pattern=play_mode_feed._NAME_SHAPE.pattern,
        expected="'rehearsal'",
        files=f"'{path.as_posix()}'",
    )
    connection = duckdb.connect()
    try:
        connection.execute(view)
        rows = connection.execute("SELECT row_order, session_id FROM labels ORDER BY 1").fetchall()
    finally:
        connection.close()
    assert rows == [(1, "s5"), (2, "s3"), (3, "s4"), (4, "s1"), (5, "s2"), (6, "s9")]


def test_a_file_missing_ready_confirmation_fails_with_its_header_message(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    short = "session_id,park_id,play_mode,data_set,delivered_on"
    write_csv(feed / "v1" / SECOND, [short, "s3,parka,managed,rehearsal,2026-11-14"])
    assert verdict(feed, data_set="rehearsal") == [BAD_HEADER.format(name=SECOND)]


def test_a_file_with_an_extra_column_fails_with_its_header_message(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    write_csv(
        feed / "v1" / SECOND,
        [HEADER + ",note", "s3,parka,managed,,rehearsal,2026-11-14,x"],
    )
    assert verdict(feed, data_set="rehearsal") == [BAD_HEADER.format(name=SECOND)]


def test_valid_headers_pass_the_header_check(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    assert [line for line in verdict(feed, data_set="rehearsal") if "header is not" in line] == []


def test_one_data_set_passes_and_two_fail_under_an_unnamed_folder(tmp_path: Path) -> None:
    one = deliver(tmp_path / "one", GOOD_FIRST, GOOD_SECOND)
    assert play_mode_feed.check_feed(one) == []
    two = deliver(
        tmp_path / "two",
        GOOD_FIRST,
        [GOOD_SECOND[0].replace("rehearsal", "company"), GOOD_SECOND[1]],
    )
    assert verdict(two) == [TWO_DATA_SETS]


def test_a_refused_sequence_file_is_not_read_by_the_reader(tmp_path: Path) -> None:
    feed = deliver(tmp_path, GOOD_FIRST, GOOD_SECOND)
    zero = "session_play_mode_2026-11-13_00.csv"
    write_csv(feed / "v1" / zero, [HEADER, "s9,parka,managed,,rehearsal,2026-11-13"])
    assert [path.name for path in play_mode_feed.delivery_files(feed)] == [FIRST, SECOND]
    assert set(play_mode_feed.read_labels(feed)) == {"s1", "s2", "s3", "s4"}
