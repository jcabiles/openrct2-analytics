"""Copy and verify every original before a company delete changes anything."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from openrct2_analytics.ingest.delete_plan import Plan
from openrct2_analytics.ingest.publish_errors import PublishFailed, PublishRefused

StepObserver = Callable[[str], None]
MAX_ARCHIVE_ID_PREFIX_LENGTH = 140


def _archive_scope(plan: Plan) -> str:
    if not plan.scope.named:
        return "all"
    kind, value = (
        ("park", plan.scope.park)
        if plan.scope.park is not None
        else ("session", plan.scope.session)
    )
    encoded = quote(str(value), safe="", errors="surrogatepass")
    if len(encoded) > MAX_ARCHIVE_ID_PREFIX_LENGTH:
        digest = hashlib.sha256(str(value).encode(errors="surrogatepass")).hexdigest()
        encoded = f"{encoded[:MAX_ARCHIVE_ID_PREFIX_LENGTH]}-{digest}"
    return f"{kind}-{encoded}"


def check_destination(
    state_dir: Path, data_root: Path, project_dir: Path, run: Path | None = None
) -> None:
    """Refuse an archive folder (or dated run folder) that is a link or resolves into the repo.

    The state folder check cannot see a link one level below it, so this runs again just
    before the first archive write.
    """
    archive_root = state_dir / "archive"
    for path in (archive_root, run):
        if path is not None and path.is_symlink():
            raise PublishRefused("unsafe-path", f"archive folder is a symbolic link: {path}")
    resolved = archive_root.resolve()
    for label, base in (("project folder", project_dir), ("data root", data_root)):
        if resolved.is_relative_to(base.resolve()):
            raise PublishRefused(
                "unsafe-path", f"archive folder {archive_root} is inside the {label}"
            )


def manifest(plan: Plan, data_root: Path, now: datetime) -> dict[str, object]:
    """Describe the snapshots and intended mutations for manual recovery."""
    return {
        "scope": {"park": plan.scope.park, "session": plan.scope.session},
        "utc_time": now.astimezone(UTC).isoformat(),
        "completed": False,
        "files": [
            {
                "path": str(change.path.relative_to(data_root)),
                "bytes": len(change.original),
                "sha256": change.digest,
                "lines_removed": change.removed_lines,
                "lines_removed_per_session": change.sessions,
                "unattributed_lines_kept": change.unattributed if change.kept is not None else 0,
                "unattributed_lines_removed": change.unattributed if change.kept is None else 0,
                "action": "remove" if change.kept is None else "rewrite",
            }
            for change in plan.changes
        ],
        "derived_removed": [str(path) for path in plan.derived],
    }


def archive(
    plan: Plan,
    state_dir: Path,
    data_root: Path,
    project_dir: Path,
    *,
    copy: Callable[[Path, Path], object] = shutil.copy2,
    on_step: StepObserver = lambda _: None,
) -> Path:
    """Copy originals, check hashes, then write the manifest; never alter an original."""
    now = datetime.now(UTC)
    # IDs have no pattern restrictions, but must remain one bounded path component.
    scope = _archive_scope(plan)
    folder = state_dir / "archive" / f"{now:%Y%m%dT%H%M%SZ}-{scope}"
    check_destination(state_dir, data_root, project_dir, folder)
    folder.parent.mkdir(parents=True, exist_ok=True)
    try:
        folder.mkdir()
    except FileExistsError as error:
        raise PublishFailed("archive-exists", str(folder)) from error
    for change in plan.changes:
        on_step("copying")
        target = folder / change.path.relative_to(data_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        copy(change.path, target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != change.digest:
            raise PublishFailed("archive-mismatch", str(change.path))
    (folder / "manifest.json").write_text(
        json.dumps(manifest(plan, data_root, now), indent=2) + "\n"
    )
    on_step("archived")
    return folder


def complete(folder: Path) -> None:
    """Mark a fully applied archive manifest completed."""
    path = folder / "manifest.json"
    value = json.loads(path.read_text())
    value["completed"] = True
    path.write_text(json.dumps(value, indent=2) + "\n")
