"""The Python action-name table must equal the plugin's TypeScript table."""

from __future__ import annotations

import re
from pathlib import Path

from openrct2_analytics.ingest.action_names import (
    CHEAT_ACTION_NAMES,
    DROPPED_ACTION_NAMES,
    KEPT_ACTION_NAMES,
    RIDE_SET_SETTING_KEPT_SUBTYPES,
    RIDE_SET_VEHICLE_KEPT_SUBTYPES,
    SUBTYPE_FILTERED_ACTION_NAMES,
)

TS_FILE = Path(__file__).resolve().parent.parent / "plugin" / "src" / "action_names.ts"
CODES = {"DROP": 0, "KEEP": 1, "KEEP_BY_SUBTYPE": 2, "CHEAT": 3}


def _ts_text() -> str:
    return TS_FILE.read_text(encoding="utf-8")


def _ts_names() -> dict[str, str]:
    body = re.search(r"ACTION_NAME_CODES[^=]*=\s*\{(.*?)\n\};", _ts_text(), flags=re.DOTALL)
    assert body is not None
    pairs = re.findall(r"^\s+(\w+): ACTION_CODE_(\w+),?$", body.group(1), flags=re.MULTILINE)
    assert len(pairs) == len({name for name, _ in pairs})
    return dict(pairs)


def _ts_kept_subtypes(array_name: str) -> frozenset[int]:
    body = re.search(rf"{array_name}[^=]*=\s*\[(.*?)\];", _ts_text(), flags=re.DOTALL)
    assert body is not None
    flags = re.findall(r"^\s*(true|false)\b", body.group(1), flags=re.MULTILINE)
    return frozenset(i for i, flag in enumerate(flags) if flag == "true")


def test_python_names_are_81_disjoint() -> None:
    assert len(KEPT_ACTION_NAMES) == 13
    assert len(DROPPED_ACTION_NAMES) == 68
    assert KEPT_ACTION_NAMES.isdisjoint(DROPPED_ACTION_NAMES)
    assert len(KEPT_ACTION_NAMES | DROPPED_ACTION_NAMES) == 81
    assert SUBTYPE_FILTERED_ACTION_NAMES <= KEPT_ACTION_NAMES
    assert CHEAT_ACTION_NAMES <= DROPPED_ACTION_NAMES


def test_typescript_names_equal_python_names() -> None:
    table = _ts_names()
    kept = {n for n, c in table.items() if CODES[c] in (CODES["KEEP"], CODES["KEEP_BY_SUBTYPE"])}
    assert len(table) == 81
    assert kept == KEPT_ACTION_NAMES
    assert set(table) - kept == DROPPED_ACTION_NAMES
    assert {n for n, c in table.items() if c == "KEEP_BY_SUBTYPE"} == SUBTYPE_FILTERED_ACTION_NAMES
    assert {n for n, c in table.items() if c == "CHEAT"} == CHEAT_ACTION_NAMES


def test_cheat_names_are_exactly_cheatset_and_ridefreezerating() -> None:
    assert frozenset({"cheatset", "ridefreezerating"}) == CHEAT_ACTION_NAMES


def test_typescript_kept_subtypes_equal_python_sets() -> None:
    assert _ts_kept_subtypes("RIDE_SET_SETTING_KEPT") == RIDE_SET_SETTING_KEPT_SUBTYPES
    assert _ts_kept_subtypes("RIDE_SET_VEHICLE_KEPT") == RIDE_SET_VEHICLE_KEPT_SUBTYPES
