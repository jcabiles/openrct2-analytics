"""The dbt house rules (docs/CONVENTIONS.md), run by scripts/check_dbt_rules.py.

Each rule function takes the loaded `Project` and returns one line per problem as
`<file>: rule <letter>: <what is wrong>`. The rules are lettered as in R8 of the removed
staging spec (`git show 6eafb6d:docs/ai-dlc/specs/staging-models.md`):
(a) required tests, (b) unit and clock in every description, (c) contract version and type list,
(d) D16: no `_tenths` read outside staging, no `select *` from a source, no dbt package files, and
(e) the repeat-delivery test applied.

Rules (a), (c) and (e) apply to models named `stg_<contracted type>` and to `stg_envelope`; rule
(b) applies to every model. Every `.sql` under `models/` needs a YAML entry, and a model in
`models/staging/` named anything else fails rule (a). Models are the entries under the `models:` key
of the YAML files in `models/`, so the generated `_sources.yml` is never read.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path

from metric_catalog_yaml import Map, as_list, as_map, as_text, maps
from openrct2_analytics.ingest.contracts import Field, load_reference_fields, read_contract_version

MODELS_DIR = "models"
STAGING_DIR = "models/staging/"
ENVELOPE_MODEL = "stg_envelope"
ENVELOPE_CONTRACT = "envelope"
# Reference-feed staging models and the contract (in contracts/reference/) behind each.
REFERENCE_MODELS = {
    "stg_park_registry": "park_registry",
    "stg_session_play_mode": "session_play_mode",
}
STAGING_PREFIX = "stg_"
# The generic test of R7; its file is tests/dbt/generic/repeat_delivery_payload_differs.sql.
REPEAT_TEST = "repeat_delivery_payload_differs"
# The one landed type with no event-type model; stg_envelope's YAML applies the R7 test to it.
UNSTAGED_TYPE = "plugin_stats"
MONEY_SUFFIX = "_tenths"
# The one `_tenths` field that keeps its name (unit-unverified; R5 of the removed staging spec,
# `git show 6eafb6d:docs/ai-dlc/specs/staging-models.md`).
RAW_TENTHS_FIELD = "value_tenths"
TEST_KEYS = ("data_tests", "tests")

MACROS_DIR = "macros"
# A single-quoted string is matched first so a `--` or `/*` inside it is not taken for a comment.
COMMENT_OR_STRING = re.compile(r"'(?:[^']|'')*'|--[^\n]*|/\*.*?\*/|\{#.*?#\}", re.DOTALL)
TENTHS_COLUMN = re.compile(r"\b\w*_tenths\b")
SQL_TOKEN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|'(?:[^']|'')*'|\"[^\"]*\"|\w+|\S", re.DOTALL)
SET_SOURCE = re.compile(r"\{%-?\s*set\s+(\w+)\s*=\s*source\s*\(")
JINJA_HEAD = re.compile(r"\{\{-?\s*(\w+)\s*(\(|-?\}\})")
STAR_MODIFIERS = ("exclude", "replace", "rename")
SOURCE_TABLE = re.compile(r"\bsource\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)")


@dataclass(frozen=True)
class Model:
    """One entry under `models:` of a YAML file: its name, that file's relative path, its spec."""

    name: str
    path: str
    spec: Map


@dataclass(frozen=True)
class Project:
    """The repo root, its dbt models and the contracted fields of each event type."""

    root: Path
    models: list[Model]
    fields: dict[str, list[Field]]

    def event_type(self, model: Model) -> str:
        """Return the contracted type a model stages (`stg_<type>`), or an empty string."""
        name = model.name.removeprefix(STAGING_PREFIX)
        return name if model.name.startswith(STAGING_PREFIX) and name in self.fields else ""

    def is_staged(self, model: Model) -> bool:
        """Say whether a model is an event-type staging model or `stg_envelope`."""
        return bool(self.event_type(model)) or model.name == ENVELOPE_MODEL

    def is_registry(self, model: Model) -> bool:
        """Say whether a model stages a reference feed (park registry or play-mode labels)."""
        return model.name in REFERENCE_MODELS


def test_entries(node: Map) -> list[tuple[str, object]]:
    """Return (test name, arguments) for each test a model or column declares."""
    entries: list[tuple[str, object]] = []
    for key in TEST_KEYS:
        for item in as_list(node.get(key)):
            if isinstance(item, str):
                entries.append((item, None))
            elif isinstance(item, dict):
                entries.extend((str(name), args) for name, args in item.items())
    return entries


def is_running(args: object) -> bool:
    """Say whether a test runs at default strictness: not disabled, not `warn`, no `where`.

    dbt reads `enabled`, `severity` and `where` from the test's `config:` or from its top-level
    arguments, so both places are checked.
    """
    if not isinstance(args, dict):
        return True
    for settings in (args, as_map(args.get("config"))):
        if settings.get("enabled") is False:
            return False
        if str(settings.get("severity", "")).lower() == "warn":
            return False
        if settings.get("where") is not None:
            return False
    return True


