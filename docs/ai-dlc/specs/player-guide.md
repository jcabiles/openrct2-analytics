# Spec: player guide page

status: draft, revised after its first review (a Sonnet refuter and Codex Sol); every ruling of
`docs/ai-dlc/ledger/player-guide.md` is applied (section 13)

**Bottom line.** The public site gains a second page, `/guide`, built with the site. It teaches a non-technical gamer
to install the tools by hand on a Mac, one command per step, each with what the player should see and the fix for its
common failures, and it explains how Theme Park Enterprise works: several parks on one company calendar, Company or
Sandbox, filing, and autopilot. Its words live in two new passage files under `docs/showcase/story/`; the "how the game
works" file is the one the two later site sections will share. A page check covers the guide, and a test pins every
code span on the guide to the code that prints it, so a later rewording fails `make check` instead of drifting. The
README gains a short "Play it yourself" section below its reviewer-facing opening. The install half builds now; the
"how the game works" words and the blind test by a fresh Opus and a fresh Sol reader wait until six in-flight slices
that change launcher or filing text are merged or parked. One point needs the project owner, and it stops the slice
before its pull request, not before its build: the README cannot link the page itself until the site has a public
address (section 12).

Source names used below:
- **roadmap** is `docs/ai-dlc/roadmap/park-company.md` at `0e0c3261`, cited by line (the item is lines 273-280; its
  pass/fail is line 275; the run rules are lines 174-179; the format is line 198).
- **map** is the contract map, `docs/ai-dlc/contracts/player-guide.md`, cited by section.
- **novice test** is `docs/ai-dlc/novice-test.md`.
- **ledger** is `docs/ai-dlc/ledger/player-guide.md`, the adjudicated review findings, cited by row ID.
- **preflight** is the run's authorizations of 2026-11-19: "spec + build (auto-build; format chosen 2026-11-18)";
  website content items and final copy are out of scope (roadmap :179) but the guide page is in scope as its own item;
  owner-only checks (a real play, a real autopilot start, a play from the app icon, a browser look) never become a
  ledger row and never hold a merge, and go to one morning list in `waiting-on-owner.md`; a spec finished unattended
  proceeds under auto-build rules, and anything needing the project owner parks that slice.
- **run rules** are the director's rules for this draft (2026-11-19): pin every quoted player-visible string; build the
  stable half now and the blind test last; reuse the novice test's persona and count method.

## Goal

The roadmap format (roadmap :198) and pass/fail (roadmap :275), verbatim. Section 10 says which clauses this slice
delivers and which wait.

> Its format was chosen on 2026-11-18 (an HTML guide page on the site, one shared passage file with the two site
> sections, step-by-step install with fixes, a blind test by a fresh Opus and a fresh Sol reader); the run specifies and
> builds it.

> a guide page (HTML, at /guide on the public site, built with the site and passing its page check) explains installing
> the tools by hand and how Theme Park Enterprise works (several parks on one company calendar, Company or Sandbox,
> filing, autopilot); the "how the game works" words live in one shared passage file that "'How a play works' section
> on the site" and "Explain the Theme Park Enterprise setup on the site" also use; the install steps give each command,
> what the player should see after it, and the fix for each common failure; the README gains a short "Play it
> yourself" section that links to the page and keeps its reviewer path first; a fresh Claude Opus reader and a fresh
> Codex Sol reader, each playing the non-technical gamer of docs/ai-dlc/novice-test.md, install and explain the game
> from the page alone, and a dated docs/FINDINGS.md row records what each got stuck on.

Problem served: since the installer moved after v1, a player who gets the tools has no written path to install them,
and nothing in one place explains the company game (roadmap :273; :162, :164). Outcome served: (a) and (b) of the
block (roadmap :204); the measure is outcome (b), the "setup or rules themselves" count, baseline 8 on Claude Sonnet and
5 on Codex Sol (novice test, "Baseline"). Both observational.

## 1. Requirements

Each requirement names its source. "Check" means the acceptance criteria in section 9 and the tickets.

### 1.1 The page

