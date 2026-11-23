# ADR 0015: Observable Framework for the showcase website, with one source of text for the README

- Date: 2026-10-03
- Status: superseded 2026-10-08 by ADR 0021 (`docs/adr/0021-showcase-site-tool.md`), which picks hand-built Eleventy after the Eleventy spike passed all five gates. History: accepted 2026-10-03 and confirmed 2026-10-06 together with the jszip MIT option; reopened 2026-10-07 because the render spike met the fallback condition (`docs/FINDINGS.md`, the four 2026-10-07 rows). The original sign-off: the project owner approved on 2026-10-03 Observable Framework as an npm dependency with telemetry off, Eleventy the fallback; `@observablehq/plot` and `@duckdb/duckdb-wasm` approved, pinned in the lockfile, nothing loaded from a CDN at view time.

## Bottom line

**Reopened 2026-10-07:** the render spike failed question 1 on a Framework limit, so the fallback condition below is met; Eleventy is the fallback, and this record is superseded by the site-tool decision made after the Framework warm-cache spike (roadmap NEXT 15b) and/or the Eleventy spike (NEXT 15a) (see the result note at the end).

The showcase website should be built with Observable Framework, an
ISC-licensed static-site generator for data pages, with three npm packages
pinned at exact versions in `package-lock.json`: `@observablehq/framework`,
`@observablehq/plot` and `@duckdb/duckdb-wasm` (the latter two approved by the
project owner on 2026-10-03). The deciding criterion is built-in dashboards:
every dashboard group in the roadmap's v1 list (executive reporting, ride
profitability, stall profitability, and the stack's "interactive dashboards")
needs charts over mart rows, inputs that filter them by park, company year,
ride or stall, and a browser DuckDB to read the marts. Framework is the only
finalist with charts, inputs, reactive layouts and page loaders built in. The
browser DuckDB does not come from Framework: its built-in DuckDB client loads
apache-arrow at its latest release outside the lockfile, so pages import Plot
and DuckDB-WASM by bare name from `node_modules` and read Parquet through one
hand-written DuckDB loader, as Eleventy would. Accepting the unpinnable import
as a named risk was the alternative not taken ("Needs owner decision", kept as
history).
Eleventy, which locks every library but has no chart layer, is the fallback.
Whichever tool is adopted must pass two acceptance tests: the site reproduces
from an empty download cache after upstream releases change, and every page
loads with networking disabled. Every business result in a chart, table or the
README is a mart column traced to its in-game source by a dbt reconciliation
test, charts show mart rows as delivered, and the README and the site share
one source of text, checked at the source. Evidence, the 2026-09-27 default, is
not adopted now, because its open-source framework was replaced on 2026-08-26.
The evidence is in `docs/ai-dlc/reports/showcase-site-tool--findings.md`.

## Context

The roadmap's north star is a local website and a full README that a hiring
reader understands in 30 seconds and can verify in 30 minutes (roadmap NEXT
15, the showcase). The site needs narrative pages, the dashboards in the
roadmap's "v1 is done when" list over DuckDB, direct querying, a local build,
and room for a semantic layer and an AI chat later. Evidence was chosen on
2026-09-27 because it built static business-intelligence pages from SQL and
markdown. Since then its maker has replaced that npm framework with Evidence
Core, a `curl`-installed binary that sends usage data by default, is
documented as self-hosted through a Docker server, and documents its local
flat-file connector only for Studio's managed warehouse. One research lane on
2026-10-03 compared fifteen tools, and three blind reviews from another model
vendor corrected the comparison. On the same criteria, Framework leads on
dashboards, Eleventy on lockability (every dependency pinned, so a clean build
reproduces it), and Quarto on narrative features. No tool was installed, so
sandbox, reproducibility and network-free behaviour remain to be tested.

## Decision

