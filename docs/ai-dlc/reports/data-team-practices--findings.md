# How real data teams run an analytics build, adapted for this project — research findings
status: research complete; reviewed once, blind, with every finding fixed (`docs/ai-dlc/ledger/park-company.md`, rows DP-S1 to DP-S5) · date: 2026-10-02 · initiative: park-company (roadmap NOW slice "Data-team practices research")

## Bottom line
- **The project can follow real data-team practice without any cloud-only tool.** Separate development, test and production warehouses, CI on every pull request, layered data-quality tests, written service levels and governed metric definitions all work with dbt-core, DuckDB and GitHub Actions. A local test on 2026-10-02 defined and queried metrics through MetricFlow (dbt's metric engine) on this repo's pinned dbt 1.11.15 and DuckDB 1.5.5. The roadmap's riskiest assumption for this slice holds.
- **One new constraint came out of that test.** dbt's metric validator crashes inside the agents' sandbox, so metric definitions placed in dbt's model folders would turn `make check` red for every agent session (section 2.6). The metric catalog therefore starts as its own file, shaped so dbt and MetricFlow can read it later.
- **Use the industry's own vocabulary.** Public park operators report guest visits (not unique people), revenue per visit by category, operating days, same-park year-over-year figures and operating profit. This project should name its metrics the same way, call ride income "ride revenue" (never "admissions", because entry is free), and never show the closed months as zero months.
- **A metric tree must separate arithmetic from belief.** Links like revenue = visits × revenue per visit are identities and must reconcile exactly in dbt tests. Links like "new rides grow visits" are hypotheses: each one carries its evidence, rival explanations and the word "observational".
- **Ceremonies are adopted in their lightest honest form.** Reviewers credit a few process documents tied to real changes, and distrust a large ceremonial library or simulated stakeholders presented as real. The project keeps one requirements brief, one acceptance walkthrough before v1, release notes on each promotion to `main`, runbooks, and incident records only for real failures. It says plainly that one person directs the work and AI agents write most of it.
- **What changes:** ADR 0012 records these choices; the roadmap gains two slices (NEXT 19, a v1 acceptance walkthrough; NEXT 20, operating documents), and NEXT 13, 14, 15, 2e, 3·0 and 3d gain the adopted detail. The metric catalog (NEXT 13) can start now.

## How this was produced
Six research lanes ran on 2026-10-02, each a separate Codex agent (OpenAI gpt-5.6-terra) with web search only, blind to the others and to this project's files. The first wave covered the slice's three areas: delivery lifecycle and ceremonies, metrics and dimensional modeling, and environments, CI/CD and data quality. A second wave followed up on what the first raised: how real theme-park operators measure their business, metric trees from stronger sources than the first wave found, and how hiring reviewers judge solo, AI-assisted projects. One question was checked by running it instead of searching: whether MetricFlow installs beside the pinned dbt and works on DuckDB (section 2.6; `docs/FINDINGS.md` holds the measurement).

One blind reviewer from another model family (Codex, gpt-6-sol) then opened 27 of the cited pages and checked the report against the slice's requirements; its five findings and their resolutions are in the ledger, and this version includes the fixes.

Each claim below carries its source URL and an "as of" date. "As of 2026-10" means the page was read then and carried no date of its own. Evidence strength: **strong** (several primary sources agree), **moderate** (one primary source, or several secondary ones), **weak** (one secondary source, a vendor guide, or inference). Each practice ends with a verdict: **adopted** (used as real teams use it), **adapted** (used in a stated lighter form), or **rejected** (with the reason). The owner's earlier ruling applies: when real-world practice and portfolio appeal disagree, real-world practice wins, and the showcase comes from documenting the choice.

## Decisions at a glance

| Practice | Verdict | Form here | Roadmap home |
|---|---|---|---|
| Discovery and requirements, including the requirements workshop | adapted | One requirements brief, drafted by agents from the project owner's written rulings; the workshop is one review session in which the project owner, as the company's decision-maker, confirms or corrects it | NEXT 13 |
| Phasing the build | adopted | dbt Labs' Analytics Development Lifecycle per change; consulting-style milestones for the narrative | site narrative (NEXT 15) |
| Design review before build | adopted | Spec plus blind review before each build (already practiced); a per-mart design note reviewed in the dbt design session | NEXT 3·0 |
| Acceptance testing and sign-off | adapted | One v1 acceptance walkthrough with a dated go/no-go note | new NEXT 19 |
| Release and change management | adapted | Release notes and a tag on each promotion to `main`; versioned contracts (already); dbt model versions for breaking mart changes after v1 | new NEXT 20 |
| Retrospectives and incident reviews | adapted | One retrospective at v1; incident records only for real failures | new NEXT 20 |
| Documentation | adopted | Existing homes plus dbt docs, runbooks and a "How this was built" section | NEXT 15, new NEXT 20 |
| Metric definitions | adopted | One governed definition per metric, with unit and clock; a standalone catalog file first | NEXT 13, 3·0 |
| Metric tree | adapted | Identity links reconcile in dbt tests; hypothesis links carry evidence and caveats | NEXT 13 |
| Industry metric names | adopted | Guest visits, revenue per visit by category, operating days, same-park year-over-year, operating profit | NEXT 13, 4, 5 |
| Bus matrix and four-step design | adopted | Grain declared first; conformed park, ride, stall and date dimensions | NEXT 13, 3·0 |
| Star schema and wide tables | adopted | Stars are the governed core; wide views only for the site | NEXT 3c (already) |
| Semantic layer (MetricFlow) | not yet | Stays a LATER bet; its local test passed; adopting it needs dependency sign-off and a fix for the sandbox crash | LATER |
| Development, test and production | adopted | Separate DuckDB files; CI builds only from the committed sample; rehearsal and company data in separate files and paths | NEXT 14 |
| CI/CD | adapted | Full `dbt build` in every pull request (already); production runs are local `make` runs; slim CI rejected | NEXT 14, 2e |
| Data-quality testing | adopted | Unit tests, data tests, model contracts, reconciliation, explicit severity; hand-built mutation tests | NEXT 3d, 3·0 |
| Data service levels | adapted | A short service note per published table; required reconciliations block publication; targets below 100% only for operational indicators; no contractual SLAs | NEXT 2e |
| Data observability | adapted | dbt run artifacts kept in a run-history table; no paid or new tool | NEXT 2e |
| How the work is presented | adopted | Few, linked process documents; simulated roles labeled; honest AI disclosure | NEXT 15 |

## 1. Running the build: lifecycle and ceremonies

### 1.1 Discovery and requirements — adapted
**In plain terms.** Before building, real teams write down who needs the data, what decisions it serves, and what "done" looks like. Here, the project owner really is the company's decision-maker, building and running the parks, and most requirements already exist as written rulings.

**The evidence.**
- GitLab's data team requires a problem statement, business value and expected outcome before triage, refined until another developer could pick the work up (https://handbook.gitlab.com/handbook/enterprise-data/how-we-work/, as of 2026-10). **Strong.**
- Kimball's lifecycle makes business acceptance the goal from the requirements step on, delivered in manageable increments (https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dw-bi-lifecycle-method/, as of 2026-10). **Strong.**
- Pitfall: a vague request treated as a specification produces correct work that answers no decision; open-ended discovery produces no buildable scope (same sources). **Moderate.**

**Verdict: adapted.** Agents draft one requirements brief (users of the data, the decision each makes, success criteria, non-goals) from the roadmap's "v1 is done when" list and business rules. The project owner confirms it in one review (verify: owner-later, about 20 minutes). The brief says one real decision-maker answered for every role; it does not invent stakeholders. The requirements workshop becomes that review: one working session, written or live, in which the project owner answers the brief's open questions and confirms or corrects each requirement; its output is the confirmed brief. Recorded interviews with role-play were rejected as theater (section 4).

### 1.2 Phasing the build — adopted
**In plain terms.** Real teams work in repeated small loops (plan, build, test, release, watch), and consultancies package a whole engagement as discovery, design, build, acceptance and handover.

**The evidence.**
- dbt Labs' Analytics Development Lifecycle runs plan, develop, test, deploy, operate and observe, and discover and analyze for every change (https://www.getdbt.com/blog/improving-analytics-quality-with-the-analytics-development-lifecycle, as of 2026-10). **Moderate.**
- Two consultancies publish matching engagement stages: discovery, design, build and test, deployment and training, support (https://bluepeakdataconsulting.com/how-we-work/ and https://www.northern-analytics.com/process, as of 2026-10). **Moderate.**
- Pitfall: a rigid waterfall delays feedback; skipping phases makes a project read as loose scripts (Kimball, above). **Moderate.**

**Verdict: adopted.** The existing spec, build, review and merge loop already follows that per-change lifecycle. The site tells the story through the consulting milestones, mapped onto v1's five steps. A separate project board was rejected because the roadmap already serves as the board.

### 1.3 Design review before build — adopted
**In plain terms.** A design is checked against the brief before code is written, and every code change gets a second pair of eyes.

**The evidence.**
- GitLab's data team uses merge-request templates and code-owner review covering implementation, business fit and data-model quality (https://handbook.gitlab.com/handbook/enterprise-data/how-we-work/mr-review/, as of 2026-10). **Strong.**
- dbt Labs recommends review of every analytics-code change to enforce documentation and test standards (https://www.getdbt.com/blog/adlc-develop, as of 2026-10). **Strong.**
- Pitfall: review only after the code is done turns reviewers into late redesigners (Blue Peak, above, reviews the data-model design with the client before build). **Moderate.**

**Verdict: adopted, mostly as already practiced.** Specs and blind reviews come before builds, and ADRs record the choices. The dbt design session (NEXT 3·0) adds a short design note for each mart: business process, grain, dimensions and facts. The note is reviewed before that mart is built.

### 1.4 Acceptance testing and sign-off — adapted
**In plain terms.** Before a release, the business walks through realistic tasks and signs off, or lists what is deferred.

**The evidence.**
- The University of Illinois BI process defines user acceptance testing as the client's final walkthrough, producing a test report, logged enhancements and approval (https://www.aits.uillinois.edu/sdlc/business_intelligence/process/test, as of 2026-10). **Moderate.**
- Northern Analytics lists acceptance sign-off within build and test (https://www.northern-analytics.com/process, as of 2026-10). **Moderate.**
- Pitfall: an engineer's own test run called "acceptance" removes the business check; heavyweight acceptance for every small release invites bypassing it (same sources). **Moderate.**

**Verdict: adapted, as new slice NEXT 19.** Acceptance scenarios are written from the requirements brief and the metric catalog before the site is built. Before the v1 release, the project owner answers each scenario using only the site. Defects are logged, and a dated go/no-go note lists what is deferred. The note says it is a one-person acceptance test. The cold-read tests remain the outside view.

### 1.5 Release and change management — adapted
**In plain terms.** Teams announce what changed, version anything others depend on, and give notice before breaking it.

**The evidence.**
- dbt's model versions let a team publish a new version, deprecate the old one and remove it after consumers move (https://docs.getdbt.com/docs/mesh/govern/model-versions, as of 2026-10). **Moderate.**
- GitLab's issue, merge request and review chain forms a traceable change record (handbook, above). **Moderate.**
- Pitfall: silently renaming or redefining a column breaks consumers unseen; keeping every old version forever leaves an unmaintainable catalog (dbt, above). **Moderate.**

**Verdict: adapted, in new slice NEXT 20.** Contracts are already versioned (`CLAUDE.md`, "Never break" 6). Each promotion of `develop` to `main` becomes a release: a git tag and agent-drafted release notes in a changelog. After v1, a breaking change to a published mart uses a dbt model version with a deprecation note. A label taxonomy for pull requests was rejected as noise for one person.

### 1.6 Retrospectives and incident reviews — adapted
**In plain terms.** Teams look back after a delivery, and write a blameless account of anything that broke.

**The evidence.**
- GitLab's data-science teams open a retrospective after every project and close it only after synthesis (https://handbook.gitlab.com/handbook/enterprise-data/organization/data-science/project_dev_approach/, as of 2026-10). **Moderate.**
- GitLab's data-incident process names a responsible person, communicates status, validates the recovered data and ends in a retrospective (https://handbook.gitlab.com/handbook/enterprise-data/data-governance/incident-management/, as of 2026-10). **Strong.**
- Pitfall: a retrospective with no follow-up is performance; blame suppresses reporting (same sources). **Moderate.**

**Verdict: adapted, in NEXT 20.** One retrospective at the v1 release names what worked, what did not and one process change. An incident record (impact, timeline, cause, fix, prevention) is written only for a real failure that reached a published number or broke a run; the ai-org escape log already records code bugs that reached `main`. A recurring retrospective cadence was rejected: there is no team to align.

### 1.7 Documentation — adopted
**In plain terms.** Teams keep reference docs next to the code, runbooks for recovery, decision records, and a guide that lets someone else operate the system.

**The evidence.**
- GitLab separates handbook pages, code-local READMEs, runbooks and project records (https://handbook.gitlab.com/handbook/enterprise-data/how-we-work/, as of 2026-10). **Strong.**
- Consultancies hand over runbooks and training so the client can operate alone (Blue Peak and Northern Analytics, above). **Moderate.**
- Pitfall: generated docs alone leave decisions and recovery steps unwritten, and stale docs mislead more than missing ones (same sources). **Moderate.**

**Verdict: adopted.** The existing homes stay (README, `ARCHITECTURE.md`, `docs/adr/`, `docs/FINDINGS.md`, `docs/CONVENTIONS.md`), and dbt docs publish lineage (NEXT 3c). NEXT 20 adds runbooks for a stopped listener, a failed contract check, a failed dbt build and a full rebuild from raw files. NEXT 15 adds a "How this was built" section (section 4.3).

## 2. From business questions to metrics and models

### 2.1 Metric definitions — adopted
**In plain terms.** Each number the company reports gets one written definition that every dashboard uses, so "revenue" cannot mean two things.

**The evidence.**
- dbt semantic models give each metric a name, description, aggregation and time dimension (https://docs.getdbt.com/docs/build/semantic-models, as of 2026-10). **Strong.**
- dbt allows arbitrary `meta` on metrics (https://docs.getdbt.com/reference/resource-configs/meta, as of 2026-10), but the docs' metric-level examples are labeled dbt 1.12 and later. The local test on 2026-10-02 settled it for this repo: dbt 1.11.15 accepted `config: meta:` on a metric and carried owner, unit, clock and status into both its manifest and its semantic manifest (`docs/FINDINGS.md`). **Strong for 1.11, from the test.**
- Pitfall: a dashboard formula treated as the definition breeds several plausible versions of one metric; a formula without grain and time rules gets aggregated wrongly (same sources). **Moderate.**

**Verdict: adopted.** Each metric carries a name, label, plain definition, formula, grain, unit, clock (game date, company date or wall-clock hour, as `CLAUDE.md` "Never break" 3 requires), owner role, status (draft, certified or deprecated) and source model. The catalog starts as one standalone file in the shape of dbt 1.11's metric YAML, outside dbt's model folders because of the sandbox crash in section 2.6. The dbt design session (NEXT 3·0) decides when it moves into dbt.

### 2.2 Metric tree — adapted
**In plain terms.** A metric tree puts the company's top number at the root and breaks it into the numbers that drive it. Some branches are plain arithmetic and always add up. Others are beliefs about cause and effect that need evidence.

**The evidence.**
- Amplitude publishes a North Star playbook built around one outcome metric and the inputs that drive it (https://amplitude.com/books/north-star/about-north-star-framework, as of 2026-10). The cited page is the playbook's introduction; its chapter text could not be opened to confirm the exact wording on input counts or causal links. **Weak.**
- The DuPont analysis, a corporate-finance driver tree from 1914, is an exact identity: its parts multiply back to return on equity but do not explain why a part moved (https://www.oreilly.com/library/view/key-mba-models/9781292016856/html/chapter-041.html, 2015-04). **Strong.**
- Cutler, a product-practice writer then at Amplitude, asks that hypotheses linking a metric to outcomes be written down and open to challenge, and that each metric be inspectable and decomposable (https://amplitude.com/blog/vanity-metrics, 2022-06). **Strong.**
- McKinsey's driver-tree guidance separates volume from price and mix and warns against double counting across branches (https://www.mckinsey.com/capabilities/strategy-and-corporate-finance/our-insights/selecting-p-and-l-linked-kpis-for-industrial-transformations, as of 2026-10). **Moderate.**
- Observational links are not causal without stated assumptions such as exchangeability; Hernán and Robins set these out (https://miguelhernan.org/whatifbook, 2020-01). **Strong.**
- Pitfall: an arrow from marketing to visits looks proven when it is only plausible; an unowned tree decays into an unused diagram (Cutler and McKinsey, above). **Moderate.**

**Verdict: adapted.** The root is company operating profit. Every link is labeled **identity** or **hypothesis**; no published standard exists for these labels, so this scheme is the project's own, inferred from the sources. Identity links get dbt tests that reconcile exactly. Hypothesis links record the claim, expected direction and lag, evidence, rival explanations, confidence and the date last reviewed, and their findings say "observational evidence consistent with". Every target metric is paired with a guardrail metric, such as operating cost against visits. The tree is reviewed at each company year-end close, which is this business's natural reporting cycle.

### 2.3 Theme-park industry metrics — adopted
**In plain terms.** Real park companies report a small, stable set of numbers. Using their names makes the project read as a park business, not a game.

**The evidence.**
- United Parks defines attendance as "the number of guest visits", and in-park per-capita spending as food, merchandise and other revenue divided by attendance (https://www.sec.gov/Archives/edgar/data/1564902/000095017025030398/prks-20241231.htm, 2025-02). **Strong.**
- Cedar Fair reported operating days (2,365 in 2023 against 2,302 in 2022) and explained the change by added early-season days and weather closures (https://www.sec.gov/Archives/edgar/data/811532/000081153224000035/fun-20231231.htm, 2024-02). **Strong.**
- Six Flags quantified a fiscal-calendar shift (37 fewer operating days in Q4 2024 for the legacy Cedar Fair parks) and its effect on revenue and attendance (https://www.sec.gov/Archives/edgar/data/1999001/000199900125000048/sixflags-exh991xq42024.htm, 2025-02). **Strong.**
- Six Flags presents results on a "same-park basis" that excludes parks sold or closed between the compared periods (https://www.sec.gov/Archives/edgar/data/1999001/000199900126000094/sixflags-exh991xq22026.htm, 2026-08). **Moderate, single source.**
- The TEA and AECOM attendance report covers only gated, ticketed parks, so its rankings do not fit a free-entry park (https://aecom.com/wp-content/uploads/documents/reports/AECOM-Theme-Index-2023.pdf, 2024-08). **Strong.**
- Pitfall: "per capita" changes meaning when its denominator or revenue scope changes; Cedar Fair counted parking as in-park revenue, while the combined Six Flags counts it as admissions (Cedar Fair Q1 2024 10-Q, https://www.sec.gov/Archives/edgar/data/811532/000081153224000079/fun-20240331.htm, 2024-05). **Strong.**

**Verdict: adopted.** Metric names follow the filings: **guest visits** (in this game every guest is one visit, because guests never return); **ride revenue**, never "admissions"; **revenue per visit** split into ride, food and drink, and merchandise; **operating days** and **revenue per operating day**; **operating profit**, not adjusted EBITDA (earnings before interest, taxes, depreciation and amortization), which the game cannot support; and **capital spending** per park for ride construction. Year-over-year views show fiscal months with an operating-days bridge, and same-park figures list a park in its first season separately. The closed months never appear as zero months. Survey-style satisfaction scores and queue wait times are not claimed unless the capture records them; the game's guest happiness value is reported under its own name.

### 2.4 Bus matrix and four-step design — adopted
**In plain terms.** Before building tables, teams list the business processes and the shared dimensions each one uses, then decide each table's grain (what one row means) first.

**The evidence.**
- Kimball's bus matrix lists business processes as rows and shared dimensions as columns, marking where dimensions must be conformed (https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/kimball-data-warehouse-bus-architecture/, as of 2026-10). **Strong.**
- The four steps run in order: business process, grain, dimensions, facts (https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/four-4-step-design-process/, as of 2026-10). **Strong.**
- Pitfall: failing to declare the grain first is the most frequent design error (https://www.kimballgroup.com/2003/03/declaring-the-grain/, 2003-03). **Strong.**

**Verdict: adopted** in NEXT 13 (the matrix) and NEXT 3·0 (the per-mart grain). A first draft of the grid, from the event types already captured; NEXT 13 confirms each grain and cell:

| Business process (draft grain) | Park | Ride | Stall and item | Game date | Company date |
|---|---|---|---|---|---|
| Admissions (park-day) | x | | | x | x |
| Ride operations (ride-day) | x | x | | x | x |
| Stall sales (stall-day) | x | | x | x | x |
| Finance (park-month statement) | x | | | x (month) | x (month) |
| Weather (park-day) | x | | | x | x |

Every process shares park and both dates, so those dimensions must be conformed first; ride and stall each serve one process today, and the finance row joins the dates at month level.

### 2.5 Star schema and wide tables — adopted
**In plain terms.** Fact and dimension tables are the reusable core; a wide, pre-joined table is a convenience for one consumer.

**The evidence.**
- dbt Labs says to choose by consumer: separate facts and dimensions for users and tools that join, wide tables for those that do not (https://www.getdbt.com/blog/guide-to-dimensional-modeling, as of 2026-10). **Moderate, vendor guidance.**
- Pitfall: one company-wide table duplicates logic and hides grain (same source). **Moderate.**

**Verdict: adopted, as NEXT 3c already plans:** stars first, and a few wide views derived from them for the site.

### 2.6 Semantic layer — not adopted yet; its local test passed
**In plain terms.** A semantic layer stores metric definitions once and answers queries from them. dbt's open-source engine for this, MetricFlow, works on this project's stack, but it would be a new dependency and it trips a sandbox limit.

**The evidence.**
- dbt documents a local `mf` command for self-hosted dbt that lists, validates and queries metrics; only the hosted Semantic Layer's integrations need a paid plan (https://docs.getdbt.com/docs/build/metricflow-commands, as of 2026-10). **Strong.**
- MetricFlow is Apache 2.0 licensed from version 0.209 and lists dbt-duckdb as a supported adapter (https://github.com/dbt-labs/metricflow, as of 2026-10). **Strong.**
- **Local test, 2026-10-02:** `dbt-metricflow` 0.15.0 (MetricFlow 0.213.0) resolved beside the pinned `dbt-core` 1.11.15, `dbt-duckdb` 1.11.0 and `duckdb` 1.5.5, in a scratch environment outside the repo. A small project with a park-day semantic model and three metrics passed `dbt build` and `mf validate-configs`, including its checks against the warehouse. `mf query` grouped revenue, visits and revenue per visit by month and park, and the ratio was correct: 219.5 ÷ 73 = 3.007 (`docs/FINDINGS.md`).
- **The sandbox crash:** any `dbt parse` of a project holding semantic models fails inside Claude Code's sandbox with `PermissionError` from `os.sysconf("SC_SEM_NSEMS_MAX")`. dbt-core's metric validator creates a process pool even though it runs its rules one at a time, and the sandbox blocks the system call the pool needs. The test above ran only with a scratch-only patch that skips that call. CI and a normal terminal are unaffected.
- The newest dbt docs describe a semantic-model YAML for dbt 1.12 and later; this project stays on 1.11 (`docs/adr/0004-dbt-core-1x-on-duckdb.md`), so the catalog uses the 1.11 shape the test used.

**Verdict: stays the LATER bet "Governed metrics, then an AI chat",** with its first assumption now tested and holding. Adopting it needs the project owner's sign-off on the new dependency, and a way to keep `make check` runnable by agents: an upstream fix, or a sandbox exception the project owner approves.

## 3. Environments, CI/CD and data quality

### 3.1 Development, test and production — adopted
**In plain terms.** Experiments, automated tests and the real warehouse never write to the same place, and test data never mixes with real data.

**The evidence.**
- DuckDB can attach several database files and read one while writing another, but it writes to only one file per transaction and has no cross-file atomic commit (https://duckdb.org/docs/lts/sql/statements/attach, as of 2026-10). **Strong.**
- dbt's hosted CI builds each pull request in its own temporary schema and drops it afterwards; the isolation idea carries over to dbt-core without the automation (https://docs.getdbt.com/docs/deploy/continuous-integration, as of 2026-10). **Moderate.**
- Pitfall: pointing CI at the production file "read-only except for models" is not isolation, since builds and stored test failures still write (inference from the same sources). **Weak.**

**Verdict: adopted** for NEXT 14: one DuckDB file per environment (development, a temporary CI file built only from the committed sample, and production), with rehearsal data kept in its own landing path and file, apart from company data. NEXT 14's research step narrows to the mechanics: dbt targets, file paths, and how a production build is published.

### 3.2 CI/CD — adapted
**In plain terms.** Every change is built and tested before merge; the real warehouse is rebuilt after the change lands.

**The evidence.**
- dbt-core supports "slim CI": compare against a saved production manifest, build only `state:modified+`, and defer the rest to production (https://docs.getdbt.com/reference/node-selection/state-selection and https://docs.getdbt.com/best-practices/best-practice-workflows, as of 2026-10). **Strong.**
- GitHub Actions triggers on pull requests and pushes and keeps run artifacts between jobs (https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows and https://docs.github.com/en/actions/concepts/workflows-and-actions/workflow-artifacts, as of 2026-10). **Strong.**
- A GitHub-hosted runner cannot reach data on a laptop, so production runs must be local or use a self-hosted runner (inference from the same sources). **Moderate.**
- Pitfall: slim CI breaks silently when the saved manifest no longer matches what is deployed; for a small sample, a full build is simpler and safer (dbt workflow guidance, above). **Moderate.**

**Verdict: adapted.** Every pull request already runs a full `dbt build` on the committed sample inside `make check`. Production builds stay local `make` runs (NEXT 2e decides when they run). Rejected: slim CI, because the sample builds in minutes and the stale-manifest risk buys nothing; and a self-hosted runner, because it would expose the project owner's machine to CI jobs. Write-audit-publish (build a candidate file, audit it, then swap it in) is the candidate for publishing production; NEXT 14 tests the swap, since DuckDB cannot commit across files atomically.

### 3.3 Data-quality testing — adopted
**In plain terms.** Different tests catch different problems; key checks alone never prove a total is right.

**The evidence.**
- dbt data tests return failing rows, cover keys, accepted values and relationships, and take `warn_if` and `error_if` thresholds (https://docs.getdbt.com/docs/build/data-tests, as of 2026-10). **Strong.**
- dbt unit tests check a model's logic on fixed inputs before it builds, and are recommended for complex logic and past bugs (https://docs.getdbt.com/docs/build/unit-tests, as of 2026-10). **Strong.**
- A model contract checks a model's shape at build time, not its accuracy (https://docs.getdbt.com/guides/mesh-qs, as of 2026-10). **Moderate.**
- No standard mutation-testing tool for dbt data tests was found. **Gap.**
- Pitfall: `unique` and `not_null` passing is not evidence that revenue is right; that needs an independent total (dbt data-test docs, above). **Strong.**

**Verdict: adopted** for NEXT 3·0 and 3d: unit tests for the complex intermediate logic (click collapsing, save lineage, company dates); data tests for keys and relationships; contracts on the published marts; reconciliation to the game's own totals (already planned); and a stated severity for every test. Mutation tests stay as planned but are hand-built: alter a fixture or a predicate on purpose and require a named test to fail.

### 3.4 Data service levels — adapted
**In plain terms.** A team writes down how fresh, complete and correct each published table should be, how it measures that, and what happens when it slips.

**The evidence.**
- Google's SRE book separates the indicator measured (SLI), the target (SLO) and the agreement with consequences (SLA) (https://sre.google/sre-book/service-level-objectives/, as of 2026-10). **Strong.**
- Google recommends indicators of the form "good events ÷ total events" and warns that a 100% target leaves room only for reactive work (https://sre.google/workbook/implementing-slos/, as of 2026-10). This advice concerns service reliability, not whether a wrong number may publish. **Strong.**
- dbt frames source freshness checks as measuring a defined service level (https://docs.getdbt.com/docs/deploy/source-freshness, as of 2026-10). **Moderate.**
- Pitfall: calling every schedule an SLA, or setting 100% targets that cannot be operated (Google, above). **Strong.**

**Verdict: adapted** for NEXT 2e: one short service note per published table, naming its owner and what triggers a refresh, with three indicators. Currency is measured two ways: whether raw captures exist that the table has not been built from, and the time since its last successful build, because capture age alone cannot show a table whose build never ran (the problem NEXT 2e exists to solve). Completeness uses the existing `seq` audit. Accuracy uses the reconciliation tests. Targets are set per indicator: required reconciliations and the year-end close are publication gates that must pass in full, and only operational indicators, such as build success and currency, get targets below 100%. The note ends with the response steps. Rejected: contractual SLAs, since no consumer holds a contract.

### 3.5 Data observability — adapted
**In plain terms.** Keep enough history of runs and test results to notice a problem and trace what it affected.

**The evidence.**
- dbt writes run and freshness artifacts and recommends keeping results over time for trends (https://docs.getdbt.com/reference/commands/source, as of 2026-10). **Strong.**
- Elementary's open-source package adds anomaly tests and alerts; no source confirmed its DuckDB support (https://docs.elementary-data.com/, as of 2026-10). **Moderate.**
- Pitfall: buying a tool before defining owners, thresholds and responses yields a dashboard nobody acts on (lane synthesis of the above). **Weak.**

**Verdict: adapted** for NEXT 2e: dbt's run artifacts load into a local run-history table, and CI keeps its artifacts. Rejected for now: Elementary and Great Expectations, both new dependencies, and dbt tests already cover their checks here.

## 4. How a reviewer will read it

### 4.1 Few process documents, each tied to a real change — adopted
**In plain terms.** Reviewers skim the README and a demo first, and credit decisions they can trace, not a pile of templates.

**The evidence.**
- dbt Labs' hiring guide has interviewers probe how a candidate framed the problem, handled wrong source data and explained trade-offs (https://www.getdbt.com/blog/hiring-analytics-engineer, 2025-02). **Moderate.**
- dbt Labs describes contracts, tests, semantic definitions and documentation as the analytics engineer's 2026 output, with business judgment as the human part (https://www.getdbt.com/blog/the-analytics-engineer-in-2026-system-designer-governance-owner-ai-context-provider, 2026-06). **Moderate.**
- No source measures whether hiring reviewers read ADRs, runbooks or service notes in a portfolio. **Gap.**

**Verdict: adopted** as a constraint on NEXT 15: the site links a handful of process documents, each to the change, test or failure it governed.

### 4.2 A simulated company, honestly labeled — adopted
**In plain terms.** A game company reads as credible when the data is real, the limits are stated and nothing pretends to be a real organization.

**The evidence.**
- A data-science hiring manager described hiring a candidate whose centerpiece was a Dota project, because the candidate could defend it to people who did not know the game (https://www.reddit.com/r/datascience/comments/tbh2e, as of 2026-10). **Weak, single account.**
- Pitfall: presenting invented executives, sign-offs or business impact as real external validation (lane synthesis; no source contradicts it). **Weak.**

**Verdict: adopted.** The site says this is one person's simulated park company built on real game events, names the project owner's role as the company's sole decision-maker, and claims no business impact beyond what the game shows.

### 4.3 Heavy AI involvement, disclosed — adopted
**In plain terms.** Employers increasingly accept AI-built work, as long as the candidate says so and can defend every decision.

**The evidence.**
- Canva requires AI tools in some engineering interviews and asks candidates what they kept, changed or built on (https://www.canva.dev/blog/engineering/yes-you-can-use-ai-in-our-interviews/, 2025-06). **Strong.**
- DoorDash allows AI for preparation but requires take-home work to reflect the candidate's own conclusions, and treats undisclosed misrepresentation as disqualifying (https://careersatdoordash.com/blog/doordash-stance-ai-interviewing/, 2025-10). **Strong.**
- Pitfall: hiding heavy AI use, or making it the headline while being unable to explain the work (same sources). **Strong.**

**Verdict: adopted** for NEXT 15: a "How this was built" section says AI agents wrote most code and documents; the project owner set the requirements, business rules, architecture choices, metric meanings and acceptance; and blind reviewers checked the work. It shows two or three real examples of agent output that review rejected or corrected, taken from the finding ledgers.

## 5. Where sources disagree
- **How much ceremony to show.** The lifecycle lane proposed role-played stakeholder interviews and a signed approval by a sponsor persona; the reviewer lane found that simulated stakeholders presented as real read as theater. Resolved for the lighter form: one real decision-maker, labeled roles, and few documents.
- **Phasing models.** Kimball's lifecycle, dbt's per-change loop and consulting stages differ in scope and audience, not in substance; this project uses the loop for work and the stages for the story.
- **Star or wide tables.** Kimball favors conformed stars; dbt Labs accepts wide tables for some consumers. Resolved as stars first, wide views derived.
- **Per-capita scope.** Cedar Fair and the combined Six Flags put parking in different revenue lines, so the project fixes each per-visit metric's scope in its catalog entry.

## 6. Gaps and thin evidence
- No source studies how hiring reviewers weigh process documents, simulated stakeholders or game-themed projects; section 4 rests on employer AI policies and dbt Labs' hiring guidance.
- No standard formula for ride throughput, capacity use, wait time or satisfaction appears in public operator sources.
- No standard mutation-testing tool for dbt, and no standard vocabulary for identity and hypothesis links in a metric tree.
- No source confirms Elementary on DuckDB, or an atomic file swap for publishing a DuckDB warehouse on every operating system.
- Single-source claims: the Six Flags same-park basis (2026-08 release) and the Dota hiring anecdote. The Amplitude playbook's wording could not be checked (section 2.2).
- Not researched here, by design: dbt project structure and setup (NEXT 3·0's own research), warehouse-environment mechanics (NEXT 14), and the website tool (NEXT 15).

## 7. What changes on the roadmap
- The NOW slice moves to the archive with its result, and the metric catalog (NEXT 13) can start.
- NEXT 13 gains the requirements brief, the industry metric names, the identity and hypothesis labels, and the standalone catalog file.
- NEXT 14 adopts one DuckDB file per environment and narrows its research to the mechanics and the publish swap.
- NEXT 2e gains the service notes and the run-history table; NEXT 3·0 gains the per-mart design note, the test-layer policy and the sandbox constraint; NEXT 3d gains hand-built mutation tests.
- NEXT 15 gains the curated process documents, the simulation label and the "How this was built" section.
- New: NEXT 19 (v1 acceptance walkthrough, verify: owner-later) and NEXT 20 (operating documents: release notes and tags, runbooks, incident records, the v1 retrospective).
- The LATER bet on governed metrics records the passed local test and the sandbox crash.
