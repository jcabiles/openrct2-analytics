"""The contract runner on its own folders: an empty root, a missing column, a new contract file.

The Parquet comes from ``tests.test_contracts.write_data``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from datacontract.data_contract import DataContract

from openrct2_analytics.ingest import contracts
from tests.test_contracts import write_data


def test_a_data_root_without_parquet_fails_with_one_clear_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert contracts.main(["--data-root", str(empty)]) == 1

    output = capsys.readouterr().out.strip().splitlines()
    assert len(output) == 1
    assert "No Parquet files" in output[0]
    assert "make convert" in output[0]


def test_files_are_lined_up_by_column_name_so_a_column_missing_from_one_file_counts_as_null(
    tmp_path: Path,
) -> None:
    root = write_data(tmp_path / "data", "ALTER TABLE snapshot DROP COLUMN game_day")

    assert (
        "test Check that field game_day has no missing values:"
        " failed (Actual missing_count(game_day) was 2, expected = 0)"
    ) in contracts.check_all(root)["envelope.odcs.yaml"]


def test_a_fourth_contract_needs_no_code_change(tmp_path: Path) -> None:
    root = write_data(tmp_path / "data")
    shutil.copy(root / "v1" / "park_snapshot.parquet", root / "v1" / "extra.parquet")
    contracts_dir = tmp_path / "contracts"
    shutil.copytree(contracts.CONTRACTS_DIR, contracts_dir)
    text = (contracts_dir / "park_snapshot.odcs.yaml").read_text(encoding="utf-8")
    (contracts_dir / "extra.odcs.yaml").write_text(
        text.replace("park_snapshot", "extra"), encoding="utf-8"
    )

    results = contracts.check_all(root, contracts_dir)

    assert sorted(results) == [
        "envelope.odcs.yaml",
        "extra.odcs.yaml",
        "finance_month.odcs.yaml",
        "game_action.odcs.yaml",
        "guest_arrived.odcs.yaml",
        "guest_boarded.odcs.yaml",
        "guest_left.odcs.yaml",
        "guest_refused.odcs.yaml",
        "guest_snapshot.odcs.yaml",
        "park_snapshot.odcs.yaml",
        "plugin_stats.odcs.yaml",
        "ride_snapshot.odcs.yaml",
        "save_written.odcs.yaml",
        "session_start.odcs.yaml",
        "weather_change.odcs.yaml",
    ]
    assert results["extra.odcs.yaml"] == []


def test_envelope_declares_a5_field_flags() -> None:
    contract_text = (contracts.CONTRACTS_DIR / "envelope.odcs.yaml").read_text(encoding="utf-8")
    data_contract = DataContract(data_contract_str=contract_text).get_data_contract()
    envelope = next(schema for schema in data_contract.schema_ or [] if schema.name == "envelope")
    properties = {prop.name: prop for prop in envelope.properties or []}

    assert properties["event_id"].unique is not True
    assert properties["_raw_file"].required is True
    assert properties["_raw_line"].required is True
