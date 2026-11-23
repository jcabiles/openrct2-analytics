"""Committed sample and site exports contain no dropped game actions."""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path

import duckdb
import pytest

from openrct2_analytics.ingest.action_names import (
    DROPPED_ACTION_NAMES,
    dropped_action_row,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
SITE_DATA = ROOT / "site" / "_data"


def contains_dropped_name(value: object) -> bool:
    """Find a dropped action name anywhere in a decoded site export."""
    if isinstance(value, str):
        return value in DROPPED_ACTION_NAMES
    if isinstance(value, dict):
        return any(
            contains_dropped_name(key) or contains_dropped_name(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_dropped_name(item) for item in value)
    return False


def assert_no_dropped_actions(sample_root: Path, site_data_root: Path) -> None:
    """Fail when sample Parquet or committed site data contains a dropped action."""
    for path in sample_root.rglob("game_action.parquet"):
        with contextlib.closing(duckdb.connect()) as db:
            columns = db.execute(
                "describe select * from read_parquet(?)", [path.as_posix()]
            ).fetchall()
            rows = db.execute("select * from read_parquet(?)", [path.as_posix()]).fetchall()
        names = [column[0] for column in columns]
        for values in rows:
            row = dict(zip(names, values, strict=True))
            assert not dropped_action_row(row), f"dropped action row in {path}"

    for path in site_data_root.rglob("*"):
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert not has_action_column(payload), f"action column in {path}"
        assert not contains_dropped_name(payload), f"dropped action name in {path}"


def has_action_column(value: object) -> bool:
    """Return whether a decoded export object contains an `action` field."""
    if isinstance(value, dict):
        return "action" in value or any(has_action_column(item) for item in value.values())
    if isinstance(value, list):
        return any(has_action_column(item) for item in value)
    return False


def copied_sample(tmp_path: Path) -> Path:
    """Return a private sample copy for one planted-row case."""
    copied = tmp_path / "sample"
    shutil.copytree(SAMPLE, copied)
    return copied


def plant_action_row(sample_root: Path, action: str, label: str, args_json: str) -> None:
    """Replace the copied empty action file with one row matching its existing schema."""
    path = sample_root / "rehearsal" / "v1" / "game_action.parquet"
    staged = path.with_name("planted.parquet")
    with contextlib.closing(duckdb.connect()) as db:
        schema = db.execute("describe select * from read_parquet(?)", [path.as_posix()]).fetchall()
        expressions = []
        for name, data_type, *_ in schema:
            if name == "action":
                expression = "'" + action.replace("'", "''") + "'"
            elif name == "action_label":
                expression = f"'{label}'"
            elif name == "args_json":
                expression = "'" + args_json.replace("'", "''") + "'"
            else:
                expression = f"cast(null as {data_type})"
            expressions.append(f'{expression} as "{name}"')
        db.execute(
            f"copy (select {', '.join(expressions)}) to '{staged.as_posix()}' (format parquet)"
        )
    staged.replace(path)


def assert_planted_sample_is_rejected(sample_root: Path) -> None:
    """Check that a planted sample row makes the committed-data guard fail."""
    with pytest.raises(AssertionError, match="dropped action row"):
        assert_no_dropped_actions(sample_root, SITE_DATA)


def test_committed_sample_and_site_data_have_no_dropped_actions() -> None:
    assert_no_dropped_actions(SAMPLE, SITE_DATA)


def test_ridesetname_row_is_rejected(tmp_path: Path) -> None:
    planted = copied_sample(tmp_path)
    plant_action_row(planted, "ridesetname", "confirmed", "{}")

    assert_planted_sample_is_rejected(planted)


def test_ridesetprice_preview_row_is_rejected(tmp_path: Path) -> None:
    planted = copied_sample(tmp_path)
    plant_action_row(planted, "ridesetprice", "preview", "{}")

    assert_planted_sample_is_rejected(planted)


def test_unknown_action_name_is_rejected(tmp_path: Path) -> None:
    planted = copied_sample(tmp_path)
    plant_action_row(planted, "unknown_action", "confirmed", "{}")

    assert_planted_sample_is_rejected(planted)


def test_ridesetvehicle_disallowed_type_is_rejected(tmp_path: Path) -> None:
    planted = copied_sample(tmp_path)
    plant_action_row(planted, "ridesetvehicle", "confirmed", '{"type": 2}')

    assert_planted_sample_is_rejected(planted)


def test_ridesetsetting_disallowed_subtype_is_rejected(tmp_path: Path) -> None:
    planted = copied_sample(tmp_path)
    plant_action_row(planted, "ridesetsetting", "confirmed", '{"setting": 6}')

    assert_planted_sample_is_rejected(planted)


def test_ridesetsetting_bool_subtype_is_rejected(tmp_path: Path) -> None:
    planted = copied_sample(tmp_path)
    plant_action_row(planted, "ridesetsetting", "confirmed", '{"setting": true}')

    assert_planted_sample_is_rejected(planted)


def test_site_export_with_dropped_name_is_rejected(tmp_path: Path) -> None:
    planted_sample = copied_sample(tmp_path)
    planted_site = tmp_path / "site-data"
    shutil.copytree(SITE_DATA, planted_site)
    file = next(planted_site.glob("*.json"))
    payload = json.loads(file.read_text(encoding="utf-8"))
    payload["planted_action"] = next(iter(DROPPED_ACTION_NAMES))
    file.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AssertionError, match="dropped action name"):
        assert_no_dropped_actions(planted_sample, planted_site)
