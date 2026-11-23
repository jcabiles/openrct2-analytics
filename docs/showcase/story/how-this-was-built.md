# How this was built

**This file holds the words of the showcase page's "How it was built" section: the lead, "The build crew" diagram with its hover detail, and "The data stack" with its reading panel. The page build renders each passage below in place, so these words are edited here, never in the page templates.**

Each passage starts at its `passage` marker and runs to the next one. A claim that no record in the repository backs is not written here. The counts under "By the numbers" come from `site/figures/built-counts.mjs`, which holds the date they were taken and the commands that recount them. The count and version of the data contracts are read from the contract files when the page is built.

<!-- passage: built-title -->
How it was built

<!-- passage: built-lead -->
I designed the system that built this project. AI agents wrote most of the code, under rules I set: which model does which job, who reviews whose work, and which checks must pass before anything merges.

<!-- passage: crew-intro -->
I built this project's architecture and infrastructure with a multi-agent workflow: a crew of AI agents from three vendors, Anthropic's Claude, OpenAI's GPT-6 through Codex, and Google's Gemini, each model matched to the job it does best. I set the goals and the rules; the agents plan, write and review the code.

<!-- passage: crew-review -->
Every review is adversarial: the reviewer never sees the conversation that produced a change, and its job is to break it, hunting for bugs, broken rules and missed edge cases, not to confirm that it works. Where it pays, the reviewer comes from a different vendor than the writer: Claude reviews every commit that Codex's GPT-6 Luna writes before it is pushed, and Gemini reviews some specs.

<!-- passage: why-cheaper -->
Fast, low-cost models take the small, fully specified tickets, so the most expensive model is spent only on planning and judgment calls. Each vendor also has its own usage limit, so work keeps moving when one runs low.

<!-- passage: why-better -->
A reviewer from another vendor is less likely to share the writer's blind spots.

<!-- passage: key-fix -->
A fix made after a review caught a defect (hover for the story)

<!-- passage: crew-aria -->
The build crew, in the order work moves

<!-- passage: fix-aria -->
, a fix made after a review caught a defect

<!-- passage: me-why -->
goals, design, final merge

<!-- passage: me-pop -->
Goals, scope, architecture, design, disputed rulings, and manual code corrections; only I merge into the main branch.

<!-- passage: dir-why -->
strongest reasoning; plans and briefs

<!-- passage: dir-pop -->
Plans the work and writes a brief for each worker, which writes the code.

<!-- passage: return-note -->
findings: accepted or rejected with a reason

<!-- passage: spec-why -->
judgment calls on unclear work

<!-- passage: spec-pop -->
Ambiguous work that needs design judgment.

<!-- passage: impl-why -->
strong coder at mid-tier cost

<!-- passage: impl-pop -->
Clear coding tickets.

<!-- passage: small-why -->
cheap, fast, well-scoped edits

<!-- passage: small-pop -->
Short, fully specified edits, where speed and cost matter more than judgment.

<!-- passage: rev-why -->
a fresh reviewer checks the work

<!-- passage: rev-pop -->
A reviewer that never saw the writer's conversation checks each branch before it merges.

<!-- passage: gate-why -->
tests, types, contracts, secrets

<!-- passage: gate-pop -->
One command runs the tests, type checks, data-contract checks, a dbt build and a secret scan; a merge guard blocks any branch with a serious open finding.

<!-- passage: fix-3-title -->
A test assertion was loosened in place.

<!-- passage: fix-3-body -->
A script that checks for weakened tests flagged the moved and removed assertions but could not see this one; an independent review caught it, and a planted break in the code stayed green.

<!-- passage: fix-3-rule -->
a new test now fails on that planted break in every one of ten runs, and a second review re-ran the break and confirmed it.

<!-- passage: merge-note -->
only I merge here

<!-- passage: counts-note -->
Each count was taken on the commit named above, in the project's private development history; this public repository starts from a later snapshot, so that commit and most review ledgers are not here. The commands that produced the counts are in `site/figures/built-counts.mjs`.

<!-- passage: models-as-of -->
Models as of October 2026: Claude Opus 5.5, Sonnet 5.5 and Haiku 5.5; GPT-6 Sol and Luna via Codex; Gemini 3.8 Flash.

<!-- passage: stack-lead -->
The tools sit in seven bands, in the order the data moves. Point at, focus or tap a tool to read what it is, what it does here and why it was chosen. Tools in gold are planned, not yet in use.

<!-- passage: board-aria -->
The data stack, grouped by band

<!-- passage: explain-aria -->
About the selected tool

<!-- passage: whole-cat -->
Seven bands, from capture to the page

<!-- passage: status-used -->
In use today

<!-- passage: status-planned -->
Planned, not yet in use

<!-- passage: band-capture -->
The game runs the park, and the plugin sends each event.

<!-- passage: band-land -->
The listener saves each event, and the converter writes Parquet.

<!-- passage: band-check -->
Data contracts and SQL style are checked before anything is built.

<!-- passage: band-model -->
dbt builds and tests the reporting tables.

<!-- passage: band-publish -->
A checked warehouse file is swapped in, read-only.

<!-- passage: band-show -->
The showcase page and its charts.

<!-- passage: band-run -->
Tools that build, run, test and review the work.

<!-- passage: contracts-share -->
contracts share one version line,

