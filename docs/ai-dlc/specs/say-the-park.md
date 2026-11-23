# Spec: say the park and its company year

**Bottom line.** After `make auto-file DATA_SET=company COUNT_AS=<x>` files a play and exits 0, it prints one more line
for each company park that run registered: `<name> joins the company as Park <n>, starting in company year <Y>`. The
park order has one home: a new integer column `park_number` in the `dim_park` mart, counted by company start year (ties
by the earliest `session_start`, then park ID) over every registered non-Sandbox park. The filing line reads n and Y
from `marts.dim_park` in the development warehouse that after-play has just built; the public site reads the same column
from a new `park` export. Nothing else computes the order, in Python or in JavaScript. Sandbox parks, parks registered
by an earlier run, and any run that is refused or fails get no line. When the number cannot be read after a successful
filing, the run prints one plain "could not be shown" line and still exits 0. A registered park with no monthly
statement holds its number, so the site shows it under that number once its rows appear. Before the line is added, the
record-file code moves out of `auto_file.py`, which sits 19 lines under the repo's 500-line limit.

Source names used below: the roadmap is the item "Say the park and its company year" in
`docs/ai-dlc/roadmap/park-company.md` (lines 179-186, quoted below); the 2026-11-16 ruling is the project owner's
design ruling recorded in `docs/ai-dlc/contracts/say-the-park.md` (the contract map), section "Owner rulings"; the
2026-11-17 ruling is the project owner's numbering ruling, recorded in the contract map, section "Site numbering map";
the ledger is `docs/ai-dlc/ledger/say-the-park.md`; "the code" is the code on this branch at `16783665` (the code is
unchanged since `116db2b8`); `docs/CONVENTIONS.md` is the written house rules.

## Change history

- **Revision after the second review (ledger rows STP-S-16 to STP-S-30).** The filing line no longer computes the
  park order in Python: it reads `dim_park.park_number` from the development warehouse once after-play returns 0
  (STP-S-16, by the repo rule "Delete, don't duplicate"). The Python ordering rule, its tests and the agreement test
  (old R27) are removed; the tie cases are tested once, as dbt unit tests on `dim_park`. The site part now also owns the
  two templates and the story file that label parks by position (STP-S-17, STP-S-18), adds a short ADR for the seventh
  served file (STP-S-19), and makes the page check require the embedded park rows (STP-S-22). Old section 12 items 2
  and 3 are decided (section 2.1, section 2.3); section 12 keeps only the two points shown to the project owner in the
  PR.
- **Amendment after the 2026-11-17 ruling.** The site's numbering moved from "not changed" to "aligned": R11 (site
  unchanged) was replaced by R19-R26, and old section 12 item 1 (ledger row STP-S-1) was closed.
- **2026-11-16.** First version, revised after review (ledger rows STP-S-1 to STP-S-15).

## Roadmap item (verbatim)

```
- [ ] **Say the park and its company year** — problem: the year order of new parks has to be remembered · outcome-link: outcome (b) item 4 · verify: agent ·
      status (2026-11-17): spec written and reviewed, on branch `feat/say-the-park`; no code built.
      waits-on-owner: the project owner picks the park numbering rule (align the site's Park n with company start year, keep both numbers, or use the site's order)
      pass/fail: after filing, each new company park gets one line, "<name> joins the company as Park <n>, starting in company year <Y>", where n is the park's place in the order of company start year among non-Sandbox company parks (ties by earliest `session_start`); Sandbox parks get no number; tests cover the first park, a later one and two filed together; `make check` passes.
      riskiest-assumption: none beyond the existing year rule · cheapest-test: not needed · assumption-status: not applicable
      outcome-measure: outcome (b) item 4 absent in the next novice test
      touches: `src/openrct2_analytics/ingest/auto_file.py`, its tests
      after: File several new parks in one play
```

The `waits-on-owner` line is answered by the 2026-11-17 ruling: "align the site: the site's Park n follows company
start year order (ties by earliest session_start), from an exported data column, never a second computation in
JavaScript; the filing line prints only after filing succeeds (exit 0), only for company parks this run registered,
beside the unchanged "is new" line; Sandbox parks get no number; name only, park ID when the name is missing; a
registered park with no monthly statement keeps its number on the site once its rows appear."

## Stated goal

The player no longer has to remember the year order of new parks (roadmap, problem), and sees one number per park on
the filing line and on the site (2026-11-17 ruling). This serves outcome (b) item 4 of the roadmap; the measure is that
item being absent in the next novice test. The filing feature "File several new parks in one play" (ADR 0055) must
land first (roadmap, "after"). The ticket branches start from the branch that carries that feature, so the move commit
(R10) and every diff check are measured against it, not against `develop`.

## 1. Requirements

### 1.1 The filing line

- **R1 The line text.** (roadmap pass/fail; rulings) For each park the line is
  `<name> joins the company as Park <n>, starting in company year <Y>`, with no prefix and no full stop, exactly as the
  roadmap quotes it. No consumer parses the output (`launcher/play-company.command` only runs `make` and prints).
  `check:` a test asserts the exact line for a fixture park as Park 1 in company year 2000.
- **R2 Company parks only.** (rulings; roadmap) A park this run registered as Sandbox (`practice`) gets no line and is
  not looked up; that it is never counted in n is a property of `park_number` (R19). `check:` a test with one Sandbox
  park and one company park filed in one run prints exactly one line, for the company park.
- **R3 n is read, never computed.** (2026-11-17 ruling, "align the site"; ledger STP-S-16; engineering standards
  "Delete, don't duplicate") n is the park's `park_number` in `marts.dim_park` of the development warehouse,
  `warehouse/dev/dev.duckdb`, which after-play builds with `make transform` before it returns 0
  (`src/openrct2_analytics/ingest/after_play.py:158-164` adds the contracts, transform and results steps;
  `after_play.py:184-194` returns 0 only after every step passed). R19 defines the order. No Python function sorts
  parks by start year, first session or park ID for this line. `check:`
  `git grep -n "def park_numbers\|def company_park_numbers" src/` prints nothing, and
  `test -e tests/test_park_number_agreement.py` fails.