def column_tests(model: Model) -> dict[str, set[str]]:
    """Return the names of the tests that really run on each column of a model."""
    return {
        as_text(column.get("name")): {
            name for name, args in test_entries(column) if is_running(args)
        }
        for column in maps(model.spec.get("columns"))
    }


def column_for(field: str) -> str:
    """Name a field's staging column: `_tenths` becomes `_usd`, except in `value_tenths`."""
    if field.endswith(MONEY_SUFFIX) and field != RAW_TENTHS_FIELD:
        return field.removesuffix(MONEY_SUFFIX) + "_usd"
    return field


def envelope_required(fields: dict[str, list[Field]]) -> list[str]:
    """Return the required envelope fields: the required names every event type's list carries.

    `load_fields` puts the envelope's fields in front of each type's own, so the names common to
    all lists are the envelope's, and `load_fields` stays the only reader of contract fields.
    """
    lists = list(fields.values())
    if not lists:
        return []
    common = set.intersection(*({field.name for field in fields_of} for fields_of in lists))
    return [field.name for field in lists[0] if field.name in common and field.required]


def required_fields(project: Project, model: Model) -> list[str]:
    """Return the contract fields whose columns a staged model must test `not_null`."""
    if project.is_registry(model):
        fields = load_reference_fields(project.root / "contracts" / "reference")[
            REFERENCE_MODELS[model.name]
        ]
        return [field.name for field in fields if field.required]
    event_type = project.event_type(model)
    if event_type:
        return [field.name for field in project.fields[event_type] if field.required]
    return envelope_required(project.fields)


def is_staged_name(project: Project, name: str) -> bool:
    """Say whether a model name is `stg_envelope` or `stg_<contracted type>`."""
    contracted = (
        name.startswith(STAGING_PREFIX) and name.removeprefix(STAGING_PREFIX) in project.fields
    )
    return name == ENVELOPE_MODEL or name in REFERENCE_MODELS or contracted


def unstaged_message(name: str) -> str:
    """Say why a model in `models/staging/` is out of reach of rules a, c and e."""
    return (
        f"{name} is in {STAGING_DIR} but is neither stg_<contracted type> nor {ENVELOPE_MODEL}; "
        "rules a, c and e cannot check it (rename it or move it out of staging)"
    )


def check_scope(project: Project) -> list[str]:
    """Rule a: a model has no YAML entry, or sits in staging under a name no rule reads."""
    problems: list[str] = []
    yaml_models = {model.name for model in project.models}
    unstaged: set[str] = set()
    for path, _ in sql_files(project.root):
        name = Path(path).stem
        if path.startswith(STAGING_DIR) and not is_staged_name(project, name):
            problems.append(f"{path}: rule a: {unstaged_message(name)}")
            unstaged.add(name)
        elif name not in yaml_models:
            problems.append(f"{path}: rule a: {name} has no YAML entry")
    problems.extend(
        f"{model.path}: rule a: {unstaged_message(model.name)}"
        for model in project.models
        if model.path.startswith(STAGING_DIR)
        and not project.is_staged(model)
        and not project.is_registry(model)
        and model.name not in unstaged
    )
    return problems


def check_required_tests(project: Project) -> list[str]:
    """Rule a: a staged model lacks `not_null` on a required column or `unique` on `event_id`."""
    problems = check_scope(project)
    for model in project.models:
        if not project.is_staged(model) and not project.is_registry(model):
            continue
        tests = column_tests(model)
        for field in required_fields(project, model):
            column = column_for(field)
            if "not_null" not in tests.get(column, set()):
                problems.append(f"{model.path}: rule a: {model.name} lacks not_null on {column}")
        unique = "unique" in tests.get("event_id", set())
        if project.event_type(model) and not unique:
            problems.append(f"{model.path}: rule a: {model.name} lacks unique on event_id")
        if model.name == ENVELOPE_MODEL and unique:
            problems.append(f"{model.path}: rule a: {model.name} carries unique on event_id")
    return problems


def states(text: str, label: str) -> bool:
    """Say whether text has a `<label>` statement: `no <label>`, or `<label>:` and a word.

    The word must come before the next `;` or `.` (rule b, R8 of the removed staging spec,
    `git show 6eafb6d:docs/ai-dlc/specs/staging-models.md`); `unit: none` states nothing.
    """
    lowered = text.lower()
    if re.search(rf"\bno {label}\b", lowered):
        return True
    for match in re.finditer(rf"\b{label}:([^;.]*)", lowered):
        body = match.group(1).strip()
        if re.search(r"\w", body) and body != "none":
            return True
    return False


