"""The metric catalog's house rules (docs/CONVENTIONS.md), run by scripts/check_metric_catalog.py.

Each rule function takes a loaded `Catalog` and records one line per problem as
`rule <number><letter>`.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterator

from metric_catalog_files import Catalog, item_expr
from metric_catalog_yaml import REF, Map, as_list, as_map, as_text, maps, meta_of

REQUIRED_FIELDS = ("name", "label", "description", "type", "type_params")
# fmt: off
REQUIRED_META = (
    "unit", "clock", "grain", "owner", "status", "role", "source_models", "excludes",
    "roadmap_source",
)
# fmt: on
TEXT_META = ("unit", "grain", "roadmap_source")
LIST_META = ("excludes", "source_models")
CLOCKS = frozenset({"game day", "company date", "wall-clock hour"})
OWNER = "the project owner"
STATUSES = frozenset({"draft", "certified", "deprecated"})
ROLES = frozenset({"north_star", "tree", "guardrail", "supporting"})
# fmt: off
SQL_WORDS = frozenset({
    "case", "when", "then", "else", "end", "and", "or", "not", "null", "is", "in", "true", "false",
    "as", "distinct",
})
SQL_FUNCTIONS = frozenset({"coalesce", "nullif", "abs", "cast", "round", "greatest", "least"})
# fmt: on
LINKS = frozenset({"identity", "hypothesis"})
HYPOTHESIS_FIELDS = ("claim", "direction", "lag", "evidence", "rivals", "review", "check")
TREE_ROLES = frozenset({"tree", "guardrail"})
IN_TREE = TREE_ROLES | {"north_star"}
ZERO_MONTH_KEYS = frozenset({"fill_nulls_with", "join_to_timespine"})
MONEY_SUFFIX = "_usd"
REFERENCE_KEYS = ("measure", "numerator", "denominator")
YOY_UNIT = "fraction of the prior year"
YOY_OFFSET = "1 year"
THRESHOLD_DIRECTIONS = frozenset({"at least", "at most"})
THRESHOLD_PROVENANCE = "project decision"

QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
WORD = re.compile(r"\b[a-z_][a-z0-9_]*\b")
CONDITION = re.compile(r"\bwhen\b.*?\bthen\b", re.DOTALL)
DIMENSION = re.compile(r"Dimension\(\s*'([^']+)'")
SPACE = re.compile(r"\s+")


def ref_name(entry: object) -> str:
    """Name a reference: a plain string or a mapping with a `name`."""
    return as_text(entry) or as_text(as_map(entry).get("name"))


def identifiers(expr: str) -> list[str]:
    """Return the column-like words of a SQL expression, outside quoted literals."""
    words = WORD.findall(QUOTED.sub(" ", expr))
    return [word for word in words if word not in SQL_WORDS | SQL_FUNCTIONS]


def contains_key(value: object, keys: Collection[str]) -> bool:
    """Say whether any mapping nested in value has one of keys."""
    if isinstance(value, dict):
        return any(key in keys or contains_key(item, keys) for key, item in value.items())
    return any(contains_key(item, keys) for item in as_list(value))


def planned_columns(model: Map) -> set[str]:
    """Return the names a semantic model lists under planned_columns."""
    return {as_text(entry.get("name")) for entry in maps(meta_of(model).get("planned_columns"))}


def model_ref(model: Map) -> str:
    """Return the dbt model a semantic model names with ref('...'), or an empty string."""
    match = REF.search(as_text(model.get("model")))
    return match.group(1) if match else ""


def is_planned(model: Map) -> bool:
    """Say whether a semantic model is marked planned_model: true."""
    return meta_of(model).get("planned_model") is True


def check_names(catalog: Catalog, expected: Collection[str]) -> None:
    """Rule 2: names are unique and the metric set is exactly the expected one."""
    model_names = [as_text(model.get("name")) for model in catalog.semantic_models]
    measure_names = [
        as_text(measure.get("name"))
        for model in catalog.semantic_models
        for measure in maps(model.get("measures"))
    ]
    metric_names = [as_text(metric.get("name")) for metric in catalog.metrics]
    for rule, kind, names in (
        ("2a", "semantic model", model_names),
        ("2b", "measure", measure_names),
        ("2c", "metric", metric_names),
    ):
        for name in sorted({n for n in names if names.count(n) > 1}):
            files = ", ".join(catalog.defined_in.get((kind, name), []))
            catalog.add(rule, f"two {kind}s are named {name!r} (in {files})")
    missing, unexpected = (
        sorted(set(expected) - set(metric_names)),
        sorted(set(metric_names) - set(expected)),
    )
    if missing or unexpected:
        catalog.add(
            "2d", f"metric names differ from the list: missing {missing}, unexpected {unexpected}"
        )


def check_required(catalog: Catalog, metric: Map) -> None:
    """Rule 3: every metric has its fields and house meta, with allowed values."""
    name = as_text(metric.get("name"))
    for key in REQUIRED_FIELDS:
        value = metric.get(key)
        if not value or (key == "type_params" and not isinstance(value, dict)):
            catalog.add("3a", f"metric {name!r} lacks {key} or it is not a mapping", metric)
    meta = meta_of(metric)
    for key in REQUIRED_META:
        if key not in meta:
            catalog.add("3b", f"metric {name!r} lacks config.meta.{key}", metric)
    check_meta_values(catalog, metric, meta)


def check_meta_values(catalog: Catalog, metric: Map, meta: Map) -> None:
    """Rules 3b to 3g: the house meta fields present have usable, allowed values."""
    name = as_text(metric.get("name"))
    for key in TEXT_META:
        if key in meta and not as_text(meta[key]).strip():
            catalog.add("3b", f"metric {name!r} has an empty or non-text config.meta.{key}", metric)
    for key in LIST_META:
        if key in meta and not as_list(meta[key]):
            catalog.add("3c", f"metric {name!r} has an empty {key}, or it is not a list", metric)
    allowed = (
        ("3d", "clock", CLOCKS),
        ("3e", "owner", frozenset({OWNER})),
        ("3f", "status", STATUSES),
        ("3g", "role", ROLES),
    )
    for rule, key, values in allowed:
        if key in meta and as_text(meta[key]) not in values:
            catalog.add(
                rule,
                f"metric {name!r} has {key} {meta[key]!r}, not one of {sorted(values)}",
                metric,
            )


def input_metrics(metric: Map) -> list[Map]:
    """Return the entries of a metric's type_params.metrics list."""
    entries = as_map(metric.get("type_params")).get("metrics")
    return [
        as_map(entry) if isinstance(entry, dict) else {"name": entry} for entry in as_list(entries)
    ]