| Area | Choice |
|---|---|
| Site tool | Observable Framework, with `@observablehq/framework`, `@observablehq/plot` and `@duckdb/duckdb-wasm` each pinned at one exact version in `package-lock.json`. The Makefile sets `OBSERVABLE_TELEMETRY_DISABLE=true`. Every browser import is pinned through `node_modules` and the lockfile: pages import libraries by bare name, which Framework bundles from the locked `node_modules`, including `@observablehq/plot` and `@duckdb/duckdb-wasm` (approved 2026-10-03), and read Parquet through one hand-written DuckDB loader. Framework's built-in DuckDB client and SQL blocks go unused, because they load apache-arrow at its latest release outside the lockfile (Framework 1.13.4's source); that choice is recorded under "Needs owner decision", kept as history. Every DuckDB extension file a page needs is named in the config and copied in with a recorded checksum, or listed as unpinnable. |
| Fallback | Eleventy, with Plot, Inputs and DuckDB-WASM as npm packages locked in `package-lock.json`, under the same acceptance tests. |
| Dashboards | Framework pages with Observable Plot and inputs over DuckDB-WASM; no server. Charts are declarative: each chart is a committed spec naming its mart relation, the columns it plots, the input that filters it and its title key, and one shared chart function runs the spec's select-and-filter query and passes the rows to Plot unchanged. |
| Dashboard data | A `make` step writes Parquet copies of the dbt marts with the pinned `duckdb`; pages read only those files, because Framework's DuckDB-WASM cannot open a DuckDB 1.5.5 file. |
| Published numbers | The rule covers business results, meaning figures measured from the parks' data (visitors, money, ratings, units sold, and anything computed from them), in charts, tables and the README. Each is a mart column. A committed mapping gives, for each published business result, its mart query, its in-game source (for example a monthly-statement line, cash, the park rating or a ride's ratings as the plugin recorded them), and the dbt reconciliation test that compares the modeled value with that source and fails `make check` when they drift (roadmap, guardrail "the numbers match the game"); a result computed from several values names the source and test of each input. README results are generated from the mapped queries, and dashboard figures are asserted against them. Explanatory numbers in story text, such as game-calendar constants, rules and measured plugin timings, are not mart columns; they pass when their sentence cites a source. `make check` also rebuilds every export from an allowlist of approved mart relations and compares it with the served copy by row count and a hash of the sorted rows. |
| Chart calculations | A chart displays mart rows as delivered; no arithmetic happens in chart JavaScript or browser SQL. A source check in `make check` rejects page and chart code that calls Plot directly, uses a Plot transform that groups, bins or reduces, maps over data rows, or writes its own query, so the only route to a chart is a spec. The shared chart function has a Node test asserting that the marks it builds carry the mart rows unchanged. |
| README and site text | Five markdown story files in `docs/showcase/story/` hold all story text. A standard-library script generates `README.md` from them, followed by the "Run it yourself" section of `docs/showcase/story/README.md`, which also becomes the only source of today's `README.md` run instructions when the script is built; `make check` compares the result byte for byte and fails when a `make` target named in that section is missing. Each story page (wrapper) contains only the include directive for its story file: in Framework a one-line page loader, in Eleventy one Liquid include. The site-text check fails on any other text in a wrapper, and unless each story file is included exactly once. Dashboard pages hold only chart specs, whose titles and annotations come from the story files or the metric catalog. Links in story files are root-relative and are resolved in both outputs. No rendered HTML is compared. |
| Direct querying | A documented page and README section with read-only `duckdb` commands; the DuckDB UI is offered as an optional extra. |
| Semantic layer | The metric catalog stays the one definition; MetricFlow later writes metric tables that the site reads like marts. |
| AI chat | A separate local service in the roadmap's LATER bet (governed metrics, then an AI chat); the site links to it. |
| First screen | A one-sentence big idea, one line on the game, one line on the company, one headline chart labelled with its sample, unit and clock, and links to the four named sections and "How this was built". The README opens the same way. |
| Before adoption | A short spike builds a two-page site with one chart over a mart Parquet file, inside the agents' sandbox and in CI, records the resolved version of every browser import, and records the size of any download cache. It must pass two adoption acceptance tests, which apply to whichever tool is adopted, including Quarto if it becomes the fallback. **Reproduction:** with every browser import pinned through `node_modules` and the lockfile or listed as unpinnable, the site is rebuilt from a fresh clone with an empty download cache after at least one imported library, or a dependency of one, has published a newer latest release than the recorded build used; the served files match the recorded build except for listed unpinnable imports. If no such release has happened by the spike, the test is repeated before v1 ships. **Offline page load:** every built page, loaded with networking disabled, makes no network request, and any unintended remote import or DuckDB extension load is rejected. "Runs locally" (served from this machine, the roadmap's requirement) is met by any static build; network-free viewing is the stricter test. |

