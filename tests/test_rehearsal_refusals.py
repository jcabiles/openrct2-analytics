"""The rehearsal capture's refusals (spec R3): each returns 2 from ``main`` and writes nothing.

One test per refusal item, in R3 order.
"""

from __future__ import annotations

import dataclasses
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from openrct2_analytics.ingest.game_check import GameCheck
from openrct2_analytics.ingest.rehearsal_capture import main
from openrct2_analytics.ingest.rehearsal_chain import attempt_name
from tests.test_bench_run import REPO_ROOT
from tests.test_convert import tree
from tests.test_rehearsal_capture import AUTOSAVE_TIME, RehearsalHarness

NOTHING = "Nothing was written."


def assert_refused(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str], match: str, **changes: object
) -> None:
    """``main`` returns 2 with one refusal line ending NOTHING, and nothing was written."""
    code = main(
        ["--data-set", "rehearsal"], options=rh.options(**changes), build=lambda: rh.bench.plugin
    )
    assert code == 2

    out = capsys.readouterr().out
    assert match in out and out.endswith(f"{NOTHING}\n"), out
    for private in [*rh.bench.private_texts(), str(rh.park2), str(rh.data_root)]:
        assert private not in out
    assert "--any-park" not in out
    assert not rh.bench.bench_dir.exists()
    assert not (rh.data_root / "rehearsal").exists()
    assert rh.bench.launches() == []  # the stand-in at most answered --version
    rh.assert_protected()


# ---- item 1: the data set ----


