"""Company go-live markers and the external archive setting."""

from __future__ import annotations

import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path

from openrct2_analytics.config import ConfigError, env_optional_path


def default_state_dir(
    system: str, home: Path, xdg_data_home: Path | None, localappdata: Path | None
) -> Path:
    """Return the platform's application-data folder."""
    match system:
        case "Darwin":
            return home / "Library/Application Support/openrct2-analytics"
        case "Windows":
            return (localappdata or home / "AppData/Local") / "openrct2-analytics"
        case _:
            return (xdg_data_home or home / ".local/share") / "openrct2-analytics"


def state_dir() -> Path:
    """Read the state setting at run time, refusing an explicitly empty value."""
    explicit = env_optional_path("OPENRCT2_STATE_DIR")
    if explicit is not None:
        return explicit
    xdg = os.environ.get("XDG_DATA_HOME")
    local = os.environ.get("LOCALAPPDATA")
    return (
        default_state_dir(
            platform.system(),
            Path.home(),
            Path(xdg) if xdg else None,
            Path(local) if local else None,
        )
        .expanduser()
        .absolute()
    )


def _existing_ancestors(path: Path) -> list[Path]:
    return [candidate for candidate in (path, *path.parents) if candidate.exists()]


def _inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    if child.is_relative_to(parent):
        return True
    # Existing ancestors establish identity even when the requested folders do not exist.
    # Case-folding the unresolved tails then fails safe on case-insensitive filesystems.
    for child_base in _existing_ancestors(child):
        child_tail = tuple(part.casefold() for part in child.relative_to(child_base).parts)
        for parent_base in _existing_ancestors(parent):
            if not os.path.samefile(child_base, parent_base):
                continue
            parent_tail = tuple(part.casefold() for part in parent.relative_to(parent_base).parts)
            return child_tail[: len(parent_tail)] == parent_tail
    return False


def check_state_dir(folder: Path, data_root: Path, project_dir: Path, user_dir: Path) -> None:
    """Refuse state inside the project/game or overlapping data and warehouses."""
    forbidden = (data_root, project_dir / "warehouse")
    if (
        _inside(folder, project_dir)
        or _inside(folder, user_dir)
        or any(_inside(folder, path) or _inside(path, folder) for path in forbidden)
    ):
        raise ConfigError(f"unsafe state folder: {folder}")


def marker_paths(folder: Path, data_root: Path) -> tuple[Path, Path]:
    """Return both independent go-live marker locations."""
    return folder / "go-live-company.json", data_root / "company/go-live.json"


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def is_live(state_dir: Path, data_root: Path) -> str | None:
    """Return a marker date, failing closed when state cannot be inspected."""
    try:
        if _entry_exists(state_dir):
            list(state_dir.iterdir())
        for marker in marker_paths(state_dir, data_root):
            if _entry_exists(marker):
                payload = json.loads(marker.read_text())
                went_live_at = payload.get("went_live_at") if isinstance(payload, dict) else None
                if not isinstance(went_live_at, str) or not went_live_at.strip():
                    return "unknown (invalid marker)"
                return went_live_at
    except (OSError, ValueError):
        # Unreadable or corrupt evidence must never enable deletion of permanent captures.
        return "unknown (unreadable state or marker)"
    return None


def write_go_live_marker(state_dir: Path, data_root: Path, now: datetime) -> None:
    """Write both dated markers, refusing if either already exists."""
    paths = marker_paths(state_dir, data_root)
    if any(os.path.lexists(path) for path in paths):
        raise FileExistsError("company already has a go-live marker")
    payload = {"data_set": "company", "went_live_at": now.astimezone(UTC).isoformat()}
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as stream:
            json.dump(payload, stream)