## Build acceptance tests

The site build is done only when these pass on the rehearsal data; none was
run during the research. Each runs inside `make check`.

1. One value changed in a served export, with its mart intact, fails.
2. An export of a relation not on the allowlist fails.
3. For each published business result, changing its in-game source or its
   modeled value so that the two drift fails through that result's
   reconciliation test; a published result whose mapping entry lacks a source
   or a test fails.
4. A calculation added in chart code, such as a value scaled in a mark or a
   Plot grouping transform, with the mart, the export and the mapping
   unchanged, fails.
5. One README result changed with the marts unchanged fails.
6. A game-calendar constant whose sentence cites its source passes; an
   unmapped business result in a chart, table or the README fails.
7. A contradictory paragraph added to a wrapper that keeps its single include
   fails; a chart title typed into page code fails; a page that omits its
   story file fails; a valid formatted paragraph in a story file passes; a
   valid root-relative document link passes.
8. The generated README contains the "Run it yourself" section and the
   retained run instructions; editing either in `README.md` without its
   source fails, and a `make` target named there that does not exist fails.
9. Removing each unit, clock, sample or "observational" label once fails.

## v1 requirements this site must carry

Each v1 requirement (roadmap, North-star outcome and "v1 is done when") has a
named home and an acceptance check. The site is not done until every check
passes on the rehearsal data.

| Requirement | Where it lives | Acceptance check |
|---|---|---|
| Cold read in 30 seconds and 5 minutes | The first screen, then the four sections, each story file at most 200 words of body | A blind agent persona (recruiter, hiring manager) and at least one real person each read the site and README cold and state what the roadmap's cold-read test asks: the game and the company from the first screen; the rules, timeline, analytics needs, stack and verification after 5 minutes. |
| Runs locally | A `make` target that builds and serves the site | The site is served from this machine with no hosted service; network-free viewing is checked by the offline page-load test above. |
| Trace one headline number end to end | The stack section, "Follow one number" | A page traces the headline number from its game event through the contract, staging, intermediate and mart models to its dashboard, with links to each file; a technical reviewer repeats it in 30 minutes. |
| Direct DuckDB query | The "Query the warehouse" page and README section | The documented read-only commands run as written against the warehouse built from the committed sample. |
| One-command run from the committed sample | README "Run it yourself", sourced from `docs/showcase/story/README.md` and labelled planned until the command exists | From a fresh clone, the documented command builds the pipeline and the site from the committed sample. |
| The numbers match the game | The published-number mapping and its dbt reconciliation tests | Every published business result names its in-game source and the dbt reconciliation test that fails `make check` on drift; build acceptance test 3. |
| At least two parks on one company calendar, labelled rehearsal | Every dashboard and the first screen | Every page showing data carries a "rehearsal data" label and its park sample; the dashboards show at least two parks on one company calendar. |
| Executive reporting | Dashboards: year-over-year; P&L | Year-over-year visitors, revenue, profit and operating costs, per park and for the company; a monthly and annual P&L that reconciles to the game's ledger and cash by a dbt test; the visitor-growth finding; average park rating across parks. |
| Ride profitability | Dashboards: ride ratings and profit; pricing | Profit by ride type, excitement, intensity, nausea, age and coaster statistics; popularity against ratings; the pricing model labelled observational. |
| Stall profitability | Dashboards: stall units; weather | Units sold per single-item stall; drivers of stall profit, including the weather effect on umbrella sales, labelled observational. |
| The stack story | The stack section | Shows the versioned data contracts and their CI gate, the separate development, test and production warehouses, the layered dbt models ending in a star schema, the reconciliation tests and the mutation tests, each linked to its file or test. |
| Four named narrative sections | Story files in `docs/showcase/story/` and site pages | The game; the company timeline; the analytics strategy; the stack. Each appears in both the site and the README, enforced by the story-file checks above. |
| "How this was built" | Its own story file and page | States that AI agents wrote most code and documents, what the project owner decided, how blind reviewers checked the work, and two or three real examples of agent output that review rejected or corrected, each naming its ledger row and linked to the change it caused (ADR 0012, Presentation). |
| Only a few process documents | Links from "How this was built" and the stack section | The site links only a few process documents, each to the change, test or failure it governed (roadmap NEXT 15, from ADR 0012). At v1, a review of every process-document link on the site finds that each names the change, test or failure it governed. |
| Units, clocks, samples and causal labels | Every published chart, table, README result and analysis | Every metric names its unit and its clock (game day, company date, or wall-clock hour); every analysis states its sample (parks, players) and says "observational" unless an experiment design backs it. A publication check in `make check` fails when any label is missing; build acceptance test 9. |

