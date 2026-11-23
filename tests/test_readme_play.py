"""The README "Play it yourself" section: its place and its install link (R21, R22)."""

from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
HEADING = "## Play it yourself"
LINK = "(docs/showcase/story/install-by-hand.md)"
GAME_LINK = "[How the game works](docs/showcase/story/how-the-game-works.md)"


def _section() -> str:
    start = README.index(HEADING)
    rest = README[start + len(HEADING) :]
    end = rest.find("\n## ")
    return HEADING + (rest if end == -1 else rest[:end])


def test_play_it_yourself_heading_exists() -> None:
    assert README.count(HEADING + "\n") == 1


def test_section_follows_the_opening_before_other_headings() -> None:
    before = README[: README.index(HEADING)]
    assert before.startswith("# openrct2-analytics\n")
    assert "A portfolio analytics stack for a theme park game" in before
    headings = [line for line in before.splitlines() if line.startswith("## ")]
    assert all("reviewer" in h.lower() for h in headings)


def test_section_comes_before_how_to_run_it() -> None:
    assert README.index(HEADING) < README.index("## How to run it")


def test_section_is_at_most_twelve_lines() -> None:
    assert len(_section().strip().splitlines()) <= 12


def test_section_links_install_by_hand() -> None:
    assert "[Install by hand]" + LINK in _section()


def test_section_names_the_guide_page() -> None:
    assert "`/guide`" in _section()


def test_install_by_hand_link_target_exists() -> None:
    assert "[Install by hand]" + LINK in _section()
    target = "docs/showcase/story/install-by-hand.md"
    assert (Path(__file__).resolve().parents[1] / target).is_file()


def test_section_links_how_the_game_works() -> None:
    assert GAME_LINK in _section()
    target = "docs/showcase/story/how-the-game-works.md"
    assert (Path(__file__).resolve().parents[1] / target).is_file()


def test_launcher_block_is_a_pointer_to_the_guide_and_agents_md() -> None:
    start = README.index("**Play the company park from the Dock.**")
    block = README[start : README.index("\n\n", start)]
    assert GAME_LINK in block
    assert "`AGENTS.md`" in block
    assert len(block.splitlines()) <= 6
    assert "Where should this play count?" not in README
