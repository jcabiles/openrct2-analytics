# ADR 0021: hand-built Eleventy and Observable Plot for the showcase website

- Date: 2026-10-08
- Status: accepted 2026-10-08, when all five gates of the site tool smoke spike passed. The project owner approved this decision in advance on 2026-10-07, on the condition that every gate pass (approved item 7 of the spike spec, since removed from the tree and kept in git history). Supersedes ADR 0015 (`docs/adr/0015-showcase-site-tool.md`). json-bignum 0.0.3 was accepted as MIT by the project owner on 2026-10-09, which closes the open question below.
- Amended by ADR 0043 (`docs/adr/0043-showcase-system-fonts-and-story-passages.md`), 2026-11-02.

## Bottom line

The showcase website is built with Eleventy 3.1.6, a static-site generator,
and hand-written pages that draw charts with Observable Plot, filter them with
Observable Inputs and query Parquet in the browser with DuckDB-WASM. Every
package is pinned at an exact version in `package-lock.json`. The deciding
criterion is control of brand and design, and portability into the project
owner's personal site, a Next.js site: plain pages and plain chart code carry
over, while a dashboard framework brings its own look. A throwaway spike
proved the stack works offline under the GitHub Pages path
`/openrct2-analytics/`, with one real chart and one real query page: all five
gates passed on 2026-10-08 (`docs/FINDINGS.md`, the six 2026-10-08 rows).
Observable Framework, the tool ADR 0015 chose, is rejected because it could
not build without the network. The Evidence legacy framework is rejected for
its fixed look, its "Legacy" label and its 918 locked packages. Every rule in
ADR 0015 that does not depend on the tool carries forward unchanged.

## Context

ADR 0015 chose Observable Framework on 2026-10-03 for its built-in
dashboards, with Eleventy as the named fallback. The render spike of
2026-10-07 met the fallback condition: Framework 1.13.4's own client bundle
fetches `npm:react-dom@latest` at build time, and the network guard refused
it in all four guarded builds (`docs/FINDINGS.md`, the four 2026-10-07 rows).
The tool was then chosen for brand and design control and for portability
into the project owner's personal site, rather than for built-in dashboards
(spike spec, Goal; approved items 1 and 7). The smoke spike asked one
question before NEXT 15's build spec (NEXT 15 is the roadmap item that builds
the showcase website): can a hand-built Eleventy site with Plot, Inputs and
DuckDB-WASM, installed from its lockfile, build and show one real chart and
one real query page with no network, under `/openrct2-analytics/`?

## Decision

| Area | Choice |
|---|---|
| Site tool | Eleventy 3.1.6 with hand-written pages. The browser libraries are `@observablehq/plot` 0.6.17, `@observablehq/inputs` 0.12.0 and `@duckdb/duckdb-wasm` 1.33.1-dev57.0, each pinned at one exact version in `package-lock.json` and installed with `npm ci --ignore-scripts`. |
| Browser files | Every browser library is self-hosted from the locked `node_modules`, never a CDN. Plot and Inputs load as script tags; DuckDB-WASM loads its bundles through one hand-written loader that never calls its CDN loader and turns off extension auto-install and auto-load. |
| The one pinned exception | One Parquet extension file, matched to the DuckDB engine inside the locked DuckDB-WASM (engine v1.5.4, `wasm_eh` bundle, the build that uses WebAssembly exceptions), is downloaded once by hand, pinned by SHA-256 (`sha256:4845705bbd69fc9ad52878d96a505c73cae4a6c509822079cc2413e5eb437f95`, 3,218,307 bytes) and self-hosted with the site. It mirrors `https://extensions.duckdb.org/v1.5.4/wasm_eh/parquet.duckdb_extension.wasm`. Without it, `read_parquet` is not in the browser catalog. It is the only browser file not taken from `node_modules`, ruled by the project owner on 2026-10-08. |
| Base path | Every URL a page or script builds starts from the page's base, so the site works under the GitHub Pages path `/openrct2-analytics/`. |
| Carried forward from ADR 0015, unchanged | The rules that do not depend on the tool, as written in ADR 0015's Decision table and Build acceptance tests: pages read Parquet exports of the dbt marts written by a `make` step, never a warehouse file; `make check` rebuilds every export from an allowlist of approved mart relations and compares it with the served copy by row count and a hash of the sorted rows; the published-number mapping gives each published business result its mart query, its in-game source and its dbt reconciliation test; story files in `docs/showcase/story/` are the single source of text for the README and the site (in Eleventy, each story page holds one include); the publication check fails when a unit, clock, sample or "observational" label is missing; and the offline page-load and reproduction acceptance tests apply to this tool. |

## Evidence