## Rejected alternatives

- **Eleventy as the first choice (it is the fallback).** It locks every
  build-time and browser library in `package-lock.json`, is actively
  developed, and has native includes, but it has no chart, input or data
  layer, so every v1 dashboard, its filters and a DuckDB-WASM loader would be
  hand-written JavaScript. It represents general static-site generators such
  as Astro and Hugo, which share that gap. If lockability is weighed above
  built-in dashboards, it wins outright.
- **Quarto.** It writes the best narrative pages and has a documented
  client-side dashboard format, but it adds a binary outside every lockfile,
  so it ranks behind Eleventy as a fallback. Whether its OJS pages load files
  from external hosts when opened is an unverified risk: the evidence is
  Quarto's external-host list and an open issue reported against Quarto
  1.0.23 in 2022, which also describes a local-copy workaround, and no current
  build was tested. If Framework and Eleventy both fail, Quarto is next and
  must pass the same two acceptance tests, including the offline page load.
- **Evidence, legacy npm framework.** Its maker has moved off it, and its
  migration path drops features.
- **Evidence Core, for now.** It is five weeks old, cannot be pinned by a
  lockfile, and sends usage data unless disabled. Its flat-file connector is
  documented for Studio's managed warehouse, so reading local Parquet without
  Studio is unverified, and its documentation disagrees on whether a build is
  static. Whether its own metric files would add a second metric definition
  depends on that verification. It is re-checked when the site build starts.
- **Observable Notebook Kit.** It is a technology preview. Framework's
  maintainer recommended in March 2026 that Framework users migrate to it;
  the evidence does not show that it meets this site's requirements, so the
  recommendation is recorded as a maintenance risk for Framework, not as a
  reason to adopt Notebook Kit.
- **marimo.** It is good for interactive SQL and lockable in `uv.lock`, but a
  set of notebooks is not a narrative site, and in-browser Python is slow to
  start for a first impression. It remains a candidate for a later "query it
  yourself" notebook.
- **Rill, Streamlit, Dash, Vizro, Metabase, Superset, Lightdash, Shaper.**
  Each needs a running server and has no static build. Most write narrative
  poorly, and Rill and Lightdash bring metric layers of their own.
- **Checking only a generated README, comparing rendered pages with the story
  text, or a third-party generator such as cog.** The first leaves the site
  unchecked. The second rejects valid formatting and cannot see chart titles
  that render in the browser. The third adds a dependency for a job the
  standard library does.
- **Committing Framework's download cache to make builds reproducible.** It
  puts third-party files, possibly tens of megabytes of WebAssembly, in the
  repo, and it cannot pass the reproduction test, which starts from an empty
  cache.

## Consequences

- **What the choice gives up:** Quarto's richer narrative features (includes,
  cross-references, callouts), Eleventy's lockfile-only reproducibility, and
  an actively developed tool, since Framework is supported but no longer
  developed and its maintainer recommends a move to Notebook Kit; and
  Evidence's ready-made components and business-intelligence-as-code signal.
  The site also cannot compute an arbitrary metric breakdown at view time,
  only what the marts and metric tables hold, and a chart can show only what a
  spec can name.
