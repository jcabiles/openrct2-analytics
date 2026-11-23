"""Reuse compiled ODCS validators across the test run.

datacontract-cli 1.2.2 calls ``fastjsonschema.validate`` on every contract read, which
compiles the ODCS schema from scratch each time (about 0.16 s); the suite reads contracts
about 4,400 times. ``cached_validate`` compiles each distinct schema once and reuses it.
``tests/test_validator_cache.py`` fails when an upgrade stops routing reads through it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import fastjsonschema

Validator = Callable[[Any], Any]

ORIGINAL_COMPILE = fastjsonschema.compile


@dataclass
class CacheStats:
    """Counts since the last ``reset``: calls served, and compiles they needed."""

    calls: int = 0
    compiles: int = 0
    validators: dict[tuple[object, ...], Validator] = field(default_factory=dict)

    def reset(self) -> None:
        self.calls = 0
        self.compiles = 0
        self.validators.clear()


STATS = CacheStats()


def _key(
    definition: dict[str, Any] | bool,
    handlers: dict[str, Callable[..., Any]],
    formats: dict[str, Any],
    flags: tuple[bool, ...],
) -> tuple[object, ...]:
    # The schema arrives as a fresh dict on every call, so identity never repeats; key on content.
    return (
        json.dumps(definition, sort_keys=True, default=str),
        tuple(sorted(handlers.items())),
        tuple(sorted(formats.items())),
        flags,
    )


def cached_validate(  # noqa: PLR0913, PLR0917 - mirrors fastjsonschema.validate's signature
    definition: dict[str, Any] | bool,
    data: Any,  # noqa: ANN401 - any JSON value
    handlers: dict[str, Callable[..., Any]] | None = None,
    formats: dict[str, Any] | None = None,
    use_default: bool = True,  # noqa: FBT001, FBT002 - keyword-compatible with the original
    use_formats: bool = True,  # noqa: FBT001, FBT002
    detailed_exceptions: bool = True,  # noqa: FBT001, FBT002
    fast_fail: bool = True,  # noqa: FBT001, FBT002
) -> Any:  # noqa: ANN401 - returns the validated data, as the original does
    """Validate ``data`` like ``fastjsonschema.validate``, compiling each schema once."""
    handlers = handlers or {}
    formats = formats or {}
    flags = (use_default, use_formats, detailed_exceptions, fast_fail)
    key = _key(definition, handlers, formats, flags)
    STATS.calls += 1
    validator = STATS.validators.get(key)
    if validator is None:
        STATS.compiles += 1
        validator = ORIGINAL_COMPILE(definition, handlers, formats, *flags)
        STATS.validators[key] = validator
    return validator(data)
