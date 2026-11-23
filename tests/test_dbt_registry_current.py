"""The current registry model: one row per park, and a feed row for another data set fails.

Real dbt runs in a temporary project copy over feeds written to a temporary folder.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests import test_dbt_environments as environments
from tests.test_dbt_environments import build_deliveries, delivery_row

project = environments.project  # the fixture, re-exported so pytest finds it here

CURRENT = "int_park_registry__current"
DATA_SET_TEST = "assert_park_registry_current_data_set_matches_target"
CURRENT_KEY_TEST = "unique_int_park_registry__current_park_id"
HISTORY_KEY_TEST = "unique_int_park_registry__history"
ALSO = (CURRENT, DATA_SET_TEST, CURRENT_KEY_TEST)


def status_of(done: subprocess.CompletedProcess[str], test: str) -> str:
    """The PASS, WARN or FAIL dbt printed for the test whose name starts with `test`."""
    found = re.search(rf"of \d+ (PASS|WARN|FAIL)\b[^\n]*?\b{test}", done.stdout)
    assert found, done.stdout
    return found.group(1)


def test_registry_current_row_labelled_company_fails_a_rehearsal_build(
    project: Path, tmp_path: Path
) -> None:
    done, _ = build_deliveries(
        project,
        tmp_path,
        {"park_registry_2026-10-10_01.csv": delivery_row("2026-10-10", data_set="company")},
        target="rehearsal",
        also=ALSO,
    )

    assert done.returncode != 0
    assert status_of(done, DATA_SET_TEST) == "FAIL"


def test_registry_current_row_labelled_for_the_target_passes_a_rehearsal_build(
    project: Path, tmp_path: Path
) -> None:
    done, _ = build_deliveries(
        project,
        tmp_path,
        {"park_registry_2026-10-10_01.csv": delivery_row("2026-10-10")},
        target="rehearsal",
        also=ALSO,
    )

    assert done.returncode == 0, done.stdout
    assert status_of(done, DATA_SET_TEST) == "PASS"


def test_registry_current_row_labelled_company_passes_a_dev_build(
    project: Path, tmp_path: Path
) -> None:
    done, _ = build_deliveries(
        project,
        tmp_path,
        {"park_registry_2026-10-10_01.csv": delivery_row("2026-10-10", data_set="company")},
        also=ALSO,
    )

    assert done.returncode == 0, done.stdout
    assert status_of(done, DATA_SET_TEST) == "PASS"


def test_registry_two_rows_for_one_park_in_its_current_delivery_fail(
    project: Path, tmp_path: Path
) -> None:
    done, _ = build_deliveries(
        project,
        tmp_path,
        {"park_registry_2026-10-10_01.csv": delivery_row("2026-10-10") * 2},
        also=ALSO,
    )

    assert done.returncode != 0
    assert status_of(done, CURRENT_KEY_TEST) == "FAIL"


def test_registry_one_file_with_two_dates_for_one_park_fails(project: Path, tmp_path: Path) -> None:
    done, _ = build_deliveries(
        project,
        tmp_path,
        {
            "park_registry_2026-10-10_01.csv": delivery_row("2026-10-10")
            + delivery_row("2026-10-01")
        },
        also=ALSO,
    )

    # The failing date test skips the current model and its key test, so the build stops there.
    assert done.returncode != 0
    assert status_of(done, environments.DELIVERY_TESTS[0]) == "FAIL"
    assert status_of(done, HISTORY_KEY_TEST) == "WARN"


DUPLICATED_THEN_CURED = {
    "park_registry_2026-10-10_01.csv": delivery_row("2026-10-10") * 2,
    "park_registry_2026-10-12_01.csv": delivery_row("2026-10-12"),
}


def test_registry_later_delivery_cures_duplicates_in_the_earlier_one(
    project: Path, tmp_path: Path
) -> None:
    done, _ = build_deliveries(project, tmp_path, DUPLICATED_THEN_CURED, also=ALSO)

    assert done.returncode == 0, done.stdout
    assert status_of(done, CURRENT_KEY_TEST) == "PASS"


def test_registry_duplicates_in_a_superseded_delivery_only_warn(
    project: Path, tmp_path: Path
) -> None:
    done, _ = build_deliveries(project, tmp_path, DUPLICATED_THEN_CURED, also=ALSO)

    assert done.returncode == 0, done.stdout
    assert status_of(done, HISTORY_KEY_TEST) == "WARN"