- **Costs accepted:** one npm package with 44 direct dependencies; explicit
  bare-name imports from `node_modules` instead of Framework's implicit ones;
  a telemetry opt-out in the Makefile; one more `make` step for the Parquet
  copies; about 150 lines of script and tests for the README and site checks;
  a chart-spec format, its shared chart function and its source check; and
  the published-number mapping, reconciliation, export and publication-label
  checks.
- **Roadmap:** NEXT 15 is blocked on the project owner's sign-off. The
  narrative drafts are in `docs/showcase/story/` for the project owner's
  review and become the story files unchanged. Item 3e's mention of Evidence
  (the dashboard line, folded into the website) is updated when this record
  is accepted.
- **How we would know this is wrong:** the spike shows that Framework cannot
  build in the agents' sandbox or in CI, that it fails the reproduction test
  with no acceptable way to pin or list the imports that changed, or that a
  built page needs the network; the v1 dashboards need interactivity that a
  static Framework page or a chart spec cannot give; Framework stops working
  on the repo's Node version; or Evidence Core meets the re-check conditions
  in the findings report (a project with no Studio account reads local mart
  Parquet and builds offline, a static or account-free local build, and
  pinnable versioned binaries) while offering clearly better dashboards. Any
  of these reopens this record, and the first three move the site to
  Eleventy.

## Needs owner decision

**Decided 2026-10-03:** both items were decided by the project owner: item 1, Observable Framework with telemetry off and Eleventy the fallback; item 2, the recommended route, with `@observablehq/plot` and `@duckdb/duckdb-wasm` approved as packages pinned in the lockfile and imported by bare name from `node_modules`, so nothing loads from a CDN at view time.

1. **Sign off Observable Framework as an npm dependency** (fallback Eleventy;
   if lockability outranks built-in dashboards, Eleventy wins). Recommended.
   Gain: built-in charts, inputs, reactive layouts and page loaders, so the v1
   dashboards need the least hand-written code. Cost: a tool that is
   supported but not developed, one npm package with 44 direct dependencies,
   and the checks listed under Consequences.
2. **The unpinnable import.** Framework's built-in DuckDB client and SQL
   blocks load apache-arrow, a dependency of DuckDB-WASM, at its latest
   release through Framework's `npm:` path, which neither `node_modules` nor
   `package-lock.json` can pin (report section 1.1, from the 1.13.4 source).
   - **Import DuckDB-WASM and apache-arrow by bare name from `node_modules`
     (recommended).** Gain: every browser import is locked, and the
     reproduction test needs no exception. Cost: one shared DuckDB loader
     written by hand, as Eleventy would need, and Framework's built-in DuckDB
     client and SQL blocks go unused; the chart specs already route every
     query through one shared function, so pages lose nothing they use.
     Framework's lead over Eleventy then rests on its built-in charts, inputs,
     reactive layouts and page loaders.
   - **Keep the built-in DuckDB client and accept the import as a named
     risk.** Gain: no hand-written loader. Cost: a rebuild after an
     apache-arrow release can serve different library code from the recorded
     build, which the reproduction test excuses rather than catches.

## Result note (2026-10-07)

The fallback condition named above is met, so ADR 0015 is reopened and the site tool is
undecided: Framework if the warm-cache spike (roadmap NEXT 15b) passes,
Eleventy, its named fallback, otherwise. Eleventy is not adopted: it needs
its own spike (NEXT 15a) and the project owner's approval of `@11ty/eleventy`. The source
is `spike/site-render/summary.json` on the unmerged branch
`spike/site-render-code`, summarised in the four 2026-10-07 rows of
`docs/FINDINGS.md`.

**Measured findings.** Question 1 failed: Framework 1.13.4's own client bundle
fetches `npm:react-dom@latest` at build time, and the network guard refused it
in all four guarded builds, each starting with no Framework npm cache
(`build-1` to `build-3` and the telemetry build each exited 1). No build
completed, so no dist was judged. The GitHub Actions half did not run: no job
started.

**Rulings by the project owner, 2026-10-07.** Question 1 is a fail on a
Framework limit, and the Eleventy fallback fires. Questions 2 and 3 are
inconclusive, question 4 is partial, and the CI half is `ci-unavailable`.
