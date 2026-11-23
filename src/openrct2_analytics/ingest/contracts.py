"""Check the landed Parquet against the data contracts in ``contracts/``.

datacontract-cli 1.2.2 cannot type-check Parquet files (every type check comes
back as a warning), so each contract names a DuckDB server. This module builds
a throwaway DuckDB file with one view per contract schema object over the
Parquet files and replaces the ``__DATABASE__`` placeholder in the contract text
with a fixed name. The real path goes to datacontract-cli through its config, so an
environment variable such as ``DATACONTRACT_DUCKDB_DATABASE`` cannot redirect the
check. It runs lint and test, then deletes the file.

The runner fails unless every result is exactly ``passed``: the command-line
tool exits 0 on a warning, which would let an unrunnable check go unnoticed.
Run it with ``python -m openrct2_analytics.ingest.contracts``, giving exactly one of
``--data-set {rehearsal,company}`` and ``--data-root PATH``.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import duckdb
from datacontract.data_contract import DataContract
from datacontract.model.run import ResultEnum, Run

from openrct2_analytics.config import DATA_SETS, ConfigError, landing_dirs

CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
DATABASE_PLACEHOLDER = "__DATABASE__"
# Replaces the placeholder in the YAML text: plain characters only. The real path goes in config.
DATABASE_TEXT = "views.duckdb"

LANDING_FOLDER = "v1"
ENVELOPE = "envelope"
# Logical type -> the DuckDB json_type() results a value may have. An integer
# field never accepts a decimal, so a cast cannot round silently.
ACCEPTED_JSON_TYPES = {
    "integer": ("BIGINT", "UBIGINT"),
    "number": ("BIGINT", "UBIGINT", "DOUBLE"),
    "boolean": ("BOOLEAN",),
    "string": ("VARCHAR",),
    "timestamp": ("VARCHAR",),
}
# Reference contracts (feeds, in-repo records) also use dates; the converter never sees them.
REFERENCE_TYPES = (*ACCEPTED_JSON_TYPES, "date")
PHYSICAL_TYPE = re.compile(r"[A-Z][A-Z ]*(\(\d+(,\d+)?\))?")


@dataclass(frozen=True)
class Field:
    """One contract field: its name, logical type, DuckDB type, required flag and description."""

    name: str
    logical: str
    physical: str
    required: bool
    description: str


def _read_schemas(
    paths: Sequence[Path], accepted: Sequence[str] = tuple(ACCEPTED_JSON_TYPES)
) -> dict[str, list[Field]]:
    schemas: dict[str, list[Field]] = {}
    for path in paths:
        contract = DataContract(data_contract_str=path.read_text(encoding="utf-8"))
        for schema in contract.get_data_contract().schema_ or []:
            schemas[str(schema.name)] = [
                _field(schema.name, p, accepted) for p in schema.properties or []
            ]
    return schemas


def read_contract_version(contract_text: str) -> str:
    """Return the version parsed from contract YAML text.

    Raises:
        ValueError: if the contract has no version.
    """
    version = DataContract(data_contract_str=contract_text).get_data_contract().version
    if not isinstance(version, str):
        raise ValueError("Contract version is missing")
    return version


def _field(schema_name: str | None, prop: object, accepted: Sequence[str]) -> Field:
    name = getattr(prop, "name", None)
    logical = getattr(prop, "logicalType", None)
    physical = getattr(prop, "physicalType", None)
    if not isinstance(name, str) or not name:
        raise ValueError(f"{schema_name}: a field has no name")
    where = f"{schema_name}.{name}"
    if not isinstance(logical, str) or logical not in accepted:
        raise ValueError(f"{where}: unsupported logicalType {logical!r}")
    if not isinstance(physical, str) or not PHYSICAL_TYPE.fullmatch(physical):
        raise ValueError(f"{where}: unsupported physicalType {physical!r}")
    # ODCS defaults `required` to false, so a field that omits it is optional. A field with no
    # description reads as "", so the converter's callers need none.
    description = getattr(prop, "description", None)
    return Field(
        name,
        logical,
        physical,
        bool(getattr(prop, "required", False)),
        description.strip() if isinstance(description, str) else "",
    )


def _merge(event_type: str, envelope: list[Field], payload: list[Field]) -> list[Field]:
    known = {f.name: f for f in envelope}
    merged = list(envelope)
    for extra in payload:
        base = known.get(extra.name)
        if base is None:
            merged.append(extra)
        elif (base.logical, base.physical) != (extra.logical, extra.physical):
            raise ValueError(f"{event_type}.{extra.name}: type differs from the envelope contract")
    return merged


def _split(contracts_dir: Path) -> tuple[list[Field], dict[str, list[Field]]]:
    schemas = _read_schemas(sorted(contracts_dir.glob("*.odcs.yaml")))
    if ENVELOPE not in schemas:
        raise FileNotFoundError(f"No envelope contract in {contracts_dir}")
    return schemas.pop(ENVELOPE), schemas


def load_envelope(contracts_dir: Path) -> list[Field]:
    """Read the contracts and return the envelope fields every event type carries.

    Raises:
        FileNotFoundError: if there is no envelope contract in ``contracts_dir``.
        ValueError: if a field has no name, no type, an unknown logical type or an odd
            physical type.
    """
    return _split(contracts_dir)[0]


def load_fields(contracts_dir: Path) -> dict[str, list[Field]]:
    """Read the contracts and return each event type's full field list.

    The envelope contract's fields come first and apply to every event type; each
    event-type contract adds its payload fields.

    Raises:
        FileNotFoundError: if there is no envelope contract in ``contracts_dir``.
        ValueError: if a field has no name, no type, an unknown logical type, an odd
            physical type, or repeats an envelope field with a different type.
    """
    envelope, schemas = _split(contracts_dir)
    return {name: _merge(name, envelope, payload) for name, payload in schemas.items()}


def load_reference_fields(reference_dir: Path) -> dict[str, list[Field]]:
    """Read the reference contracts (``contracts/reference/``) and return each schema's fields.

    These contracts describe feeds from outside processes and records written inside the repo, not
    events: the envelope is not merged in, and the logical type ``date`` is accepted.

    Raises:
        FileNotFoundError: if ``reference_dir`` holds no ``*.odcs.yaml`` contract.
        ValueError: if a field has no name, no type, an unknown logical type or an odd
            physical type.
    """
    paths = sorted(reference_dir.glob("*.odcs.yaml"))
    if not paths:
        raise FileNotFoundError(f"No *.odcs.yaml contracts in {reference_dir}")
    return _read_schemas(paths, REFERENCE_TYPES)


def view_globs(paths: Sequence[Path]) -> dict[str, str]:
    """Map each schema object in the contracts to the Parquet glob its view reads.

    The envelope view reads every event type's file (``union_by_name`` lines the
    files up by column name); any other schema object reads ``<name>.parquet``.
    """
    return {
        name: f"{LANDING_FOLDER}/{'*' if name == ENVELOPE else name}.parquet"
        for name in _read_schemas(paths)
    }


def build_views(database: Path, data_root: Path, globs: dict[str, str]) -> None:
    """Create one view per schema name in a DuckDB file, each over its Parquet glob.

    Raises:
        FileNotFoundError: if a name's glob matches no Parquet file.
    """
    for name, glob in globs.items():
        if not list(data_root.glob(glob)):
            raise FileNotFoundError(
                f"No Parquet files for contract {name!r} at {data_root / glob};"
                " run `make convert` first."
            )
    connection = duckdb.connect(str(database))
    try:
        for name, glob in globs.items():
            pattern = (data_root / glob).as_posix().replace("'", "''")
            connection.execute(
                f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{pattern}', union_by_name=true)"
            )
    finally:
        connection.close()


def _result_text(result: ResultEnum | None) -> str:
    """Return a check result's text, or ``none`` when there is no result."""
    return result.value if result is not None else "none"