def check_descriptions(project: Project) -> list[str]:
    """Rule b: a model or column description lacks a unit statement or a clock statement."""
    problems: list[str] = []
    for model in project.models:
        nodes = [(model.name, model.spec)] + [
            (f"{model.name}.{as_text(column.get('name'))}", column)
            for column in maps(model.spec.get("columns"))
        ]
        for label, node in nodes:
            description = as_text(node.get("description"))
            for word in ("unit", "clock"):
                if not states(description, word):
                    problems.append(
                        f"{model.path}: rule b: the description of {label} has no {word} "
                        f"statement (`no {word}` or `{word}: <words>`)"
                    )
    return problems


def declared_version(spec: Map) -> object:
    """Return `contract_version` from a model's `meta`, else its `config.meta`, else None."""
    for meta in (as_map(spec.get("meta")), as_map(as_map(spec.get("config")).get("meta"))):
        if "contract_version" in meta:
            return meta["contract_version"]
    return None


def contract_name(project: Project, model: Model) -> str:
    """Name the contract file (without `.odcs.yaml`) behind a staged model."""
    if project.is_registry(model):
        return REFERENCE_MODELS[model.name]
    return ENVELOPE_CONTRACT if model.name == ENVELOPE_MODEL else project.event_type(model)


def check_contract_version(project: Project) -> list[str]:
    """Rule c: a staged model's `meta.contract_version` differs from its contract's `version`."""
    problems: list[str] = []
    for model in project.models:
        if not project.is_staged(model) and not project.is_registry(model):
            continue
        name = contract_name(project, model)
        folder = "reference" if project.is_registry(model) else ""
        path = project.root / "contracts" / folder / f"{name}.odcs.yaml"
        contract_path = f"{folder + '/' if folder else ''}{name}"
        version = read_contract_version(path.read_text(encoding="utf-8"))
        declared = declared_version(model.spec)
        if declared != version:
            problems.append(
                f"{model.path}: rule c: {model.name} has meta.contract_version {declared!r}; "
                f"contracts/{contract_path}.odcs.yaml is at {version!r}"
            )
    return problems


def strip_comments(text: str) -> str:
    """Blank out SQL and Jinja comments, keeping string literals whole."""
    return COMMENT_OR_STRING.sub(lambda m: m.group(0) if m.group(0)[0] == "'" else " ", text)


def sql_files(root: Path, directory: str = MODELS_DIR) -> list[tuple[str, str]]:
    """Return (root-relative path, text without comments) for each SQL file under a folder."""
    return [
        (path.relative_to(root).as_posix(), strip_comments(path.read_text(encoding="utf-8")))
        for path in sorted((root / directory).glob("**/*.sql"))
    ]


def check_envelope_types(project: Project) -> list[str]:
    """Rule c: the sources `stg_envelope.sql` unions differ from the contracted event types."""
    problems: list[str] = []
    envelope_files = [
        (path, text) for path, text in sql_files(project.root) if Path(path).stem == ENVELOPE_MODEL
    ]
    has_staging_sql = any(
        path.startswith(STAGING_DIR) and Path(path).stem not in REFERENCE_MODELS
        for path, _ in sql_files(project.root)
    )
    if not envelope_files and has_staging_sql:
        problems.append(
            f"{STAGING_DIR}{ENVELOPE_MODEL}.sql: rule c: {ENVELOPE_MODEL}.sql is missing"
        )
    for path, text in envelope_files:
        listed = sorted(SOURCE_TABLE.findall(text))
        contracted = sorted(project.fields)
        if listed != contracted:
            missing, extra = (
                sorted(set(contracted) - set(listed)),
                sorted(set(listed) - set(contracted)),
            )
            problems.append(
                f"{path}: rule c: the type list differs from contracts/: missing {missing}, "
                f"unexpected {extra}, listed {len(listed)} times for {len(contracted)} types"
            )
    return problems


def check_contract(project: Project) -> list[str]:
    """Rule c: each staged model's contract version, and `stg_envelope`'s type list."""
    return check_contract_version(project) + check_envelope_types(project)


@dataclass
class Scope:
    """One parenthesis level of the star scan: its select list so far and what follows `from`."""

    has_select: bool = False
    listing: bool = False
    star: bool = False
    in_from: bool = False
    items: list[list[str]] = dataclasses.field(default_factory=lambda: [[]])


def is_source_token(token: str, aliases: set[str]) -> bool:
    """Say whether a `{{ ... }}` token is `source(...)` or a `{% set name = source(...) %}` name."""
    head = JINJA_HEAD.match(token)
    if head is None:
        return False
    return head.group(1) == "source" if head.group(2) == "(" else head.group(1) in aliases


