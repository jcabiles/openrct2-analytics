# Spec: port the latest mockup into the site

status: revised after review round 1 (2026-11-02); not yet re-reviewed.

Written from the roadmap item "Port the latest mockup into the site" (`docs/ai-dlc/roadmap/park-company.md`, lines
473-477: "L474" is its done-line, "L475" its preflight question, "L476" its exclusions, "L477" its verify line), the
neighbouring roadmap lines 462 ("v1 shows company play data only"), 465 ("Department figures") and 478 ("Company data
to the site"), the project owner's rulings of 2026-11-02 (cited "O1" to "O7", listed under "Sources"), the
director's rulings on the first review round (`docs/ai-dlc/ledger/site-mockup-port.md`, cited by finding ID, for
example "ledger C-02"), and the contract map `docs/ai-dlc/contracts/site-mockup-port.md` (cited "CM §n").

The design source is **the frozen mockup copy given in the ticket brief** ("the frozen copy", SHA-256
`09560046226e7cec53e6b8dd0f92d8a5a6ec0ed76037ecbca1d7390f6a2fa021`). It is git-ignored and never committed; line
numbers below written "mockup :n" are lines of that file.

## Bottom line

The showcase page is rebuilt to look and read like the picked mockup: its sections, top menu, layout, "The build
crew" diagram, chart look and draft copy become Eleventy templates (Eleventy is the static-site generator the site
already uses). Charts keep using Observable Plot, the chart library the site already loads, styled to the mockup's
colours, type and axes, so every page-check rule stays in force. Every number about the park company comes from the
export files in `site/_data/` (ADR 0045 grew them to six files, of which this page reads three) or shows a visible "figure pending" box; the mockup's made-up facts, its
rehearsal results and its findings drawn from made-up data are removed or shown as pending. The page loads nothing
from the internet: the animation library and web fonts are dropped for system fonts.

The work is cut into seven tickets in an order where `make check` passes at the end of every ticket. It is done when
`make check` passes, builds against empty data and two different test data sets prove every figure follows the data,
and a reviewer has compared the built page with the frozen copy. One question is left for the project owner (the
author label in the menu) and one default (park display names); neither blocks building.

## Sources

- **O1-O7, the project owner's rulings of 2026-11-02**: O1 the mockup is final; O2 drop GSAP (the animation library)
  and web fonts, use system font stacks, add no dependency; O3 every page-check rule is kept (pinned sentences and
  tables may be rewritten); O4 no CSS or JavaScript file over 500 lines; O5 "no illustrative values" is proved by
  builds against empty data and two test data sets; O6 desktop only (amended: the phone layout is restored, ADR 0046); O7 `make check` is not loosened and the
  `site/_data/` file names and shapes stay the export contract.
- **Director's rulings** (ledger): C-02 charts stay on Plot, PC12 unchanged, no dependency change; C-08 / R-1 every
  ticket ends with a green `make check`, at most about eight tickets with disjoint files, the page-check groundwork
  first; the remaining rows are cited where they apply.
- **ADR numbering**: a parallel plugin branch claims ADR 0042, so this item's new ADR is 0043.

## Goal

Give the portfolio site (CLAUDE.md:3, "a portfolio analytics stack for a theme park run as a business") the design the
project owner picked, so hiring managers, recruiters and interviewers see the final layout now, and so company play
figures fill it later without another redesign (L474; line 478).

## Requirements

Each requirement cites its source. A **figure region** is an element carrying `data-figure="<id>"`; it is **live**
when its values come from `site/_data/` and **pending** when no export holds them yet.

### Design fidelity

- **R1. Sections and order.** The page renders, in the frozen copy's order: the top menu (`#topbar`), the hero with
  its drawn park scene and section coupons, "The company and its business rules" (`#enterprise`), "Extracting data
  from the game" (`#extract`), "Data and analytics infrastructure" (`#infra`), "How it was built" with "The build
  crew" diagram and its hover detail (`#built`), "The board meeting" (`#story`), "Business insights" with its
  Finance, Operations and Attractions views (`#insights`), and the footer. Source: L474; O1.
- **R2. Templates, not one file.** The markup is Nunjucks templates (Eleventy's template language) under
  `site/_includes/`, assembled by `site/index.njk`. Source: L474 ("as Eleventy templates (ADR 0021)").
- **R3. Draft copy carried as written**, except the edits in "Required text edits", each forced by a kept rule or by
  the truthfulness rulings. Copy rewrites are not in this item. Source: L474, L476; ledger C-01.
- **R4. Chart look on Plot.** Every chart is drawn with Observable Plot, styled to the frozen copy's chart look
  (colours, type, axis and grid treatment, bar shapes, legends) through CSS classes and the colour tokens of R18.
  The frozen copy's hand-written SVG chart helpers are not ported. Drawings that are not charts (the hero park scene,
  "The build crew" diagram, the infrastructure track) stay SVG markup and modules. Source: L474 ("chart styles");
  ledger C-02; ADR 0021 (Plot for charts).
- **R5. Desktop only (amended by ADR 0046: the phone layout is restored and the rule below no longer applies).** CSS rules and script branches that apply only below 1024 px wide (the frozen copy's own
  `NARROW` threshold) are dropped. Rules that apply at 1024 px and wider are kept, including the topbar's
  `max-width:1099px` rule (mockup :418), which applies between 1024 and 1099 px. The bodies of `min-width` queries at
  760, 900 and 960 px are kept, since every desktop width satisfies them. Both `prefers-reduced-motion` rules are
  kept. Source: L474, L476, O6; ledger R-16.
- **R6. Light mode only.** The `prefers-color-scheme: dark` block is dropped. `<html>` keeps both
  `data-palette="rct-exact"` and `data-theme="light"`, because the palette block's selector needs both
  (mockup :851-872). Source: CM §1, §6.7; `docs/showcase/design-mockups.md`; L476; ledger C-07 / R-11.
- **R7. Controls rendered, not finished.** The range brush, its presets, the park switch and the department tabs are
  ported as the frozen copy has them, but their months, years and parks come from the export rows; the frozen copy's
  "All 16 months", "Mar 2000 to Oct 2001", "Company year 2001", "Park 2" and "2000 2001" are not typed in. A preset or
  park choice with no rows is disabled and labelled "figure pending". Finishing the controls is the LATER item.
  Source: L476; `docs/showcase/design-mockups.md` ("Known gaps, deferred"); O5.

### Truthful copy