def describe(run: Run) -> list[str]:
    """Return one line per result of a lint or test run that is not exactly ``passed``."""
    problems: list[str] = []
    if run.result != ResultEnum.passed:
        problems.append(f"overall result: {_result_text(run.result)}")
    if not run.checks:
        problems.append("no checks ran")
    for check in run.checks or []:
        if check.result != ResultEnum.passed:
            problems.append(f"{check.name}: {_result_text(check.result)} ({check.reason})")
    return problems


def run_contract(
    text: str, prepare: Callable[[Path], None], prefix: str = "contracts-"
) -> list[str]:
    """Lint contract ``text``, then test it over the DuckDB file that ``prepare`` fills.

    ``prepare`` receives the throwaway database path and builds the views the contract names.

    Returns:
        One line per lint or test check whose result is not exactly ``passed``, or an empty list
        when everything passed.
    """
    with tempfile.TemporaryDirectory(prefix=prefix) as temp_dir:
        database = Path(temp_dir) / "views.duckdb"
        contract = DataContract(
            data_contract_str=text.replace(DATABASE_PLACEHOLDER, DATABASE_TEXT),
            config={
                "DATACONTRACT_DUCKDB_DATABASE": database.as_posix(),
                "DATACONTRACT_DUCKDB_SCHEMA": "main",
            },
        )
        lint_problems = [f"lint {line}" for line in describe(contract.lint())]
        if lint_problems:
            # A contract that fails lint cannot be read for its schema objects, so no view is built.
            return lint_problems
        prepare(database)
        return [f"test {line}" for line in describe(contract.test())]


def check_contract(contract_path: Path, data_root: Path) -> list[str]:
    """Lint and test one contract over the Parquet under ``data_root``.

    Returns:
        One line per lint or test check whose result is not exactly ``passed``,
        or an empty list when everything passed.
    """
    return run_contract(
        contract_path.read_text(encoding="utf-8"),
        lambda database: build_views(database, data_root, view_globs([contract_path])),
    )


def check_all(data_root: Path, contracts_dir: Path = CONTRACTS_DIR) -> dict[str, list[str]]:
    """Check every ``*.odcs.yaml`` in ``contracts_dir``; map each name to its problems."""
    paths = sorted(contracts_dir.glob("*.odcs.yaml"))
    if not paths:
        raise FileNotFoundError(f"No *.odcs.yaml contracts in {contracts_dir}")
    return {path.name: check_contract(path, data_root) for path in paths}


def main(argv: Sequence[str] | None = None) -> int:
    """Run every contract; return 0 only when every result is exactly ``passed``."""
    parser = argparse.ArgumentParser(description=__doc__)
    chosen = parser.add_mutually_exclusive_group(required=True)
    chosen.add_argument("--data-set", choices=DATA_SETS, help="Data set whose Parquet to check")
    chosen.add_argument("--data-root", type=Path, help="Folder holding v1/*.parquet")
    args = parser.parse_args(argv)
    if args.data_root is not None:
        data_root: Path = args.data_root
    else:
        try:
            data_root = landing_dirs(args.data_set).parquet
        except ConfigError as exc:
            print(f"{exc}. Nothing was checked.")
            return 2

    try:
        results = check_all(data_root)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    failed = False
    for name, problems in results.items():
        for problem in problems:
            print(f"{name}: {problem}")
        failed = failed or bool(problems)
    if failed:
        return 1
    print("Every contract check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