def check_references(catalog: Catalog, metric: Map) -> None:
    """Rule 4: type_params references and a derived expr name real things."""
    name = as_text(metric.get("name"))
    params = as_map(metric.get("type_params"))
    known = set(catalog.measures) | catalog.metric_names
    refs = [ref_name(params.get(key)) for key in REFERENCE_KEYS if key in params]
    inputs = input_metrics(metric)
    refs += [ref_name(entry) for entry in inputs]
    for ref in refs:
        if ref not in known:
            message = f"metric {name!r} references {ref!r}, which is no measure or metric"
            catalog.add("4a", message, metric)
    if metric.get("type") == "derived":
        allowed = {ref_name(entry) for entry in inputs} | {
            as_text(entry.get("alias")) for entry in inputs
        }
        for word in identifiers(as_text(params.get("expr"))):
            if word not in allowed:
                message = f"metric {name!r} expr uses {word!r}, not in its metrics or aliases"
                catalog.add("4b", message, metric)


def check_models(catalog: Catalog) -> None:
    """Rule 5: semantic models point at real or planned models; source_models do too."""
    planned_refs: set[str] = set()
    for model in catalog.semantic_models:
        ref = model_ref(model)
        exists = ref in catalog.model_columns
        name = as_text(model.get("name"))
        if is_planned(model):
            planned_refs.add(ref)
            if exists:
                catalog.add(
                    "5b", f"semantic model {name!r} is planned_model but {ref!r} now exists", model
                )
        elif not exists:
            catalog.add(
                "5a",
                f"semantic model {name!r} names model {ref!r}, which no models YAML has",
                model,
            )
    for metric in catalog.metrics:
        for source in as_list(meta_of(metric).get("source_models")):
            if not isinstance(source, str) or (
                source not in catalog.model_columns and source not in planned_refs
            ):
                catalog.add(
                    "5c",
                    f"metric {metric.get('name')!r} source model {source!r} is unknown",
                    metric,
                )