def is_star_item(item: list[str]) -> bool:
    """Say whether a select-list item is a star, including DuckDB's `columns(*)`."""
    words = item[1:] if item[:1] == ["distinct"] else item
    if words[:2] == ["columns", "()"]:
        return True
    if words[:1] == ["*"]:
        rest = words[1:]
    elif words[1:3] == [".", "*"]:
        rest = words[3:]
    else:
        return False
    return not rest or rest[0] in STAR_MODIFIERS


def advance_clause(scope: Scope, word: str) -> bool:
    """Update a scope's query-clause state and say whether its token was handled."""
    if word == "select":
        scope.has_select, scope.listing, scope.star, scope.items = True, True, False, [[]]
    elif word == "from" and (scope.listing or not scope.has_select):
        scope.star = scope.listing and any(is_star_item(item) for item in scope.items)
        scope.listing, scope.in_from = False, True
    elif word in ("where", "group", "having", "qualify", "order", "limit"):
        scope.in_from = False
    elif word in ("union", "intersect", "except", ";"):
        scope.in_from = False
        scope.has_select = scope.listing = scope.star = False
    else:
        return False
    return True


def advance(scopes: list[Scope], word: str) -> None:
    """Move the star scan past one lower-cased token; `scopes` is the stack of open parentheses."""
    scope = scopes[-1]
    if advance_clause(scope, word):
        return
    if word == ")":
        if len(scopes) > 1:
            scopes.pop()
    elif not scope.listing:
        if word == "(":
            scopes.append(Scope())
    elif word == ",":
        scope.items.append([])
    elif word == "(":
        scope.items[-1].append("()")
        scopes.append(Scope())
    else:
        scope.items[-1].append(word)


def reads_source_star(text: str) -> bool:
    """Say whether any select, in any CTE or subquery, takes a star from a `source()`.

    The rule is lexical: a `*` item anywhere in a select list whose FROM relation or join target
    is a `source()` call (or a name set to one), and DuckDB's FROM-first form with no select.
    `select * from final`
    and a star over a `ref()` are not caught.
    """
    aliases = set(SET_SOURCE.findall(text))
    scopes = [Scope()]
    for token in SQL_TOKEN.findall(text):
        if token.startswith("{%"):
            continue
        if is_source_token(token, aliases) and any(
            scope.in_from and (scope.star or not scope.has_select) for scope in scopes
        ):
            return True
        advance(scopes, token.lower())
    return False


def check_forbidden(project: Project) -> list[str]:
    """Rule d: `_tenths` outside staging, source stars, and dbt package files are forbidden."""
    problems: list[str] = []
    for path, text in sql_files(project.root) + sql_files(project.root, MACROS_DIR):
        if not path.startswith(STAGING_DIR):
            for column in sorted(set(TENTHS_COLUMN.findall(text))):
                problems.append(f"{path}: rule d: reads {column} outside {STAGING_DIR}")
        if reads_source_star(text):
            problems.append(f"{path}: rule d: select * from a source(); name the columns")
    for filename in ("packages.yml", "dependencies.yml"):
        if (project.root / filename).exists():
            problems.append(f"{filename}: rule d: dbt packages are not allowed")
    return problems


def repeat_test_source(args: object) -> str | None:
    """Return the source table named through dbt's real test interface, if any."""
    if not isinstance(args, dict):
        return None
    arguments = args.get("arguments")
    if not isinstance(arguments, dict):
        return None
    source_relation = arguments.get("source_relation")
    if not isinstance(source_relation, str):
        return None
    source_match = SOURCE_TABLE.search(source_relation)
    return source_match.group(1) if source_match else None


def check_repeat_test(project: Project) -> list[str]:
    """Rule e: a staged model's YAML lacks the R7 test (`stg_envelope`'s, for plugin_stats)."""
    problems: list[str] = []
    for model in project.models:
        if not project.is_staged(model):
            continue
        nodes = [model.spec, *maps(model.spec.get("columns"))]
        applied = [
            args for node in nodes for name, args in test_entries(node) if name == REPEAT_TEST
        ]
        expected_source = (
            UNSTAGED_TYPE if model.name == ENVELOPE_MODEL else project.event_type(model)
        )
        matching_source = any(repeat_test_source(args) == expected_source for args in applied)
        if not applied and model.name == ENVELOPE_MODEL:
            problems.append(
                f"{model.path}: rule e: {model.name} does not apply {REPEAT_TEST} "
                f"to {UNSTAGED_TYPE}"
            )
        elif not applied:
            problems.append(f"{model.path}: rule e: {model.name} does not apply {REPEAT_TEST}")
        elif not matching_source:
            if model.name == ENVELOPE_MODEL:
                problems.append(
                    f"{model.path}: rule e: {model.name} does not apply {REPEAT_TEST} "
                    f"to {UNSTAGED_TYPE}"
                )
            else:
                problems.append(
                    f"{model.path}: rule e: {model.name} applies {REPEAT_TEST} "
                    f"without source {expected_source}"
                )
    return problems
