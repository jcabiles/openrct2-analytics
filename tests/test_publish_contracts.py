"""Tests for the publish contract check."""

import shutil
from pathlib import Path

import pytest

from openrct2_analytics.ingest import contracts, publish_contracts
from openrct2_analytics.ingest.publish_errors import PublishFailed
from tests.test_contracts import write_data

SAMPLE_FEED_V1 = Path(__file__).resolve().parents[1] / "data/sample/rehearsal/registry/v1"


def write_candidate(tmp_path: Path, mutation: str = "", *, feed: bool = True) -> Path:
    """Write a candidate with valid Parquet and, unless ``feed`` is false, the sample feed."""
    candidate_dir = tmp_path / "candidate"
    write_data(candidate_dir / "landing", mutation)
    if feed:
        shutil.copytree(SAMPLE_FEED_V1, candidate_dir / "landing" / "registry" / "v1")
    return candidate_dir


def test_clean_snapshot_passes(tmp_path: Path) -> None:
    """A candidate with valid Parquet passes every contract."""
    candidate_dir = write_candidate(tmp_path)

    publish_contracts.check_contracts(candidate_dir)


def test_contract_failures_are_all_listed(tmp_path: Path) -> None:
    """The publish error includes each problem reported by every contract."""
    candidate_dir = write_candidate(
        tmp_path, "UPDATE snapshot SET park_id = NULL, cash_tenths = NULL"
    )
    landing = candidate_dir / "landing"
    results = contracts.check_all(landing)
    failures = [f"{name}: {problem}" for name, problems in results.items() for problem in problems]

    with pytest.raises(PublishFailed) as raised:
        publish_contracts.check_contracts(candidate_dir)

    assert raised.value.reason == "contracts"
    assert len(failures) >= 2
    assert raised.value.detail == "; ".join(failures)


def test_contract_failure_detail_is_one_line_and_lists_every_problem(tmp_path: Path) -> None:
    """The failure detail is one line and includes every reported problem."""
    candidate_dir = write_candidate(
        tmp_path, "UPDATE snapshot SET park_id = NULL, cash_tenths = NULL"
    )
    landing = candidate_dir / "landing"
    results = contracts.check_all(landing)
    failures = [f"{name}: {problem}" for name, problems in results.items() for problem in problems]

    with pytest.raises(PublishFailed) as raised:
        publish_contracts.check_contracts(candidate_dir)

    detail = raised.value.detail
    assert len(failures) >= 2
    assert "\n" not in detail
    assert all(failure in detail for failure in failures)


def test_registry_feed_empty_fails_naming_the_folder(tmp_path: Path) -> None:
    """A candidate whose feed copy holds no delivery file is refused."""
    candidate_dir = write_candidate(tmp_path, feed=False)
    feed_v1 = candidate_dir / "landing" / "registry" / "v1"
    feed_v1.mkdir(parents=True)

    with pytest.raises(PublishFailed) as raised:
        publish_contracts.check_contracts(candidate_dir)

    assert raised.value.reason == "contracts"
    assert str(feed_v1) in raised.value.detail


def test_registry_feed_bad_file_fails_naming_the_file(tmp_path: Path) -> None:
    """A delivery file that breaks the feed contract is refused and named."""
    candidate_dir = write_candidate(tmp_path)
    feed_v1 = candidate_dir / "landing" / "registry" / "v1"
    bad = feed_v1 / "park_registry_2026-10-11_01.csv"
    bad.write_text(
        "park_id,company_start_year,game_year_origin,data_set,note,delivered_on\n"
        ",2000,9,rehearsal,,2026-10-11\n",
        encoding="utf-8",
    )

    with pytest.raises(PublishFailed) as raised:
        publish_contracts.check_contracts(candidate_dir)

    assert raised.value.reason == "contracts"
    assert bad.name in raised.value.detail