<!-- passage: tool-openrct2 -->
**What it is.** An open-source version of the classic RollerCoaster Tycoon game, with a JavaScript plugin interface.

**What it does here.** Runs the parks. Every number on this page starts as an event inside the game.

<!-- passage: tool-typescript -->
**What it is.** A typed version of JavaScript that compiles to plain JavaScript.

**What it does here.** The plugin's language. The build compiles it to ES5, the older JavaScript the game runs.

**Why it was chosen.** The game runs plugins in an engine that understands only ES5. Version 5.9.3 is the newest that still compiles cleanly to ES5 (decision record ADR 0002).

<!-- passage: tool-jsonl -->
**What it is.** A text format with one JSON record per line, sent over a network connection on the same computer.

**What it does here.** Carries each event from the plugin to the listener. It is also the format of the dated raw files.

**Why it was chosen.** Game plugins can open only local connections, so no cloud queue is reachable. A local connection and dated files give an ordered stream that can be replayed, with no cloud account (ADR 0003).

<!-- passage: tool-python -->
**What it is.** A general-purpose programming language.

**What it does here.** Runs the listener, the converter, the contract checks, and the capture and publish commands.

<!-- passage: tool-parquet -->
**What it is.** A columnar file format for analytics data.

**What it does here.** Holds the converted events, one file per event type.

<!-- passage: tool-odcs -->
**What it is.** The Open Data Contract Standard: files that describe a data set's fields and quality rules.

**What it does here.** The `make contracts` step checks every Parquet file against them.

<!-- passage: tool-sqlfluff -->
**What it is.** A linter for SQL: it checks the style and layout of queries.

**What it does here.** Lints every dbt model as a failing step of `make check`.

**Why it was chosen.** The project follows dbt Labs' SQL style guide, and sqlfluff enforces it in `make check` (ADR 0016).

<!-- passage: tool-dbt -->
**What it is.** A tool that builds and tests SQL tables from version-controlled models.

**What it does here.** Builds the staging, intermediate and mart models on DuckDB, with enforced contracts and reconciliation tests.

**Why it was chosen.** An earlier project already ran dbt 1.x on DuckDB, so its lessons carry over (ADR 0004). Every practice runs on a local stack, with no cloud-only tool (ADR 0012).

<!-- passage: tool-metricflow -->
**What it is.** dbt's semantic layer, which defines each metric once.

**What it does here.** Approved, not yet in use: dashboards read the marts until it lands.

**Why it was chosen.** Approved as the dbt tool that runs the metric catalog locally, so each metric has one governed definition (ADR 0012 and ADR 0019).

<!-- passage: tool-duckdb -->
**What it is.** An analytics database that runs inside a program and keeps a whole database in one file.

**What it does here.** The warehouse and the converter's engine. Each data set publishes as one read-only file.

**Why it was chosen.** Chosen together with dbt Core: an earlier project already ran dbt on DuckDB (ADR 0004). It keeps the stack local, with no cloud-only tool (ADR 0012).

<!-- passage: tool-eleventy -->
**What it is.** A static site generator: it builds HTML pages from templates and data files.

**What it does here.** Builds the showcase page from the committed JSON exports.

**Why it was chosen.** It gives full control of the design, the pages can move into a personal Next.js site later, and it builds with no network (ADR 0021).

<!-- passage: tool-plot -->
**What it is.** A JavaScript library for drawing charts.

**What it does here.** Draws the site's charts (version 0.6.17).

**Why it was chosen.** Chosen with Eleventy for design control and builds with no network (ADR 0021).

<!-- passage: tool-inputs -->
**What it is.** A JavaScript library of form controls for charts.

**What it does here.** Planned: the controls for the site's future explorer.

**Why it was chosen.** Chosen with Eleventy and Plot (ADR 0021). It waits because the first page reads JSON built ahead of time (ADR 0026).

<!-- passage: tool-wasm -->
**What it is.** DuckDB compiled to run inside a web browser.

**What it does here.** Planned: query the warehouse in the browser.

**Why it was chosen.** Chosen with Eleventy and Plot (ADR 0021). It waits because the first page reads JSON built ahead of time (ADR 0026).

<!-- passage: tool-node -->
**What it is.** A JavaScript runtime that runs outside the browser.

**What it does here.** Builds the plugin and runs its tests.

<!-- passage: tool-uv -->
**What it is.** A Python package and environment manager.

**What it does here.** Installs the pinned Python and the locked packages from `uv.lock`.

<!-- passage: tool-make -->
**What it is.** A command-line tool that runs named steps, called targets.

**What it does here.** Every step, from capture to publish, is a `make` target.

**Why it was chosen.** The `make` targets already run the pipeline, and a scheduler would be one more service to operate. The choice is revisited when make is outgrown (ADR 0019).

<!-- passage: tool-actions -->
**What it is.** GitHub's service for running checks on each change.

**What it does here.** Runs `make check` on pull requests and on pushes to `develop` and `main`.

**Why it was chosen.** The repository template sets up the `make check` gate and continuous integration from the first day (ADR 0001).

<!-- passage: tool-claude -->
**What it is.** AI agents built on Anthropic's Claude models.

**What it does here.** Wrote most of the code and documents, under the project owner's decisions.

<!-- passage: tool-openai -->
**What it is.** AI models from OpenAI, run through the Codex tool.

**What it does here.** Independent reviewers that see only the work and its requirements; GPT-6 Luna also writes some small, fully specified tickets.
