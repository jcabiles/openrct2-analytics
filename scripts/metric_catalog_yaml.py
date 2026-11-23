"""YAML helpers shared by the metric catalog validator and its shape check."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

CATALOG_DIR = "metrics"
REF = re.compile(r"ref\(\s*['\"]([\w]+)['\"]\s*\)")

Map = dict[str, object]


def catalog_files(root: Path) -> list[Path]:
    """Return every `metrics/*.yml` file under root, sorted; no rule may depend on the order."""
    return sorted((root / CATALOG_DIR).glob("*.yml"))


def as_map(value: object) -> Map:
    """Return value as a string-keyed dict, or an empty one when it is not a mapping."""
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return {}


def as_list(value: object) -> list[object]:
    """Return value if it is a list, else an empty list."""
    return value if isinstance(value, list) else []


def as_text(value: object) -> str:
    """Return value if it is a string, else an empty string."""
    return value if isinstance(value, str) else ""


def maps(value: object) -> Iterator[Map]:
    """Yield each mapping in a list, skipping anything else."""
    for item in as_list(value):
        if isinstance(item, dict):
            yield as_map(item)


def meta_of(item: Map) -> Map:
    """Return an item's `config.meta` mapping."""
    return as_map(as_map(item.get("config")).get("meta"))
