"""The public go-live command cannot yet write a marker."""

from pathlib import Path

import pytest

from openrct2_analytics.ingest.go_live import main


def test_go_live_refuses_without_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(tmp_path / "data"))
    assert main() == 2
    assert "A way around the seq stop in make pipeline" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())