All five gates passed on the judged run `t6-judged-retry1` (2026-10-08, a
fresh clone at code commit 623d0dd), as recorded in the spike's `gates.json`.
The CI half did not run: GitHub Actions could not start jobs because billing
is unavailable, so it is recorded as unavailable, not passed, and the local
run decides the gates.

| Gate | Verdict | What passed |
|---|---|---|
| G1, offline build from the lockfile | pass | The four approved packages at exact versions; `npm ci` and `npm ls` exit 0; the lockfile digest is unchanged; every install connection is npm's own to the registry; `build-1` exits 0 with an empty network-guard log and three pages. |
| G2, GitHub Pages base path | pass | The prefixed build exits 0 with an empty guard log; every root-relative path in the built site starts with the prefix; every request is answered 200 under the prefix. |
| G3, offline page view | pass | Zero requests to any host but 127.0.0.1 on all three pages and on the three failure passes (the Parquet file, the worker and the WASM file each answering 404); zero console errors; no built file names an outside URL. |
| G4, one real chart | pass | One chart with one dot per exported row; mark titles equal the export row for row; all five labels present, including "pilot"; the page-code lint and its self-test exit 0. |
| G5, real Parquet offline | pass | The Parquet response digest equals the export's; the self-hosted extension file equals the pin (the extension check rests on the SHA-256 of the extension response body, captured in the separate labelled run `t6-measure-2` and equal to the pinned hash in all three renders; the verdicts stay bound to `t6-judged-retry1`); the default query shows 108 rows; each game month shows its count, and "all months" restores 108. |

One earlier attempt, `t6-judged`, was inconclusive, not failed: Chrome did
not start in the worker sandbox, so G2 to G5 had no browser reading. The
sample is rehearsal data: one park, three headless sessions, no player
(observational). The spike code lives on the unmerged branch
`spike/site-bakeoff-code` (final code commit 459269c, which only hardened the judge and changed no evidence) and is never merged; its report is
`spike/site-bakeoff/REPORT.md` on that branch. Costs are in the 2026-10-08
cost row of `docs/FINDINGS.md`.

## Rejected alternatives

- **Observable Framework (ADR 0015's choice).** Its own client bundle fetches
  `npm:react-dom@latest` at build time, so it cannot build from the lockfile
  with no network; the project owner ruled this a Framework limit on
  2026-10-07 (`docs/FINDINGS.md`, the four 2026-10-07 rows). The planned
  warm-cache retry is not needed, because Eleventy passed.
- **Evidence, legacy npm framework.** Its components carry their own look,
  which resists theming to the project's brand; its maker labels it "Legacy";
  and its lockfile holds 918 packages, against 221 for the Eleventy set. Its
  locked set would have been the fallback had an Eleventy gate failed on a tool limit; no
  gate failed, so it was not built.
- **The other tools ADR 0015 rejected** (Quarto, Evidence Core, Observable
  Notebook Kit, marimo, and the server-based dashboard tools) stay rejected
  for the reasons ADR 0015 gives.

## Consequences

- **What the choice gains:** full control of markup, styles and chart code,
  so the site can take the project's own brand and its pages and charts can
  move into the project owner's personal site; a small locked dependency set
  (221 lockfile entries); and a build measured at 0.444 s.
- **Costs accepted:** every dashboard, filter and the DuckDB-WASM loader is
  hand-written, because Eleventy has no chart, input or data layer; one
  browser file outside `node_modules`, held to its pinned hash; a `/query/`
  page of 40,643,870 bytes uncompressed (39,873,217 bytes encoded, run
  `t6-measure-2`), almost all of it DuckDB-WASM; 9
  `npm audit` findings (4 moderate, 5 high) and 4 lockfile licenses outside
  the allowlist (BlueOak-1.0.0, Python-2.0, Unlicense and one package with no
  license field), recorded and not blocking.
- **What the spike did not test:** looks and theming, the real marts, the
  story-file wrappers and README generator, the published-number mapping,
  hosting and CI. NEXT 15's build spec carries ADR
  0015's acceptance tests for these.
- **How we would know this is wrong:** the real site cannot pass ADR 0015's
  offline page-load or reproduction tests; hand-writing the v1 dashboards
  costs more than a framework would save; or a DuckDB-WASM upgrade cannot be
  matched with a pinned Parquet extension. Any of these reopens this record.

## Needs owner decision

One open question for NEXT 15: the license of `json-bignum` 0.0.3, which
`apache-arrow` pulls in. Its `package.json` declares no `license` field, only a
legacy `licenses` entry naming MIT, and the package folder holds a `LICENSE`
file (an MIT-style text, copyright Datalanche, Inc.). The project owner decides
whether that is enough before NEXT 15 builds; no gate verdict depends on it.

Ruled: the Parquet extension question, by the project owner on 2026-10-08. One
pinned, self-hosted extension file is allowed.
