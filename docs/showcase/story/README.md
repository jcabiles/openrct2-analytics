# Story drafts for the showcase website and the README

**This folder holds ten files: this index and nine story pages showing a theme-park video game run as a small company, and how its numbers are checked.** The setup is called Theme Park Enterprise: one company runs several parks and reports them as one business. The showcase page renders its words from named passages in these files (each starts at a `passage` marker); the repo's front-page README is built from them once approved.

- [The game](/docs/showcase/story/the-game.md): the page's hero, top menu and footer passages.
- [The company and its timeline](/docs/showcase/story/the-company-timeline.md): four rules and a calendar starting 1 March 2000.
- [The analytics strategy](/docs/showcase/story/the-analytics-strategy.md): what the company must know, and why.
- [The stack](/docs/showcase/story/the-stack.md): how a game event becomes a checked number.
- [Install by hand](/docs/showcase/story/install-by-hand.md): the words of the player guide's install section.
- [How the game works](/docs/showcase/story/how-the-game-works.md): the words of the player guide's "how a play works" section.
- [Fix a problem](/docs/showcase/story/fix-a-problem.md): the player guide's help page: what an on-screen message means and what to do.
- [Guide site labels](/docs/showcase/story/guide-site-labels.md): the few labels only the site's guide page uses: the page title and navigation links.
- [How this was built](/docs/showcase/story/how-this-was-built.md): who did what, with two real corrections.

## How to read the numbers

Four clocks: game day (one in-game day), company date (the company calendar, from 1 March 2000), company year (one game season, March to October) and real elapsed time (one company year is about 55 minutes of play (docs/FINDINGS.md)). Each business number names its unit, clock and sample, and says "observational" (a pattern, not proof of cause). An unmeasured number is a placeholder.

## Run it yourself

Planned, not yet built: one command, `make site`, will build the pipeline and website from the repo's practice data.
