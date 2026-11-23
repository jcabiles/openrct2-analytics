"""The one place a configured data folder is placed under the project folder.

A folder from ``config`` stays as it is when it is absolute (``OPENRCT2_DATA_DIR`` may point
anywhere) and goes under the project folder when it is relative. Every command that needs a
landing folder as an absolute path calls this module instead of repeating the rule; a test in
``tests/test_landing_paths.py`` fails when a copy of the rule comes back.
"""

from __future__ import annotations

from pathlib import Path

from openrct2_analytics.config import LandingDirs, landing_dirs


def project_path(path: Path, project_dir: Path) -> Path:
    """Return ``path`` if absolute, else ``path`` under ``project_dir``; no link is resolved.

    Args:
        path: A configured folder, absolute or relative.
        project_dir: The project folder that a relative ``path`` goes under.
    """
    return path if path.is_absolute() else project_dir / path


def landing(data_set: str, project_dir: Path) -> LandingDirs:
    """Return the raw and Parquet landing folders of ``data_set`` as absolute paths.

    The environment is read on every call, through ``config.landing_dirs``.

    Args:
        data_set: One of ``config.DATA_SETS``.
        project_dir: The project folder that a relative configured folder goes under.

    Raises:
        ConfigError: as ``config.landing_dirs`` does.
    """
    folders = landing_dirs(data_set)
    return LandingDirs(
        raw=project_path(folders.raw, project_dir),
        parquet=project_path(folders.parquet, project_dir),
    )
