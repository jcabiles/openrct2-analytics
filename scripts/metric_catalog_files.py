"""The loaded metric catalog and the file each of its entries came from.

`scripts/check_metric_catalog.py` fills `Catalog.sources` and `Catalog.defined_in` while it reads
every `metrics/*.yml` file; `Catalog.add` uses them to prefix each problem with its file.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metric_catalog_yaml import CATALOG_DIR, Map, as_text, maps, meta_of


def item_expr(item: Map) -> str:
    """Return an item's expr; without one, dbt reads the column named after the item."""
    return as_text(item["expr"] if "expr" in item else item.get("name"))


@dataclass
class Catalog:
    """A loaded catalog and the model YAML around it."""

    semantic_models: list[Map]
    metrics: list[Map]
    model_columns: dict[str, set[str]]
    problems: list[str] = field(default_factory=list)
    sources: dict[int, str] = field(default_factory=dict)
    defined_in: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def add(self, rule: str, message: str, entry: Map | None = None) -> None:
        """Record a problem under a rule such as `3b`, prefixed with the file of `entry`.

        A problem about the merged catalog passes no entry and is prefixed with `metrics/`.
        """
        where = self.sources.get(id(entry), f"{CATALOG_DIR}/")
        self.problems.append(f"{where}: rule {rule}: {message}")

    @property
    def measures(self) -> dict[str, str]:
        """Map each measure name to the expr dbt reads for it."""
        return {
            as_text(measure.get("name")): item_expr(measure)
            for model in self.semantic_models
            for measure in maps(model.get("measures"))
        }

    @property
    def metric_names(self) -> set[str]:
        """Names of all metrics."""
        return {as_text(metric.get("name")) for metric in self.metrics}

    @property
    def roles(self) -> dict[str, str]:
        """Map each metric name to its role, or an empty string when the role is not text."""
        return {as_text(m.get("name")): as_text(meta_of(m).get("role")) for m in self.metrics}
