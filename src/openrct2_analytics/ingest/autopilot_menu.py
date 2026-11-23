"""Turn the JSON of ``make autopilot-parks`` into tab-separated menu lines for the launcher.

Standard input holds that JSON; standard output gets one line per park, in input order, with four
tab-separated fields: the park ID; the park's label (``park_label``, which must be a string with
a visible character); the source problem (``-`` when null, empty or only spaces); and the readiness
sentence (``-`` when the park does not need it). Tabs, carriage returns and line feeds inside a
field become one space, and no field is empty, because zsh's ``read`` merges empty tab-separated
fields. Only ``park_id``, ``park_label``, ``source_problem`` and ``needs_ready`` are read. It
writes no file and takes no lock. It takes no arguments.
Exit 0 printed, 1 input not in the documented shape, 2 refused arguments, 130 interrupted.
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import sys
from collections.abc import Sequence

from openrct2_analytics.ingest import lock
from openrct2_analytics.ingest.play_mode_feed import ready_phrase

_CONTROL = re.compile(r"[\t\r\n]")
_NONE = "-"


class _BadShape(Exception):
    """The input is not the JSON that ``make autopilot-parks`` prints."""


def _field(value: str | None, fallback: str) -> str:
    return value if value is not None and value.strip() else fallback


def _line(park: object) -> str:
    if not isinstance(park, dict):
        raise _BadShape("a park entry is not an object")
    try:
        park_id, label = park["park_id"], park["park_label"]
        problem, needs_ready = park["source_problem"], park["needs_ready"]
    except KeyError as missing:
        raise _BadShape(f"a park entry has no {missing.args[0]!r}") from None
    if not isinstance(park_id, str) or not park_id.strip():
        raise _BadShape("park_id is not a non-empty string")
    if not isinstance(label, str) or not label.strip():
        raise _BadShape("park_label is not a non-empty string")
    if problem is not None and not isinstance(problem, str):
        raise _BadShape("source_problem is neither a string nor null")
    if not isinstance(needs_ready, bool):
        raise _BadShape("needs_ready is not true or false")
    ready = ready_phrase(park_id) if needs_ready else _NONE
    fields = (park_id, label, _field(problem, _NONE), ready)
    return "\t".join(_CONTROL.sub(" ", f) for f in fields)


def main(argv: Sequence[str] = ()) -> int:
    """Read the JSON on standard input and print the menu lines."""
    parser = argparse.ArgumentParser(description=__doc__)
    handlers = {
        name: signal.getsignal(getattr(signal, name))
        for name in lock.SIGNAL_NAMES
        if hasattr(signal, name)
    }
    lock.set_signal_handlers(lock.raise_interrupted)
    try:
        parser.parse_args(argv)
        data = json.load(sys.stdin)
        if not isinstance(data, dict) or not isinstance(data.get("parks"), list):
            raise _BadShape("the top level is not an object with a 'parks' list")
        lines = [_line(park) for park in data["parks"]]
    except (lock.Interrupted, KeyboardInterrupt):
        return 130
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError, _BadShape) as problem:
        print(f"autopilot_menu: input is not the park list: {problem}", file=sys.stderr)
        return 1
    finally:
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
