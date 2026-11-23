"""The registry delivery bound uses the build's UTC date across session zones."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests import test_dbt_environments as environments
from tests.test_dbt_environments import build_deliveries, delivery_row
from tests.test_dbt_registry_current import status_of

project = environments.project

DATE_TEST = "assert_park_registry_delivered_on_in_bounds"


def copy_project(project: Path, destination: Path) -> Path:
    """Copy the dbt project inputs without carrying over build outputs."""
    for name in environments.COPIED:
        source = project / name
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return destination


def set_session_zone(project: Path, zone: str) -> None:
    """Set the dev connection's DuckDB session zone in the copied profile."""
    profiles_path = project / "profiles.yml"
    profiles = profiles_path.read_text(encoding="utf-8")
    dev_threads = "      threads: 4\n    ci:"
    assert profiles.count(dev_threads) == 1
    profiles_path.write_text(
        profiles.replace(
            dev_threads,
            f"      threads: 4\n      settings:\n        TimeZone: {zone}\n    ci:",
            1,
        ),
        encoding="utf-8",
    )


def test_utc_date_delivery_passes_in_utc_minus_twelve_session(
    project: Path, tmp_path: Path
) -> None:
    set_session_zone(project, "Etc/GMT+12")
    utc_date = datetime.now(UTC).date()
    date_text = utc_date.isoformat()

    done, _ = build_deliveries(
        project,
        tmp_path,
        {f"park_registry_{date_text}_01.csv": delivery_row(date_text)},
    )

    assert status_of(done, DATE_TEST) == "PASS"


def test_tomorrow_utc_delivery_warns_in_utc_plus_fourteen_session(
    project: Path, tmp_path: Path
) -> None:
    set_session_zone(project, "Pacific/Kiritimati")
    utc_date = datetime.now(UTC).date()
    tomorrow = utc_date + timedelta(days=1)
    date_text = tomorrow.isoformat()

    done, _ = build_deliveries(
        project,
        tmp_path,
        {f"park_registry_{date_text}_01.csv": delivery_row(date_text)},
    )

    build_date = datetime.now(UTC).date()
    if build_date != utc_date:
        tomorrow = build_date + timedelta(days=1)
        date_text = tomorrow.isoformat()
        retry_project = copy_project(project, tmp_path / "retry_project")
        done, _ = build_deliveries(
            retry_project,
            tmp_path / "retry_feed",
            {f"park_registry_{date_text}_01.csv": delivery_row(date_text)},
        )

    assert status_of(done, DATE_TEST) == "WARN"