- **R4 Y is what landed.** (roadmap; code) Y is `company_start_year` from the same `dim_park` row, which dbt copies from
  the registry the run has just written (`models/marts/dim_park.sql:10-17`), not the year planned before filing.
  `check:` a test plants a `dim_park` row whose `company_start_year` differs from the year in the run's "is new" line
  and asserts the line shows the planted year; in the R8 tests, whose planted rows copy the registry's year, Y equals
  the year in the same park's "is new" line.
- **R5 Only after success.** (rulings) The lines print only when the run would exit 0 after filing, that is after
  `file_with` (after-play) returned 0, on both paths: the several-park chain (`auto_file.py:357-366`,
  `several_parks.file_chain`) and the one-company-park path (`auto_file.py:367-373`). The warehouse is read right
  after `file_with` returns 0 and before `_clear` (`auto_file.py:374-375`) removes the record and answers files; the
  lines print after `_clear`, so they are the last lines of the run. `check:` tests where after-play returns 1, where a
  registration in the chain raises, where the run is refused before any question, and "Don't file now" each plant a
  warehouse that would number the park and print no line containing `joins the company`.
- **R6 Only parks this run registered, and only company ones.** (rulings) The parks looked up are the keys of
  `to_register` (`auto_file.py:352`) whose choice is Company: the same parks this run announced in `shown`
  (`several_parks.announce`, `several_parks.py:216-219`). When there is none, the warehouse is not opened. A registered
  park that only had waiting sessions filed (plan `KEEP`, `CONFLICT` or a stored answer for an already registered park)
  gets no line, and a run with nothing waiting prints none. `check:` a test where an earlier run registered Park 1 and
  this run files more play for it prints no line; a successful run with an earlier registered company park and one
  newly registered company park prints exactly one new line (for the new park), and its rerun prints none; a run that
  registers only a Sandbox park with no warehouse present prints no fallback line.
- **R7 Name, or park ID when there is none.** (rulings; code `auto_file.py:110-120`) `<name>` is the park's name from
  the waiting sessions (`_Park.name`), or its park ID when the name is missing. The label form `name (id)` is not used.
  `check:` a test with a park whose `session_start` has no name prints the park ID as `<name>`.
- **R8 The three roadmap cases.** (roadmap pass/fail) Tests cover the printing for: the first company park (Park 1,
  year 2000); a later company park filed alone (Park 2); and two company parks filed together through the chain (two
  lines, printed in order of n). Each test registers its parks for real and plants the `dim_park` rows a build would
  give. The order itself is proven by the `dim_park` unit tests (R19). `check:` the tests in
  `tests/test_auto_file_park_number.py` pass.
- **R9 The "is new" line and every other existing line are unchanged.** (rulings; contract map item 1) The text and
  timing of `auto-file: park <label> is new; registering it as <how>.` do not change, and no existing assertion about
  an existing line is loosened or removed. Whole-output assertions of successful runs may only gain appended lines
  (section 5). `check:` the existing test files pass with edits that only append expected text.
