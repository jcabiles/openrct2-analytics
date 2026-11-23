"""Fail when a built OBT model is not referenced by a dbt exposure.

Usage: python scripts/check_exposures.py MANIFEST
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any


def uncovered_models(manifest: dict[str, Any]) -> list[str]:
    """Return the names of OBT models not listed in any exposure's dependencies."""
    exposed_ids = {
        unique_id
        for exposure in manifest["exposures"].values()
        for unique_id in exposure["depends_on"]["nodes"]
    }
    return sorted(
        node["name"]
        for node in manifest["nodes"].values()
        if node["resource_type"] == "model"
        and node["name"].startswith("obt_")
        and node["unique_id"] not in exposed_ids
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Check manifest exposure coverage and return a process exit code."""
    parser = argparse.ArgumentParser(description="Check that every OBT model has an exposure.")
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"check_exposures: {error}", file=sys.stderr)
        return 1

    uncovered = uncovered_models(manifest)
    for name in uncovered:
        print(f"{name}: no exposure", file=sys.stderr)
    if uncovered:
        return 1
    print("check_exposures: every obt_ model has an exposure.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