def column_problems(model: Map, valid: set[str]) -> Iterator[str]:
    """Yield each unknown column that a semantic model's measures, dimensions or entities read."""
    name = as_text(model.get("name"))
    for kind, singular in (
        ("measures", "measure"),
        ("dimensions", "dimension"),
        ("entities", "entity"),
    ):
        for item in maps(model.get(kind)):
            for word in identifiers(item_expr(item)):
                if word not in valid:
                    yield f"{singular} {item.get('name')!r} of {name!r} reads unknown {word!r}"


def filter_dimensions(metric: Map) -> list[str]:
    """Return every Dimension('...') name in a metric's filters and its input metrics' filters."""
    params = as_map(metric.get("type_params"))
    entries = [metric, params, *input_metrics(metric)]
    entries += [as_map(params.get(key)) for key in ("numerator", "denominator")]
    return [name for entry in entries for name in DIMENSION.findall(as_text(entry.get("filter")))]


def check_filter(catalog: Catalog, metric: Map, dimension: str) -> None:
    """Rule 6a for one filter dimension named `<entity>__<dimension>`."""
    entity, _, column = dimension.rpartition("__")
    if entity == "metric_time":
        return
    owners = [m for m in catalog.semantic_models if entity in entity_names(m)]
    for model in owners:
        spec = next((d for d in maps(model.get("dimensions")) if d.get("name") == column), {})
        words = identifiers(as_text(spec.get("expr"))) or [column]
        valid = catalog.model_columns.get(model_ref(model), set()) | planned_columns(model)
        if all(word in valid for word in words):
            return
    where = f"no semantic model has entity {entity!r}" if not owners else "no column found"
    catalog.add("6a", f"metric {metric.get('name')!r} filters on {dimension!r}: {where}", metric)


def entity_names(model: Map) -> set[str]:
    """Return a semantic model's entity names, including its primary_entity."""
    names = {as_text(entity.get("name")) for entity in maps(model.get("entities"))}
    return names | {as_text(model.get("primary_entity"))}


def check_columns(catalog: Catalog) -> None:
    """Rule 6: expr identifiers and filter dimensions are columns; planned ones are not yet real."""
    for model in catalog.semantic_models:
        existing = catalog.model_columns.get(model_ref(model), set())
        planned = planned_columns(model)
        for message in column_problems(model, existing | planned):
            catalog.add("6a", message, model)
        for column in sorted(planned & existing):
            catalog.add(
                "6b",
                f"{model.get('name')!r} lists planned column {column!r}, which now exists",
                model,
            )
    for metric in catalog.metrics:
        for dimension in filter_dimensions(metric):
            check_filter(catalog, metric, dimension)


def check_money(catalog: Catalog, metric: Map) -> None:
    """Rule 7: a simple usd metric reads only `_usd` columns."""
    params = as_map(metric.get("type_params"))
    unit = meta_of(metric).get("unit")
    if metric.get("type") != "simple" or unit != "usd":
        return
    measure = ref_name(params.get("measure"))
    expr = CONDITION.sub(" ", QUOTED.sub(" ", catalog.measures.get(measure, "")))
    for word in identifiers(expr):
        if not word.endswith(MONEY_SUFFIX):
            catalog.add(
                "7a",
                f"metric {metric.get('name')!r} (usd) reads {word!r}, not a _usd column",
                metric,
            )


def tree_of(metric: Map) -> Map:
    """Return a metric's config.meta.tree mapping."""
    return as_map(meta_of(metric).get("tree"))


