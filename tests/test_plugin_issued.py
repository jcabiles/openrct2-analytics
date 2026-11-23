"""The plugin-issued player value in Python must equal the dbt variable that classifies rows."""

from __future__ import annotations

import json
import re
from pathlib import Path

from openrct2_analytics.ingest.plugin_issued import PLUGIN_ISSUED_PLAYER_VALUES

DBT_PROJECT = Path(__file__).resolve().parent.parent / "dbt_project.yml"


def test_constant_equals_the_dbt_variable() -> None:
    # The repo reads no YAML with a library; the variable is a one-line flow list.
    found = re.findall(
        r"^\s*plugin_issued_player_values:\s*(\[.*\])\s*$",
        DBT_PROJECT.read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    assert len(found) == 1
    assert tuple(json.loads(found[0])) == PLUGIN_ISSUED_PLAYER_VALUES
