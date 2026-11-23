"""Where the game settings come from besides the environment: the settings file and config.ini.

``bench_setup.load_settings`` picks each of ``OPENRCT2_BINARY``, ``OPENRCT2_GAME_PATH`` and
``OPENRCT2_BENCH_PARK`` from an exported value, then the git-ignored ``local/game-settings.env``
read here, then OpenRCT2's own ``config.ini`` read here. Both files are only read, never written.
Refusal messages name the file and line, never the value, because values are private paths.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

from openrct2_analytics.ingest.capture import Refused

NOTHING_WRITTEN = "Nothing was written."
SETTINGS_FILE_LABEL = "local/game-settings.env"
SETTING_NAMES = ("OPENRCT2_BINARY", "OPENRCT2_GAME_PATH", "OPENRCT2_BENCH_PARK")


def _unquoted(value: str) -> str:
    """Strip one pair of matching surrounding quotes; an unmatched quote stays in the value."""
    if value[1:] and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _settings_text(path: Path) -> str | None:
    """Return the file's text, None when nothing exists at the path, or refuse."""
    if not path.exists():
        return None
    if not path.is_file():
        raise Refused(f"{SETTINGS_FILE_LABEL} is not a file. {NOTHING_WRITTEN}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refused(
            f"{SETTINGS_FILE_LABEL} could not be read ({type(exc).__name__}). {NOTHING_WRITTEN}"
        ) from exc


def read_settings_file(path: Path) -> dict[str, tuple[Path, str]]:
    """Read ``KEY=value`` lines; a path that does not exist holds no settings.

    Blank lines and ``#`` comments are skipped, one pair of matching quotes around a value is
    removed and a leading ``~/`` is expanded. Only the three game settings are accepted:
    data-set choices (``DATA_SET``, ``PARKS``, ``START_YEAR``) stay on the command line.

    Returns:
        For each key, its path and the label of the line it came from.

    Raises:
        Refused: on a path that is not a file, a file that cannot be read, a line without
            ``=``, an unknown or repeated key, an empty value, or a ``#`` comment after an
            unquoted value.
    """
    text = _settings_text(path)
    if text is None:
        return {}
    found: dict[str, tuple[Path, str]] = {}
    first_lines: dict[str, int] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{SETTINGS_FILE_LABEL} line {number}"
        key, separator, value = (part.strip() for part in line.partition("="))
        if not separator:
            raise Refused(f"{where}: expected KEY=value. {NOTHING_WRITTEN}")
        if key not in SETTING_NAMES:
            raise Refused(
                f"{where}: {key} is not accepted here. Only {', '.join(SETTING_NAMES)} are read "
                "from this file; data-set choices such as DATA_SET, PARKS and START_YEAR stay on "
                f"the command line. {NOTHING_WRITTEN}"
            )
        if key in first_lines:
            raise Refused(
                f"{where}: {key} is already set on line {first_lines[key]}. {NOTHING_WRITTEN}"
            )
        unquoted = _unquoted(value)
        if unquoted == value and re.search(r"\s#", value):
            raise Refused(
                f"{where}: {key} has a # comment after the value; put comments on their own "
                "line, or put the value in quotes if the path really contains a space and a "
                f"#. {NOTHING_WRITTEN}"
            )
        if not unquoted:
            raise Refused(f"{where}: {key} must not be empty. {NOTHING_WRITTEN}")
        first_lines[key] = number
        found[key] = (Path(unquoted).expanduser().absolute(), where)
    return found


def game_path_from_openrct2(user_dir: Path) -> Path | None:
    """Return ``game_path`` from ``[general]`` of the game's own ``config.ini``, if it is a folder.

    Only that one file is read, and never written. A missing file, key or folder gives None.

    Raises:
        Refused: if the file exists but cannot be read or parsed.
    """
    ini = user_dir / "config.ini"
    if not ini.is_file():
        return None
    # A [DEFAULT] section would otherwise count as part of [general]; renaming the special
    # section makes it an ordinary one that [general] does not inherit from.
    parser = configparser.ConfigParser(
        interpolation=None, strict=False, default_section="no-inherited-defaults"
    )
    try:
        with ini.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, UnicodeDecodeError, configparser.Error) as exc:
        raise Refused(
            f"OpenRCT2's own settings file could not be read ({type(exc).__name__}). "
            f"{NOTHING_WRITTEN}"
        ) from exc
    value = parser.get("general", "game_path", fallback="").strip().strip('"')
    if not value:
        return None
    folder = Path(value).expanduser()
    return folder.absolute() if folder.is_dir() else None
