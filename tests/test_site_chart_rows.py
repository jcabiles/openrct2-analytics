"""Row functions follow the data (R29, D6): every figure's rows function, run under Node.

Each figure registry entry's rows function runs on the parsed exports of the empty set and of
fixture sets A and B. On the empty set every function returns no rows; on A and B every value
in the returned rows is a value or row key of that set's exports (a flag aside).
"""

from __future__ import annotations

import json
import subprocess

import pytest

from tests.site_fixtures import ROOT, SETS, fixture_rows

SCRIPT = """
import { FIGURES } from "./site/figures.mjs";
let input = "";
for await (const chunk of process.stdin) input += chunk;
const exports = JSON.parse(input);
const out = {};
for (const entry of FIGURES) out[entry.id] = entry.rows(exports);
process.stdout.write(JSON.stringify(out));
"""

# Figures whose rows come from a committed counts file, not the exports; they ignore the fixture.
NOT_FROM_EXPORTS = {"built-numbers"}


def _run_rows(name: str) -> dict[str, list[object]]:
    done = subprocess.run(
        ["node", "--input-type=module", "-e", SCRIPT],
        cwd=ROOT,
        input=json.dumps(fixture_rows(name)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout)
    assert isinstance(result, dict) and result
    return result


def _scalars(value: object) -> list[object]:
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _scalars(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _scalars(nested)]
    return [value]


@pytest.mark.parametrize("name", SETS, ids=SETS)
def test_every_row_function_returns_only_fixture_values(name: str) -> None:
    rows = {key: value for key, value in _run_rows(name).items() if key not in NOT_FROM_EXPORTS}
    if name == "empty":
        assert all(value == [] for value in rows.values()), rows
        return
    # Only values that appear in some column of the fixture exports; no constant is added.
    allowed = {
        value
        for export in fixture_rows(name).values()
        for row in export
        for value in row.values()
        if not isinstance(value, bool)
    }
    assert any(rows.values()), "no row function returned rows"
    for figure_id, values in rows.items():
        for value in _scalars(values):
            assert isinstance(value, bool) or value in allowed, (figure_id, value)
