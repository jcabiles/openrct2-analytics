"""The game's remembered save folder: read from config.ini, merged into the watched set."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openrct2_analytics.ingest.capture_session import EXIT_PROBLEM
from openrct2_analytics.ingest.save_pairing import judge_saves, render_saves
from openrct2_analytics.ingest.save_watch import (
    NO_REMEMBERED_NOTE,
    REMEMBERED_KIND,
    SaveWatcher,
    remembered_folder,
    watch_folders,
)
from tests.test_capture import (
    READY,
    Folders,
    Game,
    Start,
    children_fixture,
    folders_fixture,
    free_port,
    game_fixture,
    play,
    start_fixture,
)
from tests.test_capture_saves import GAP, capture_run, records, session_lines
from tests.test_save_pairing import LATER, T0, at, record, row
from tests.test_save_watch import RUN_STARTED, Clock, Lines, put
from tests.test_save_watch import records as landed_records

# The shared fixtures are registered under their `name=`; listing them keeps the imports used.
__all__ = ["children_fixture", "folders_fixture", "game_fixture", "start_fixture"]

TAIL = "watching the save, autosave and user folders only."
PRIVACY = (
    " On macOS, allow the terminal under System Settings, Privacy & Security, "
    "Files and Folders (or Full Disk Access), then run the capture again."
)
IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


@pytest.fixture
def user(tmp_path: Path) -> Path:
    (tmp_path / "user" / "save" / "autosave").mkdir(parents=True)
    return tmp_path / "user"


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    folder = tmp_path / "elsewhere"
    folder.mkdir()
    return folder


def config(user: Path, text: str) -> None:
    (user / "config.ini").write_text(text, encoding="utf-8")


def named(user: Path, value: str) -> None:
    config(user, f"[general]\nlast_game_directory = {value}\n")


def put_at(path: Path, modified: datetime) -> None:
    path.write_bytes(b"placeholder bytes, not game content")
    os.utime(path, (modified.timestamp(),) * 2)


def is_case_insensitive(folder: Path) -> bool:
    (folder / "CaseProbe").mkdir()
    return (folder / "caseprobe").exists()


# --- A2: no remembered folder ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        None,
        "[display]\nx = 1\n",
        "[general]\nx = 1\n",
        '[general]\nlast_game_directory = ""\n',
        "[DEFAULT]\nlast_game_directory = /somewhere/inherited\n[general]\nx = 1\n",
    ],
    ids=["no-file", "no-section", "no-key", "empty-value", "key-only-in-default"],
)
def test_no_remembered_folder_adds_nothing_and_says_so(user: Path, text: str | None) -> None:
    if text is not None:
        config(user, text)

    assert remembered_folder(user) == (None, NO_REMEMBERED_NOTE)
    assert (f"Note: config.ini names no remembered save folder; {TAIL}") == NO_REMEMBERED_NOTE


# --- A2b: unreadable or malformed config.ini ------------------------------------------------


def unreadable_note(line: str | None, error: str) -> None:
    assert line is not None
    assert line.startswith(f"Note: config.ini could not be read ({error}: ")
    assert line.endswith(f"); {TAIL}")


def test_a_latin_1_config_is_a_note_with_the_error_name(user: Path) -> None:
    (user / "config.ini").write_bytes(b'[general]\nlast_game_directory = "caf\xe9"\n')

    folder, line = remembered_folder(user)

    assert folder is None
    unreadable_note(line, "UnicodeDecodeError")


def test_a_config_without_a_section_header_is_a_note(user: Path) -> None:
    config(user, 'last_game_directory = "/somewhere"\n')

    folder, line = remembered_folder(user)

    assert folder is None
    unreadable_note(line, "MissingSectionHeaderError")


def test_a_config_that_is_a_folder_is_a_note(user: Path) -> None:
    (user / "config.ini").mkdir()

    folder, line = remembered_folder(user)

    assert folder is None
    unreadable_note(line, "IsADirectoryError")


def test_a_config_without_read_permission_is_a_note(user: Path) -> None:
    config(user, "[general]\n")
    (user / "config.ini").chmod(0)

    folder, line = remembered_folder(user)

    assert folder is None
    if IS_ROOT:  # root reads any file, so the empty config is read and names no folder
        assert line == NO_REMEMBERED_NOTE
    else:
        unreadable_note(line, "PermissionError")


# --- A2c: not absolute ----------------------------------------------------------------------


def test_a_value_with_a_nul_character_is_a_note_and_the_defaults_stay(user: Path) -> None:
    named(user, '"/somewhere/a\x00b"')

    shown = "'/somewhere/a\\x00b'"
    assert remembered_folder(user) == (
        None,
        f"Note: config.ini's remembered save folder {shown} is not a usable path; {TAIL}",
    )


def test_a_relative_value_is_a_note_naming_it(user: Path) -> None:
    named(user, '"saves/here"')

    assert remembered_folder(user) == (
        None,
        f"Note: config.ini's remembered save folder saves/here is not an absolute path; {TAIL}",
    )


# --- A3: reading the value ------------------------------------------------------------------


def test_outer_quotes_are_stripped_and_an_unquoted_value_is_unchanged(
    user: Path, outside: Path
) -> None:
    named(user, f'"{outside}"')
    quoted, _ = remembered_folder(user)
    named(user, str(outside))
    bare, _ = remembered_folder(user)

    assert quoted == bare == outside


def test_a_percent_sign_in_the_value_is_read_without_error(user: Path, tmp_path: Path) -> None:
    odd = tmp_path / "100%saves"
    odd.mkdir()
    named(user, f'"{odd}"')

    assert remembered_folder(user)[0] == odd


def test_a_byte_order_mark_is_tolerated(user: Path, outside: Path) -> None:
    text = f'[general]\nlast_game_directory = "{outside}"\n'
    (user / "config.ini").write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))

    assert remembered_folder(user)[0] == outside


# --- A4: the same folder as a default -------------------------------------------------------


@pytest.mark.parametrize("sub", ["save", "save/autosave", ""], ids=["save", "autosave", "user"])
def test_a_default_folder_is_not_added_whatever_its_spelling(
    user: Path, tmp_path: Path, sub: str
) -> None:
    target = user / sub if sub else user
    (tmp_path / "link").symlink_to(target, target_is_directory=True)
    for spelling in (target, tmp_path / "link", user / "save" / ".." / (sub or ".") / "."):
        named(user, f'"{spelling}"')
        assert remembered_folder(user) == (None, None)


def test_a_missing_default_folder_is_not_added_whatever_its_spelling(
    user: Path, tmp_path: Path
) -> None:
    (user / "save" / "autosave").rmdir()  # not created yet: samefile fails, the paths are compared
    (tmp_path / "link").symlink_to(user, target_is_directory=True)
    for spelling in (
        user / "save" / "autosave",
        tmp_path / "link" / "save" / "autosave",
        user / "save" / ".." / "save" / "autosave",
    ):
        named(user, f'"{spelling}"')
        assert remembered_folder(user) == (None, None)


def test_a_case_variant_of_a_default_folder_is_not_added(user: Path, tmp_path: Path) -> None:
    named(user, f'"{user / "SAVE"}"')

    if is_case_insensitive(tmp_path):  # one folder under two spellings
        assert remembered_folder(user) == (None, None)
    else:  # user/SAVE is a different, missing folder inside the user folder
        assert remembered_folder(user) == (user / "SAVE", None)


def test_a_symlink_loop_is_a_note_and_the_defaults_stay(user: Path, tmp_path: Path) -> None:
    loop = tmp_path / "loop"
    loop.symlink_to(loop)
    named(user, f'"{loop}"')

    folder, line = remembered_folder(user)

    assert folder is None
    assert line is not None
    assert line.startswith(f"Note: the game's remembered save folder {loop} cannot be read (")
    assert line.endswith("); it is not watched.")


# --- A5, A6: inside and outside the user folder ---------------------------------------------


def test_a_folder_inside_the_user_folder_is_added_silently(user: Path) -> None:
    inside = user / "my saves"
    inside.mkdir()
    named(user, f'"{inside}"')

    assert remembered_folder(user) == (inside, None)


def test_a_folder_outside_the_user_folder_is_added_with_a_warning(
    user: Path, outside: Path
) -> None:
    named(user, f'"{outside}"')

    assert remembered_folder(user) == (
        outside,
        f"Warning: the game's remembered save folder {outside} is outside the OpenRCT2 user "
        "folder; watching it too.",
    )


def test_the_warning_prints_the_folder_as_config_ini_gives_it(user: Path, outside: Path) -> None:
    given = f"{outside}/"
    named(user, f'"{given}"')

    folder, line = remembered_folder(user)

    assert folder == outside
    assert line == (
        f"Warning: the game's remembered save folder {given} is outside the OpenRCT2 user "
        "folder; watching it too."
    )


def test_no_record_holds_the_remembered_path(user: Path, outside: Path, tmp_path: Path) -> None:
    named(user, f'"{outside}"')
    folders = watch_folders(user)
    folders[REMEMBERED_KIND] = outside
    landing = tmp_path / "landing"
    watcher = SaveWatcher(folders, landing, RUN_STARTED, 0.01, say=Lines(), clock=Clock(T0))
    put(outside / "Beta-main.park", 5, 1_700_000_000)
    watcher.scan()

    text = "".join(p.read_text() for p in (landing / "v1").glob("*.jsonl"))
    assert str(outside) not in text and outside.name not in text
    assert "remembered" in text


# --- A7: missing or unreadable at start -----------------------------------------------------


def test_a_missing_folder_is_kept_and_a_file_created_later_is_recorded(
    user: Path, tmp_path: Path
) -> None:
    later = tmp_path / "usb" / "saves"
    named(user, f'"{later}"')
    folder, line = remembered_folder(user)
    assert folder == later
    assert line is not None and line.startswith("Warning: ")
    folders = watch_folders(user)
    folders[REMEMBERED_KIND] = later
    landing = tmp_path / "landing"
    watcher = SaveWatcher(folders, landing, RUN_STARTED, 0.01, say=Lines(), clock=Clock(T0))
    watcher.scan()

    later.mkdir(parents=True)
    put(later / "Gamma.park", 5, 1_700_000_000)
    watcher.scan()

    [made] = landed_records(landing)
    assert (made["observation"], made["file_name"], made["folder_kind"]) == (
        "created",
        "Gamma",
        REMEMBERED_KIND,
    )


def cannot_read(user: Path, folder: Path, error: str, suffix: str) -> None:
    named(user, f'"{folder}"')
    result, line = remembered_folder(user)
    assert result is None
    assert line is not None
    assert line.startswith(
        f"Note: the game's remembered save folder {folder} cannot be read ({error}: "
    )
    assert line.endswith(f"); it is not watched.{suffix}")


def unreadable_or_root(user: Path, folder: Path) -> None:
    """Not root: the note with the macOS sentence. Root reads any folder, so the warning."""
    if not IS_ROOT:
        cannot_read(user, folder, "PermissionError", PRIVACY)
        return
    named(user, f'"{folder}"')
    assert remembered_folder(user) == (
        folder,
        f"Warning: the game's remembered save folder {folder} is outside the OpenRCT2 user "
        "folder; watching it too.",
    )


def test_a_folder_without_read_permission_is_a_note_with_the_macos_sentence(
    user: Path, outside: Path
) -> None:
    outside.chmod(0)
    try:
        unreadable_or_root(user, outside)
    finally:
        outside.chmod(0o700)


def test_a_folder_with_read_but_no_search_permission_is_a_note(user: Path, outside: Path) -> None:
    put(outside / "Hidden.park", 5, 1_700_000_000)
    outside.chmod(0o444)
    try:
        unreadable_or_root(user, outside)
    finally:
        outside.chmod(0o700)


def test_a_file_in_place_of_the_folder_is_a_note_without_the_macos_sentence(
    user: Path, tmp_path: Path
) -> None:
    afile = tmp_path / "not-a-folder"
    afile.write_text("x", encoding="utf-8")

    cannot_read(user, afile, "NotADirectoryError", "")


# --- A8: gone and back ----------------------------------------------------------------------


def test_the_remembered_folder_records_its_kind_and_prints_gone_and_back(
    user: Path, outside: Path, tmp_path: Path
) -> None:
    folders = watch_folders(user)
    folders[REMEMBERED_KIND] = outside
    say = Lines()
    landing = tmp_path / "landing"
    watcher = SaveWatcher(folders, landing, RUN_STARTED, 0.01, say=say, clock=Clock(T0))
    watcher.scan()

    outside.rmdir()
    watcher.scan()
    outside.mkdir()
    put(outside / "Delta.park", 5, 1_700_000_000)
    watcher.scan()

    assert say.lines == [
        "remembered save folder is gone; watching for it to return.",
        "remembered save folder is back.",
    ]
    [made] = landed_records(landing)
    assert made["folder_kind"] == "remembered"


# --- A9: end to end -------------------------------------------------------------------------


def test_a_save_in_the_remembered_folder_pairs_and_the_warning_comes_first(
    folders: Folders, start: Start, game: Callable[[], Game], tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    named(folders.user, f'"{elsewhere}"')
    emitted = datetime.now(UTC)

    def save_there() -> None:
        put_at(elsewhere / "quicksave.park", emitted + GAP)

    command = capture_run(start, game, session_lines("one", emitted), while_playing=save_there)

    assert command.finish() == 0, command.output
    out = command.output
    assert out.index("is outside the OpenRCT2 user folder") < out.index("Open OpenRCT2 now")
    assert "quicksave (remembered): save_id one-save" in out
    assert {r["folder_kind"] for r in records(folders)} == {"remembered"}


def test_an_error_in_the_remembered_folder_after_start_fails_the_capture(
    folders: Folders, start: Start, game: Callable[[], Game], tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    named(folders.user, f'"{elsewhere}"')
    port = free_port()
    command = start(port)
    command.wait_for(READY)
    running = game()
    command.wait_for("game seen")
    elsewhere.rmdir()  # the first scan was clean; a file in its place makes listing raise
    elsewhere.write_text("not a folder", encoding="utf-8")  # NotADirectoryError, even as root
    command.wait_for("Save-file watcher stopped at")
    play(port, session_lines("one"))
    command.wait_for("events arriving")
    running.quit()
    code = command.finish()

    assert code == EXIT_PROBLEM, command.output
    assert "capture failure: watcher error at" in command.output


# --- A17: the report for a remembered record ------------------------------------------------


def test_the_pair_line_and_main_history_lines_read_the_same_for_remembered() -> None:
    pair = render_saves(
        judge_saves(
            [record(at(1), "mine", kind=REMEMBERED_KIND)],
            [row(at(0), save_id="sv7", park="pk9")],
            T0,
            unreadable=[],
            watcher_error=None,
        )
    )
    assert "mine (remembered): save_id sv7, park_id pk9" in pair

    old = record(at(1), "me-main", kind=REMEMBERED_KIND, run=T0)
    start = record(at(5000, LATER), "me-main", obs="start", kind=REMEMBERED_KIND, run=LATER)
    j = judge_saves(
        [old, start], [row(at(0), "old", "so")], LATER, unreadable=[], watcher_error=None
    )
    assert j.main_lines == (
        "warning: me-main changed since its last paired write at "
        "2026-10-19T12:00:01+00:00; that play was not captured",
    )


# --- A18: the same name in two folders ------------------------------------------------------


def test_one_name_in_the_remembered_and_another_folder_is_a_two_candidate_window(
    folders: Folders, start: Start, game: Callable[[], Game], tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    named(folders.user, f'"{elsewhere}"')
    emitted = datetime.now(UTC)

    def both() -> None:
        for folder in (elsewhere, folders.user / "save"):
            put_at(folder / "twin.park", emitted + GAP)

    command = capture_run(start, game, session_lines("one", emitted), while_playing=both)

    assert command.finish() == EXIT_PROBLEM, command.output
    assert "two-candidate window" in command.output