- **R8. No made-up fact or finding.** Every sentence that states a business fact or a finding is either driven by an
  export or sits in a pending figure region. Rehearsal results and the rehearsal footer are removed. The only numbers
  kept as plain copy are those in the table "Numbers kept as copy", each a measurement or rule of the pipeline with a
  checkable source in the repository. Source: ledger C-01 / R-4 / R-5 / R-12 / C-06; L462; L474 ("never an invented
  number").
- **R9. Business figures read the exports.** A displayed number about the park company is an export cell, formatted
  (dollars, month label) and nothing else; the page computes no sum, ratio or growth rate from export values, in the
  browser or at build time. Axis ticks, month labels, year lists, period ranges and park order may be derived from
  row keys. A figure that needs any other value is pending. Source: L474; `site/exports.toml` header ("computes
  nothing"); line 462.
- **R10. Unit lines follow the data.** Each figure's unit line names its unit and its clock with the literal
  prefixes `unit:` and `clock:`. Its period (the dates, months or company year it covers) is derived from the
  figure's rows when live and reads "period: figure pending" when pending; no unit line carries a year as fixed
  text. Source: invariant 3; ledger C-01 (unit lines), R-9.

### Data and "figure pending"

- **R11. One pending form.** Every figure region carries `data-figure="<id>"` and `data-figure-state="live"` or
  `"pending"`; the figure macro (`site/_includes/figure.njk`) also writes `data-figure-unit` on the unit line and
  `data-figure-body` on the body. A pending region keeps its heading and unit line, and its body shows exactly the
  text "figure pending" and no digit. Every element that shows a number taken or derived from the exports sits inside
  a figure region, including step values, the hero's company-year range, legends and the controls' month, year and
  park labels. Source: L474; O5, O6; CM §6.5; ledger R-9.
- **R12. Always-live table regions.** The three tables of PC6 and PC7 are separate figure regions that are always
  live. The month table and the park-year table render with zero body rows when their export is empty. The
  company-year region always shows, with the sentence "No company year has closed yet." when `company_year.json` has
  no rows, and the `#company-year-table` element is then absent, as PC8 requires. Source: O3; ledger C-09.
- **R13. Live today.** With the committed sample these are live: the Finance "Operating profit by month" chart
  (mount `#park-month-chart`) and its month table `#park-month-table`; the park-openings list's Park 1 line (R16);
  board-meeting step 1's chart and month values; and the evidence block of R14. Step 2 is live only when
  `company_year.json` has at least two rows (its sentence compares two company years) and pending otherwise, as
  today. Everything else is pending. Source: CM §2; O6; ledger C-01 (R-4c).
- **R14. The evidence block.** The two year tables (`#company-year-table`, `#park-year-table`), the "No company year
  has closed yet." sentence and the four pinned sentences (close rule, reconciliation, first month, sample) keep
  their current text and table layout, restyled with the frozen copy's table classes, in one block inside `#infra`
  beside the balance check. Source: O3; CM §6.2.
- **R15. Embedded rows.** Each export a module reads is embedded once as
  `<script type="application/json" id="<name>-data">` (`park-month-data` exists; `park-year-data` and
  `company-year-data` are added only if a module reads them). Only `site/assets/js/data.mjs` and
  `site/assets/park-month-chart.mjs` read these blocks. Every module draws nothing, without an error, on zero rows.
  Source: CM §5; O5; ledger R-8.
- **R16. Park openings follow the data.** The `#enterprise` list "Parks, by opening year" is a figure region: one
  line per park in `park_month.json`, giving the company month of that park's first row, plus one line stating the
  rule for the next park ("opens the March after the latest park goes to autopilot; no date until then"). The frozen
  copy's "Park 2 opens in March 2001" and "Park 3 is unbuilt" lines are not carried. Source: ledger C-01; roadmap
  line 89 (the company timeline rule).
- **R17. Park labels.** Parks are labelled "Park 1", "Park 2" and so on by the order of their first company month,
  then `park_id`; the export carries no park name. Source: CM §6.4; see "Needs owner decision".
- **R18. The export contract is unchanged.** `site/_data/` keeps exactly its three files with their current names,
  columns and shapes; `site/exports.toml` does not change; no file is added to `site/_data/` by this page's work.
  ADR 0045 later grew `site/_data/` to six export files, of which this page reads three. Source: O7; CM §6.9.
- **R19. No illustrative values committed.** No tracked file in the repository (`git ls-files`) holds the frozen
  copy's invented identifiers: the second park's invented ID, the invented ride names in its `rides` rows, or its
  embedded data rows. The scan stores SHA-256 digests of these strings, never the strings. Tracked docs that spell
  the invented park ID today (`docs/ai-dlc/contracts/site-mockup-port.md:51`) are rewritten to name it without
  spelling it. The frozen copy's first park ID is not invented: it is the earlier rehearsal sample's park ID, cited in
  dated records (for example `docs/ai-dlc/specs/two-park-capture.md:79`), so the tree scan does not forbid it; the
  built page instead shows no park ID that the served exports do not hold (PC16). Game vocabulary in the frozen copy
  (ride types such as "Wooden Roller Coaster", stall items such as "Cola") is not invented and not forbidden. Markup
  and copy may be committed. Source: L474; `docs/showcase/design-mockups.md` ("Nothing from the mockups enters the
  repository", read as the roadmap clarifies it); ledger C-05.

### Page text sources

- **R20. Story files are the single source of section prose.** Every section's prose lives in a story file under
  `docs/showcase/story/` as named passages marked `<!-- passage: <id> -->`; templates render a passage through one
  shortcode built on Eleventy 3.1.6's built-in RenderPlugin (no new dependency). Each figure's heading, unit line and
  the sentence pattern that carries its values live in the figure registry (`site/figures.mjs` and
  `site/figures/<section>.mjs`). A template holds markup, labels of at most three words, and nothing else; a module
  holds no prose. Prose the frozen copy builds in script (`STEPS`, the navigation list, the stack detail, the crew
  popovers) becomes passages rendered at build time. Source: ADR 0021 `:46` ("story files in `docs/showcase/story/`
  are the single source of text"); ledger C-03 / R-10.
- **R21. Story files and sections.** The five existing story files take the frozen copy's text for the sections
  whose topic they hold, replacing their earlier drafts (git history keeps those): `the-game.md` the hero, top menu
  and footer; `the-company-timeline.md` `#enterprise`; `the-stack.md` `#extract` and `#infra`;
  `how-this-was-built.md` `#built`; `the-analytics-strategy.md` `#story` and `#insights`. `README.md` in that folder
  keeps its index and drops its "All data are rehearsal data" line. Source: ledger C-03 / R-10; L462.

### Offline, motion, colours and file size

- **R22. Offline.** The page and its modules load nothing from another host. GSAP, ScrollTrigger and the Google Fonts
  are removed; the font tokens use the frozen copy's own system fallbacks (the `system-ui` sans stack and the Georgia
  serif stack); no font or image file is added. Plot and d3 stay self-hosted from the locked `node_modules`, as
  today. No dependency is added or removed. Source: O2; ADR 0021 ("never a CDN"); CM §3; ledger C-02.
- **R23. Motion without GSAP.** Only the hero park scene keeps moving: its `requestAnimationFrame` loop (mockup
  :2270) runs and stops with the pause control and under `prefers-reduced-motion`. Everything the frozen copy animates
  with GSAP takes its existing no-GSAP path (`HAS_GSAP` false): tweens and fades apply instantly, and the
  infrastructure train sits at its last stop and does not move (mockup :2649-2650). The extraction roll's three
  buttons (mockup :2423-2452) work with their instant result. The board meeting's steps keep advancing on scroll
  through the browser's built-in `IntersectionObserver`; no scroll library replaces ScrollTrigger. Source: O2;
  ledger R-2.
- **R24. Colours in one place.** Every colour literal (hex, `rgb()`, `hsl()`) and every `color-mix()` in a `.css`,
  `.mjs` or `.njk` file under `site/` lives in `site/assets/css/tokens.css`, which holds the five seed colours of the
  frozen copy's palette block (mockup :851-872), the derived tokens, and the scene and vendor colours; the one
  `color-mix(` outside the palette block (mockup :411) becomes a token. Plot charts take colours only through CSS
  classes or a token reader (`site/assets/js/chart-style.mjs`) that reads custom properties at draw time. The one
  documented exception is `site/assets/favicon.svg`, an icon file that cannot use `var()`; `tokens.css` carries a
  comment that a palette swap also edits it. Source: L474; CM §6.6; ledger C-07 / R-11.
- **R25. File size.** No `.css`, `.mjs` or `.py` file passes 500 lines, as `scripts/check_file_sizes.py` checks. CSS
  and JavaScript are split by the frozen copy's own section markers. Source: O4; CONVENTIONS rule on file size.
- **R26. Links.** No `src` or `href` points off the page. The frozen copy's outbound links (the repository link, the
  author link, the tool links in "The data stack") become plain text or `[link: …]` placeholders, the style the frozen
  copy already uses; modules build no link to another host. Source: O3; CM §6.2.

### Checks and proofs

- **R27. The page check keeps every rule** (table "Page-check rules and how each survives"). Source: O3.
- **R28. Proof by data swap.** Tests build the real site against empty exports and against two test data sets with
  different values, and prove that live figures follow the data, pending figures say "figure pending", and numbers
  outside figure regions equal the "Numbers kept as copy" list. Source: O5.
- **R29. Module output follows the data.** No built module holds a year, money or large count literal outside a
  small pinned allowlist (PC17), and each chart's input rows come from a pure row function that a test runs on the
  empty and two test data sets. Source: ledger R-7.
- **R30. `make check` is not loosened**, and it is green at the end of every ticket. Source: O7; ledger C-08 / R-1;
  engineering standards ("Never weaken a gate").

### Repo invariants this item touches

- Invariant 3: every figure's unit line names its unit and its clock (company month, company year, company date,
  game day or wall-clock hour); money stays in US dollars as exported.
- Invariant 5: the hero scene and diagrams are hand-drawn SVG; no game file, screenshot or private machine path is
  committed.
- Invariant 7: the pinned sample sentence states the sample and "observational"; the footer keeps "Every result is
  observational."
- Invariants 1, 2, 4, 6 and 8 are not touched (no event, raw file, contract or plugin change).

## Required text edits

These are the only copy changes; each is forced by a kept rule (the park-count rule PC11, R11, R19, R26) or by the
truthfulness rulings (R8, R10, R16). The replacement wording is the build's default; the final copy passes revise it
(L476). Rows marked "pending" put the sentence inside a pending figure region.

| Where (frozen copy) | Text | Why | Default replacement |
|---|---|---|---|
| `#enterprise`, company-year length sentence | The unlabelled sentence giving the number of months in a company year | R8 (an unlisted number outside figure regions) | removed; the pinned close rule keeps "eight monthly statements, March to October" |
| `#enterprise`, rule heading (mockup :1035) | "One park at a time" | PC11 | "Parks open one at a time" |
| `#enterprise`, real-time clock (:1056) | "In a timing test on one park (68 game days …" | PC11 | "In a timing test (68 game days …" |
| `#enterprise`, park list (:1063-1065) | Park 1, Park 2 and Park 3 lines | R16 | one data-driven line per park, plus the next-park rule line |
| `#enterprise`, timeline note (:1067) | "Illustrative timeline: two parks across two company years." | R19, PC11 | removed |
| `#enterprise`, media note (:1068) | "… one coaster lap about 8 s, muted loop" | R8 (no source) | "Coming soon: Park 1 from above, muted loop" |
| `#extract`, benchmark line (:1116) | "three 35-day runs, one park of 1,938 guests" | PC11 | "three 35-day runs on a park of 1,938 guests" |
| `#infra`, balance check (:1156) | "Rehearsal run, two parks, 21 October 2026: 67 of 67 eligible months matched" | R8, L462 | removed |
| `#infra`, balance check (:1157) | "Committed sample, Park 1: one park, three game months, …" | PC11; duplicates the pinned sample sentence | the pinned sample sentence (R14) |
| `#infra`, per-month lines (:1159-1160) | "April 2000: matched exactly …" and "May 2000: matched exactly …" | R8, R9 (no export holds the verdict, capital, interest or cash) | one pending figure region, "Balance check by month"; the evidence block's reconciliation sentence stays live |
| `#built`, review study (:1222) | "… caught 56.7% of planted errors, against 42.7% …" | R8 (no in-repo source) | the sentence in a pending region |
| `#built`, Fix 2 (:1308) | "… spent 1.34 million tokens in one run …" | R8 (no in-repo source) | the sentence in a pending region |
| `#built`, "By the numbers" (:1348-1353) | four counts | R8; the frozen copy marks them "recount" | the block is a pending region |
| `#infra`, "The data stack" (:2713) | "Thirteen contracts share one version line, 1.5.0." | R8 (the version is stale) | "<count> contracts share one version line, <version>.", both read at build time from `contracts/*.odcs.yaml` (14 and 1.7.0 today) |
| `#infra`, "The data stack" | tool links | R26 | tool name as plain text |
| `#story`, lead note | "one park is built at a time while …" | PC11 | "parks are built one at a time while …" |
| `#story`, step 1 (:2284) | "One park, one company year. Park 1 opened on 1 March 2000 and ran the eight-month season. March, April and May are real rehearsal months: …" | PC11, R8, L462 (the sample holds 3 of 8 months; rehearsal claim) | a live region: "Park 1 opened in <first month>. Its months so far: <month> <value>, …" from `park_month.json` |
| `#story`, step 2 (:2287) | "Park 2 opened in March 2001. Operating profit went from X to Y per company year." | R8, R13 | first sentence removed; the second is a region, live with two or more company-year rows, pending otherwise |
| `#story`, step 3 (:2290) | "Most of the doubling is a second park, not a better first one. As reported, profit grew …" | R8 (a finding of made-up data) | the whole step text in a pending region |
| `#story`, step 4 (:2293) | "Wooden coasters lead this illustrative season with …" | R8, R19 | that sentence in a pending region; the guidance sentences before it stay |
| `#story`, step 5 | "rehearsal or illustrative" | R19, L462 | removed |
| `#story`, lead | "… through two company years" | C-01 (two company years is a made-up period) | "… one company year at a time" |
| `#story`, section tag | "No. 05 · Business insights" | R8 (the label names a section the page does not have) | "No. 05" |
| `#story`, step notes | the five notes under the steps | R8 (they stated periods and findings no export holds) | rewritten without a period or a finding |
| `#insights`, all panels (:1420-1553) | "Illustrative data" tags, the "Rehearsal data: Mar to May 2000" tag and legend entry, "Company play: [Park], [dates]" | R19, L462, R10 | the "figure pending" tag on pending panels, none on live ones; park and period from the data; the "Company play:" label becomes "Data shown:", because the committed sample is benchmark data, not company play (ruling C-01); the final wording is an open question for the project owner |
| `#insights`, unit lines (:1438, 1452, 1493, 1517, 1525, 1531, 1541, 1546, 1553) | fixed periods ("1 May to 30 June 2001", "company year 2001", "the five busiest rides of 2001") | R10 | period from the rows, or "period: figure pending" |
| `#insights`, stall items caption (:1454) | "… these are illustrative." | R19 | clause removed |
| `#insights`, attractions caption | "Observational: twelve rides in two parks, one season." | PC11, R8 | "Observational; sample: figure pending." |
| hero and top menu | repository and author links | R26; house rule on naming the project owner | `[link: repository]`, `[link: author]` (see "Needs owner decision") |
| footer (:1565) | "All data are rehearsal data (practice runs of old parks) or illustrative." | R8, L462 | removed; "Every result is observational." and the unaffiliated sentence stay |

## Numbers kept as copy

Only these numbers appear outside figure regions as plain copy. Each is a measurement or rule of the pipeline with
an in-repo source, and the copy-figure test checks that each phrase below is found, as a fixed string, in its source
file. Source: ledger C-01, R-12, C-06.

| # | Where | Shown | Source | Phrase found in the source |
|---|---|---|---|---|
| K1 | `#enterprise` rule; Finance note | "$0.00" entrance revenue | `docs/ai-dlc/roadmap/park-company.md:87` | `entry is free` |
| K2 | `#enterprise` clocks and park list | "1 March 2000" (the company calendar's first day); the page shows this date in serial form, "No. 2000 0301", and the copy-figure frame lists the phrase "1 March 2000" as its source | `docs/ai-dlc/roadmap/park-company.md:89` | `1 March 2000` |
| K3 | `#enterprise` real-time clock | "68 game days", "28 September 2026", "54.7 minutes" | `docs/FINDINGS.md`, row 2026-09-28 "Real minutes per game year" | `one run of 68 game days`; `54.7 real minutes per game year` |
| K4 | `#extract` budget line | "25 ms", "40 ticks a second", "10 ms", "1.25 ms" | `docs/adr/0005-plugin-per-tick-budget.md` | `25 ms tick slot`; `40 ticks per second`; `1.25 ms per tick` |
| K5 | `#extract` gauges | "5.260 ms", "0.1491 ms" | `docs/FINDINGS.md`, row 2026-10-13 | `worst tick 5.260 ms and highest mean 0.1491 ms` |
| K6 | `#extract` benchmark line | "three 35-day runs", "1,938 guests", "13 October 2026" | `docs/FINDINGS.md`, row 2026-10-13 | `3 runs of 35 judged game days`; `1,938-guest benchmark park` |
| K7 | `#extract` first design | "28 September 2026", "three 35-day runs", "OpenRCT2 0.5.5", "95.6 ms" | `docs/FINDINGS.md`, row 2026-09-28 "Worst single tick" | `**95.6 ms**`; `3 valid runs of 35 game days` |
| K8 | `#extract`; data stack | "OpenRCT2 0.5.6" | `CLAUDE.md:3` | `OpenRCT2 0.5.6` |
| K9 | data stack | "TypeScript 5.9", "5.9.3" | `package.json` | `"typescript": "5.9.3"` |
| K10 | data stack | "Python 3.12", "Node 24" | `README.md:15` | `Python 3.12`; `Node 24` |
| K11 | data stack | "Eleventy 3.1.6", Plot "0.6.17" | `package.json` | `"@11ty/eleventy": "3.1.6"`; `"@observablehq/plot": "0.6.17"` |
| K12 | data stack | "dbt 1.x" | `docs/adr/0004-dbt-core-1x-on-duckdb.md` | `1.x` |
| K13 | data stack | contract count and version | `contracts/*.odcs.yaml`, read at build time | the test recounts the files and reads their shared `version:` |

**Not figures, so not in the list:** section numbers ("No. 01", the menu's "01" to "07"), step and fix ordinals
("Step 1 of 5", "Fix 1"), the company-date calendar's month ordinals 1 to 8, the gauges' axis ends ("0 ms",
"12 ms", "1.5 ms"), "ES5", decision-record numbers, the release names "v1" and "v1.1", and the model names with
their "as of October 2026" line (names of the tools used; the repository holds no source for them). The test keeps
these as a pinned list of patterns, and every other digit outside a figure region fails it.

## Decisions taken in this spec

Each states its gain and cost.

- **D1. Plot, styled to the mockup.** Gain: PC12 and PC13 keep their exact rules, ADR 0021's chart choice stands,
  the data-stack copy that names Plot stays true, and no dependency changes. Cost: each chart is rebuilt as a Plot
  specification with CSS styling, and fine details of the frozen copy's hand-drawn charts (hand-placed labels, custom
  bar ends) may differ; the reviewer's side-by-side check (Verify-by 10) judges the match. Source: ledger C-02.
- **D2. Keep the park-count rule page-wide and edit the copy it catches.** Gain: the rule is untouched. Cost: the
  phrases marked PC11 in "Required text edits" differ from the draft.
- **D3. One evidence block in `#infra`.** Gain: the pinned tables and sentences, and their tests, stay unchanged.
  Cost: a small block the frozen copy does not have, in its table style.
- **D4. Prose and figures render at build time; modules only draw and wire controls.** Gain: the page check and the
  data-swap tests see every sentence and number in the built HTML, and the page reads without JavaScript. Cost: the
  frozen copy's script-built text is rewritten as story passages and markup rather than pasted.
- **D5. Story passages, not whole story pages.** The one-page site renders named passages of each story file rather
  than one include per story page. Gain: ADR 0021's single-source rule holds on a page that interleaves prose with
  figures. Cost: the story files carry passage markers, and ADR 0043 records the change of form.
- **D6. Chart rows come from pure row functions.** Each chart's rows come from a function in
  `site/assets/js/rows/` that takes the parsed exports and returns rows, with no DOM access. Gain: a test runs every
  function under Node on the empty and two test data sets, so what the browser draws is proved to follow the data.
  Cost: chart modules are split into a pure part and a drawing part.
- **D7. The contract count and version are read at build time.** Gain: the data-stack line never goes stale when a
  contract version moves (a parallel plugin branch is about to bump it). Cost: about ten lines in
  `site/eleventy.config.mjs` reading `contracts/`, which is not an export; it holds no business figure.
- **D8. ADR 0043** records system fonts and no animation library (O2), Plot styled through tokens (D1), story
  passages (D5), and two amendments with the ADR each amends: ADR 0021 `:46` (story text as passages on a one-page
  site) and ADR 0026 (its story-file departure ends; its embedded-JSON data path and build-time month table stay
  through this item, and its Parquet migration waits for a later website-build item). Gain: the decisions survive
  this spec's deletion. Cost: one short file and one status line in ADR 0026. Source: ledger C-04, C-03 / R-10.

## Page-check rules and how each survives

The page check is `src/openrct2_analytics/showcase/page_check.py`, with pinned text in `page_check_text.py`.
"Unchanged" means the code and pinned values stay as they are; "tightened" means the rule covers more than today;
"new" means an added rule. No rule is narrowed.

| # | Rule today (file:line) | After the port |
|---|---|---|
| PC1 | `index.html` exists (:197-199) | Unchanged. |
| PC2 | No `src` or `href` starts with `http:`, `https:`, `//` or `/` (:205-207) | Unchanged. Tightened: no quoted string literal in a built `.mjs` starts with `http:`, `https:` or `//` (the W3C SVG and XLink namespace strings excepted), and no `url(` in a built `.css` names another host. Files under `assets/vendor/` (the locked Plot and d3) are excluded, as today. |
| PC3 | `#park-month-data` exists, is valid JSON, and equals the served `park_month.json` rows (:209-229) | Unchanged. Tightened: each further `*-data` block (R15) equals its served file the same way. |
| PC4 | `#park-month-chart` exists (:212-214) | Unchanged; the mount sits in the Finance "Operating profit by month" region. |
| PC5 | Page text holds "unit: US dollars" and "clock: company month" (:231-232) | Unchanged: the figure macro writes the literal `unit:` and `clock:` prefixes. Tightened: every figure's unit line (`data-figure-unit`) holds `unit:` and `clock:` with a clock of invariant 3. |
| PC6 | `#park-month-table`: caption, header row, one `th scope=row` and one `td` per served row, month labels, dollar values, no stray text, the "not checked: first month" mark (:256-320) | Unchanged; the table is the Finance region's data table. |
| PC7 | `#company-year-table` and `#park-year-table`: captions, "clock: company year" in the nearest heading, rows equal to served rows, status words, no stray text (:341-364, :402-432) | Unchanged; both sit in the evidence block under their current headings. |
| PC8 | "No company year has closed yet." shows, and the company-year table is absent, exactly when there are no company-year rows (:397-401) | Unchanged; the region stays and the table element is absent (R12). |
| PC9 | Every park in `park_month.json` is listed in the park-years table (:433-438) | Unchanged. |
| PC10 | The close-rule, reconciliation, first-month and sample sentences are present (:376-392) | Unchanged text, rendered from the figure registry in the evidence block. |
| PC11 | Prose and captions state no park count (`PARK_COUNT`, :393-396) | Unchanged, page-wide (D2). |
| PC12 | The scripts d3, Plot and `assets/park-month-chart.mjs` are present, in that order, and exist as files (:237-252) | Unchanged. Tightened: every other script `src` is a local file in the built site, every static import in a built module resolves to a file in the built site, and no inline script runs code (only the JSON blocks). |
| PC13 | `park-month-chart.mjs` names exactly `park-month-data` and `park-month-chart`, uses no `querySelector` or `getElementsBy`, and no `fetch`, `XMLHttpRequest`, dynamic `import()` or remote import (:441-459) | Unchanged for `site/assets/park-month-chart.mjs`. Tightened for every built `.mjs`: the network bans apply, and element lookups (`getElementById`, `querySelector`, `querySelectorAll`, `closest`, `matches`, and the `$`/`$$` helpers of `site/assets/js/dom.mjs`) take string literals, except inside the helpers' own definitions; every id and class named in those literals exists in the built HTML. A module keeps a reference to an element it creates rather than looking it up. |
| PC14 | Served files exist, are valid JSON with a `rows` list, money is numeric, counts are whole numbers, dates are `YYYY-MM-DD` (:150-192, :323-338) | Unchanged. |
| PC15 | (new) | Every `data-figure` region has a state; a pending one's body (`data-figure-body`) is exactly "figure pending" with no digit (R11). |
| PC16 | (new) | The built page and modules hold no "Illustrative" (any case); no pending region's unit line holds a four-digit year; every park ID in the built site (the pattern `k` plus 13 digits, a hyphen and 6 letters or digits) occurs in the served exports (R10, R19). |
| PC17 | (new) | No built `.mjs` outside `assets/vendor/` holds a numeric literal from 1900 to 2099, a numeric literal of 1,000 or more, or a string literal holding `$` before a digit, a thousands-separated number, or a four-digit year, unless the value is in the per-module allowlist `MODULE_NUMBER_ALLOWLIST` in `page_check_text.py`, each entry with a one-line reason (R29). |

`page_check.py` is 499 of 500 lines, so the tightened and new rules go in `page_check_site.py` and some helpers move
there. File sizes stay with `scripts/check_file_sizes.py`, unchanged.

## Files and owning modules

Owning modules follow the CONVENTIONS module table: `site/` (the Eleventy site) and
`src/openrct2_analytics/showcase/` (build-time checks), plus `tests/` and `docs/`. The ticket column refers to
"Ticket order" below.

| File | Change | Owns | Ticket |
|---|---|---|---|
| `src/openrct2_analytics/showcase/page_check.py` | calls the new module; helpers moved out to stay at or under 500 lines | R27 | T1 |
| `src/openrct2_analytics/showcase/page_check_site.py` (new) | PC2, PC3, PC5, PC12, PC13 tightenings; PC15, PC16, PC17 | R27, R29 | T1 |
| `src/openrct2_analytics/showcase/page_check_text.py` | "figure pending" pin; `MODULE_NUMBER_ALLOWLIST` | R27, R29 | T1 |
| `tests/page_check_support.py` | `render_page` copies the whole `site/` tree except `_data` and `_site`, then adds the served files | R28 | T1 |
| `tests/test_showcase_page_check_site.py` (new) | one failing case per tightened or new rule, including a planted unknown selector in a non-chart module and a planted year literal | R27, R29 | T1 |
| `tests/test_committed_tree_scan.py` (new) | digests of the invented identifiers (R19); scans every `git ls-files` text file; a canary digest proves a planted value in a docs file fails it | R19 | T1 |
| `docs/ai-dlc/contracts/site-mockup-port.md` | line 51 names the invented park ID without spelling it; line 31 calls the first park ID the earlier rehearsal sample's ID | R19 | T1 |
| `site/assets/css/tokens.css`, `base.css`, `nav.css`, `sections.css`, `crew.css`, `insights.css`, `charts.css` (new) | the frozen copy's CSS split by section, desktop rules only; `charts.css` styles Plot output through classes | R4-R6, R24, R25 | T2 |
| `tests/test_site_tokens.py` (new) | scope `.css`, `.mjs`, `.njk` under `site/` (not `_site`, `_data`); `tokens.css` exists and holds the five seeds; colour literals and `color-mix(` only there; favicon the one listed exception; no new font or image file | R22, R24 | T2 |
| `site/index.njk` | rewrite: `<html data-palette data-theme>`, CSS links, includes for every section in order, the JSON blocks, the three PC12 scripts, then `assets/js/boot.mjs`; the old inline `<style>` deleted | R1, R2, R15 | T3 |
| `site/_includes/topbar.njk`, `hero.njk`, `footer.njk`, `icons.njk`, `figure.njk`, `evidence.njk`, `finance-profit.njk` (new) | top menu, hero, footer, SVG icon sprite, figure macro, evidence block, and the Finance profit region (mount `#park-month-chart`, unit line, `#park-month-table`) | R1, R11, R12, R14 | T3 |
| `site/_includes/enterprise.njk`, `extract.njk`, `infra.njk`, `built.njk`, `story.njk`, `insights.njk`, `insights-ops.njk`, `insights-attr.njk`, `insights-finance.njk` | created by T3 as stubs (`infra.njk` holds only the evidence include; `insights-finance.njk` only the profit-region include); each later ticket writes its own | R1 | T3, then T4-T7 |
| `site/figures.mjs` (new), `site/figures/<section>.mjs` (stubs) | figure registry: id, export file, rows function, heading, unit line, sentence pattern; decides live or pending | R9-R11, R20 | T3 (core), T4-T7 (own section) |
| `site/eleventy.config.mjs` | registry as global data; figure-state filter; story-passage shortcode on RenderPlugin; contract count and version (D7); passthrough of `site/assets/css/` and `site/assets/js/`; d3 and Plot copies kept | R9, R20, D7 | T3 |
| `site/assets/js/boot.mjs`, `data.mjs`, `dom.mjs`, `motion.mjs`, `chart-style.mjs`, `nav.mjs`, `hero-scene.mjs`, `rows/park-month.mjs` (new) | boot: calls each section's `init` in page order and owns the debounced resize; data: the data-block reader, shared desk state and the `usd` formatter; dom: lookup helpers; motion: pause control, reduced motion, the instant no-GSAP path; chart-style: token reader for Plot | R15, R23, R24, ledger R-8 | T3 |
| `site/assets/js/extract-roll.mjs`, `infra-track.mjs`, `crew.mjs`, `story.mjs`, `insights.mjs`, `ops.mjs`, `attractions.mjs`, `finance.mjs` | created by T3 as stubs exporting `init()`; each later ticket writes its own | R1 | T3, then T4-T7 |
| `docs/showcase/story/the-game.md`, `README.md` | hero, menu and footer passages; index updated | R20, R21 | T3 |
| `tests/site_fixtures.py`, `tests/test_site_figures.py`, `tests/test_site_text_sources.py`, `tests/test_site_chart_rows.py` (new) | fixture writers; empty, A and B builds; copy-figure test; template and module prose test; row functions run under Node | R11-R13, R20, R28, R29 | T3 |
| `tests/site_copy_figures/<section>.toml` (new) | the "Numbers kept as copy" entries per section; T3 writes `frame.toml` and empty files for the other sections | R8, R28 | T3 (frame), T4-T6 (own section) |
| `site/_includes/enterprise.njk`, `extract.njk`, `infra.njk`; `site/assets/js/extract-roll.mjs`, `infra-track.mjs`; `site/figures/enterprise.mjs`, `infra.mjs`; `docs/showcase/story/the-company-timeline.md`, `the-stack.md`; `tests/site_copy_figures/enterprise.toml`, `extract.toml`, `infra.toml` | the three opening sections, with "The data stack" at the end of `#infra` (its copy stays in `how-this-was-built.md`) | R1, R3, R16, R23 | T4 |
| `site/_includes/built.njk`; `site/assets/js/crew.mjs`; `site/figures/built.mjs`; `docs/showcase/story/how-this-was-built.md`; `tests/site_copy_figures/built.toml` | "How it was built", "The build crew" | R1, R3, R8 | T5 |
| `site/_includes/story.njk`, `insights.njk`, `insights-ops.njk`, `insights-attr.njk`; `site/assets/js/story.mjs`, `insights.mjs`, `ops.mjs`, `attractions.mjs`, `rows/story.mjs`, `rows/insights.mjs`; `site/figures/story.mjs`, `insights.mjs`; `docs/showcase/story/the-analytics-strategy.md`; `tests/site_copy_figures/story.toml`, `insights.toml` | the board meeting, the insights desk and its controls, Operations and Attractions | R1, R4, R7, R13 | T6 |
| `site/_includes/insights-finance.njk`; `site/assets/js/finance.mjs`; `site/assets/park-month-chart.mjs`; `site/figures/finance.mjs` | the Finance view; `park-month-chart.mjs` is the profit chart, draws on load and exports `redrawParkMonthChart`, which `finance.mjs` calls for the range brush and park switch; its Plot code restyled through `chart-style.mjs`, same two element ids | R4, R7, ledger R-8 | T7 |
| `docs/adr/0043-showcase-system-fonts-and-story-passages.md` (new); `docs/adr/0026-build-time-json-for-the-first-site-page.md` (one status line: "Amended by ADR 0043") | D8 | D8 | T3 |
| `ARCHITECTURE.md` (the site paragraph, about lines 234-262, and the file list, about line 573); `docs/CONVENTIONS.md` (the `site/` row) | the new page structure, text sources and checks | docs | T3 |
| `docs/showcase/design-mockups.md` | the offline sentence and the "Nothing from the mockups" sentence, as the roadmap reads it | docs | T3 |
| `docs/showcase/trace-operating-profit.md` | hop 1: the page is assembled from includes; the April bar is drawn by the restyled Plot chart in the Finance view | docs | T7 |
| `CHANGELOG.md` | one entry for the port | docs | T7 |

Each file's content is written by one ticket. T3 creates empty stubs for files a later ticket owns, so no two
tickets edit the same lines and T4, T5 and T6 can run side by side.

**Hotspot files are not touched.** `Makefile` already runs the site build, the page check and pytest; `package.json`,
`package-lock.json`, `pyproject.toml`, `uv.lock` and `dbt_project.yml` need no change because no dependency or
model changes. A builder that finds one unavoidable stops and reports.

## Contracts and regeneration

- **`site/_data/` exports** (`park_month.json`, `park_year.json`, `company_year.json`, from `site/exports.toml`): not
  changed and not regenerated; no mart changes, so `make site-export` is not run. `make check`'s export comparison
  proves they still match a fresh sample build.
- **The page check**: changed as in the table above; its pinned values live in `page_check_text.py`, and `make check`
  runs it on a fresh build of the real templates.
- **Event and data contracts** (`contracts/`): not touched; the site only reads their count and shared version (D7).

## Test seams

- **Real build into a temporary folder.** `npm run --silent site:build -- --input=<dir> --output=<dir>` builds the
  real templates over any `_data` folder. `render_page` copies the whole `site/` tree except `_data` and `_site`, then
  adds the served files. The story-passage shortcode reads `docs/showcase/story/` from the repository root, not from
  the input folder.
- **Fixture data sets.** `tests/site_fixtures.py` writes the three export files with the exact column lists of
  `site/exports.toml`: an empty set (every `rows` list empty), and sets A and B, each with two parks, months across
  two company years and one closed company year, where no money value or count in A appears in B and none appears in
  "Numbers kept as copy".
- **Figure regions.** The `data-figure`, `data-figure-state`, `data-figure-unit` and `data-figure-body` attributes
  let a test list every figure, its state, its unit line and its body from the built HTML with the standard-library
  HTML parser, tracking nesting.
- **Row functions under Node.** `tests/test_site_chart_rows.py` runs each row function named in the figure registry
  with `node --input-type=module` (Node is already required; no new dependency) on the parsed fixture exports and
  reads its JSON output.
- **Prose test.** In every `.njk` under `site/`, after removing Nunjucks tags, HTML comments, and `<script>` and
  `<style>` contents, any text run or `aria-label`, `title` or `alt` value of four or more words (a word is a run of
  letters, apostrophes or hyphens) fails. In every built `.mjs` outside `assets/vendor/`, any string literal of four
  or more words fails, except the message of a thrown `Error`.
- **Committed-tree scan.** The scan stores SHA-256 digests of the invented identifiers and of each embedded data
  row's text, plus one canary digest that only the scan's own test writes, and compares them with the candidate
  strings of every tracked text file (word runs up to the longest name's length, and identifier-like tokens).

## Golden paths

- `site/index.njk` and `site/eleventy.config.mjs` (today's versions): filters, the `usd` and `monthLabel` formats,
  the JSON block, the passthrough copy.
- `site/assets/park-month-chart.mjs`: the element-id discipline, the Plot call, and the zero-network rule for a chart
  module.
- `src/openrct2_analytics/showcase/page_check.py`: the `_require` style, one message per failed rule.
- `tests/page_check_support.py` and `tests/test_dbt_two_parks.py`: building the real site in a test and running the
  page check on it.
- The frozen copy for markup, CSS and the non-chart drawings; never for its data or its chart helpers.

## Out of scope

- Palette changes, copy rewrites (the final copy passes), and finishing the Business Insights
  controls (L476).
- Dark mode (R6).
- New exports or mart columns; they belong to "Department figures" (line 465).
- A company-data source for the site; it belongs to "Company data to the site" (line 478). This item only keeps the
  export file names and shapes stable (R18).
- Real links for `[link: blog post]`, `[link: review record]` and the repository and author links; they belong to the
  blog-post item and the publication steps. Sources for the pending study, token and "By the numbers" figures belong
  to the final copy passes.
- Moving the train or any other GSAP-driven motion with new code (R23); vendoring GSAP or fonts (O2).
- Deploying or publishing the site.

## Constraints

- Prefix every Python, uv or make command with `env -u VIRTUAL_ENV`.
- No dependency added or removed (O2, ledger C-02); no hotspot file change (see "Files").
- Committed text never names the project owner; the frozen copy's author link and repository link are not carried in
  any form that names a person. No private machine path in any committed file.
- The frozen copy is never committed or copied into the repository. A worker checks its SHA-256 before reading it,
  and copies markup, CSS and non-chart drawing code only.
- Relative URLs only (`assets/…`, `#…`), so the site works under its project base path (ADR 0021).
- Engineering standards apply: no error swallowing in modules, no dead code left beside its replacement, each new
  rule has a test that fails before it and passes after.

## Verify-by

A fresh worker runs these in its own worktree, in order, as written.

0. Set the two variables every later step uses: `MOCKUP="scratch/mockup-19-rct-exact.html"` and `OUT="$(mktemp -d)"`.
   Run from the worktree root; the frozen copy is git-ignored and exists only in the build worktree.
1. `check:` `echo "09560046226e7cec53e6b8dd0f92d8a5a6ec0ed76037ecbca1d7390f6a2fa021  $MOCKUP" | shasum -a 256 -c`
   exits 0.
2. `check:` `env -u VIRTUAL_ENV make check` exits 0.
3. `check:` `env -u VIRTUAL_ENV uv run pytest tests/test_site_figures.py tests/test_site_tokens.py
   tests/test_site_text_sources.py tests/test_site_chart_rows.py tests/test_committed_tree_scan.py
   tests/test_showcase_page_check_site.py tests/test_showcase_page_check.py
   tests/test_showcase_page_check_month_table.py tests/test_dbt_two_parks.py` passes, and `tests/test_site_figures.py`
   reports the empty build, build A and build B as separate passed cases.
4. `check:` `npm run --silent site:build -- --output="$OUT"` exits 0, then
   `env -u VIRTUAL_ENV uv run python -m openrct2_analytics.showcase.page_check --site "$OUT" --served-dir site/_data`
   prints "showcase page: checks passed".
5. `check:` `! grep -rnoE --exclude-dir=vendor "(https?:)?//[A-Za-z0-9.-]+\.[a-z]{2,}(/[A-Za-z0-9._/-]*)?" "$OUT" | grep -vE "www\.w3\.org/(2000/svg|1999/xlink)"`
   exits 0 (no outside host in the built site outside the locked vendor files).
6. `check:` `git diff --exit-code origin/develop...HEAD -- site/_data site/exports.toml Makefile package.json
   package-lock.json pyproject.toml uv.lock dbt_project.yml` exits 0.
7. `check:` `! git grep -n -i "illustrative" -- site` exits 0; `! git ls-files site | grep -E
   "\.(woff2?|ttf|otf|png|jpe?g|gif|webp)$"` exits 0; `test -z "$(git ls-files scratch mockups)"` exits 0.
8. `check:` `env -u VIRTUAL_ENV uv run python scripts/check_file_sizes.py` exits 0.
9. `check:` `python3 -m http.server --bind 127.0.0.1 --directory "$OUT" 8765 & sleep 1` serves the build in the
   background (modules do not load from `file://`); `curl -sf http://127.0.0.1:8765/assets/js/boot.mjs -o /dev/null`
   exits 0. Stop the server with `kill %1` after step 10.
10. `judgment:` with the server of step 9 running and the network otherwise off, a reviewer opens
    `http://127.0.0.1:8765/` beside the frozen copy at a desktop width of at least 1280 px and confirms: every
    section, the top menu, the layout, "The build crew" diagram with its hover detail, the chart look and the draft
    copy match, except the system fonts, the instant tweens, the "figure pending" boxes and the rows of "Required text
    edits"; the hero scene moves and stops with the pause control and under reduced motion; the train sits at its
    last stop; the extraction buttons show their result at once; the board meeting's steps advance on scroll. The
    browser look itself is also the project owner's later check (L477); the agent-side browser review is waived
    (waiver BR-1, recorded in the ledger).
11. `judgment:` a reviewer reads the "Page-check rules" table against the page-check diff and confirms each rule is
    unchanged, tightened or new as stated, and that no `make check` step was removed or weakened.

## Definition of Done

- `check:` Verify-by steps 1 to 9 pass on the branch, and `make check` passes on `develop` after merge.
- `check:` `tests/test_site_figures.py` proves, on real builds: (a) with empty exports the build and the page check
  pass, the month and park-year tables have no body rows, the company-year region shows its sentence with no table
  element, and every other figure region is pending; (b) in builds A and B every number inside a live figure region
  is a formatted value or row key of that build's fixtures, and no money value or count shown in A's live regions
  appears in B's (dates, years and `statements_expected`, which both sets share, are excluded from this comparison
  but must still trace to the fixture); (c) the numbers outside figure regions are the same in the empty, A and B
  builds and equal the "Numbers kept as copy" entries plus the pinned not-a-figure patterns, and each entry's phrase
  is found in its source file (K13 recounted from `contracts/`).
- `check:` `tests/test_committed_tree_scan.py` passes on the tracked tree and fails when its canary value is planted
  in a docs file.
- `check:` `tests/test_showcase_page_check_site.py` has a case that fails the check for each tightening of PC2, PC3,
  PC5, PC12 and PC13 and for PC15, PC16 and PC17.
- `check:` `tests/test_site_tokens.py` fails on today's tree (no `tokens.css`) and passes after T2.
- `check:` `tests/test_site_text_sources.py` passes, and fails when a four-word sentence is planted in a section
  template or a module.
- `check:` `tests/test_site_chart_rows.py` passes: every row function returns no rows on the empty set, and only
  fixture values and row keys on sets A and B.
- `judgment:` Verify-by steps 10 and 11 pass review.
- `judgment:` a reviewer confirms the docs in "Files" are updated, ADR 0043 names each ADR it amends and why, and
  ADR 0026 carries its "Amended by ADR 0043" line.
- `judgment:` the project owner opens the built site (`verify: owner-later`, L477); not required for merge into
  `develop`.

## Ticket order

Seven tickets; every ticket ends with `make check` green and merges on its own. The order works because each new
rule passes on today's page before any section exists, and today's pinned elements (the `#park-month-chart` mount,
its "unit: US dollars" and "clock: company month" line, the three tables, the pinned sentences and the three PC12
scripts) move once, intact, into their final places in T3. With Plot kept (D1), no pinned value has to change later.
Each ticket's done-condition is: its own new tests pass and `env -u VIRTUAL_ENV make check` exits 0. Source: ledger
C-08 / R-1.

1. **T1, page-check groundwork.** Adds PC2, PC3, PC5, PC12 and PC13's tightenings and PC15 to PC17, each passing on
   today's page (no figure regions, no further data blocks, one module) and each with a failing planted case; the
   `render_page` fix; the committed-tree scan; the contract-map rewrite. If a new rule cannot pass on today's page,
   it moves to the ticket that makes it pass, and the report says so.
2. **T2, tokens and styles.** The CSS files and the token test. The files are not linked yet, so the page does not
   change.
3. **T3, page shell, data layer and proofs.** The new `index.njk`, the frame includes, the figure macro and
   registry, the evidence block and Finance profit region carrying today's pinned elements unchanged (the existing
   Plot chart keeps drawing into `#park-month-chart`), every section stub, the shared modules, story passages for
   the frame, the fixture, copy-figure, prose and row-function tests, ADR 0043 and the docs. The old inline `<style>`
   is deleted here.
4. **T4, opening sections** (`#enterprise`, `#extract`, `#infra`). Runs alongside T5 and T6.
5. **T5, how it was built** (`#built`). Runs alongside T4 and T6.
6. **T6, board meeting and insights desk** (`#story`, `#insights` with Operations and Attractions). Runs alongside
   T4 and T5.
7. **T7, Finance and the profit chart.** The Finance view, `finance.mjs`, and `park-month-chart.mjs` restyled on
   Plot with `redrawParkMonthChart`; the trace doc and the changelog entry. Runs after T6, because the desk's shared
   controls come from `insights.mjs`.

## Needs owner decision

Neither item blocks building; each has a default the build follows.

- **The author label in the top menu.** The frozen copy's menu names the project owner beside an author link. The
  default, per the ledger's ruling on R-13, is the placeholder `[link: author]`, since committed text names the
  project owner only on an explicit instruction for that line. If the name should appear, the project owner says so
  and the line carries the `owner-name: allow` marker.
- **Park display names.** Default: "Park 1", "Park 2" by first company month (R17). Real names need a new export
  column, which belongs to "Department figures" (line 465) or a later item.
