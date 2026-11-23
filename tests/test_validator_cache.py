"""The run-wide validator reuse in ``conftest.py`` is live, keyed safely, and pinned."""

from __future__ import annotations

from importlib.metadata import version

import fastjsonschema
import pytest

from openrct2_analytics.ingest.contracts import CONTRACTS_DIR, load_fields
from tests.validator_cache import STATS

PATCHED_FOR = {"datacontract-cli": "1.2.2", "fastjsonschema": "2.22.2"}


@pytest.mark.parametrize(("package", "pinned"), PATCHED_FOR.items())
def test_libraries_are_the_versions_the_reuse_was_written_for(package: str, pinned: str) -> None:
    assert version(package) == pinned, (
        f"{package} changed: check that contract reads still call fastjsonschema.validate "
        "with the same arguments, then update PATCHED_FOR, or delete tests/validator_cache.py "
        "if the library now reuses its validators"
    )


def test_contract_reads_reuse_one_compiled_schema() -> None:
    contracts = sorted(CONTRACTS_DIR.glob("*.odcs.yaml"))
    STATS.reset()

    load_fields(CONTRACTS_DIR)

    # Zero calls means contract reads no longer reach the patch, and the slow path is back.
    assert STATS.calls == len(contracts)
    assert STATS.compiles == 1


def test_different_schemas_never_share_a_validator() -> None:
    needs_a = {"type": "object", "required": ["a"]}
    needs_b = {"type": "object", "required": ["b"]}

    fastjsonschema.validate(needs_a, {"a": 1})

    with pytest.raises(fastjsonschema.JsonSchemaValueException):
        fastjsonschema.validate(needs_b, {"a": 1})


def test_same_schema_with_other_format_rules_compiles_separately() -> None:
    schema = {"type": "string", "format": "even-length"}

    fastjsonschema.validate(schema, "abc", formats={"even-length": lambda _: True})

    with pytest.raises(fastjsonschema.JsonSchemaValueException):
        fastjsonschema.validate(schema, "abc", formats={"even-length": lambda s: len(s) % 2 == 0})


def test_same_schema_with_other_flags_compiles_separately() -> None:
    schema = {"type": "object", "properties": {"n": {"default": 3}}}
    STATS.reset()

    assert fastjsonschema.validate(schema, {}, use_default=False) == {}
    assert fastjsonschema.validate(schema, {}) == {"n": 3}
    assert STATS.compiles == 2