- **R10 Move code out of `auto_file.py` first.** (`docs/CONVENTIONS.md`, "500 lines"; engineering standards "adding a
  feature to a god file is the moment to split it") The first filing ticket, as its own commit, moves the helpers in
  section 2.1 into a new module with no change in behaviour or output. `check:` `make check` passes on the move commit
  alone; after the move `wc -l src/openrct2_analytics/ingest/auto_file.py` is at most 435; after the feature it is at
  most 455.
- **R11 (withdrawn).** The 2026-11-16 requirement "the site's numbering is not changed" is withdrawn by the 2026-11-17
  ruling; R19-R26 replace it. Only the dashboard stays unchanged (R26).
- **R12 Each new test fails before the change.** (engineering standards) `judgment:` the reviewer confirms each ticket
  report shows its new tests (R1-R8, R15-R18 for the filing line; R19-R25 for the site) failing before the change and
  passing after it.
- **R13 Records.** (contract map "Docs"; engineering standards "a change that invalidates a doc updates that doc";
  ledger STP-S-19, STP-S-29) The `make auto-file` bullet in `AGENTS.md` and the `auto_file.py` paragraph in
  `ARCHITECTURE.md` each gain one sentence describing the new line, when it prints and that it reads `marts.dim_park`
  from the development warehouse. `ARCHITECTURE.md` also states, where it describes the site and `dim_park`, that
  `dim_park.park_number` is the one home of the park order. `docs/CONVENTIONS.md` names the new module
  `auto_file_state.py` where it names `several_parks.py` and `start_year.py`. The `make site-company` bullet in
  `AGENTS.md` gains one sentence: a company warehouse published before this change lacks `park_number`, so
  `make site-company` refuses it until `make publish DATA_SET=company` is run again. A short new ADR (the next free
  number in `docs/adr/`, 0057) amends ADR 0045 without editing it: `site/_data/` holds seven
  files, and the seventh is a dimension export (one row per park), not a department figure. The three "six" counts in
  `ARCHITECTURE.md` (lines 33, 237 and 674) become "seven". `judgment:` the reviewer checks the edits match R1-R7 and
  R19-R21 and that the ADR amends, not edits, ADR 0045.
- **R14 The gate passes.** (roadmap) `check:` `env -u VIRTUAL_ENV make check` exits 0 in each ticket worktree.
- **R15 The number cannot be read after a successful filing.** (ledger STP-S-2, STP-S-16) After `file_with` returns
  0, the run reads `marts.dim_park` once, read-only, and closes the connection before it returns. When the read raises
  `OSError` (the warehouse file is absent: the reader raises `FileNotFoundError`) or `duckdb.Error` (a writer holds
  the file's lock, the table or the `park_number` column is missing, as in a warehouse built before this change, or
  the file is damaged), the run prints exactly one line,
  `auto-file: the play is filed, but the park number could not be shown (<reason>).`, where `<reason>` is a short fixed text chosen from the kind of the error (ledger
  STP-W2T4-R1): `no warehouse file`, `the warehouse is locked by another program`, `the warehouse was built before
  park numbers` or `the warehouse could not be read`; the error's own text is never printed. Then it clears the
  record and answers files as today and exits 0. It never prints "already registered by this run", a rerun line or
  "Nothing was changed.". The fallback carries a comment giving this reason. `check:` three tests, each with after-play
  returning 0: no warehouse file; a writer holding the lock (the pattern of `tests/test_play_status.py:150-170`); and a
  planted `marts.dim_park` without a `park_number` column. Each asserts exit 0, exactly that one extra line, and the
  record and answers files removed.
  Amended 2026-11-19: the first version pinned `(<error>)` and the text `warehouse/dev/dev.duckdb does not exist`;
  the fixed reasons above replaced them (ledger STP-W2T4-R1, STP-WB-C3, STP-WB-Q2).
- **R16 A newly registered company park has no number.** When the read works but a company park of `to_register` has
  no `dim_park` row or a null `park_number`, the run prints the lines for the parks it can number, then one line,
  `auto-file: the play is filed, but the park number could not be shown for <name>[, <name>].`, then exits 0 with the
  files cleared. `check:` a test with a planted `dim_park` that lacks the run's company park asserts that one line and
  exit 0.
- **R17 An interrupt while the new lines print.** The printing is a function that catches `lock.Interrupted` and
  `KeyboardInterrupt` and returns 130 with no further output, the way `_end` handles a second interrupt
  (`auto_file.py:396-398`: parks already landed stay landed). The record and answers files are already cleared
  (R5), so the run prints no "Nothing was changed.", no filed-parks report (`several_parks.filed_report`,
  `several_parks.py:156`) and no rerun line; a filed-parks report here would be false, since nothing is left to file.
  An interrupt during the read before `_clear` is not caught there: it reaches `main` (`auto_file.py:470`) and ends
  as an interrupt after a registration does today, with the filed-parks report, the rerun line and exit 130, and the
  files kept. `check:` a test that raises `KeyboardInterrupt` from the print asserts exit 130, none of the three
  phrases above, and no traceback; a second test raises `KeyboardInterrupt` from the read before `_clear` (after
  `file_with` returns 0) and asserts exit 130, the filed-parks report and rerun line printed, and the record and
  answers files still present.
- **R18 A failed run followed by a successful rerun prints no line for the failed run's parks.** (rulings, "only for
  company parks this run registered") A park registered by a run that then failed is registered by the time of the
  rerun, so the rerun does not announce it and prints no line for it. This is accepted: the failed run already printed
  the "is new" line and the filed-parks report; the site shows the park's number once its rows appear (R21). The PR
  lists it for the project owner (section 12, item 2). `check:` the rerun test in `tests/test_auto_file_chain.py`
  (`test_rerun_after_a_partial_failure_files_the_rest`, line 390) asserts the rerun prints a line only for the park the
  rerun registered, and a test with a first run that registers one park and fails, then a rerun that registers
  nothing, asserts no `joins the company` line at all.

### 1.2 The park order and the site's "Park n"

- **R19 One numbering home: `dim_park.park_number`.** (2026-11-17 ruling, "from an exported data column"; contract map
  "Risks", "One numbering home"; ledger STP-S-16, STP-S-26, STP-S-27) The mart `marts.dim_park` gains a column
  `park_number`, cast to `integer` and declared `data_type: integer` in the enforced contract of
  `models/marts/dim_park.yml` (golden path: `cast(riders_rank_in_park_year as integer)`,
  `models/marts/obt_ride_year.sql:73`). For every registered park that is not a Sandbox park it is the 1-based position
  by `company_start_year`, then the earliest `emitted_at` of any of its `session_start` rows (all sessions, not only
  kept ones), with `nulls last` written out so a park without a `session_start` row sorts after tied parks that have
  one, then `park_id`. A Sandbox park (registry note equal to `registry_feed.PRACTICE_NOTE`,
  `src/openrct2_analytics/ingest/registry_feed.py:45`) has `park_number` null and is not counted. Parks are numbered
  among every non-Sandbox park of the warehouse, whatever their `data_set` value, because each warehouse is built from
  one data set's registry; so the committed sample (one `rehearsal` park) shows Park 1. A registered park with no
  park-day and no monthly statement still gets its number. The tie rules are tested with synthetic rows only: the
  start-year rule gives every later company park a distinct year (ADR 0050; ADR 0055 decision 1), so a tie arises only
  after a hand edit of the registry. `check:` dbt unit tests in `models/marts/dim_park.yml`, run by the dbt build in
  `make check`, cover: four parks where start-year order differs from both park-ID order and first-company-date order;
  one start-year tie broken by the earlier first session; one tie with equal first sessions broken by park ID; one tied
  park with no `session_start` row sorting last; one park with no park-day numbered; and one Sandbox park with a null
  number. The existing unit test's registry mock (`dim_park.yml:63-76`) gains the `note` column the model now reads.
- **R20 The site reads the number, never computes it.** (2026-11-17 ruling, "never a second computation in
  JavaScript"; ledger STP-S-18) A new export `park` in `site/exports.toml` (relation `marts.dim_park`, output
  `park.json`, columns `park_id` and `park_number`, order by `park_number` then `park_id`) carries the column.
  `deskParks` (`site/assets/js/rows/insights.mjs:10-23`) keeps the first and last month of each park from `park_month`,
  but orders parks by their exported `park_number` and carries it on each entry; `parkLabels` (`insights.mjs:26`)
  labels each entry `Park ${park_number}`, not by its position. `parkOpeningRows` (`site/figures/enterprise.mjs:8-16`)
  and `firstParkMonths` (`site/assets/js/rows/story.mjs:7-17`) are built from the `deskParks` entries and carry
  `park_number`, in park-number order; under ADR 0050 start-year order is the opening order, so the heading "Parks, by
  opening year" stays. No site file sorts parks by month, start year or first session. `check:`
  `git grep -n "first_month <\|month <\|index + 1\|Park {{ loop.index" -- site/assets/js/rows site/figures site/_includes/insights.njk site/_includes/insights-finance.njk`
  prints nothing, and Node-run tests (pattern of `tests/test_site_registry.py:90-111`) with synthetic exports where
  `park_number` order differs from first-month order and from park-ID order assert that the labels and order of
  `deskParks`, `parkOpeningRows` and `firstParkMonths` follow `park_number`.
- **R21 A park with no monthly statement keeps its number.** (2026-11-17 ruling; ledger STP-S-17, STP-S-28) A park with
  a `park` row but no `park_month` row is not listed on the page; the other parks keep their own numbers, so the page
  can show "Park 2" with no "Park 1". When the park's rows appear, it shows under its number, and no other park's label
  changes. Page copy that needs a month ("Park n opened in <Month>", `site/figures/enterprise.mjs:28` and
  `site/figures/story.mjs:22`; "Data shown: Park 1, ...", `site/figures/insights.mjs:35`) is written only for parks
  that have month rows. The park switch (`site/_includes/insights.njk:34`) and the Finance legend
  (`site/_includes/insights-finance.njk:12`) print `Park {{ park.park_number }}`, not `Park {{ loop.index }}`. Colour
  and the story's "first park" wording still follow position in `deskParks` order (`parkClass`,
  `site/assets/js/data.mjs:8`): with no Park 1 rows, Park 2 takes the first colour and is the story's first park. This
  is cosmetic and accepted. `check:` a test with three numbered parks of which Park 1 has no month rows asserts the
  enterprise lines read "Park 2 opened in ..." and "Park 3 opened in ...", and the "Data shown" sentence names Park 2
  and Park 3 only; a rendered-page test (through `tests/page_check_support.py`, `render_page`) with the same served
  set asserts the park switch and the Finance legend read "Park 2" and "Park 3" and the page holds no "Park 1".