def check_tree_roots(catalog: Catalog) -> None:
    """Rule 8a and 8b: one north star, whose guardrails are exactly the guardrail metrics."""
    roles = catalog.roles
    stars = [m for m in catalog.metrics if meta_of(m).get("role") == "north_star"]
    if len(stars) != 1:
        catalog.add("8a", f"{len(stars)} metrics have role north_star, not exactly one")
    for star in stars:
        guardrails = as_list(meta_of(star).get("guardrails"))
        if not guardrails:
            catalog.add("8b", f"north star {star.get('name')!r} lacks guardrails", star)
        for name in guardrails:
            if roles.get(as_text(name)) != "guardrail":
                catalog.add("8b", f"guardrail {name!r} does not have role guardrail", star)
        listed = {as_text(name) for name in guardrails}
        for entry in catalog.metrics:
            name = as_text(entry.get("name"))
            if roles.get(name) == "guardrail" and name not in listed:
                message = f"guardrail metric {name!r} is not in the north star's guardrails"
                catalog.add("8b", message, entry)


def check_link(catalog: Catalog, metric: Map) -> None:
    """Rules 8f to 8k: the shape of one tree link."""
    name, tree = as_text(metric.get("name")), tree_of(metric)
    link = tree.get("link")
    if not isinstance(link, str) or link not in LINKS:
        catalog.add("8f", f"metric {name!r} has link {link!r}, not identity or hypothesis", metric)
    reconciled = as_text(tree.get("reconciled_by"))
    if link == "identity":
        if not reconciled:
            catalog.add("8g", f"identity link of {name!r} lacks reconciled_by", metric)
        if "tolerance" in tree or re.search(r"within|tolerance", reconciled):
            catalog.add("8h", f"identity link of {name!r} carries a tolerance", metric)
    if link == "hypothesis":
        what = f"hypothesis link of {name!r}"
        check_hypothesis(catalog, what, tree, ("8i", "8j", "8k"), metric=metric)


def check_hypothesis(
    catalog: Catalog, what: str, link: Map, rules: tuple[str, str, str], *, metric: Map
) -> None:
    """Rules 8i to 8k, or 11d to 11f for an additional link: a hypothesis link's fields."""
    fields, observational, tolerance = rules
    for key in HYPOTHESIS_FIELDS:
        if not link.get(key):
            catalog.add(fields, f"{what} lacks {key}", metric)
    if "observational" not in as_text(link.get("evidence")).lower():
        catalog.add(observational, f"{what} has evidence that never says observational", metric)
    if link.get("direction") == "equal" and not link.get("tolerance"):
        catalog.add(tolerance, f"{what} has direction equal but no tolerance", metric)


def check_tree_node(catalog: Catalog, metric: Map) -> None:
    """Rules 8c and 8d for one tree or guardrail metric."""
    name, tree = as_text(metric.get("name")), tree_of(metric)
    if not tree.get("parent") or not tree.get("link"):
        catalog.add("8c", f"metric {name!r} lacks tree.parent or tree.link", metric)
    parent = tree.get("parent")
    if parent and (not isinstance(parent, str) or parent not in catalog.metric_names):
        message = f"metric {name!r} has tree.parent {parent!r}, not one metric name"
        catalog.add("8d", message, metric)
    elif parent and catalog.roles.get(as_text(parent)) not in IN_TREE:
        message = f"metric {name!r} has tree.parent {parent!r}, which is not in the tree"
        catalog.add("8d", message, metric)


def check_cycles(catalog: Catalog) -> None:
    """Rule 8e: following parents from any metric never returns to it."""
    parents = {as_text(m.get("name")): tree_of(m).get("parent") for m in catalog.metrics}
    for start in sorted(parents):
        current, steps = parents[start], 0
        while isinstance(current, str) and current in parents and steps <= len(parents):
            if current == start:
                catalog.add("8e", f"the tree parents of {start!r} form a cycle")
                break
            current, steps = parents[current], steps + 1


