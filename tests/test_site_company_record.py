"""Case 22 of the company site command: the sample-record guard."""
# WEAKENED-OK: tests/test_site_company_guard.py is removed with the sentence guard;
# its cases are replaced by this file's record-guard cases (spec case 22).

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from openrct2_analytics.ingest import site_company
from openrct2_analytics.showcase import export
from tests.test_site_company import (
    BUILT_WITHOUT_SAMPLE,
    Build,
    _never_built,
    _no_stage,
    _outputs,
    _project,
    _reach_landing,
    _run,
    _write_outputs,
    _writes,
)

COMMITTED = "site/_data/sample.json"
COMPANY_ROW = {"data_set": "company", "parks": 2, "sessions": 5, "player_played": True}


def _record(row: dict[str, object]) -> str:
    return json.dumps({"name": "sample", "columns": list(row), "rows": [row]})


def _staged(monkeypatch: pytest.MonkeyPatch, change: Callable[[Path], object]) -> None:
    """Let the real export run, then change the staged export folder once, before any build."""
    real_run = export.run

    def run(
        mode: str, warehouse: Path, entries: list[export.Entry], served: Path, *, data_set: str
    ) -> None:
        real_run(mode, warehouse, entries, served, data_set=data_set)
        change(served)

    monkeypatch.setattr(export, "run", run)


def _refused(project: Path, build: Build, capsys: pytest.CaptureFixture[str], detail: str) -> None:
    before = _outputs(project)
    assert _run(project, build) == 2
    assert capsys.readouterr().out.strip().splitlines()[-1] == (
        f"site-company refused: sample-record: {detail}. Nothing was changed."
    )
    assert _outputs(project) == before
    _no_stage(project)


def test_equal_counts_to_the_committed_record_are_refused_and_nothing_lands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write_outputs(project)
    (project / COMMITTED).write_text(_record({**COMPANY_ROW, "data_set": "sample"}))

    _refused(
        project,
        _never_built,
        capsys,
        "the staged sample.json holds the same parks, sessions and player_played as the "
        "committed site/_data/sample.json, so the page would state the committed sample, "
        "not the company data",
    )


def test_a_differing_record_passes_the_guard_and_lands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _reach_landing(monkeypatch)

    assert _run(project, _writes(BUILT_WITHOUT_SAMPLE)) == 0

    assert capsys.readouterr().out.strip().splitlines()[-1] == (
        "site-company: exported 8 files from warehouse/company.duckdb to local/site-data/; "
        "built site/_site/"
    )
    assert (project / "site" / "_site" / "index.html").read_text() == BUILT_WITHOUT_SAMPLE


@pytest.mark.parametrize(
    "committed",
    [
        {"data_set": "sample", "parks": 1, "sessions": 5, "player_played": True},
        {"data_set": "sample", "parks": 2, "sessions": 3, "player_played": True},
        {"data_set": "sample", "parks": 2, "sessions": 5, "player_played": False},
    ],
    ids=["parks_differ", "sessions_differ", "player_played_differs"],
)
def test_a_record_matching_on_two_fields_only_passes_the_guard(
    committed: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = _project(tmp_path)
    (project / COMMITTED).write_text(_record(committed))
    _reach_landing(monkeypatch)

    assert _run(project, _writes(BUILT_WITHOUT_SAMPLE)) == 0

    assert capsys.readouterr().out.strip().splitlines()[-1] == (
        "site-company: exported 8 files from warehouse/company.duckdb to local/site-data/; "
        "built site/_site/"
    )


def test_a_staged_record_labelled_sample_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write_outputs(project)
    _staged(
        monkeypatch,
        lambda exports: (exports / "sample.json").write_text(
            _record({**COMPANY_ROW, "data_set": "sample"})
        ),
    )

    _refused(
        project, _never_built, capsys, "the staged sample.json has data_set sample, not company"
    )


def test_a_missing_committed_record_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write_outputs(project)
    (project / COMMITTED).unlink()

    _refused(
        project,
        _never_built,
        capsys,
        "the committed site/_data/sample.json is missing",
    )


def test_a_missing_staged_record_is_refused_before_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write_outputs(project)
    _staged(monkeypatch, lambda exports: (exports / "sample.json").unlink())

    _refused(project, _never_built, capsys, "the staged sample.json is missing")


def test_a_staged_record_that_is_not_json_is_refused_before_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write_outputs(project)
    _staged(monkeypatch, lambda exports: (exports / "sample.json").write_text("{not json"))

    _refused(
        project,
        _never_built,
        capsys,
        "the staged sample.json is not a valid sample record: "
        "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
    )


def test_a_staged_record_without_a_field_is_refused_before_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write_outputs(project)
    row = {key: value for key, value in COMPANY_ROW.items() if key != "sessions"}
    _staged(monkeypatch, lambda exports: (exports / "sample.json").write_text(_record(row)))

    _refused(
        project,
        _never_built,
        capsys,
        "the staged sample.json is not a valid sample record: 'sessions'",
    )


def test_a_committed_record_that_is_not_json_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _project(tmp_path)
    _write_outputs(project)
    (project / COMMITTED).write_text("{not json")

    _refused(
        project,
        _never_built,
        capsys,
        "the committed site/_data/sample.json is not a valid sample record: "
        "Expecting property name enclosed in double quotes: line 1 column 2 (char 1)",
    )


def test_the_guard_called_directly_refuses_through_refused(tmp_path: Path) -> None:
    project = _project(tmp_path)
    exports = tmp_path / "staged"
    exports.mkdir()
    (exports / "sample.json").write_text(_record({**COMPANY_ROW, "data_set": "sample"}))

    with pytest.raises(site_company._Refused) as caught:
        site_company._sample_guard(project, exports)

    assert caught.value.reason == "sample-record"
    assert caught.value.detail == "the staged sample.json has data_set sample, not company"