- **R22 A park with month rows but no number is an error.** (engineering standards, "no swallowed errors") When a
  `park_month` row's `park_id` has no `park` row or a null `park_number`, `deskParks` throws an error naming the park
  ID, so the site build fails rather than printing an unnumbered park. This cannot happen on a company build, which
  refuses a Sandbox park (`src/openrct2_analytics/ingest/site_company.py:151-170`), nor on the sample. `check:` a Node
  test asserts the throw and its message.
- **R23 Every caller moves together.** (contract map "Labels are positional: every page string, chart label and test
  moves together"; ledger STP-S-17, STP-S-18) The callers of `deskParks` and `parkLabels` pass the `park` rows and the
  `deskParks` entries: `site/assets/js/rows/panels.mjs:6-12` (today it passes park IDs to `parkLabels`),
  `site/assets/js/rows/story.mjs:4-8`, `site/assets/js/finance.mjs:8-14` and `site/assets/js/story.mjs:14` (browser;
  today each builds `{ park_month: parkMonthData() }`, so the page also embeds the `park` rows as a `park-data` block
  and `site/assets/js/data.mjs` gains a reader for them), `site/index.njk:1` (the `exports` object gains `park`) and
  `:35` (the embedded JSON), `site/figures/insights.mjs:5,30,35,51`, `site/figures/finance.mjs:6,17`,
  `site/figures/story.mjs:5,10`, `site/figures/enterprise.mjs:5,8-16,28`, and the two templates of R21. `check:` the
  site build and page check in `make check` pass on the sample. `judgment:` the reviewer reads every hit of
  `grep -rn "parkLabels(\|deskParks(\|firstParkMonths(" site/assets site/figures` and confirms each passes `deskParks`
  entries or exports that include `park`, never park IDs or month rows.
- **R24 The served data and its records follow the export.** (`AGENTS.md`, `make site-export`; engineering standards;
  ledger STP-S-20, STP-S-22) `site/_data/park.json` is generated by `make site-export` and committed; no other served
  file changes. `models/marts/dim_park.yml` documents `park_number` (unit: none; meaning; null for Sandbox parks) with
  a `unique` test, and the exposures in `models/marts/exposures.yml` whose pages show "Park n" depend on
  `ref('dim_park')`. The test helpers that write served sets (`tests/page_check_support.py`, `_site` at lines 51-62
  and `write_every_status_served_files` at lines 178-223) write a `park.json` in every set. The page check refuses a
  page without the embedded `park-data` block (beside the `park-month-data` requirement,
  `src/openrct2_analytics/showcase/page_check.py:202-204`); the existing comparison of every embedded `*-data` block
  with its served file (`src/openrct2_analytics/showcase/page_check_site.py:255-270`) then compares it with
  `park.json`. `check:` `make check` passes, including the showcase export comparison, the built-columns check and the
  exposure check; `git diff --stat <branch point>...HEAD -- site/_data` lists only `site/_data/park.json`; two
  page-check fault tests, one removing the `park-data` block and one changing a `park_number` in it, each make the page
  check fail with its own message.
- **R25 The Sandbox note has one home in Python and a guarded copy in dbt.** (engineering standards, "delete, don't
  duplicate", with the duplication made checkable) The dbt model needs the practice note text; it lives in one macro,
  `macros/practice_note.sql` (with its `macros/practice_note.yml`, as every macro has), and a test asserts the macro's
  text equals `registry_feed.PRACTICE_NOTE`. No dbt model knows the note today, so this copy is needed. `check:` that
  test fails when either string is changed alone.
- **R26 The dashboard is unchanged.** (2026-11-17 ruling covers the site only; contract map "Dashboard has no Park n
  numbering") `src/openrct2_analytics/dashboard/data.py:352` selects named columns from `dim_park`, so the new column
  does not reach it. `check:` `git diff --stat <branch point>...HEAD -- src/openrct2_analytics/dashboard` is empty.
- **R27 (withdrawn).** The agreement test between a Python order and the dbt column is removed with the Python order
  (ledger STP-S-16, STP-S-21); R3 and R19 leave one implementation.

## 2. Design

### 2.1 Placement plan: the filing line

**One home for the order (decided; ledger STP-S-16, old section 12 item 3).** The filing line reads the number the
site reads.
- **Gain:** one implementation of the order; no Python ordering rule, no unit tests of it and no agreement test with
  its dbt build in the test suite; the line and the site cannot disagree on order.
- **Cost:** the line depends on the development warehouse that after-play has just built, so a failed read gives the
  R15 line instead of the number (exit 0 either way); the read holds DuckDB's read-only lock for a moment, so a
  `make transform` started from another terminal in that moment fails to open the file, as with `make play-status`;
  tests plant a small warehouse; and the line shows the development warehouse's number while the site shows the
  published one (the lag of section 2.3).
- **Why it is safe after exit 0.** after-play runs `make transform` as a subprocess that has exited, then reads the
  same file read-only through `results.main` (`src/openrct2_analytics/ingest/results.py:304-315`), before it returns
  0. `play_status.warehouse_sessions` (`src/openrct2_analytics/ingest/play_status.py:125-160`) already opens that file
  read-only in this process family and maps a held lock to a state.

**The move (R10).** The record-file state moves to a new `src/openrct2_analytics/ingest/auto_file_state.py`, beside
`several_parks.py`; the module takes the data set and project folder as arguments, so it imports nothing from
`auto_file` (no circular import). Moved, with the public name (no leading underscore) in the new module, counted at
`16783665`:

| In `auto_file.py` today | Line | New name | Notes |
|---|---|---|---|
| `BEFORE_FILE` | 56 | same | constant; `ANSWERS_FILE` (line 57) stays, it aliases `several_parks.ANSWERS_FILE` |
| `_absolute` | 127-128 | `absolute` | also used at `auto_file.py:294-295`, `337` |
| `_record(project_dir)` | 131-144 | `record(project_dir, data_set)` | `DATA_SET` passed in; uses `landing_dirs`, `managed_years`, `absolute`, `clear`, `write_json` |
| `_write_json` | 147-152 | `write_json` | |
| `_clear` | 159-162 | `clear` | uses `several_parks.ANSWERS_FILE` |
| `_read_before` | 165-182 | `read_before` | |

`_skip` (`auto_file.py:155-156`) stays: it is a no-op used only at `auto_file.py:356`. The answers reader already
lives in `several_parks.read_answers` (`several_parks.py:128`), so it does not move. `auto_file.py` drops `json` (used
only at lines 151 and 168, both moved), adds `auto_file_state` to the `openrct2_analytics.ingest` import (lines 43-51,
one name per line, +1 line), and adds `from openrct2_analytics.ingest.auto_file_state import write_json` (+1 line), so
line 356 stays one line under the 100-character limit (`partial(write_json, ...)`; a module prefix would wrap it).
Call sites that change: `_record` at 407, `_clear` at 321 and 375, `_read_before` at 326, `_absolute` at 294, 295 and
337, `_write_json` at 356. Tests: `tests/test_auto_file_answers.py:390,394` call `auto_file_state.write_json` instead of
`auto_file._write_json`; a search of `tests/`, `src/` and `scripts/` finds no other use of a moved name.

**Line count.** At `16783665` `auto_file.py` has 481 lines. The move removes 55 lines (line 56, and the blocks 127-130,
131-146, 147-154, 159-164 and 165-184 with their trailing blank lines), removes the `json` import (-1) and adds two
import lines (+2): 481 - 55 - 1 + 2 = 427. A reviewer reproduces it by applying the move, running `ruff format` and
`wc -l`. The feature adds about 16 lines (the read call with its R15 fallback, the print call and the function of R17),
so `auto_file.py` ends near 443. The R10 targets (435 after the move, 455 after the feature) add a margin for wrapping
the count did not foresee; both stay well under 500. The new module is about 75 lines.

**The feature.**

| Part | Owner module | What it does | Reuses |
|---|---|---|---|
| Order (R3, R19) | `models/marts/dim_park.sql` | `park_number`; nothing in Python orders parks for this line. | section 2.4 |
| Reader (R3, R4, R15, R16) | `src/openrct2_analytics/ingest/play_status.py` (260 lines, about 285 after) | `dim_park_numbers(project_dir, park_ids)` returns park ID to (`park_number`, `company_start_year`) for the listed parks whose `marts.dim_park` row has a number. It raises `FileNotFoundError` naming `warehouse/dev/dev.duckdb` when the file is absent, opens it read-only with `open_warehouse`, closes it in a `finally`, and lets every `duckdb.Error` raise. | `WAREHOUSE` (`play_status.py:36`), `open_warehouse`, the shape of `warehouse_sessions` |
| Wording (R1, R15, R16) | `src/openrct2_analytics/ingest/several_parks.py` (290 lines) | `joins_line(name, number, year)` and the two fallback lines, beside `how` and `announce`. | none |
| Call (R5, R6, R7, R17) | `src/openrct2_analytics/ingest/auto_file.py` | In `_file`, after `code == 0` and before `_clear`, read the numbers for the Company parks of `to_register` (none: no read), catching `(OSError, duckdb.Error)` for R15; after `_clear`, print the lines (a small function that handles R17). Names come from `parks`. | `to_register`, `parks`, the existing `play_status` import (`auto_file.py:48`) |

- **Reader home: `play_status.py`.** Gain: it already owns the development warehouse path, the read-only open and the
  lock handling, `auto_file.py` already imports it, and `tests/test_play_status.py` already plants warehouses. Cost:
  the module named for `make play-status` gains a second reader (about 25 lines). The alternative, `several_parks.py`,
  holds wording and the chain and has no warehouse code; putting the reader there would add a second warehouse path
  constant. Not chosen.
- **Dependents:** `make auto-file` (`Makefile`, the auto-file target) and the launcher (`launcher/play-company.command`)
  show the output as it is; neither changes.

### 2.2 Behaviour after the change: the filing line

1. Everything up to `file_with` returning runs as today (R9).
2. When `file_with` returns non-zero, or anything raises, the run ends as today, with no new line (R5).
3. When it returns 0: if `to_register` holds a Company park, `marts.dim_park` is read once and closed (R15 on a read
   failure); then `_clear` runs; then, in order of n, one R1 line prints per park found (R16 for a park with no
   number, R17 for an interrupt); then exit 0.
4. The read failure and the missing number are separate cases: a failed read gives one line for the whole run, a
   missing number gives one line naming the parks without one.

### 2.3 The site's "Park n" after the change

- **Bottom line:** the site and the filing line give a park the same number, except while the published site lags
  the development warehouse.
- **Before (`16783665`).** `deskParks` orders parks by their first month in `exports.park_month` (parks with a closed
  monthly statement only), then park ID, and `parkLabels` labels them by position. That differed from the start-year
  order in four cases: a park with no closed statement was skipped and later parks were numbered one lower; an earlier
  park whose first statement closed after a later park's came second; tied start years were broken differently; and the
  published site lags filing.
- **After.** The first three cases go away: both read `dim_park.park_number` (R3, R19), and a park without statements
  holds its number (R21). The fourth stays: the line reads the development warehouse at filing time, and the site shows
  the last `make site-company` build of the published warehouse (`AGENTS.md`, `make site-company`).
- **Numbers are stable as parks are added.** A later company park always gets a start year above every earlier park's
  (`start_year.next_start_year`, `start_year.py:104`), so registering it never changes an earlier park's number.
- **A delete before go-live renumbers later parks (decided; ledger STP-S-30, old section 12 item 2).** The number is
  the start-year order among the parks registered now, with no stored state. After
  `make delete-company-data PARK=<id>` (which exists only before go-live, ADR 0033), the parks after the deleted one
  move up one number on the next filing line and the next site build alike. Gain: no stored number to maintain and no
  contract change. Cost: a number a player saw once can change after a delete. A stored number per park would need a
  new registry column (a minor contract bump) and is not built.
- **Sandbox parks** have no number (R19), and `make site-company` refuses a published file that lists one.

### 2.4 Placement plan: the export

**Choice: a new `park` export from `marts.dim_park`, with the number computed in `dim_park`.** Reasons, from the code:

- `park_month` (`marts.fct_park_month`) has rows only for parks with a closed monthly statement, so a number carried
  there cannot be counted over parks without one, and a JavaScript count over its rows would renumber parks (the
  2026-11-17 ruling forbids both). `dim_park` has one row per registered park, including parks with no park-day
  (`models/marts/dim_park.yml`, unit test "keeps registered parks without events"), so the number is counted over the
  registry.
- `dim_park` already joins the registry (`company_start_year`, `models/marts/dim_park.sql:10-17`) and
  `stg_session_start` (`dim_park.sql:19-38`); the number needs one more column from each: the registry `note` (already
  in `int_park_registry__current`) and the earliest `emitted_at` of all `session_start` rows.
- `park_year` (`marts.obt_park_year`) has the same gap as `park_month` and a company-year grain.

| Part | File | What changes |
|---|---|---|
| Sandbox note | `macros/practice_note.sql`, `macros/practice_note.yml` (new) | Returns the note text as a SQL string literal (R25). |
| Column | `models/marts/dim_park.sql`, `models/marts/dim_park.yml` | `park_number` by `row_number()` over non-Sandbox parks, cast to integer, `nulls last` (R19), documented with a `unique` test, the existing unit test's mock gaining `note`, and the new unit tests. Golden path for the rank: `riders_rank_in_park_year` in `models/marts/obt_ride_year.sql`. |
| Export | `site/exports.toml`, `site/_data/park.json` (generated) | The `park` entry (R20); `make site-export` writes the file (R24). |
| Lineage | `models/marts/exposures.yml` | Pages that show "Park n" depend on `dim_park` (R24). |
| Decision record | new ADR amending ADR 0045 | Seven served files; the seventh is a dimension export (R13). |
| Site | the files of R21 and R23 | Read `park_number` (R20-R23). |
| Page check | `src/openrct2_analytics/showcase/page_check.py` | Requires the `park-data` block (R24). |

- **Gain:** one numbering home for the site and the filing line, counted over every registered park, so the ruling's
  "keeps its number" holds with no JavaScript logic; the export stays a plain column copy, as `site/exports.toml`
  line 2 requires.
- **Cost:** one new served file (`site/_data/park.json`, one row per park, park IDs only, as `park_month.json` already
  serves) and its ADR; one more `left join` and window in `dim_park`; a dbt column doc and unit tests; a regenerated
  `site/_data/` checked by the export comparison in `make check`; and a macro copy of the practice note guarded by a
  test (R25).
- **Alternative: add `park_number` to `fct_park_month`.** Gains no new export file; costs a dimension attribute
  repeated on every fact row, and the number still has to be counted in `dim_park` (or an intermediate model) first.
  Not recommended.
- **Alternative: export `company_start_year` and sort in JavaScript.** Gains no dbt change; it is the second
  computation the ruling forbids. Rejected.
- **No hotspot is touched:** `models/marts/`, `macros/`, `site/` and `src/openrct2_analytics/showcase/` are not on the
  hotspot list; `dbt_project.yml` and `models/staging/` are only read.

## 3. Files to change

- Filing line: `src/openrct2_analytics/ingest/auto_file_state.py` (new), `src/openrct2_analytics/ingest/auto_file.py`,
  `src/openrct2_analytics/ingest/play_status.py`, `src/openrct2_analytics/ingest/several_parks.py`; tests
  `tests/auto_file_support.py`, `tests/test_auto_file_answers.py`, `tests/test_auto_file.py`,
  `tests/test_auto_file_chain.py`, `tests/test_auto_file_chain_guards.py`, `tests/test_auto_file_several_parks.py`,
  new `tests/test_auto_file_park_number.py`.
- Warehouse and export: `macros/practice_note.sql` and `.yml` (new), `models/marts/dim_park.sql`,
  `models/marts/dim_park.yml`, `models/marts/exposures.yml`, `site/exports.toml`, `site/_data/park.json` (new,
  generated), new `tests/test_practice_note.py`, the new ADR, the three counts in `ARCHITECTURE.md`, and the export
  tests that list the allowlist (`tests/test_showcase_export.py`; `tests/test_site_company.py` and
  `tests/test_site_company_land.py` only where they pin the list of export files; `tests/test_dbt_two_parks.py`, which
  exports the whole allowlist and renders the page, re-run and edited only if red).
- Site: the files of R21 and R23; `src/openrct2_analytics/showcase/page_check.py`; tests `tests/site_fixtures.py`,
  `tests/test_site_registry.py`, `tests/test_site_story.py`, `tests/test_panel_figures.py`,
  `tests/test_site_finance.py`, `tests/page_check_support.py`, new `tests/test_site_park_number.py` (the rendered-page
  test of R21 and the page-check fault tests of R24), and `tests/test_showcase_page_check.py` only if it goes red, with
  no net added lines (it has 499 lines; `scripts/check_file_sizes.py` allows 500).
- Records: `AGENTS.md`, `ARCHITECTURE.md`, `docs/CONVENTIONS.md` (R13).

The roadmap's touches list only `auto_file.py` and its tests; the other files follow from R10, R13 and the 2026-11-17
ruling (section 11).

## 4. Contracts and pinned strings

- **New line (pinned):** `<name> joins the company as Park <n>, starting in company year <Y>`; `<name>` per R7, `<n>`
  a decimal integer from 1, `<Y>` the decimal start year from `dim_park`.
- **New fallback lines (pinned):** `auto-file: the play is filed, but the park number could not be shown (<reason>).`
  and `auto-file: the play is filed, but the park number could not be shown for <name>[, <name>].` (R15, R16).
  `<reason>` is one of the four fixed texts of R15; the absent-warehouse reason is `no warehouse file`.
- **Unchanged lines (pinned as today):** `auto-file: park <label> is new; registering it as <how>.`
  (`several_parks.py:219`), `auto-file: nothing is waiting to be filed.` (`auto_file.py:320`), every refusal, failure
  and filed-report line in `auto_file.py:448-477` and `several_parks.py:145-209`.
- **Exit codes:** unchanged: 0 filed or nothing waiting, 1 a step failed, 2 refused, 130 interrupted.
- **Site labels (pinned):** `Park <park_number>`; "Park n opened in <Month>." and "Data shown: Park n, ..." keep their
  wording and take n from `park_number`.
- **Mart column (new):** `marts.dim_park.park_number`, integer, null for Sandbox parks. The filing line reads
  `park_id`, `park_number` and `company_start_year` by name, so these three names are a contract between
  `dim_park.yml` and the reader. Adding a mart column is not a data contract change (the ODCS contracts in
  `contracts/` cover events, which are untouched).
- **Data contracts:** none touched. The registry feed is read through its existing readers only.

## 5. Test seams

- **Filing line.** `tests/auto_file_support.py` gives `_run` (calls `auto_file.main` with fakes), `Asked` (scripted
  answers), `Filed` (records `file_with` calls, writes nothing), `Registers` (the real `register_parks.register` with
  injected failures), `_register` (plants one registry row), `_sessions`, `_snapshots`, `_before` and the `data`
  fixture. `tests/test_auto_file_answers.py` has `Registering(Filed)`, a fake that registers the listed waiting parks
  for real, then returns its code.
- **Planted warehouse.** `tests/auto_file_support.py` gains a helper that writes `warehouse/dev/dev.duckdb` under the
  test project with a `marts.dim_park` table (`park_id`, `park_number`, `company_start_year`), following `_warehouse`
  in `tests/test_play_status.py:28-37`; the lock test follows `_writer_holds` (`tests/test_play_status.py:150-170`).
  The R8 tests plant rows whose years copy the registry the run wrote, and whose numbers the test states.
- **Existing successful tests whose whole-output assertion gains a line.** Most existing auto-file tests plant no development warehouse, so every successful run that registers at least one company park now ends with the R15 line `auto-file: the play is filed, but the park number could not be shown (no warehouse file).` Three tests do plant one (tests/test_auto_file_several_parks.py:188, tests/test_auto_file_answers.py:348, tests/test_auto_file_chain_guards.py:90); their success cases assert only the exit code, so the new line does not change them.
  Gain: one fixed appended line, with no change to the shared fixtures. Cost: those assertions show the fallback rather
  than a number; the number itself is tested in the new file. The 2026-11-16 review listed the whole-output assertions
  of successful runs (ledger row STP-S-4) in `tests/test_auto_file.py`, `tests/test_auto_file_several_parks.py`,
  `tests/test_auto_file_answers.py`, `tests/test_auto_file_chain.py` and `tests/test_auto_file_chain_guards.py`. The
  contract map lists the current "is new" pins at `552de328`: `tests/test_auto_file_several_parks.py:82-83`,
  `tests/test_auto_file_chain_guards.py:160-163,185-188,257`, `tests/auto_file_support.py:150`,
  `tests/test_auto_file_earlier_park.py:74`, `tests/test_auto_file.py:129,264,284-285`,
  `tests/test_auto_file_answers.py:35-38,288`. The ticket re-finds each whole-output assertion of a successful run
  with a company park in `to_register` and appends only; runs that register only Sandbox parks, tests of failing runs,
  refusals and runs that assert only calls, prompts or the exit code need no change.
- **Park order.** Tested once, in the `dim_park` unit tests (R19), with synthetic registry and `session_start` rows.
- **Site.** The committed sample has one park, so it shows Park 1 under either rule and cannot catch a wrong order.
  Every order test uses synthetic exports: `tests/site_fixtures.py` gains `park` rows for each fixture set and a
  multi-park set where `park_number` order differs from first-statement order and from park-ID order (for example,
  park `2` is Park 1 with its first statement in Aug 2000, park `1` is Park 2 with its first statement in Mar 2000, and
  park `3` is Park 3 with no statement). Tests that pin order today and change: `tests/test_site_registry.py:72,86,111,
  130-144,152` (`test_parks_follow_their_first_month_not_their_id` is replaced by a test of `park_number` order),
  `tests/test_site_story.py:34,128`, `tests/test_panel_figures.py:42-82`, `tests/test_site_finance.py:24,50`.
  `tests/test_showcase_page_check.py:249` (a two-park year fixture) and `:424` (a fault case about the sentence "Park 1
  Park 2 are listed") are not order assertions and are not on this list.
- **Rendered page and page check.** `tests/page_check_support.py` writes `park.json` in every served set (R24); the new
  `tests/test_site_park_number.py` renders the real template through `render_page` for R21 and holds the two page-check
  fault tests of R24.

## 6. Golden paths

- New Python test files: `tests/test_listener.py` (golden test, `docs/CONVENTIONS.md` section 5) for layout, and
  `tests/test_auto_file_chain.py` for the auto-file fixtures.
- Reader: `play_status.warehouse_sessions` (`play_status.py:125-160`); planted warehouses: `tests/test_play_status.py`.
- Mart column: `models/marts/obt_ride_year.sql` (`riders_rank_in_park_year`) and `models/marts/dim_park.sql`.
- Site rows: `site/assets/js/rows/insights.mjs` and its Node test pattern in `tests/test_site_registry.py`.
- Rendered page: `tests/page_check_support.py` (`render_page`) and `tests/test_showcase_page_check.py`.

## 7. Out of scope

- The dashboard (R26).
- Any change to the "is new" line, the questions, the chain, the refusals or exit codes (rulings; R9).
- The note about the previous park's profit (the next roadmap item, "Warn when a park opens before the last one is
  finished").
- `make register-parks`, `make after-play` and `make autopilot-year` output.
- The `Makefile`, the launcher and `dbt_project.yml`.
- A reminder of a park's number after a failed run (R18).
- A stored park number (section 2.3).
- Showing park names on the site (the site prints no park ID or name today; this change keeps that).

## 8. Constraints

- The repo invariants hold: the change reads the development warehouse, adds one mart column and one export, and
  touches no event, money, contract, plugin or raw capture. The site still states its sample.
- Every Python file stays at or under 500 lines (`docs/CONVENTIONS.md`); `auto_file.py` ends at most 455 (R10);
  `tests/test_showcase_page_check.py` gains no net lines.
- No new dependency; no `Makefile`, launcher or hotspot change.
- No swallowed errors: the one Python fallback (R15) names its exception set and states its reason in a comment; the
  site throws on an unnumbered park (R22).
- Committed text never names the project owner and holds no private machine path.

## 9. Verify by

On fixtures and the committed sample only, never on real company data:

```
.venv/bin/python -m pytest tests/test_auto_file_park_number.py \
  tests/test_auto_file.py tests/test_auto_file_chain.py tests/test_auto_file_chain_guards.py \
  tests/test_auto_file_several_parks.py tests/test_auto_file_answers.py tests/test_auto_file_earlier_park.py \
  tests/test_play_status.py tests/test_practice_note.py tests/test_site_registry.py tests/test_site_story.py \
  tests/test_panel_figures.py tests/test_site_finance.py tests/test_site_park_number.py \
  tests/test_showcase_page_check.py tests/test_showcase_export.py tests/test_dbt_two_parks.py
```

Then `make site-export` (no change to the committed files after the export ticket) and `env -u VIRTUAL_ENV make check`,
which runs the `dim_park` unit tests in its dbt build.

## 10. Definition of done

- R1-R10 and R12-R26 met (R11 and R27 are withdrawn); `make check` green in each ticket worktree, on the move commit and
  on each final commit.
- Each ticket report lists its new tests failing before its change (R12).

## 11. Where the sources disagree

- **The 2026-11-16 ruling versus the 2026-11-17 ruling.** The contract map's "Owner rulings (preflight 2026-11-16)"
  says "site numbering unchanged, documented as agreeing under the start-year rule"; the later ruling says "align the
  site". The later ruling wins; R11 is withdrawn.
- **The roadmap item is out of date.** Its `status` and `waits-on-owner` lines predate the 2026-11-17 ruling, and its
  touches list only `auto_file.py` and its tests. R10, R13 and R19-R26 touch more files; the roadmap entry is updated
  by whoever closes the item, not by this spec.
- **Contract map line numbers.** The 2026-11-16 part of the map cites `auto_file.py` and `register_parks.py` lines from
  before the several-parks work; the code at `16783665` wins, and this spec cites it. The map's "Site numbering map"
  part was taken at `552de328`, which this branch contains.
- **"Beside the unchanged is-new line" versus "only after filing succeeds".** The "is new" line prints before
  after-play runs (`auto_file.py:369`, `several_parks.file_chain`), and success is known only after it. So the new
  lines print in the same successful filing output, at its end, after the after-play output and `make results`, not
  next to the "is new" line. A literal "beside" cannot meet "only after exit 0"; the 2026-11-17 ruling repeats both
  phrases. Section 12 puts this reading to the project owner.

## 12. Needs owner decision

These two points are built as described and listed in the PR so the project owner sees them; neither blocks a ticket.

1. **"Beside" is read as "in the same successful filing output, at its end".** `open: awaiting project owner`
   (ledger STP-S-23). Built: the new lines are the last lines of a run that exits 0 (R5; section 11). Gain: the line
   never claims a number for a filing that failed. Cost: the number appears after the after-play and `make results`
   output, not next to the "is new" line. The alternative, printing next to the "is new" line, would print before
   success is known, which the ruling forbids.
2. **A failed run's parks never get the line on a successful rerun.** `open: awaiting project owner` (ledger
   STP-S-24, STP-S-7). Built: R18 as written, which follows "only for company parks this run registered". Gain: no
   state carried between runs. Cost: the player who hits a contracts or transform failure, the common failure after a
   registration, never sees the number on the terminal; the site shows it once the park's rows appear. Numbering those
   parks on the rerun would need the answers file to carry the parks the failed run registered.