- **R1. The guide is a built page at `/guide`.** A new template `site/guide.njk` with `permalink: guide/index.html`
  makes `npm run site:build` write `guide/index.html` beside `index.html`. (roadmap :275 "HTML, at /guide ... built with
  the site"; map TOP 5 item 4.)
- **R2. Static and read-only.** The page loads no script and holds no form or form control (`form`, `input`,
  `select`, `textarea`, `button`) and no data export; it shows no business figure, no figure region (`data-figure`)
  and no dollar amount, where a dollar amount is a dollar sign followed by a digit (`\$\s*\d`); years such as
  "1 March 2000" are allowed. (roadmap :280 "static page and adds no app behaviour"; :202 "nothing published shows an
  invented business figure"; ledger S8, R11.)
- **R3. No game images.** The page holds no `img`, `picture` or `video` element. (Never break rule 5: no game
  screenshots or video frames committed.)
- **R4. All words come from passages.** Every sentence on the page renders from a passage in
  `docs/showcase/story/` through the existing `passage` shortcode; `site/guide.njk` holds markup and labels of at most
  three words, as `tests/test_site_text_sources.py` already enforces for every `.njk` under `site/` (its docstring,
  lines 1-8). (map TOP 5 item 4; repo rule in that test.)
- **R5. Links are relative.** Every `href` and `src` on the guide is relative (`../`, `../assets/...`, `#id`). Web
  addresses the player needs (Homebrew's install page, the project's GitHub page) are shown as copyable text in a code
  span, never as a link. (map TOP 5 item 1; `page_check.py:198-200`; choice C2.)
- **R6. The guide links back to the home page** with a relative link (`../`). The home page is not edited, so it does
  not link to the guide in this slice (choice C5).

### 1.2 The install steps

- **R7. What must be true first, then twelve steps in a fixed order.** Before the first step, the page says what must
  already be true: a Mac; OpenRCT2 0.5.6 installed and opened once (README.md:16); the player's own RollerCoaster Tycoon
  2 game files, which OpenRCT2 asks for on its first start and records as `game_path` (`docs/FINDINGS.md:664`;
  AGENTS.md "Game settings"); and how to open Terminal. The steps are, in this order, each with its step ID (ledger
  S11+R8; the ten-command list of the novice test, "Measure (a) baseline", is the measure, not the recipe):

  | # | Step ID | What the step does | Command (copied whole) |
  |---|---|---|---|
  | 1 | `step-dev-tools` | Apple's developer tools (git and make) | `xcode-select --install` |
  | 2 | `step-homebrew` | Homebrew | the one-line install command shown on Homebrew's home page, `brew.sh` |
  | 3 | `step-homebrew-path` | Homebrew's PATH line (Apple silicon) | the "Next steps" line the Homebrew installer prints, which adds `brew shellenv` to `~/.zprofile` |
  | 4 | `step-tools` | Node 24, direnv and uv | `brew install node@24 direnv uv` |
  | 5 | `step-node-path` | Node 24's PATH line (`node@24` is keg-only) | the line Homebrew prints for `node@24`, which adds its `bin` folder to `~/.zshrc` |
  | 6 | `step-direnv-hook` | direnv's shell line | `echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc` |
  | 7 | `step-check-tools` | open a new Terminal window, then check the versions | `node --version && uv --version && direnv version` |
  | 8 | `step-clone` | get the project folder (R11) | `git clone`, a space, then the pasted address |
  | 9 | `step-cd` | go into it | `cd openrct2-analytics` |
  | 10 | `step-setup` | set up the project | `make setup` |
  | 11 | `step-direnv-allow` | trust the folder | `direnv allow` |
  | 12 | `step-launcher` | build the app | `make launcher` |

  The exact text of rows 2, 3 and 5 is what the tool prints on the day PG-T2 is built; each is pinned as an outside
  row (R17) and checked in the clean-Mac dry run (R31). (roadmap :275 "installing the tools by hand"; :162, :164.)
- **R8. Each step has three parts.** Each step is one `section class="guide-step"` whose `id` is its step ID, holding
  exactly one `.step-command` (one non-empty `<code>` element, the command to copy whole), exactly one non-empty
  `.step-see` (what the player should see after it) and at least one non-empty `.step-fix` (a common failure, in the
  words the player sees, and its fix). (roadmap :275 "give each command, what the player should see after it, and the
  fix for each common failure"; ledger S8.)
- **R9. Facts, expected output and fixes come from the code that produces them.** The steps state:
  - Node 24 is the version CI uses (`.github/workflows/ci.yml:27`, `node-version: "24"`), installed by
    `brew install node@24`; step 7's "see" part shows `node --version` printing a line that starts `v24`. (ledger R7.)
  - Python 3.12 is installed by uv during `make setup`, from `.python-version`; the player installs no Python.
  - Step 10's "see" part is the healthy doctor line, `doctor: the Python environment is whole.`
    (`scripts/doctor.py:226`). Its fixes: a setup error before doctor runs (`python3.12: command not found` means uv is
    missing, because the Makefile then falls back to `python3.12`; `make: npm: No such file or directory` means npm is
    missing; `command not found: make` means make is missing; each sends the player back to the step that installs
    that tool), and the damage line
    `doctor: the Python environment is damaged.` (`scripts/doctor.py:222`), whose only fix is the repair doctor prints,
    `rm -rf .venv && make setup` (`scripts/doctor.py:27`), run inside the project folder. The repair appears nowhere
    else on the page. (ledger S11+R8.)
  - Step 12 says the app is "OpenRCT2 Enterprise" in `~/Applications` (`Makefile:254`, `:259`) and that moving the
    project folder needs `make launcher` again (AGENTS.md `make launcher`).
  - Required fixes, each on the step where it happens: missing game files (the "before you start" passage: OpenRCT2
    cannot find RollerCoaster Tycoon 2, so point it at the player's own game files); a missing tool
    (`command not found` after steps 4 to 7: open a new window, or redo the PATH or shell line); an untrusted folder
    (direnv's "blocked" message for `.envrc`, fixed by step 11); a setup error before doctor runs (step 10). (ledger
    S11+R8.)
- **R10. Commands are copyable as written.** The project folder is `openrct2-analytics`, the public repository name
  that `git clone` creates, never a private path. No `.step-command` holds a `<` placeholder. A placeholder such as
  `<id>` appears only inside a code span, because outside one the Markdown renderer
  (`site/eleventy.config.mjs:52-63`) passes it through as an HTML tag and the word vanishes. (ledger S3+R1; Never
  break rule 5.)
- **R11. The clone step needs no address in committed text.** The step reads: open the project's GitHub page (the link
  you were sent), click the green Code button, copy the HTTPS address, type `git clone`, a space, paste, press Return.
  Its fix covers `Repository not found` and `Authentication failed`: the project is not public yet, so ask the person
  who sent the link for access. No account name is committed. (ledger R2.)

### 1.3 How the game works (the shared passage file)

- **R12. One shared passage file.** The "how the game works" words live in one new file,
  `docs/showcase/story/how-the-game-works.md`, in passages with stable topic IDs, so the two later site sections can
  render the same passages. The guide renders them; no other file of this slice restates them. (roadmap :275; :279 "the
  brainstorm chose one shared passage file for all three items"; :331.)
- **R13. It covers the four named topics with the current rules.** (roadmap :275; ledger S12.)
  - Several parks on one company calendar: the calendar starts on 1 March 2000; parks open one at a time; a park that
    joins later starts in the company year after the latest year the company's parks have played, set automatically
    (`start_year.next_start_year`, `src/openrct2_analytics/ingest/start_year.py:104-113`; ADR 0050, ADR 0051); a new
    park must start from a new game (`start_year.py:201-214`). One worked example with real years: Park 1 is played
    by hand through company years 2000, 2001 and 2002, so the next park joins in company year 2003.
  - Company or Sandbox: the launcher's question and its answers, as merged on `develop` when PG-T3 starts.
  - Filing: what happens after the game closes; the sign that a play was filed (the filing line as merged, which
    say-the-park adds); a waiting play and how to recover an unfiled play (the launcher's offer to file it first, or
    the filing command it prints); two new parks in one play; which save to load to continue a park, the newest
    `<park name>-last-plugin-save-YYYY-MM-DD.park` (README.md:91-96).
  - Autopilot: a finished company park plays one company year by itself, up to about two hours; what makes it
    available (a registered company park, not Sandbox, whose last play was recorded so its backup is proven, and a
    company year another park has already played by hand, `src/openrct2_analytics/ingest/autopilot_year.py:187-202`);
    the typed `READY` phrase on its first run.
  - Where the results show: the dashboard at `http://127.0.0.1:8780/`, five pages (Executive, Finance, Attractions,
    Pricing, Operations; ADR 0054).
- **R14. It answers the eight journey questions** of the novice test ("Journey questions for the site section's
  check"): what must be installed first, how a play starts, what Company and Sandbox mean, how to tell a play was
  filed, how to continue a park, how a second park joins and in which company year, what autopilot does and how to
  start it, where the results show. (novice test; roadmap :331, the shared file must serve that section too.)
- **R15. The autopilot phrase is quoted, never softened.** The page shows the phrase in a code span,
  `<id> is profitable and its scenario challenge is complete`, and says it is typed exactly. (roadmap :202 "the
  autopilot phrase stays"; source `src/openrct2_analytics/ingest/play_mode_feed.py:45`, `READY_SUFFIX`.)
- **R16. Launcher-dependent words are written against the merged text.** Six in-flight slices change text or flows the
  guide describes: say-the-park (a new filing line), early-park-warning (a note at filing about the previous park),
  reword-unfiled (waiting-play messages), seq-refusal ("after-play refuses a session that failed its seq audit",
  roadmap :191), park-names (park labels) and no-terminal-play (questions, warnings and failures move to dialogs,
  roadmap :301, :318). Every line the launcher prints, including its two direnv lines
  (`launcher/play-company.command:145`, `:148`), belongs to PG-T3, which starts under R30. sandbox-hide and
  dashboard-company-year change dashboard text the guide does not quote (map section 4), so nothing waits on them.
  (ledger S6; map section 4.)

### 1.4 Pinned strings

- **R17. Every code span on the guide has a pin row.** Quoted program text and commands use one markup form, the
  Markdown code span (`<code>` on the built page). A new table, `tests/guide_strings.toml`, holds one row per quoted
  string, in the shape of `tests/site_copy_figures/built.toml`: `id`, `where`, `shown` (a list of strings), and either
  `source` (the repo file whose code prints or defines the text) with `phrases` (fixed strings found in that file), or
  `outside` (the outside tool that prints it, for example `git` or the Homebrew installer). A new test,
  `tests/test_guide_strings.py`, builds the site once and fails when:
  - a `<code>` element's text on the built guide equals no row's `shown` entry (a quote without a row);
  - a `shown` entry is missing from the guide's text;
  - a `phrase` is missing from its `source`;
  - a row has both `source` and `outside`, or neither.

  Text is compared as parsed text with whitespace collapsed (entities decoded), as `tests/test_site_figures.py`
  reads its regions. The table's header comment says the fix for a red row: update the passage and the row in the
  same change (R29). (run rules; ledger S7+R3+R4, R12; map TOP 5 item 2.)
- **R18. Each row names the producer, never prose that repeats it.** (ledger S7+R3+R4.)
  - PG-T2, install rows: the healthy and damaged doctor lines and the repair (`scripts/doctor.py:226`, `:222`, `:27`);
    `make setup` and `make launcher` (the `setup:` and `launcher:` targets in `Makefile`); the app name and
    `~/Applications` (`Makefile:254`, `:259`); Node 24 (`.github/workflows/ci.yml:27`); Python 3.12
    (`.python-version`); OpenRCT2 0.5.6 (`README.md:16`, the only statement of the version until no-terminal-play's
    version check lands, when PG-T3 re-points the row to that check's code); and `outside` rows for the commands and
    messages of Apple's tools, Homebrew, direnv and git, including `Repository not found` and `Authentication failed`.
  - PG-T3, game rows: the launcher's lines and answers as merged (`launcher/play-company.command`, including the
    direnv lines at `:145`, `:148`); the filing and waiting-play lines at the code that prints them (for example
    `src/openrct2_analytics/ingest/auto_file.py`, `several_parks.py`, `unfiled.py`, as merged); the autopilot phrase
    (`play_mode_feed.py:45`); the dashboard address (`launcher/play-company.command:10-11`); the five page names (the
    `<title>` of each `src/openrct2_analytics/dashboard/app/*.html`).
  - No row's `source` is `README.md` except the OpenRCT2 version above, and no row points at `AGENTS.md`.

### 1.5 The page check

- **R19. The page check covers the guide.** A new module `src/openrct2_analytics/showcase/page_check_guide.py` checks
  `guide/index.html` of the built site, and `page_check.check_page` calls it after `check_site`, so `make check`
  (`Makefile:174-175`) checks the guide with no Makefile change. It fails when:
  - the file is missing;
  - any `src` or `href` starts with `http:`, `https:`, `//` or `/` (the home page's rule and helper,
    `page_check_site._is_remote`);
  - a relative link points to a file the built site does not hold, or to an `#id` the page does not hold; a link that
    resolves to a folder (such as `../`) is valid only when that folder holds `index.html`;
  - the page holds a `data-figure` region, a `script`, `img`, `picture` or `video` element, a form or form control
    (R2), or text matching `\$\s*\d` (R2);
  - a section in `REQUIRED_SECTIONS` is missing (`install`; from PG-T3 also `how-it-works`);
  - the `.guide-step` IDs differ from `REQUIRED_STEPS`, in order (empty in PG-T1; the twelve R7 IDs from PG-T2), or a
    step breaks R8;
  - text outside a `<code>` element holds `<` followed by a letter, or the page holds an element whose name is not an
    HTML element (a placeholder the Markdown renderer turned into a tag) (R10).

  (roadmap :275 "passing its page check"; map TOP 5 item 1; ledger S8, S3+R1, R11, S9+R14; choice C1.)
- **R20. The home-page check is unchanged.** `check_page` keeps every current rule for `index.html`; the only edit to
  `page_check.py` is the import and the call. The 500-line cap counts the lines say-the-park ticket STP-T5 adds to
  `page_check.py` (it stacks first, R20 and the tickets): `wc -l` on the branch stays at or under 500. (Delete, don't
  duplicate: the guide check reuses `_is_remote`, it does not copy it; ledger S10+R6+R10.)

### 1.6 The README

- **R21. A short "Play it yourself" section.** `README.md` gains `## Play it yourself`, at most about ten lines: who
  it is for, that the guide installs the tools by hand and explains the company game, and a link. It sits after the
  README's opening (README.md:1-9, the reviewer-facing description) and before `## How to run it`; when the reviewer
  path of roadmap item 3f lands (roadmap :381, :508), it goes above this section. (roadmap :275; choice C3.)
- **R22. The README link, a recorded partial.** No public site address exists (roadmap :398, item 27), so the section
  names the page as `/guide` on the project's site and links the guide's word files by repo path, which GitHub renders
  as readable pages: PG-T4 adds the `docs/showcase/story/install-by-hand.md` link; PG-T3, which creates
  `docs/showcase/story/how-the-game-works.md`, adds its link. This meets "links to the page" only in part; section 12
  holds the decision. Once an address is recorded, the README links the guide by its site path. (ledger S2+R9,
  S4+R5.)
- **R23. One home for player steps.** Once the guide holds the play steps (PG-T3), the README's "Play the company park
  from the Dock" block and its backup paragraph (README.md:68-98) shrink to a short pointer: `make launcher` builds the
  app, the guide explains playing, and `AGENTS.md` (`make launcher`, `make play`) keeps the full behaviour. Every
  recovery fact removed (README.md:91-98) lands in the guide (R13). (map section 5; choice C6.)
- **R24. README pins hold.** The README keeps "Python 3.12" and "Node 24" (`tests/site_copy_figures/built.toml` K10,
  README.md:16-17) and every backtick path and `make` target it names still exists (`scripts/check_docs.py`). (map
  section 3.)

### 1.7 The blind-reader test

- **R25. Two fresh readers.** One fresh Claude Opus reader and one fresh Codex Sol reader (the exact model names the
  runs report are recorded in the FINDINGS row), each with no tools and no sight of the repo, each given the persona
  brief of the novice test, first paragraph unchanged, then the visible text of the built `guide/index.html` as the
  only material. (roadmap :198, :275; run rules; choice C7.)
- **R26. What each reader does, and how it is graded.** It (a) walks the install in order, saying for each step what
  it types, what it expects to see, and where it would get stuck; (b) answers the eight journey questions (R14) from
  the page; (c) is shown one failure message taken from a `.step-fix` of the built page, chosen by the director before
  the run and recorded in the row, and says what it does; (d) says "I THINK I GET IT" with its numbered journey and
  what still confuses it; (e) answers the novice test's split question, sent unchanged. Each reader is graded pass or
  fail on four points: it finds the download (states the GitHub page, Code button, HTTPS address and `git clone` with
  the paste); it forms valid commands (every command it says it types equals that step's `.step-command`); it handles
  a common failure (its answer to (c) is that fix); it reaches a filed play from the page (it states how a play starts
  and the sign that the play was filed). The count of its "setup or rules themselves" items is measure (b), counted as
  the novice test counts it. (novice test steps 4-5; roadmap :275 "install and explain the game from the page alone";
  ledger S14.)
- **R27. A dated FINDINGS row.** `docs/FINDINGS.md` gains one row in its table format (`| Date | What was measured |
  Method | Result |`, `docs/FINDINGS.md:3-6`): the date; the guide's commit and the `develop` commit it was built
  against; each reader's model; the four grades; the install steps where each got stuck; journey answers that were
  wrong or missing; the split and the item count against the 2026-11-15 baselines (8 on Sonnet, 5 on Sol); any of
  the six R16 slices that was parked rather than merged; and "observational", with the sample (two AI readers, one
  page). A re-run adds a new row; no row is overwritten. (roadmap :275; Never break rule 7; ledger S14.)
- **R28. A failed grade is a page repair.** A failed grade or a wrong journey answer caused by the page is a finding:
  it goes back to the ticket that owns the passage (PG-T2 for install words, PG-T3 for game words), whose files a fix
  worker edits in a wave of its own; then the test re-runs with two new fresh readers. After two such fix rounds with
  a remaining failure, the slice parks. Every round's result is its own row. (preflight: "accepted blocker or major
  after two fix rounds parks that slice"; ledger S14.)

### 1.8 Upkeep and timing

- **R29. Who edits the guide when a pin turns red.** Before the guide merges into `develop`: the branch merges
  `origin/develop` at the start of every wave, and a row that turns red there is fixed before that wave's tickets
  start, by a fix worker holding the files of the ticket that owns the row (PG-T2 for install rows, PG-T3 for game
  rows). After the guide merges: the slice whose change turns a row red updates the passage and the row in the same
  change, because its own `make check` fails. (ledger R13.)
- **R30. When PG-T3 and PG-T5 run.** PG-T3 starts when each of the six R16 slices is merged into `develop` or parked
  (parked: it has a `waiting-on-owner.md` row, roadmap :177), and the branch has merged `origin/develop`. PG-T5 runs as
  soon as PG-T3 has merged into the branch, against `develop` as it is at that moment; it does not wait for a parked
  slice, and the FINDINGS row names every parked one. (ledger R13; choice C14.)
- **R31. Owner-only checks go to the morning list.** Two checks need the project owner and never hold the merge or
  become a ledger row: a dry run of the twelve steps in a new standard macOS account (it checks the outside rows,
  Homebrew's PATH lines and the `node@24` line), and a look at the built guide in a browser. Each is one entry in the
  morning list in `waiting-on-owner.md`. (preflight; ledger R7.)

## 2. Design

### 2.1 Placement plan

| Piece | Owner (file) | Code reused | Dependents | Layer |
|---|---|---|---|---|
| Guide template | new `site/guide.njk` | the `passage` shortcode (`site/eleventy.config.mjs:52-63`); `site/assets/css/tokens.css` and `base.css` | the built site; the page check | site template |
| Guide styles | new `site/assets/css/guide.css`, including the step styles (passthrough already copies `site/assets/css`, `eleventy.config.mjs:69`) | colour tokens from `tokens.css` only (`docs/CONVENTIONS.md` site row) | `site/guide.njk` | site styles |
| Install words | new `docs/showcase/story/install-by-hand.md` | the story-file shape of `docs/showcase/story/the-company-timeline.md` (bottom line, a "this file holds" line, then passages) | the guide | story passages |
| How-the-game-works words (shared) | new `docs/showcase/story/how-the-game-works.md` | same shape | the guide now; "How a play works" and "Explain the Theme Park Enterprise setup" later | story passages |
| Guide page check | new `src/openrct2_analytics/showcase/page_check_guide.py` | `page_check_site._is_remote`, `PageCheckFailed`, `_require`; an `HTMLParser` subclass as in `page_check_site._SiteParser` | `page_check.check_page`, so `make check` | showcase build checks |
| String pins | new `tests/guide_strings.toml`, `tests/test_guide_strings.py` | the `built.toml` row shape and its parsed-text reader in `tests/test_site_figures.py`; `tests/page_check_support.render_page` to build the site once | every later slice that edits a producer | tests |
| Page-check fixture | `tests/page_check_support.py` (`_site` gains a minimal valid `guide/index.html`) | its own `_site` | every test that runs the page check on a fixture site | tests |
| README section | `README.md` | none | readers; `scripts/check_docs.py` | docs |
| Doc lines | `ARCHITECTURE.md` (line 33 "one site page", line 667 `site/`), `docs/CONVENTIONS.md` (rows for `showcase/` and `site/`), `docs/showcase/story/README.md` (file index, "six files") | none | readers | docs |
| Blind test record | `docs/FINDINGS.md` (one table row) | the novice test brief and split question | the "Re-run the blind novice test" item | findings |

The guide has its own `<head>` in `site/guide.njk` (stylesheets it uses, its title from a passage) rather than a head
include shared with `site/index.njk`; see choice C8.

### 2.2 Page structure

`site/guide.njk` renders, in order: a skip link, a short header with the page title and a link home (`../`), a
bottom-line passage (what the page does and how long the install takes), `section id="install"` with the "before you
start" passage and one `.guide-step` per R7 step, then `section id="how-it-works"` (from PG-T3) rendering the shared
passages, then a short footer passage. Each passage ID is listed in the template; no prose sits in it (R4).

### 2.3 The guide page check

`check_guide(site: Path) -> None` raises `PageCheckFailed` with a message naming the rule, matching the home-page
check's message style (`page URL: ...`, `embedded rows: ...`); a step failure names the step ID. Two module constants
hold the page's shape, so a later ticket changes one line each: `REQUIRED_SECTIONS` (PG-T1 `("install",)`, PG-T3 adds
`"how-it-works"`) and `REQUIRED_STEPS` (PG-T1 `()`, PG-T2 the twelve R7 IDs in order).

## 3. Files

New: `site/guide.njk`, `site/assets/css/guide.css`, `docs/showcase/story/install-by-hand.md`,
`docs/showcase/story/how-the-game-works.md`, `src/openrct2_analytics/showcase/page_check_guide.py`,
`tests/test_showcase_page_check_guide.py`, `tests/guide_strings.toml`, `tests/test_guide_strings.py`,
`tests/test_readme_play.py`.

Changed: `src/openrct2_analytics/showcase/page_check.py` (import and one call), `tests/page_check_support.py`,
`README.md`, `ARCHITECTURE.md`, `docs/CONVENTIONS.md`, `docs/showcase/story/README.md`, `docs/FINDINGS.md`.

Not changed: `site/index.njk` and every `site/_includes/*.njk`, `site/eleventy.config.mjs`, the `Makefile`, the
launcher, any `src/openrct2_analytics/ingest/` module, `scripts/doctor.py`, any dbt model or contract. No profile
hotspot is edited.

## 4. Contracts and what regenerates

- **No data contract changes.** The guide reads no export; `site/exports.toml` and `site/_data/` are untouched.
- **New build output:** `site/_site/guide/index.html` (git-ignored). `make site-export` output is unchanged.
- **Page check contract:** a built site must hold `guide/index.html` that passes R19. The `site_company` build stamp
  still hashes `index.html` only (`ARCHITECTURE.md:545`); the guide holds no company data.
- **Pinned strings:** `tests/guide_strings.toml` is the contract between the guide and the code that prints what it
  quotes. A change to a producer fails `make check`; R29 says who updates the passage and the row.
- **Regenerates:** nothing committed. `npm run site:build` writes the guide on every build.

## 5. Test seams

- **Page check:** `tests/page_check_support.py` `_site` writes fixture HTML; `_run` calls `page_check.main`; `_html`
  and `_html_append` inject faults into `index.html`. The new guide tests add the same two fault helpers for
  `guide/index.html` inside `tests/test_showcase_page_check_guide.py` (not in `test_showcase_page_check.py`, which is
  at 499 lines). The fixture's valid guide holds every `REQUIRED_SECTIONS` section and every `REQUIRED_STEPS` step;
  the ticket that changes a constant updates the fixture and runs every fixture-based page-check suite (ledger S5).
- **Built site:** `tests/page_check_support.render_page(served, work)` builds the real `site/` into a temporary folder
  over a copy of `site/_data`; the pin test and one end-to-end guide test use it once per module.
- **Template prose:** `tests/test_site_text_sources.py` already fails on four-word text in any `.njk`; it covers
  `site/guide.njk` with no change.
- **README:** `tests/test_readme_play.py` reads `README.md`: the `## Play it yourself` heading exists; the opening
  paragraph and no other `##` heading precede it except a heading containing "reviewer"; it is at most 12 lines; it
  links `docs/showcase/story/install-by-hand.md` (PG-T4). PG-T3 adds the assertion that it also links
  `docs/showcase/story/how-the-game-works.md` (ledger S4+R5).

## 6. Golden paths

`docs/CONVENTIONS.md` and `~/.claude/rules/engineering-standards.md` outrank these.
- Story file: `docs/showcase/story/the-company-timeline.md` (bottom line, "this file holds" line, passages).
- Template rendering passages: `site/_includes/enterprise.njk` (`passage` calls in `inline`, `block` and `text`
  modes).
- Page check module: `src/openrct2_analytics/showcase/page_check_site.py` (module docstring, parser class, small
  checks raising `PageCheckFailed`).
- Page check tests: `tests/test_showcase_page_check_site.py` with `tests/page_check_support.py`.
- String pins: `tests/site_copy_figures/built.toml` and its reader in `tests/test_site_figures.py`.
- Findings row: the table rows at the top of `docs/FINDINGS.md` (lines 3-10).

## 7. Out of scope

- Editing the home page (`site/index.njk`, `site/_includes/`) or its copy, including a link to the guide (preflight;
  roadmap :179).
- The "How a play works" section and "Explain the Theme Park Enterprise setup on the site": they adopt the shared
  passages in their own roadmap items; this slice creates the file and uses it on the guide (roadmap :279, :331, :719;
  ledger S1).
- The installer, the setup checker and every after-v1 item (roadmap :162, :164, :179).
- Any change to the launcher, filing or autopilot behaviour, and rewording their strings (roadmap :280).
- A public site address or hosting (roadmap :398, item 27).
- Windows and Linux steps (roadmap :202 "macOS only").
- The "Re-run the blind novice test" item (roadmap :281); this slice's blind test is its own.

## 8. Constraints

- The repo's "Never break" rules (`AGENTS.md`) apply in full; rules 5 (no game images, no private paths) and 7 (state
  the sample, say "observational") bind this slice directly.
- No new dependency (roadmap :202); no script on the guide; the site stays a read-only portfolio (roadmap :202, :280).
- The 500-line cap of `scripts/check_file_sizes.py` (lines 26-27) applies to source files (`.py`, `.ts`, `.tsx`,
  `.css`, `.sql`, `.mjs`): `page_check.py` gains only the import and the call and stays at or under 500 lines counting
  STP-T5's lines (R20); `tests/test_showcase_page_check.py` (499) gains none. Markdown, Nunjucks and TOML files are not
  capped (ledger S15+R15).
- Committed text never names the project owner and holds no private machine path; the clone step commits no account
  name (R11).
- No test reads `data/company/`, `warehouse/*.duckdb`, `local/` or a real save.
- Every new check is seen to fail before it is relied on (engineering standards, "A check counts only after it has
  been seen to fail").

## 9. Verify by

`$BASE` is the commit the ticket's branch started from.
- `check:` `npm run --silent site:build -- --output="$TMPDIR/pg-site" && test -f "$TMPDIR/pg-site/guide/index.html"`
  (R1).
- `check:` `.venv/bin/python -m openrct2_analytics.showcase.page_check --site "$TMPDIR/pg-site" --served-dir site/_data`
  prints `showcase page: checks passed` (R2, R3, R5, R8, R10, R19).
- `check:` `env -u VIRTUAL_ENV .venv/bin/python -m pytest tests/test_showcase_page_check_guide.py tests/test_guide_strings.py tests/test_readme_play.py tests/test_site_text_sources.py tests/test_site_figures.py -q`
  passes (R4, R17-R24). The guide tests include: "1 March 2000" passes and "$12" fails (R2); a `<repo folder>`
  placeholder in prose fails and `<code>&lt;id&gt;</code>` passes (R10); a `form` fails; `../` passes only when the
  site root holds `index.html` (R19).
- `check:` deliberate breaks, each in the ticket's worktree, each seen red and then green after restoring: add
  `<a href="https://brew.sh">` to `site/guide.njk` and rebuild, and the page check fails with `page URL`; remove
  every `.guide-step` from `site/guide.njk` and rebuild, and the page check fails through the public command naming
  the first missing step; remove the only `.step-fix` of `step-cd` and rebuild, and it fails naming `step-cd`; change
  `doctor: the Python environment is whole.` in `scripts/doctor.py`, and `tests/test_guide_strings.py` fails naming
  its row; add a code span with no row to a passage and rebuild, and the same test fails naming the span (ledger
  S13).
- `check:` `git diff --name-only --diff-filter=d "$BASE" HEAD | xargs grep -nIE '/Users/|/home/|/private/|(^|[^A-Za-z])[A-Za-z]:\\'`
  prints nothing (every changed file of the ticket; ledger S15+R15).
- `judgment:` a reviewer reads the built guide and confirms every R7 step has a command, a "see" part and real fixes,
  R9's required fixes are present, the R13 topics and R14 questions are answered, and nothing contradicts `AGENTS.md`.
- `judgment:` a reviewer reads the FINDINGS row and the two reader transcripts and confirms R25-R28 were followed.

## 10. Definition of done

This slice delivers part of the roadmap item and does not tick it done (ledger S1). Clause by clause (roadmap :275,
:198):

| Clause | This slice |
|---|---|
| a guide page (HTML, at /guide, built with the site, passing its page check) | delivered (PG-T1 to PG-T3) |
| "on the public site" | waits on roadmap item 27, the public address (roadmap :398) |
| explains installing by hand and the four topics | delivered (PG-T2, PG-T3) |
| one shared passage file that the two site sections also use | partly: the file is created and used by the guide; the two site sections adopt it in their own roadmap items (roadmap :331, :335) |
| each command, what the player should see, the fix for each common failure | delivered (PG-T2) |
| a README "Play it yourself" section that links to the page and keeps its reviewer path first | partly: the section and its place are delivered (PG-T4); the link to the page waits on section 12 |
| two fresh readers install and explain from the page alone; a dated FINDINGS row | delivered (PG-T5) |

The slice's own work is done when:
- `env -u VIRTUAL_ENV make check` exits 0 on the branch with every ticket merged and `origin/develop` merged in.
- Every section 9 criterion holds.
- The FINDINGS row exists and the ledger has no open row.
- The two R31 checks are on the morning list.
- The slice then stops before its pull request until section 12 is answered.

## 11. Choices made without the project owner

Each choice follows existing repo behaviour, a house rule or a ledger ruling; a reviewer may challenge it. The earlier
choice C4 (the README link) is now section 12, N1.
- **C1. Extend the page check to the guide rather than leave the guide unchecked.** Reason: the pass/fail says
  "passing its page check", and today the check never opens `/guide` (`page_check.py:190-192`). The current checker
  requires the park-month data (`page_check.py:202-207`), so the guide gets its own module. Gain: the guide's link and
  figure rules hold in every build. Cost: one module of about 150 lines and one test file.
- **C2. Web addresses as copyable text, not links.** Reason: the page check rejects `http:`, `https:`, `//` and `/` in
  `src` and `href` (`page_check.py:198-200`; `page_check_site.py:54-56`); an allowlist would be a new rule. Gain: one
  link rule for the whole site. Cost: the player copies an address instead of clicking it.
- **C3. "Reviewer path first" means the README's opening stays first.** Reason: the README has no reviewer-path section
  today (README.md:11 is its only `##` heading); its opening (README.md:1-9) is the reviewer-facing description, and
  the 3f reviewer path is a later item (roadmap :381, :508). Gain: a player finds the section near the top. Cost: a
  reviewer passes one short section before the developer steps.
- **C5. The home page does not link to the guide in this slice.** Reason: the preflight keeps other site sections'
  copy out of scope. Gain: no conflict with the in-flight site slices. Cost: a site visitor reaches `/guide` only from
  the README or by address until a content item adds the link.
- **C6. README.md:68-98 shrinks to a pointer once the guide covers play.** Reason: delete, don't duplicate (map section
  5 and "Ownership": the launcher steps already live in `AGENTS.md`, and a guide copy would be a third). Gain: one
  home for player steps. Cost: a developer reading the README follows a link for the launcher's details.
- **C7. The blind readers read the page instead of asking questions.** Reason: the pass/fail says "from the page
  alone", while the novice test's readers learn by asking (novice test steps 1-3). The persona paragraph, the split
  question and the count are kept unchanged for comparison with the 2026-11-15 baselines. Gain: the result measures the
  page. Cost: the count is not strictly comparable with the question-and-answer baseline, which the FINDINGS row
  states.
- **C8. The guide keeps its own `<head>`.** Reason: `site/index.njk` is edited by in-flight slices (say-the-park ticket
  STP-T5, the site-sample ticket), and the guide needs different stylesheets and no scripts. Gain: no conflict with
  those slices. Cost: about eight lines of `<head>` markup that resemble the home page's.
- **C9. Two passage files, not one.** Reason: the roadmap requires one shared file for the "how the game works" words
  (:275, :279); the install steps serve only the guide. Gain: the two site sections render the shared file without
  pulling in install steps. Cost: one more story file to index.
- **C10. The shared file is new, not `the-company-timeline.md`.** Reason: the 2026-11-18 brainstorm chose one shared
  file for the three items (roadmap :279), which is later than the 2026-11-03 text that put the "Explain the setup" copy
  in `the-game.md` and `the-company-timeline.md` (roadmap :719); the timeline file is written for the hiring-manager
  reader. Gain: one home for the player-facing explanation. Cost: the company calendar and the four rules are stated in
  both files until the "Explain the setup" item moves its words; that item owns the merge.
- **C11. The code span is the one markup form for quoted text.** Reason: ledger S7+R3+R4 asks for one form that a test
  can enforce; code spans already exist in Markdown, keep placeholders visible (R10), and need no raw HTML. Gain: the
  pin test finds every quote and command without a hand list. Cost: every code span on the guide needs a row, about 40
  rows.
- **C12. Text printed by outside tools gets an `outside` row.** Reason: Homebrew, direnv, git and Apple's tools print
  text no repo file holds, so no `source` can pin it. Gain: every code span still has a row, and the dry run (R31) knows
  which rows to check by hand. Cost: those rows can drift silently until the next dry run.
- **C13. Homebrew installs Node 24, direnv and uv in one command.** Reason: the novice test's list already uses
  Homebrew for Node and direnv; one tool for all three means one command and one family of fixes. Gain: one step fewer
  than installing uv on its own. Cost: the `node@24` PATH line (step 5), because the versioned formula is keg-only.
- **C14. PG-T5 runs against `develop` as it is once PG-T3 merges.** Reason: ledger R13 asks for a condition; PG-T3
  already waits for the six slices to be merged or parked (R30). Gain: the blind test never waits on a parked slice.
  Cost: a parked slice that lands later can change text the readers saw; its own `make check` then catches the drift
  (R29).

## 12. Needs project owner

This is the only item. It does not stop the build: every ticket builds, and the slice stops before its pull request
with one `waiting-on-owner.md` row. (ledger S2+R9; preflight.)
- **N1. The README links the guide's word files, not the page, until the site has a public address.** The roadmap
  asks for a README section "that links to the page" (roadmap :275), and the address is roadmap item 27's decision
  (roadmap :398). Until it exists, the README links `docs/showcase/story/install-by-hand.md` and
  `docs/showcase/story/how-the-game-works.md` by repo path (R22). Options: (a) accept this as a recorded partial and let
  the slice open its pull request now, gain: the guide and its install steps reach `develop` now, cost: a README reader
  sees the passages as Markdown, not the styled page, until item 27; (b) wait for the address, gain: the clause is met
  in full, cost: the slice waits on the hosting decision, which starts only after the v1 showcase slices (roadmap
  :398). When the address is recorded, the README links the guide by its site path, `/guide`.

## 13. Review changes

One line per ledger row: where the ruling is applied.
- S3+R1: R10 (folder `openrct2-analytics`, no `<` in a command, placeholders only in code spans); R7 step 9; R19 last
  bullet; section 9 tests; PG-T1 and PG-T2.
- R2: section 12 no longer holds the download address; R11 (clone wording and its fix); R7 step 8; PG-T2.
- S2+R9: section 12, N1 (the only owner item); R22; section 10; the tickets' bottom line and PG-T4.
- S1: Goal (format and pass/fail verbatim); section 10 (clause table; the roadmap item is not ticked done); section 7.
- S4+R5: R22; section 5 README bullet; PG-T4 (one link) and PG-T3 (owns the `tests/test_readme_play.py` edit for the
  second link).
- S5: section 5 page-check bullet; PG-T3 owns `tests/page_check_support.py` and runs the fixture-based suites.
- S6: R16; R18 (install rows versus game rows); PG-T2 owns no launcher line; the tickets' dependency table.
- S7+R3+R4: R17 (code spans, one row per span, the four failure conditions); R18 (producers); C11; section 9 breaks.
- S8: R8; R19 (`REQUIRED_STEPS`, forms, folder links); section 2.3; PG-T2's break that removes every step.
- S9+R14: R19 names `make check` (`Makefile:174-175`) as the gate; the `make site-company` claim is removed.
- S10+R6+R10: R20; tickets "Waves and files" (serial handoffs in separate waves, PG-T1 stacks on say-the-park after
  STP-T5 is pushed, PG-T4's `ARCHITECTURE.md` edit follows say-the-park and reword-unfiled, `guide.css` with all step
  styles owned by PG-T1 only).
- S11+R8: R7 (prerequisites including the game files; the twelve steps); R9 (required fixes; the repair tied to the
  damage line only); C13.
- R7: R9 first bullet (Node 24 is the CI version, `brew install node@24`); R31 (the clean-account dry run on the
  morning list).
- S12: R13 (worked two-park example, which save to load, what makes autopilot available, the filing sign, recovering
  an unfiled play); PG-T3.
- S13: section 9 deliberate breaks; each ticket's break names the exact source and rebuilds after template edits.
- S14: R26 (four graded points); R27 (one dated table row, observational); R28 (repairs go back to PG-T2 or PG-T3);
  PG-T5.
- R11: R2 and R19 (`\$\s*\d` only); section 9 ("1 March 2000" passes).
- R12: R17 (parsed text, whitespace collapsed, entities decoded).
- R13: R29 (who edits the guide when a pin turns red); R30 (when PG-T3 and PG-T5 run); C14.
- S15+R15: section 8 (the cap applies to source files); section 9 (the private-path check over every changed file).
- S16: the contract map's TOP 5 item 2 and section 3 citations are corrected.