def test_item_1_a_missing_data_set_prints_the_missing_data_set_line(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rh.main([]) == 2

    captured = capsys.readouterr()
    assert captured.err == (
        "Name a data set (rehearsal and company), for example: "
        "make capture-rehearsal DATA_SET=rehearsal. Nothing was changed.\n"
    )
    assert not rh.bench.bench_dir.exists() and not rh.data_root.exists()
    rh.assert_protected()


def test_item_1_the_company_data_set_is_refused(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    assert rh.main(["--data-set", "company"]) == 2

    err = capsys.readouterr().err
    assert "writes only rehearsal data" in err and err.endswith("Nothing was changed.\n")
    assert not rh.bench.bench_dir.exists() and not rh.data_root.exists()
    rh.assert_protected()


# ---- item 2: the settings ----


@pytest.mark.parametrize(
    "name", ["OPENRCT2_BINARY", "OPENRCT2_BENCH_PARK", "OPENRCT2_GAME_PATH", "OPENRCT2_BENCH_DIR"]
)
def test_item_2_an_empty_setting_refuses(
    rh: RehearsalHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    name: str,
) -> None:
    monkeypatch.setenv(name, "")  # a ConfigError from the settings loader

    assert_refused(rh, capsys, f"Environment variable {name} must not be empty")


def test_item_2_a_missing_game_path_refuses(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENRCT2_GAME_PATH")

    assert_refused(
        rh, capsys, "OPENRCT2_GAME_PATH is not set and was not found in OpenRCT2's own settings."
    )


def test_item_2_a_work_folder_inside_the_players_folder_refuses(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_BENCH_DIR", str(rh.bench.user_dir / "bench"))

    assert_refused(rh, capsys, "must not be the same folder or inside one another")
    assert not (rh.bench.user_dir / "bench").exists()


def test_item_2_an_unset_park2_setting_refuses_naming_it_with_no_any_park_hint(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENRCT2_REHEARSAL_PARK2")

    assert_refused(rh, capsys, "OPENRCT2_REHEARSAL_PARK2 is not set.")


def test_item_2_an_empty_park2_setting_refuses(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_REHEARSAL_PARK2", " ")

    assert_refused(rh, capsys, "Environment variable OPENRCT2_REHEARSAL_PARK2 must not be empty")


def test_item_2_a_park2_setting_naming_a_folder_refuses(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENRCT2_REHEARSAL_PARK2", str(rh.park2.parent))

    assert_refused(rh, capsys, "OPENRCT2_REHEARSAL_PARK2 does not name a file.")


def snapshot(rh: RehearsalHarness) -> dict[Path, bytes | None]:
    """The temp tree, less the stand-in game's own log of the ``--version`` calls it answered."""
    return {p: b for p, b in tree(rh.bench.root).items() if "standin" not in p.parts}


def build_not_reached() -> Path:
    """A refusal before item 11 must stop the run; reaching the build fails the test at once."""
    raise AssertionError("the run got past its refusals to the plugin build")


def refuse_unchanged(
    rh: RehearsalHarness,
    capsys: pytest.CaptureFixture[str],
    match: str,
    *,
    game_check: GameCheck | None = None,
    project_dir: Path = REPO_ROOT,
    **changes: object,
) -> None:
    """``main`` returns 2 with ``match`` in a refusal ending NOTHING; the temp tree is as it was.

    Unlike ``assert_refused`` this allows a folder that exists beforehand (a leftover) and
    checks the whole temp tree, the work and rehearsal folders included.
    """
    before = snapshot(rh)
    options = rh.options(**changes)
    if game_check is not None:
        options = dataclasses.replace(options, game_check=game_check)
    code = main(
        ["--data-set", "rehearsal"],
        options=options,
        build=build_not_reached,
        project_dir=project_dir,
    )
    assert code == 2

    out = capsys.readouterr().out
    assert match in out and out.endswith(f"{NOTHING}\n"), out
    for private in [*rh.bench.private_texts(), str(rh.park2), str(rh.data_root)]:
        assert private not in out
    assert "--any-park" not in out
    assert snapshot(rh) == before
    assert rh.bench.launches() == []
    assert rh.protected_state() == rh.protected


# ---- item 3: protected folders ----

OVERLAPS = ["equal", "contains", "inside"]


def overlapping(folder: Path, how: str) -> Path:
    return {"equal": folder, "contains": folder.parent, "inside": folder / "sub"}[how]


@pytest.mark.parametrize("how", OVERLAPS)
@pytest.mark.parametrize("guarded", ["user", "fixture", "park2"])
@pytest.mark.parametrize("variable", ["OPENRCT2_BENCH_DIR", "OPENRCT2_DATA_DIR"])
def test_item_3_rule_a_a_protected_folder_overlap_refuses(
    rh: RehearsalHarness,
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    guarded: str,
    how: str,
) -> None:
    folder = {
        "user": rh.bench.user_dir,
        "fixture": rh.bench.fixture.parent,
        "park2": rh.park2.parent,
    }[guarded]
    path = overlapping(folder, how)
    monkeypatch.setenv(variable, str(path))
    user = rh.bench.user_dir
    # Item 2 refuses a work folder that overlaps the player's folder before item 3 is reached.
    item_2 = variable == "OPENRCT2_BENCH_DIR" and (
        path.is_relative_to(user) or user.is_relative_to(path)
    )
    match = "must not be the same folder or inside" if item_2 else "equals, contains or"

    refuse_unchanged(rh, capsys, match)


@pytest.mark.parametrize("how", ["equal", "inside"])
@pytest.mark.parametrize("protected", ["sample", "company"])
@pytest.mark.parametrize("variable", ["OPENRCT2_BENCH_DIR", "OPENRCT2_DATA_DIR"])
def test_item_3_rule_b_data_sample_and_data_company_refuse(
    rh: RehearsalHarness,
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
    protected: str,
    how: str,
) -> None:
    folder = REPO_ROOT / "data" / protected
    monkeypatch.setenv(variable, str(overlapping(folder, how)))

    refuse_unchanged(rh, capsys, f"data/{protected}/. {NOTHING}")


def test_item_3_the_default_data_root_passes_rule_b(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("OPENRCT2_DATA_DIR")
    project = temp_project(rh.bench.root / "project")
    rh.bench.fixture.write_bytes(b"another park")  # item 7 refuses; item 3 did not

    refuse_unchanged(
        rh, capsys, "OPENRCT2_BENCH_PARK is not the benchmark park", project_dir=project
    )


def temp_project(project: Path) -> Path:
    """A project folder holding the two folders rule (b) guards."""
    (project / "plugin" / "src").mkdir(parents=True)
    (project / "data" / "company").mkdir(parents=True)
    return project


@pytest.mark.parametrize("where", ["park2", "user"])
def test_item_3_a_project_folder_inside_a_protected_folder_refuses(
    rh: RehearsalHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    where: str,
) -> None:
    # The default data root is <project>/data, so a project inside a protected folder must refuse.
    monkeypatch.delenv("OPENRCT2_DATA_DIR")
    project = temp_project((rh.park2.parent if where == "park2" else rh.bench.user_dir) / "project")
    rh.bench.fixture.write_bytes(b"another park")  # item 7 refuses if item 3 misses the overlap

    refuse_unchanged(rh, capsys, "equals, contains or lies inside", project_dir=project)


@pytest.mark.parametrize("variable", ["OPENRCT2_DATA_DIR", "OPENRCT2_BENCH_DIR"])
def test_item_3_a_folder_inside_the_plugin_source_refuses(
    rh: RehearsalHarness,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    variable: str,
) -> None:
    repo = temp_project(rh.bench.root / "repo")
    monkeypatch.setenv(variable, str(repo / "plugin" / "src" / "x"))

    refuse_unchanged(rh, capsys, "equals or lies inside plugin/src/. ", project_dir=repo)
    assert list((repo / "plugin" / "src").iterdir()) == []


def test_item_3_a_data_root_inside_the_rehearsal_parquet_folder_refuses(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = temp_project(rh.bench.root / "repo")
    monkeypatch.setenv("OPENRCT2_DATA_DIR", str(repo / "data" / "rehearsal" / "parquet" / "x"))

    refuse_unchanged(
        rh, capsys, "equals or lies inside data/rehearsal/parquet/. ", project_dir=repo
    )
    assert not (repo / "data" / "rehearsal").exists()


def test_item_3_a_rehearsal_folder_linked_into_the_players_folder_refuses(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captures = rh.bench.user_dir / "captures"
    captures.mkdir()
    rh.data_root.mkdir()
    (rh.data_root / "rehearsal").symlink_to(captures)

    refuse_unchanged(
        rh, capsys, "The landing folder data/rehearsal/ equals, contains or lies inside"
    )
    assert list(captures.iterdir()) == []


def test_item_3_a_raw_folder_linked_under_company_data_refuses(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = temp_project(rh.bench.root / "repo")
    stash = repo / "data" / "company" / "stash"
    stash.mkdir()
    (rh.data_root / "rehearsal").mkdir(parents=True)
    (rh.data_root / "rehearsal" / "raw").symlink_to(stash)

    refuse_unchanged(
        rh, capsys, "data/rehearsal/raw/ equals or lies inside data/company/. ", project_dir=repo
    )
    assert list(stash.iterdir()) == []


def test_item_3_a_registry_folder_linked_to_the_park2_save_folder_refuses(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (rh.data_root / "rehearsal").mkdir(parents=True)
    (rh.data_root / "rehearsal" / "registry").symlink_to(rh.park2.parent)

    refuse_unchanged(rh, capsys, "data/rehearsal/registry/ equals, contains or lies inside")


def test_item_3_a_link_to_an_unprotected_folder_passes(
    rh: RehearsalHarness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    elsewhere = rh.bench.root / "other-drive"
    elsewhere.mkdir()
    (rh.data_root).mkdir()
    (rh.data_root / "rehearsal").symlink_to(elsewhere)
    rh.bench.fixture.write_bytes(b"another park")  # item 7 refuses; item 3 did not

    refuse_unchanged(rh, capsys, "OPENRCT2_BENCH_PARK is not the benchmark park")


# ---- items 4 and 5: the landing folders ----


def test_item_4_a_parquet_folder_that_aliases_the_raw_folder_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    (rh.data_root / "rehearsal" / "raw").mkdir(parents=True)
    (rh.data_root / "rehearsal" / "parquet").symlink_to(rh.data_root / "rehearsal" / "raw")

    refuse_unchanged(rh, capsys, "resolve to, or nest inside, another landing folder")


def test_item_4_a_rehearsal_folder_that_aliases_the_company_folder_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    (rh.data_root / "company" / "raw").mkdir(parents=True)
    (rh.data_root / "rehearsal").symlink_to(rh.data_root / "company")

    refuse_unchanged(rh, capsys, "resolve to, or nest inside, another landing folder")


def test_item_5_a_non_empty_raw_folder_refuses_naming_the_recovery(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    (rh.data_root / "rehearsal" / "raw" / "v1").mkdir(parents=True)

    refuse_unchanged(rh, capsys, "(under OPENRCT2_DATA_DIR when set) aside by hand")


def test_item_5_a_non_empty_registry_folder_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    feed = rh.data_root / "rehearsal" / "registry" / "v1"
    feed.mkdir(parents=True)
    (feed / "parks.csv").write_text("x", encoding="utf-8")

    refuse_unchanged(rh, capsys, "raw/ or registry/v1/ already holds files")


def test_item_5_a_present_parquet_lock_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    (rh.data_root / "rehearsal").mkdir(parents=True)
    (rh.data_root / "rehearsal" / "parquet.lock").write_text("", encoding="utf-8")

    refuse_unchanged(rh, capsys, "A parquet.lock is present")


def test_item_5_a_leftover_incoming_name_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    (rh.data_root / "rehearsal" / "raw" / ".incoming-v1").mkdir(parents=True)

    refuse_unchanged(rh, capsys, "(under OPENRCT2_DATA_DIR when set) aside by hand")


# ---- item 6: the work folder ----


def test_item_6_a_leftover_reserved_folder_refuses(
    rh: RehearsalHarness, capsys: pytest.CaptureFixture[str]
) -> None:
    (rh.bench.bench_dir / attempt_name(1, 1)).mkdir(parents=True)

    refuse_unchanged(rh, capsys, f"already holds {attempt_name(1, 1)} from an earlier run")


@contextmanager
def held(port: int, host: str) -> Iterator[None]:
    with socket.socket() as busy:
        busy.bind((host, port))
        busy.listen()
        yield


class FakeTime:
    """A clock that only the fake sleep moves; it starts an hour after the player's autosave."""

    def __init__(self) -> None:
        self.now = AUTOSAVE_TIME + 3600.0  # item 9's autosave age check passes first
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds
