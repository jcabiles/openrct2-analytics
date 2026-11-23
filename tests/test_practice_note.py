"""The dbt practice-note macro holds the same text as the Python constant (spec R25)."""

from __future__ import annotations

import re
from pathlib import Path

from openrct2_analytics.ingest import registry_feed

MACRO = Path(__file__).resolve().parents[1] / "macros" / "practice_note.sql"


def _macro_literal() -> str:
    body = re.search(
        r"\{% macro practice_note\(\) -%\}(.*?)\{%- endmacro %\}", MACRO.read_text(), re.S
    )
    assert body is not None
    literal = re.fullmatch(r"\s*'(.*)'\s*", body.group(1), re.S)
    assert literal is not None
    return literal.group(1)


def test_python_note_is_the_pinned_text() -> None:
    assert registry_feed.PRACTICE_NOTE == "Throwaway practice park; not company data."


def test_macro_note_is_the_pinned_text() -> None:
    assert _macro_literal() == "Throwaway practice park; not company data."


def test_macro_note_equals_the_python_note() -> None:
    assert _macro_literal() == registry_feed.PRACTICE_NOTE