def check_additional_links(catalog: Catalog, metric: Map) -> None:
    """Rule 11: each tree.additional_links entry is a full hypothesis to another real metric."""
    name, tree = as_text(metric.get("name")), tree_of(metric)
    links = tree.get("additional_links", [])
    if not isinstance(links, list):
        catalog.add("11a", f"additional_links of {name!r} is not a list", metric)
    for entry in [as_map(item) for item in as_list(links)]:
        parent = entry.get("parent")
        if not isinstance(parent, str) or parent not in catalog.metric_names:
            catalog.add(
                "11a", f"additional link of {name!r} names {parent!r}, not one metric", metric
            )
        if entry.get("link") != "hypothesis":
            message = f"additional link of {name!r} has link {entry.get('link')!r}"
            catalog.add("11b", message, metric)
        if isinstance(parent, str) and parent == tree.get("parent"):
            message = f"additional link of {name!r} repeats its tree parent {parent!r}"
            catalog.add("11c", message, metric)
        what = f"additional link of {name!r} to {parent!r}"
        check_hypothesis(catalog, what, entry, ("11d", "11e", "11f"), metric=metric)


def check_threshold(catalog: Catalog, metric: Map) -> None:
    """Rule 12: only and every guardrail has a threshold with value, unit, direction and basis."""
    name, meta = as_text(metric.get("name")), meta_of(metric)
    if "guardrail_threshold" not in meta:
        if meta.get("role") == "guardrail":
            catalog.add("12f", f"guardrail {name!r} lacks a guardrail_threshold", metric)
        return
    threshold = as_map(meta["guardrail_threshold"])
    value = threshold.get("value")
    if meta.get("role") != "guardrail":
        catalog.add(
            "12a", f"metric {name!r} has a guardrail_threshold but is not a guardrail", metric
        )
    if isinstance(value, bool) or not isinstance(value, int | float):
        catalog.add(
            "12b", f"guardrail_threshold of {name!r} has value {value!r}, not a number", metric
        )
    if not as_text(threshold.get("unit")).strip():
        catalog.add("12c", f"guardrail_threshold of {name!r} lacks a unit", metric)
    if as_text(threshold.get("direction")) not in THRESHOLD_DIRECTIONS:
        catalog.add(
            "12d",
            f"guardrail_threshold of {name!r} has direction {threshold.get('direction')!r},"
            f" not one of {sorted(THRESHOLD_DIRECTIONS)}",
            metric,
        )
    if THRESHOLD_PROVENANCE not in as_text(threshold.get("basis")).lower():
        message = f"guardrail_threshold of {name!r} has a basis that never says project decision"
        catalog.add("12e", message, metric)


def check_year_over_year(catalog: Catalog, metric: Map) -> None:
    """Rule 10a: a year-over-year metric is (current - prior) / prior, prior offset by 1 year."""
    if meta_of(metric).get("unit") != YOY_UNIT:
        return
    inputs = input_metrics(metric)
    prior = [entry for entry in inputs if entry.get("offset_window") == YOY_OFFSET]
    current = [entry for entry in inputs if "offset_window" not in entry]
    expr = SPACE.sub("", as_text(as_map(metric.get("type_params")).get("expr")))
    if len(prior) == 1 and len(current) == 1 and len(inputs) == len(prior) + len(current):
        old = as_text(prior[0].get("alias"))
        new = as_text(current[0].get("alias")) or ref_name(current[0])
        if ref_name(prior[0]) == ref_name(current[0]) and expr == f"({new}-{old})/{old}":
            return
    catalog.add(
        "10a",
        f"metric {metric.get('name')!r} is not (current - prior) / prior over one input"
        f" offset by {YOY_OFFSET}",
        metric,
    )


def check_metric(catalog: Catalog, metric: Map) -> None:
    """Run the per-metric rules: 3, 4, 7, 8c, 8d, 8f to 8k, 9, 10, 11 and 12."""
    check_required(catalog, metric)
    check_references(catalog, metric)
    check_money(catalog, metric)
    if as_text(meta_of(metric).get("role")) in TREE_ROLES:
        check_tree_node(catalog, metric)
    if tree_of(metric).get("link"):
        check_link(catalog, metric)
    if contains_key(metric, ZERO_MONTH_KEYS):
        catalog.add(
            "9a",
            f"metric {metric.get('name')!r} sets fill_nulls_with or join_to_timespine",
            metric,
        )
    check_year_over_year(catalog, metric)
    check_additional_links(catalog, metric)
    check_threshold(catalog, metric)
