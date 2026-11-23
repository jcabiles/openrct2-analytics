# dbt design and setup for the park company's warehouse — research findings
status: research complete; accepted provisionally by the project owner on 2026-10-03 with all five section-10 resolutions (verify: owner-later); the findings of three cross-family (Codex) review rounds are applied (ledger `docs/ai-dlc/ledger/dbt-design.md`) · date: 2026-10-03 · initiative: park-company (roadmap NEXT 3·0, "dbt design and setup", drafted by agents; reviewed later by the project owner)

## Bottom line
- **Accepted provisionally on 2026-10-03 (verify: owner-later).** The roadmap defined this item as a joint session with the project owner; the project owner ruled that agents draft it for later review, and on 2026-10-03 accepted ADR 0016 (`docs/adr/0016-dbt-design.md`) provisionally, with all five resolutions in section 10. A correction at the later review reopens the models built on it. Marts waited for the project owner's confirmation of the requirements brief, given on 2026-10-03; staging and intermediate work could start before it. The design ran after its two prerequisites, the data-team practices research and the metric catalog (`metrics/catalog.yml`, merged to `develop` at 3a01f17). Its outputs are this report, ADR 0016, one design note per mart (`docs/ai-dlc/reports/dbt-design--marts.md`) and the dbt rules of appendix A, now in `docs/CONVENTIONS.md`; the catalog's planned key and counter wording is edited to match section 2.
- **The design is a conventional dbt layering with a Kimball star at the end.** Staging (one model per event type: rename, cast, convert money once, sentinels to null, remove duplicate deliveries), intermediate (save lineage, company dates, counter changes, keys), and marts (five dimensions, four facts, and wide reporting tables for the site). Every model is a table, rebuilt in full on every build, in a schema named after its layer.
- **Facts key on the game date, not the company date,** so a corrected company-year stamp (ADR 0014, proposed) never changes a key. Each mart names one clock: the company date, by day or by month.
- **Tests follow the metric tree's two link kinds.** An identity link (exact arithmetic) becomes a custom dbt test with no tolerance parameter at all, at error severity. A hypothesis link with a numeric check becomes a second custom test whose tolerance sits in its YAML arguments, at warn severity. The two observational hypotheses (metrics 18 and 19) become singular tests at warn severity that store their result rows for the year-end review. Enforced model contracts on every mart pin column names and types; a probe on the pinned dbt showed they catch a money column whose decimal scale is wrong, even on an empty table, so a mart the committed sample cannot fill is still checked for its declared columns.
- **The metric catalog should split into three files along the business-process seam** (finance, admissions, ride operations), and stay outside dbt until the marts it points to exist. Its 1,089 lines are twice the house's 500-line aim.
- **The sandbox limit is narrower than recorded, but MetricFlow is still out of reach.** Plain `dbt parse` and `dbt build` crash in the agents' sandbox when semantic models sit in a model folder; with the metric-catalog branch's thread-pool swap both pass. MetricFlow queries cannot run anywhere until its package is approved, so the same-park year-over-year test that the catalog assigned to this session moves to a plain SQL test on a reporting table.
- **Five conflicts between existing records, or between a record and this design, were resolved as proposed** (section 10; accepted 2026-10-03). The edits to ADR 0014 and ADR 0013 are made on their own branches, listed in ADR 0016's follow-ups.

## How this was produced
One agent read the project's records (the roadmap item, `docs/CONVENTIONS.md`, `ARCHITECTURE.md`, `docs/FINDINGS.md`, ADRs 0004 to 0015, the data-team practices report, the dbt project, the 12 contracts at 1.3.0 on `feat/full-capture-part-2` and the metric catalog, first on `feat/metric-catalog` at 6374a1c and then as merged to `develop` at 3a01f17, where `metrics/catalog.yml` and its spec are unchanged) and ran probes on a scratch copy of the dbt project outside the repo.

**Fetching docs.getdbt.com was refused by this session's permission settings**, so no dbt documentation page was opened this session. Version-specific claims were checked instead against the pinned packages themselves (dbt-core 1.11.15, dbt-duckdb 1.11.0, dbt-semantic-interfaces 0.9.0, DuckDB 1.5.5), by reading their installed source and by running them. Those runs are the strongest evidence available for the pinned versions and are marked **verified (run)** or **verified (source)**. Documentation pages that earlier reports opened are cited with their dates. Pages listed under "For the reviewer to open" were not opened by anyone; the Codex review should open them.

**Sample for every measured claim:** the committed rehearsal extract (`data/sample/rehearsal/`: one park copy, three headless sessions, 108 park snapshots, 3 monthly statements, plugin 0.3.0, no player), one machine (Apple silicon, arm64, macOS 26.5.2), inside Claude Code's sandbox, 2026-10-03. Appendix B gives the probe script, its input, its environment and the observed output, so anyone can re-run it; the `docs/FINDINGS.md` row of that date cites it. Probe labels P1 to P8 below point into that appendix.

Evidence strength follows the data-team practices report: **strong** (a run on the pinned stack, or several primary sources agree), **moderate** (one primary source), **weak** (inference). Each section ends with a recommendation, its gain and cost, and the alternative rejected.

## Decisions at a glance

| Question | Recommendation | Section |
|---|---|---|
| Layers and folders | `models/staging`, `models/intermediate`, `models/marts`; names `stg_<event_type>`, `int_<grain>__<step>`, `dim_`, `fct_`, `obt_`; one schema per layer; all tables | 1 |
| Five guest event types | Stage `guest_boarded`, `guest_refused`, `guest_arrived` when part 2 lands; `guest_left` and `guest_snapshot` wait for a consumer after v1 | 1 |
| Grains and keys | Park-day, park-month, ride-day, boarding facts keyed on the game date; company date as the clock | 2 |
| Money | Unchanged: one conversion in staging, now through one macro; contracts pin `DECIMAL(18,2)` downstream | 3 |
| Identity and hypothesis links | Two custom generic tests; identity has no tolerance argument; hypothesis tolerance in YAML, cross-checked against the catalog; metrics 18 and 19 as warn singular tests that store their results | 4 |
| Metric catalog | Split into three files by business process; move into dbt only after the marts exist | 5 |
| Test strategy | Generic tests for keys, singular for one-offs, unit tests for intermediate logic, enforced contracts on marts, an expected row count per mart on the committed sample, stated severity, pytest-driven mutation tests, no packages | 6 |
| Incremental models | None: full rebuild of tables on every build | 7 |
| Environments | ADR 0013's four outputs unchanged; layer schemas identical in every file | 8 |
| Semantic layer in the sandbox | Keep semantic YAML out of model folders until the marts exist; offset test moves to SQL | 9 |

## 1. Layers, names and folders

### 1.1 Three layers, one schema each, all tables — recommended
**The recommendation.** Keep the three layers `docs/CONVENTIONS.md` §3 already names, flat folders inside each, and these names:

| Layer | Folder | Name | Does | Materialized |
|---|---|---|---|---|
| Staging | `models/staging/` | `stg_<event_type>`, exactly the contract name | rename, cast, convert tenths to dollars, sentinel to null, remove duplicate deliveries on `event_id`; no joins | table |
| Intermediate | `models/intermediate/` | `int_<grain or entity>__<step>`, for example `int_park_days__kept`, `int_statements__kept`, `int_events__save_lineage`, `int_company_years__validated` | save lineage, company dates, counter changes, ride and item keys, resolving reloaded days and months | table |
| Marts | `models/marts/` | `dim_<entity>`, `fct_<grain>`, `obt_<grain>` (wide reporting table) | the star schema and the site's wide tables | table |
| Seeds | `seeds/` | the reference data's name | park registry, item codes | seed |

Each layer lands in its own schema (`staging`, `intermediate`, `marts`, `seeds`) inside every DuckDB file, through `+schema` in `dbt_project.yml` and a five-line `generate_schema_name` override that uses the layer name as given. dbt's default would write `main_marts`, prefixing the target's schema, which only matters when environments share one database; here each environment is its own file (ADR 0013).

**The evidence.**
- A probe added the override and `schema: marts` to a table model: DuckDB listed it as `marts.probe_mart` while the other models stayed in `main` (dbt-core 1.11.15, dbt-duckdb 1.11.0; P5). **Strong, verified (run).**
- ADR 0013 (proposed) already requires tables in every published file and allows intermediate models to be tables or ephemeral, never views; its probe found that views over Parquet break when the file moves and change when the Parquet changes (`docs/FINDINGS.md`, 2026-10-03 warehouse row). **Strong.**
- The roadmap's deep-dive read asks a reviewer to trace a number "through the contract, staging, intermediate and mart models" and query DuckDB directly. An ephemeral model leaves no relation to query. A probe confirmed that dbt 1.11.15 runs unit tests and data tests on ephemeral models (P4), so testability does not decide it; traceability does. **Strong, verified (run).**
- The `fct_` and `dim_` prefixes are the Kimball vocabulary ADR 0012 adopted (bus matrix, four-step design, star schema). dbt Labs' project-structure guide, which uses `stg_[source]__[entity]` names, was not opened this session. **Moderate (repo rules); the guide's position is unverified.**

**Gain:** a reader sees each layer as a schema in DuckDB, the site's reader can be limited to `marts`, and ADR 0013's publish-time row check (as amended in section 6.2) can list one schema. **Cost:** intermediate tables enlarge each file (views of 0.5 MB became 1.3 MB of tables on the sample in ADR 0013's probe), one override macro, and renaming the three existing staging models (`stg_park_daily`, `stg_finance_monthly`, `stg_sessions`) to their event-type names when the parked staging rework runs. **Rejected:** dbt's double-underscore source names (`stg_landing__park_snapshot`): the project has one source, so the prefix adds characters and no meaning. Ephemeral intermediate models: smaller files, but nothing to query when tracing a number.

### 1.2 The five guest event types — recommended: stage three in v1
**The recommendation.** `docs/CONVENTIONS.md` §3 allows a staging model only for an event type with a consumer. Three of part 2's five types have a v1 consumer and get a staging model when part 2 merges: `guest_boarded` (ride popularity, metric 29, through the helper `ride_boardings`), `guest_refused` (the "too expensive" refusals the observational pricing model reads, roadmap NEXT 8) and `guest_arrived` (an independent count of visits that checks `guest_visits`, metric 18). `guest_left` and `guest_snapshot` serve the cohort, satisfaction and length-of-stay work after v1 (NEXT 9 and 10) and join the stated exceptions beside `plugin_stats`. Guest identity is `session_id` + `guest_key`; the contract mints `guest_key` within a session, guests never return, and a reload starts an empty cohort, so no guest key ever spans sessions. Boardings and refusals carry only `ride_id`; the intermediate layer finds the `ride_key` from that day's snapshot of the slot.

**The evidence.** The part 2 contracts (`contracts/guest_boarded.odcs.yaml` and the other guest contracts) list the fields, and ADR 0018 (`docs/adr/0018-guest-capture.md`) fixes the cohort at up to 100 guests drawn with probability 0.5 per arrival and per session. The metric catalog's `ride_boarding` semantic model reads `stg_guest_boarded`. **Strong (repo records).**

**Gain:** every staged type is used in v1, and the rule "staging only for a consumer" holds. **Cost:** two contracted types sit unstaged until after v1, and the CONVENTIONS exception list grows by two. **Rejected:** staging all five now. It would add about two models and 300 lines of YAML that nothing reads before v1.

## 2. Grains, keys and clocks of the marts
**The recommendation.** Nine star tables: dimensions `dim_park`, `dim_ride`, `dim_item`, `dim_date`, `dim_session`; facts `fct_park_day`, `fct_park_month`, `fct_ride_day`, `fct_ride_boarding`. Wide reporting tables (`obt_park_month`, `obt_company_month`, `obt_park_year`, `obt_company_year`, `obt_ride_day`) hold every published number as a column named after its catalog metric. The per-mart notes hold the detail; the summary:

| Mart | Grain | Key | Clock |
|---|---|---|---|
| `fct_park_day` | park × game day, kept | `park_id` + game date | company date (day) |
| `fct_park_month` | park × closed statement month, kept | `park_id` + `statement_year` + `statement_month` | company date (month of the statement) |
| `fct_ride_day` | ride occupancy × game day, kept (an occupancy as `int_ride_days__kept` detects it; the mart notes, `dim_ride`, list the replacements it cannot detect) | `ride_key` + game date | company date (day) |
| `fct_ride_boarding` | one boarding event | `event_id` | company date (day) and game ticks |
| "Company month" | company month, all parks | `company_date` | company date (month); published as `obt_company_month` |
| Guest cohort | cohort member × game day (deferred) | `session_id` + `guest_key` + game date | company date (day) |

Two clock decisions come out of the grains:
- **Keys use the game date.** A park's game dates and company dates map one to one (company year = start year + game year − origin), so the grain is the same either way. Under ADR 0014 a listed correction changes a row's company year; a key built on it would change, and every downstream key with it. The catalog's planned `park_day_key` text names the company date and needs a one-line edit when the mart lands.
- **Counter changes belong to the earlier day.** The park snapshot is read at the start of the game day, so the rise in `total_admissions` up to the next reading counts the previous day's guests. Assigned to the later date, each month's last day of visits would land in the next month, and 31 October's in March of the next company year. The same applies to ride counters.

**The evidence.** Grains come from the requirements brief's bus matrix (section 11 of `docs/requirements-brief.md`), the staging YAML ("taken at the start of that game day", `models/staging/stg_park_daily.yml`) and ADR 0008 (statements dated by their own month). No catalog metric names the wall-clock hour as its clock. **Strong (repo records); the counter-day rule is inference from the read time.**

**Gain:** keys that survive stamp corrections, and visits counted in the month they happened. **Cost:** a key and a time dimension are different columns, which readers must be told; the catalog's planned key wording changes. **Rejected:** keys on the company date (the catalog's planned wording), for the correction reason; a separate weather dimension at park-day grain, because it would duplicate `fct_park_day`'s grain, so `fct_ride_day` instead carries `park_day_key` as the one fact-to-fact link.

## 3. Where money converts from tenths
**The recommendation.** Keep `CLAUDE.md` "Never break" 3 exactly as built: each `_tenths` column converts to a `_usd` column in its event's staging model, once, as `DECIMAL(18,2)`. Two additions: the conversion moves into one macro, `tenths_to_usd(column)`, because `stg_finance_monthly.sql` repeats the same cast 16 times and `ride_snapshot` and the guest events add about ten more; and every mart declares its money columns as `decimal(18,2)` in an enforced contract. Money derived later (a ride's daily profit change, net cash change) is computed from `_usd` columns and cast back to `DECIMAL(18,2)`; no model outside staging reads a `_tenths` column.

**The evidence.**
- `docs/architecture/openrct2-facts.md` ("DuckDB surprises", "dbt reads the Parquet"): `/` returns a DOUBLE, so staging multiplies a `DECIMAL(18,0)` by 0.1; dbt unit tests compare through a double, so only a type check catches a double path on a money column. **Strong.**
- Probe: an enforced contract declaring `cash_usd` as `decimal(18,2)` failed the build when the model produced DOUBLE, `DECIMAL(18,0)` or `DECIMAL(18,4)`, each with "data type mismatch", and also when the model returned zero rows (P2). **Strong, verified (run, dbt-duckdb 1.11.0).**

**Gain:** one definition of the conversion, and a type pin that holds on empty tables. **Cost:** one macro a reader must open, and a data type on every mart column. **Rejected:** converting in the marts. It leaves tenths in intermediate models, where a sum of tenths and dollars can slip in.

## 4. Identity and hypothesis links as dbt tests
**The recommendation.** ADR 0012 labels every metric-tree link an identity (reconciled exactly) or a hypothesis (a claim with evidence). They become tests as follows:

| Link | dbt test | Where | Severity | Tolerance |
|---|---|---|---|---|
| Identity | custom generic test `reconciles_exactly(left, right)`: returns rows where `left is distinct from right` | on the mart that holds both sides at the stated grain; always across two tables or two independent sources, never a column against its own formula | error | none: the test has no tolerance argument, so one cannot be added by mistake |
| Hypothesis with a numeric check (metrics 7 to 9 against their ledger lines) | custom generic test `within_tolerance(left, right, relative, absolute)` | `fct_ride_day` rolled up to park and company month against `fct_park_month` | warn | in the test's YAML arguments; the catalog's `tolerance` becomes structured (relative, absolute) and `scripts/check_metric_catalog.py` checks the two agree |
| Observational hypothesis (metrics 18 and 19, with lags) | a singular test per metric that returns its measured association and stores the rows (`store_failures: true`), section 4.1 | `tests/dbt/`, reading `fct_park_day` and `fct_ride_day` for closed company years | warn | none (the catalog says observational, no tolerance) |

Examples of real identities: the 14 statement lines equal the change in cash minus loan (independent sources: the ledger and the balance); company totals equal the sum of parks; each wide table equals the star it is built from; the sum of daily visits over a session equals the counter's rise. The catalog's definitional identities, such as operating revenue equals its four lines, are tested as the published column (`obt_park_month.operating_revenue`) against the lines in `fct_park_month`; a test of a column against its own formula inside one SQL statement proves nothing and is not written.

Custom generic tests live in `tests/dbt/generic/`, with `test-paths: ["tests/dbt"]` set in `dbt_project.yml`, so every dbt test file stays under the folder `docs/CONVENTIONS.md` §3 already gives them.

**The evidence.**
- Probe: `reconciles_exactly` passed on the sample's statement balance and returned 2 rows when 0.1 dollars was planted (WARN on `dev`, FAIL on a `company` target); `within_tolerance` at `severity: warn` reported WARN with a planted 50-dollar drift and left the run green (P3). **Strong, verified (run).**
- Probe: with the default test path, `dbt build` could not compile generic tests kept in `tests/dbt/generic/` ("'test_reconciles_exactly' is undefined"), although `dbt parse` alone did not report it; with `test-paths: ["tests/dbt"]` they ran (P3). **Strong, verified (run).**
- dbt-core 1.11.15 sets the behavior flag `require_generic_test_arguments_property` to true, so test arguments go under `arguments:` (`dbt/contracts/project.py`). The probe used that form with no deprecation warning. **Strong, verified (source and run).**
- The catalog spec's validator rule 8h already forbids a tolerance on an identity link, and its metrics 7 to 9 carry max(1% of the ledger figure, $1.00) at warn severity. **Strong (repo records).**

**Gain:** the link kind decides the test mechanically, and a tolerance has one numeric home with a check that the catalog agrees. **Cost:** two custom tests (about 10 lines), about 20 lines added to the catalog validator, a structured `tolerance` field in the catalog, and the two review tests of section 4.1. **Rejected:** tolerances as project variables in `dbt_project.yml`, a third place to keep in step; `dbt_utils` tests, a new dependency; review queries in `analyses/`, which dbt only compiles, so nothing would run them or keep their result.

### 4.1 The observational checks of metrics 18 and 19 — recommended: warn singular tests that store their rows
**The recommendation.** The catalog's two year-end checks become two singular tests in `tests/dbt/`, each configured `severity: warn`, `store_failures: true` and `schema: review`:
- `review_visits_same_day_ride_revenue` (metric 18's check): per park and closed company year, the correlation (DuckDB's built-in `corr`) between `guest_visits` (`fct_park_day.admissions_increase`) and daily ride revenue (metric 7 summed over the park's rides) on the same company day, with the number of paired days. One row per park-year.
- `review_rating_lag_visits` (metric 19's check): per park, closed company year and lag L in 7, 14 and 28 days, the correlation between `guest_visits` on day d and `park_rating` on day d − L, pairs taken only inside one company year's kept days, with the paired-day count and a `best_lag` flag on the lag with the highest correlation. Three rows per park-year.

"Closed" means the park-year is in `obt_park_year`. A test returns rows only for closed years, so on the committed sample (no closed year) both pass with zero rows; once a year closes, each build reports WARN, which here means "results ready to read", and dbt keeps the rows as a table `review.<test name>` inside the built file (P7). The year-end close review (NEXT 6) reads those tables from the published file and records the numbers, dated and labelled observational with their sample, in `docs/FINDINGS.md`. Neither test can fail a build. **Note, 2026-10-18 (ADR 0035).** "Closed" now means `is_company_year_closed` in `obt_park_year` (or a row of `obt_company_year`), so this definition is superseded, and `obt_park_year` holds open years too.

**The lag cases are tested in pytest**, because dbt unit tests apply only to models. Following the mutation-test pattern (section 6.1), a test copies the dbt project to a temporary folder, replaces `fct_park_day`, `fct_ride_day` and `obt_park_year` with one closed park-year of fixture rows, runs `dbt test --select review_*`, and reads the stored tables. Cases: visits equal to that day's ride revenue gives correlation 1 for metric 18; visits equal to the rating shifted by exactly 7, 14 and 28 days marks that lag `best_lag` for metric 19 (three parametrized runs); a fixture without a closed year stores no rows.

**The evidence.** Probe P7 ran both tests as written here, `severity: warn`, `store_failures: true`, `schema: review`, with the layer-schema override (section 1.1), over stand-ins for `fct_park_day`, `fct_ride_day` and `obt_park_year` built from the sample's kept rows (the game year standing in for the company year, which plugin 0.3.0 does not send; ride revenue as the rise in `total_customers` times `price_1`). With no closed year, both passed (exit 0, PASS=5) and dbt still created both landing tables, `review.review_visits_same_day_ride_revenue` and `review.review_rating_lag_visits`, as BASE TABLEs with 0 rows. With year 9 marked closed, `dbt build` exited 0 with WARN 1 and WARN 3, and the tables held 1 and 3 rows, one per park-year and one per lag. A one-row synthetic test showed that dbt's default schema naming would put the table at `main_review.review_probe` instead of `review.review_probe`, so the override is what makes the `review.<test name>` address hold. **Strong, verified (run) for the landing tables and their row counts; the stand-in marts are not the designed SQL, and the correlations on one partial season mean nothing.**

**Gain:** both checks run on every build of real data and leave a dated, queryable result in the published file, with no new model and no tolerance. **Cost:** every build after the first year-end close shows two WARN lines, which a reader must know are review results; the lag fixtures run through pytest at about 4 seconds each. **Rejected:** a small results model (`obt_hypothesis_review`): dbt unit tests could feed its fixtures without pytest, but it adds a fourth kind of mart that no page reads, an enforced contract, an entry in the expected-row table (zero on the sample) and about 60 lines of model and YAML.

## 5. Whether `metrics/catalog.yml` splits, and along which seam

### 5.1 Split by business process into three files — recommended
**The recommendation.** Split the catalog into `metrics/finance.yml`, `metrics/admissions.yml` and `metrics/ride_operations.yml`. Each holds the semantic models of one row of the bus matrix and the metrics built on them; a ratio that crosses processes lives with its denominator. Estimated from the branch's line ranges (6374a1c):

| File | Semantic models | Metrics | Lines (estimate) |
|---|---|---|---|
| `finance.yml` | `finance_month` | 1–6, 10–17, 31–33 | about 470 |
| `admissions.yml` | `park_day` | 18–20, 30, and the per-visit and per-day ratios 21–25 | about 255 |
| `ride_operations.yml` | `ride_day`, `ride_boarding` | 7–9, 26–29, helpers `ride_boardings` and `ride_open_days` | about 360 |

Tree links cross files (metric 7's parent is metric 3), which dbt resolves across the project. The validator and the shape check read `metrics/*.yml` instead of one path. The split happens in the first change that edits the catalog after this design is approved, not in this research.

**The evidence.** The branch's catalog is 1,089 lines; the house aims under about 500 lines per file (engineering standards; `docs/CONVENTIONS.md`'s size check covers code files, not YAML, so the gate does not fail). NEXT 17 (coaster statistics) and NEXT 18 (umbrellas) will add dimensions and metrics. When the catalog moves into dbt, each file can sit beside the marts its semantic models will name. **Strong (repo records); the line estimates are arithmetic from the branch.**

**Gain:** each file under 500 lines, and one file per process, matching the marts. **Cost:** the two catalog scripts and their tests change from one path to a folder, and a reader follows cross-file parents. **Rejected:** semantic models in one file and metrics in another (the metrics file would still be about 845 lines); splitting by tree role (a process's measures and metrics would land in different files).

### 5.2 When the catalog moves into dbt — recommended: after the marts exist
**The recommendation.** Keep the catalog outside dbt's model folders until the facts and wide tables it should point at exist (NEXT 3c), then move each file beside its marts and repoint every `model:` from staging to the marts in the same change. Two semantic models still name planned staging models, and most columns are planned; moving now would need stub models in the real project. The move then needs one of two things, a choice for the project owner: every `dbt` call in `make` runs through the thread-pool wrapper the shape check already uses, or an upstream fix lands in dbt-semantic-interfaces.

**Gain:** no stubs in the real project, and dbt's own validation on the real marts at the move. **Cost:** until then, dbt checks the catalog only through the shape check's temporary copy. **Rejected:** moving now; it buys nothing the shape check does not already give and adds stubs.

## 6. Test strategy

### 6.1 One policy per layer — recommended
| Layer | Generic data tests | Singular tests (`tests/dbt/`) | Unit tests | Model contract |
|---|---|---|---|---|
| Staging | `not_null` on envelope fields, `unique` on `event_id`, `accepted_values` on coded fields | pass-through checks against the source, as today | conversions and sentinel rules, `format: sql` when the input is a source | enforced, when the parked staging rework runs; it replaces the two `information_schema` singular tests, which are deleted in the same change |
| Intermediate | `unique` and `not_null` on the output grain | — | every complex rule: save lineage, duplicate removal, company dates (the catalog spec's October, eight-month and corrected-stamp cases), counter changes, ride and item keys | not enforced (not published) |
| Marts | `unique`, `not_null`, `relationships`; `reconciles_exactly`; `within_tolerance`; `rows_on_sample` (section 6.2), enabled only on the `ci` target | the year-end close, the same-park fixture, the two review tests (section 4.1) | — | enforced, types only, no constraints |

Severity is stated once as the project default (`data_tests: +severity: error` in `dbt_project.yml`); a `warn` test states it on the test. A test whose severity differs by data set uses the target: the probe's `severity: "{{ 'error' if target.name == 'company' else 'warn' }}"` warned on `dev` and failed on `company`. Mutation tests are pytest tests that copy the dbt project to a temporary folder, plant one fault, run `dbt build` and require a named test to fail, the pattern `scripts/check_metric_catalog_shape.py` uses. No dbt packages.

**The evidence.**
- Unit tests run today in `make check` (`models/staging/stg_park_daily.yml`, `stg_sessions.yml`), and `ARCHITECTURE.md` records their limits on this stack: a source input needs `format: sql`, values compare through a double, and each same-typed column needs a distinct value. **Strong (run in the gate).**
- Enforced contracts: dbt-duckdb 1.11.0 declares check, not-null, unique, primary-key and foreign-key constraints as enforced (`dbt/adapters/duckdb/impl.py`, `CONSTRAINT_SUPPORT`). Probe: a `not_null` constraint failed the build ("NOT NULL constraint failed"); a view with an enforced contract still failed a DOUBLE money column (P2). **Strong, verified (source and run).**
- **Why the part 1 contract was removed:** the full capture part 1 ledger, row W4-1 (`git show 36cbfdc:docs/ai-dlc/ledger/full-capture-part-1.md`), records that "an enforced dbt model contract was tried and removed: model contracts are a dbt setup choice the roadmap leaves to the dbt design session". It was deferred, not broken. **Strong.**
- The roadmap's 3·0 text and ADR 0012 ask for "contracts on published marts" and "a stated severity for every test". **Strong.**

**Gain:** each kind of test catches what it is good at; types are pinned at build time, keys report failing rows, and the published marts cannot change shape silently. **Cost:** a `data_type` on every mart column, about 4 seconds per mutation test, and three custom tests to maintain (`reconciles_exactly`, `within_tolerance`, `rows_on_sample`). **Rejected:** constraints inside contracts (a second mechanism that fails the build before a test can report which rows); `dbt_utils` and `dbt_expectations` (new dependencies; a concatenated key column and `unique` cover the combination test); unit tests on every model (they would mostly restate SQL).

### 6.2 Expected rows per mart on the committed sample — recommended, replacing a blanket "has rows" test
**The recommendation.** Each mart's YAML carries a custom generic test `rows_on_sample(expected)`, enabled only on the `ci` target, at error severity, that fails unless `count(*)` equals the number in this table. A mart the sample cannot fill is listed with 0 and is checked by its enforced contract alone: the build creates it with exactly its declared columns and types, which the contract probe showed holds on an empty table (P2). **Refreshing the counts.** A rebuild by `make bench-sample` that leaves every Parquet file byte-identical needs no change. Any other rebuild is committed together with a recount: build the sample with `rows_on_sample` excluded (`dbt build --profiles-dir . --target dev --exclude test_name:rows_on_sample`), run `select count(*)` on each of the 11 marts and 5 intermediate models that carry `rows_on_sample` (16 in all) in the built file, copy the numbers into this table and into each model's `rows_on_sample` argument, and require `make check` to pass on that change. Until the marts exist, each count comes from a stand-in query over the sample's kept rows. Probe P8 ran this procedure once on the committed sample in a scratch copy: the build exited 0 (PASS=76) and its 14 printed counts are the numbers below for the first 14 marts; the 1 of the year-to-date table (replaced on 2026-10-18; see the note under the table) came from that built mart. A rebuilt sample could not be produced for it, because `make bench-sample` needs the game. `rows_on_sample` (`tests/dbt/generic/rows_on_sample.sql`) counts only on the `ci` target over the committed sample (see `docs/CONVENTIONS.md`). **Key coverage.** Probe P8 checks park-day and statement keys against `dim_date` (0 unresolved); it does not check ride-day keys, and the first mart build tests them through the `relationships` test on `fct_ride_day`.

| Model | Rows on the sample | Where the number comes from | Real data that fills an empty mart |
|---|---|---|---|
| `dim_park` | 1 | one row per registered park: `dim_park` is built from the park registry (`int_park_registry__current`), and the sample registers one park | — |
| `dim_session` | 3 | three sessions | — |
| `dim_date` | 122 | `dim_date` holds every company date from the first day of the earliest company month that contains a kept park-day or a kept statement to the last day of the latest such month, and never generates a date from November to February, so every fact's day or month-start key resolves and every company month present has all its days. On the sample: 1 March to 30 June of year 9, whole months around the kept park-days (7 March to 21 June) and the March to May statements; 17 dates have no kept park-day (122 dates less 105 kept days), and no fact key is left unresolved (P8) | — |
| `dim_ride` | 29 | 7 rides, 8 stalls, 14 facilities; no slot is rebuilt in the sample | — |
| `dim_item` | 10 | distinct non-null `shop_item` and `shop_item_secondary` codes on kept ride-days, of any attraction (data-layer PR 2, #76: decision D5 of its spec, `git show 8f77ea5:docs/ai-dlc/specs/marts-ride-day.md`) | — |
| `fct_park_day` | 105 | 108 snapshots less 3: every session is cut at a save, the newest at its own last save (ADR 0024, Consequences) | — |
| `fct_park_month` | 3 | March, April and May statements | — |
| `fct_ride_day` | 3,045 | 29 attractions × the kept park-days: every session is cut at a save, the newest at its own last save (ADR 0024, Consequences) | — |
| `fct_cleaning_rule_count` | 21 | one row per rule per model: 11 repeat-delivery, 3 abandoned-branch, 2 last-reading, 4 placeholder, 1 guest-exit | — |
| `fct_ride_boarding` | 2,370 | one row per `guest_boarded` event of the rebuilt sample (plugin 0.6.0): 758, 745 and 867 in the three sessions, none sent after a save | — |
| `obt_park_month`, `obt_company_month` | 3 each | one row per kept statement month; June's park-days wait for June's statement | — |
| `obt_park_year` | 1 | one park-year (company year 2000, status open, 3 of 8 statements kept); every park-year with a kept statement has a row, closed or not | — |
| `obt_company_year` | 0 | no company year has closed | the first year-end close: every park expected that year has 8 kept statements, March to October, and at least one expected park is complete |
| `int_park_years__year_close` | 1 | one row per park per company year from the park's start year to the latest year with a kept statement | — |
| `obt_ride_month` | 28 | 7 rides × 4 game months (March to June) with kept ride-days | — |
| `obt_ride_year` | 7 | 7 rides × company year 2000 | — |
| `obt_ride_day` | 3,045 | one row per `fct_ride_day` row | — |
| `int_park_years__registry_mapped` | 1 | one park-year, game year 9, the only year in the sample's snapshots and statements | — |
| `int_park_days__company_calendar` | 245 | that park-year's eight months, 1 March to 31 October | — |
| `int_park_days__kept` | 105 | 108 snapshots less 3: every session is cut at a save, the newest at its own last save (ADR 0024, Consequences) | — |
| `int_ride_days__kept` | 3,045 | 29 attractions × the kept park-days: every session is cut at a save, the newest at its own last save (ADR 0024, Consequences) | — |
| `int_game_actions__labeled` | 0 | the sample holds no `game_action` rows | the first capture with a plugin that sends `game_action` events |

**Note, 2026-10-18 (ADR 0035).** The year-to-date table, which this table once listed with 1 row (company year 2000, the open year), is replaced by `obt_park_year` (1 row) and `obt_company_year` (0 rows), and the year-close register `int_park_years__year_close` (1 row) is new. Counts for these rows come from the `rows_on_sample` arguments in their YAML.

**Why the blanket rule goes.** The first draft put a `has_rows` test on every mart; on this sample it would fail on the boarding and annual marts for a correct reason (the data does not exist yet). An exact count is also stronger than "non-empty": it catches a join that silently drops or doubles rows. **The conflict with ADR 0013 is removed the same way** (section 10): ADR 0013's publish check refuses a candidate unless every mart table has a row, which would refuse every publish of the first season, because the annual tables are correctly empty until the first year-end close. The proposed amendment makes the publish check require rows in every mart except those whose "real data" condition above is not yet met, and require rows in those too once it is; the check still refuses a wholly empty warehouse.

**Gain:** the gate fails on lost or doubled rows in any mart the sample fills, and no mart is forced to fail or carry a fake row for data that cannot exist yet. **Cost:** 16 numbers to update whenever the sample is rebuilt, and a one-paragraph edit to ADR 0013 (proposed) before it is accepted. **Rejected:** a synthetic sample that fills every mart, including a closed year and boardings: about a season of generated events in the repo, kept in step with every contract change, beside a rehearsal sample that is a real headless capture.

## 7. Incremental models or full rebuilds
**The recommendation.** No incremental models in v1: every model is a table rebuilt from the Parquet on every build.

**The evidence.**
- Under ADR 0013 (proposed), each publish builds into a new candidate file and CI into a fresh temporary file, so an incremental model would always start empty there; its incremental branch would run only in development, never where it is audited. **Strong (repo record), inference about dbt's first-run behavior.**
- Save lineage relabels earlier rows: a later session's save can make rows kept or abandoned after they were built (ADR 0006), and fixes happen downstream in dbt (`CLAUDE.md` "Never break" 2), so a code change needs a full recompute anyway. **Strong.**
- The sample builds, with every test, in 3.9 seconds (ADR 0013's probe) and 3.50 seconds (this report's `dbt build`, PASS=76; P1). **Strong, measured on the sample.**
- dbt-duckdb 1.11.0 offers `append` and `delete+insert`, plus `merge` and `microbatch` on DuckDB 1.4 or later (`dbt/adapters/duckdb/impl.py`, `constants.py`), so the option stays open. **Strong, verified (source).**

**Gain:** one code path, always the audited one, and no stale rows after a lineage change. **Cost:** build time grows with all history; no measurement exists beyond the sample. Revisit when a publish build of real data takes more than 5 minutes (the two-park rehearsal will give the first figure). **Rejected:** incremental `delete+insert` keyed on session, which would need a lookback for lineage changes and a forced full refresh after every logic change.

## 8. Environments and `profiles.yml`
**The recommendation.** Take ADR 0013's outputs unchanged: `dev` (the default, under `warehouse/dev/`), `ci` (a temporary folder per run), and `rehearsal` and `company` (candidate files only, under `warehouse/candidate/<run-id>/`), with every `make` command passing `--target`. This design adds nothing to `profiles.yml`. It adds to `dbt_project.yml`: the layer schemas (section 1.1), so a mart's address is `marts.fct_park_day` in every environment's file; `+materialized: table` for every layer; `test-paths`; and the default severity. A test that must fail on company data and warn on rehearsal data reads `target.name`.

**The evidence.** ADR 0013 and its probe (`docs/FINDINGS.md`, 2026-10-03): targets keep each environment in its own file; `--target` wins over environment variables; a database is named after its file, so a candidate keeps the published file's name. The severity-by-target probe in section 6. **Strong.**

**Gain:** the same relation names everywhere, and environment choice stays in one file. **Cost:** none beyond ADR 0013's own. **Rejected:** dbt's default target-prefixed schemas, which only separate environments sharing a database.

## 9. Semantic-layer features the sandbox cannot run

| Feature | In the agents' sandbox (observed) | In CI (GitHub Actions) | Evidence |
|---|---|---|---|
| `dbt parse` and `dbt build` with semantic models in a model folder | crashed: `PermissionError` from `os.sysconf("SC_SEM_NSEMS_MAX")`, exit 2 | not run with semantic models in a model folder; expected to pass, because the crash is the sandbox refusing a semaphore query, but unverified | verified (run, P6) in the sandbox only |
| The same with the thread-pool swap | passed: `dbt build` PASS=79 in 5.04 s | not run | verified (run, P6) |
| Column checks of semantic models against their models | in this probe, `dbt build` passed although the stub models had only an `id` column, so this build did not check them | not run | verified (run, P6) for one build with stubs; other dbt commands and MetricFlow's own validation were not tried |
| MetricFlow (`mf validate-configs`, `mf query`) | needs `dbt-metricflow`, a new dependency not approved | same | `docs/FINDINGS.md`, 2026-10-02 |
| The hosted dbt Semantic Layer and its APIs | needs dbt Cloud | same | data-team practices report, section 2.6 |

The crash comes from the semantic validator creating a process pool in its constructor whether or not it runs in parallel (`dbt_semantic_interfaces/validations/semantic_manifest_validator.py`, line 114, version 0.9.0); the swap replaces that pool with a thread pool.

**What it means for CI and for v1.**
- `make check` stays runnable by agents only while semantic YAML stays out of model folders, or while every dbt call goes through the swap (section 5.2).
- **The offset-filter test moves.** The catalog spec assigned this session a test that same-park year-over-year (metrics 30 to 33) filters prior-year rows correctly, and it can only run in MetricFlow. Recommended: v1 publishes 30 to 33 as SQL columns of `obt_park_year` and `obt_company_year`, with a singular test on a fixture (an incumbent park, a first-season park, a park with an incomplete prior year); the semantic definitions stay `draft` until the governed-metrics bet adopts MetricFlow, which then runs the original test.
- Column names in semantic models are checked by the catalog validator against model YAML; the probed `dbt build` did not check them, so the design does not rely on dbt for it.

**Gain:** the gate stays green for agents and v1's year-over-year numbers are tested now. **Cost:** until MetricFlow, the catalog formula and the SQL column are two copies of one metric, joined by the column-name rule and the reconciliation tests. **Rejected:** a sandbox exception for semantic validation, which the swap makes unnecessary; adopting MetricFlow now (a new dependency, LATER bet).

## 10. Conflicts with existing records, and their resolutions
The project owner accepted all five proposed rulings on 2026-10-03.

| Conflict | Sources | Proposed ruling | Gain | Cost |
|---|---|---|---|---|
| Where duplicate deliveries are removed | ADR 0006 and roadmap 3a put removal of repeated `event_id` deliveries in staging; `docs/CONVENTIONS.md` §3 lists "dedupe" under intermediate | Staging removes exact repeats of one delivery (same `event_id`); intermediate removes business duplicates (a reloaded day or month, repeated confirmed actions); appendix A words the rule | Every model above staging sees each event once, and business rules stay in the layer that may join | One CONVENTIONS row reworded; a reader must know two kinds of duplicate |
| ADR 0014's corrected stamp in staging | ADR 0014 (proposed) has staging hold the raw stamp and the corrected value, which needs the registry and correction seeds, a join staging forbids | Staging passes `company_year` through; `int_company_years__validated` joins the seeds | Staging keeps its no-joins rule, and the correction lives in one model | ADR 0014's wording edited before acceptance; one more intermediate model |
| Wide views against tables only | ADR 0012 says "wide views only for the site"; ADR 0013 (proposed) allows no views in a published file | Wide tables (`obt_`), built only from the star | Published files hold only tables, which survive moving the file and changing the Parquet (ADR 0013's probe) | Larger files; ADR 0012's word "views" reads as "wide tables" |
| The catalog's planned key and counter wording | `metrics/catalog.yml` builds `park_day_key` from the company date and counts "rise since the previous kept reading", implicitly on the later day | Game-date keys and earlier-day assignment (section 2) | Keys survive stamp corrections; visits land in the month they happened | Two text edits to planned catalog columns |
| Rows in every published mart | ADR 0013 (proposed) refuses a publish unless every mart table has a row; this design has annual and boarding marts that are correctly empty until a year closes or boardings are captured | The publish check requires rows in every mart whose filling data exists, per the table in section 6.2, and still refuses a wholly empty warehouse | The first season can publish, and an empty warehouse still cannot | ADR 0013's park-identity row reworded before acceptance; the publisher reads the expected-row conditions |

Consistent and unchanged: contracts on marts (roadmap 3·0, ADR 0012); one staging conversion (ADR 0008); tables only (ADR 0013).

## 11. Gaps and thin evidence
- No dbt documentation page was opened this session (permission refusal). For the reviewer to open: https://docs.getdbt.com/reference/resource-configs/contract (type and precision checks), https://docs.getdbt.com/docs/build/custom-schemas (`generate_schema_name`), https://docs.getdbt.com/best-practices/how-we-structure/1-guide-overview (naming), https://docs.getdbt.com/reference/resource-configs/severity (Jinja in severity), https://docs.getdbt.com/docs/build/incremental-strategy (DuckDB strategies), https://docs.getdbt.com/docs/build/unit-tests (ephemeral inputs).
- Every probe ran on one park's three-session sample. Build time at two-park, multi-year scale is unmeasured.
- Whether a season-only date table can serve as MetricFlow's time spine with `offset_window` is untested.
- No probe ran in CI (GitHub Actions); the CI column of section 9 is expectation, not measurement.
- The arrivals-against-admissions tolerance needs part 2's data before it can be set.
- Not decided here, by the roadmap's own split: generating dbt sources from the contracts, a `plugin_stats` staging model, and the gate check that staging YAML lists its required tests. They belong to the staging rework, which is parked by the project owner.
- SQL linting (for example sqlfluff) is a new dependency and is not proposed; style stays judgment only.

## 12. What changes on the roadmap
- Applied 2026-10-03: NEXT 3·0 is marked drafted by agents and accepted provisionally by the project owner (verify: owner-later), pointing at this report, ADR 0016 and the mart notes.
- Applied 2026-10-03: NEXT 3a and 3b (staging and intermediate) specs cite ADR 0016 now; NEXT 3c and 3d (marts and their trust tests) also wait for the project owner's confirmation of the requirements brief; the staging rework stays parked.
- Not yet applied: the catalog's offset-filter test moves from NEXT 3·0 to the governed-metrics bet; NEXT 3c gains the same-park fixture test.

## 13. Questions for the project owner
Questions 1, 3 and 4 were settled on 2026-10-03, when the project owner accepted ADR 0016 provisionally (its decision includes the guest-event deferral and the year-over-year test in SQL). Question 2 stays open, as ADR 0016's consequences record.

1. **Accept the design as a whole** (ADR 0016)? Gain: 3a to 3d can be specified. Cost: about three staging renames and their YAML when the staging rework runs.
2. **Moving the catalog into dbt later:** run every `make` dbt call through the thread-pool wrapper, or wait for an upstream fix? The wrapper works today and patches one dbt internal in the main gate; waiting keeps the catalog standalone for an unknown time.
3. **Defer staging of `guest_left` and `guest_snapshot`** until after v1? Gain: about 300 fewer lines of YAML before v1. Cost: two unstaged contracted types.
4. **Move the offset-filter test** to the MetricFlow adoption and publish v1's year-over-year from SQL? Gain: tested numbers in v1. Cost: two copies of four metrics until MetricFlow.

## Appendix A: CONVENTIONS.md dbt rules (applied 2026-10-03)
Applied to `docs/CONVENTIONS.md` on 2026-10-03 with three changes: the staging row adds `stg_envelope`, the envelope contract's staging model, which keeps repeat deliveries; the duplicate rule names exact repeat deliveries (the same `event_id`) for staging and business duplicates for intermediate; and each "new check" reads "judgment only (planned check: …)" until its check ships, as CONVENTIONS §9 requires. The draft below is kept as written; in it, "new check" marks a check that does not exist yet.

**Module map rows (replacing the three dbt rows of §3).**

| Folder | Rule | Check |
|---|---|---|
| `models/staging/` | One `stg_<event_type>` table per event type with a consumer; rename, cast, `tenths_to_usd`, sentinel to null, and removal of repeated deliveries on `event_id`; no joins. Exceptions: `plugin_stats`, `save_written`, `guest_left`, `guest_snapshot` until a consumer exists | judgment only |
| `models/intermediate/` | `int_<grain>__<step>` tables: save lineage, company dates, counter changes, keys, resolving reloaded days and months, collapsing repeated actions | judgment only |
| `models/marts/` | `dim_`, `fct_` and `obt_` tables; `obt_` tables read only `dim_` and `fct_`; the only layer the site reads | new check: `ref` names by prefix |
| `tests/dbt/` | Singular tests, including the `review_` tests of observational hypotheses (warn, stored rows), and generic tests in `tests/dbt/generic/`; `dbt_project.yml` sets `test-paths: ["tests/dbt"]` | dbt build (a generic test outside the test path fails to compile at build, not at parse) |

**Rules (§4 rows).**

| Rule | Why | Check |
|---|---|---|
| Every model is a table, in the schema named after its layer (`staging`, `intermediate`, `marts`, `seeds`). | Published files hold tables only (ADR 0013), and a reader finds a layer by schema. | new check: `dbt_project.yml` layer configs |
| Every model's YAML states its grain ("one row per …") and its key; a fact's key uses the game date, not the company date. | A correction to the company stamp must not change keys. | judgment only |
| A published average is stored as its sum and its count; every coarser grain divides summed sums by summed counts. | An average of averages weighs a short month like a long one. | judgment only |
| No model outside `models/staging/` reads a `_tenths` column; every `_tenths` input becomes a `_usd` output through `tenths_to_usd`. | One money conversion (`CLAUDE.md` "Never break" 3). | new check: grep over `models/` |
| Every mart has an enforced contract with a `data_type` on each column; money is `decimal(18,2)`. No constraints. | Types and column sets cannot change silently, even on an empty table. | new check: mart YAML; dbt enforces at build |
| A metric-tree identity is tested with `reconciles_exactly` at error severity, across two tables or two independent sources. | An identity reconciles exactly (ADR 0012). | judgment only |
| A hypothesis with a numeric check is tested with `within_tolerance` at warn severity; its tolerance equals the catalog's. | One tolerance, checked in both homes. | new check in `scripts/check_metric_catalog.py` |
| A published column is named exactly as its catalog metric. | The site's mapping and the catalog name the same thing (ADR 0015). | new check: catalog names against `obt_` YAML |
| Severity: the project default is `error`; a `warn` test states it; a severity that differs by data set reads `target.name`. | Every test has a stated severity (ADR 0012). | judgment only |
| Complex intermediate logic ships with a dbt unit test; a source input uses `format: sql`, and each same-typed column gets a distinct value. | Logic is tested on fixed inputs; the double comparison and column swaps hide faults (`ARCHITECTURE.md`). | judgment only |
| Every mart's row count on the committed sample equals its entry in the expected-row table; a mart the sample cannot fill is listed at 0 with the real data that fills it, and its enforced contract checks its columns. | A test on an empty table proves nothing, and an exact count catches lost or doubled rows. | `rows_on_sample`, error, `ci` target only |
| An observational hypothesis is a `review_` singular test at warn severity with `store_failures: true`; it returns rows only for closed company years and has no tolerance. | Its result is kept for the year-end review and never fails a build (ADR 0012). | judgment only |
| No incremental models. | Every build is a full, audited rebuild (ADR 0013). | new check: no `incremental` materialization |
| No dbt packages without approval. | A package is a dependency. | judgment only (no `packages.yml`) |

**Names (§6 additions).** **staging model**, **intermediate model**, **mart** (a `dim_`, `fct_` or `obt_` table), **one big table** (`obt_`: a wide table built from the star for one consumer), **identity test** (`reconciles_exactly`), **tolerance test** (`within_tolerance`), **kept** (a row on the timeline save lineage keeps, ADR 0006), **review test** (a `review_` singular test that stores an observational result).

**Judgment-only list (§7, replacing item 11).** Whether a staging model does only rename, cast, `tenths_to_usd`, sentinel to null and removal of repeated deliveries, with no joins; whether an identity test compares two independent sides rather than a column with its own formula.

## Appendix B: Probe script and observed output
**Re-run it with one command.** From the repo root of a clone at this report's commit, after `make setup`, save the script below outside the repo (for example as `$TMPDIR/probes.sh`) and run `TMPDIR=<a writable scratch folder> bash $TMPDIR/probes.sh`. It copies the dbt project and `data/sample/rehearsal/` into a new temporary folder, writes every probe file there, and prints each step's summary lines and exit code; it never writes inside the repo. **Input:** the committed rehearsal extract (one park copy, three headless sessions, 108 park snapshots, 3 statements, 3,132 ride snapshots) and the committed `metrics/catalog.yml`. **Environment:** the repo's `.venv` (Python 3.12.8, dbt-core 1.11.15, dbt-duckdb 1.11.0, dbt-semantic-interfaces 0.9.0, DuckDB 1.5.5), `UV_CACHE_DIR=$TMPDIR/uv-cache` for `make setup` and `make check`; `MYPYPATH` is not used. Run on 2026-10-03 inside Claude Code's sandbox, Apple silicon (arm64), macOS 26.5.2.

```bash
#!/usr/bin/env bash
# Run from the repo root after `make setup`. Every file it writes is in a temporary folder.
set -u
R=$PWD; S=$(mktemp -d "${TMPDIR:-/tmp}/dbt-probe.XXXXXX") || exit 1; DBT="$R/.venv/bin/dbt"; PY="$R/.venv/bin/python"
mkdir -p "$S/tests" "$S/warehouse" "$S/data/sample" "$S/macros" "$S/tests/dbt/generic"
cp -R "$R/dbt_project.yml" "$R/profiles.yml" "$R/models" "$R/seeds" "$S/"
cp -R "$R/tests/dbt" "$S/tests/" && cp -R "$R/data/sample/rehearsal" "$S/data/sample/"
cd "$S" || exit 1
run() { echo "## $*"; "$@" --profiles-dir . --no-use-colors 2>&1 | grep -E 'Done\.|PASS=|FAIL|ERROR|WARN|Error|mismatch|undefined|constraint|PermissionError|Completed' | head -12; echo "exit=${PIPESTATUS[0]}"; }

echo "# P1 timing"
for i in 1 2 3; do /usr/bin/time -p "$DBT" parse --no-partial-parse --profiles-dir . 2>&1 | grep '^real'; done
/usr/bin/time -p "$DBT" build --profiles-dir . 2>&1 | grep -E 'PASS=|^real'

echo "# P8 recount (section 6.2) on the dev target; until the marts exist, each count is a stand-in query over the sample's kept rows (the game year stands in for company_year)"
run "$DBT" build --target dev --exclude test_name:rows_on_sample
"$PY" -c "import duckdb, os; c = duckdb.connect(); v = 'data/sample/rehearsal/v1/'; n = lambda q: c.sql(q).fetchone()[0]; c.sql(f\"\"\"
create view w as select session_id, seq as save_seq from '{v}save_written.parquet';
create macro kept(t) as table select x.* from query_table(t) x join w using (session_id) where x.seq < w.save_seq or x.session_id not in (select loaded_save_session_id from '{v}session_start.parquet' where loaded_save_session_id is not null);
create view ps as from '{v}park_snapshot.parquet'; create view fm as from '{v}finance_month.parquet'; create view rs as from '{v}ride_snapshot.parquet';
create view kd as select distinct make_date(2000 + game_year, game_month + 3, game_day) as day from kept(ps); create view sm as select park_id, statement_year, make_date(2000 + statement_year, statement_month + 3, 1) as month_start from kept(fm);
create macro dim_date(lo, hi) as table select unnest(generate_series(m, last_day(m)::timestamp, interval 1 day))::date as company_date
  from (select unnest(generate_series(date_trunc('month', lo), date_trunc('month', hi), interval 1 month)) as m) where month(m) between 3 and 10;
create table d as from dim_date((select least(min(day), (select min(month_start) from sm)) from kd), (select greatest(max(day), (select max(month_start) from sm)) from kd));
create view occ as select lag(build_date_months_elapsed) over k is distinct from build_date_months_elapsed or lag(ride_type) over k is distinct from ride_type or lag(ride_object) over k is distinct from ride_object
  or lag(classification) over k is distinct from classification or total_customers < lag(total_customers) over k as starts from kept(rs) window k as (partition by park_id, ride_id order by game_ticks_elapsed);
create view yr as select park_id, statement_year from sm group by all having count(*) = 8\"\"\"); b = v + 'guest_boarded.parquet'
print([(m, n(q)) for m, q in [('dim_park', 'select count(distinct park_id) from kept(ps)'), ('dim_session', 'select count(distinct session_id) from (from ps union all by name from fm union all by name from rs)'), ('dim_date', 'select count(*) from d'),
  ('dim_ride', 'select count(*) from occ where starts'), ('dim_item', 'select count(distinct shop_item) from kept(rs) where classification = \'stall\' and shop_item_secondary = 255'), ('fct_park_day', 'select count(*) from kept(ps)'),
  ('fct_park_month', 'select count(*) from sm'), ('fct_ride_day', 'select count(*) from kept(rs)'), ('fct_ride_boarding', f'select count(*) from \'{b}\'' if os.path.exists(b) else 'select 0'), ('obt_park_month', 'select count(*) from sm'),
  ('obt_company_month', 'select count(distinct month_start) from sm'), ('obt_park_year', 'select count(*) from yr'), ('obt_company_year', 'select count(distinct statement_year) from yr'), ('obt_ride_day', 'select count(*) from kept(rs)')]])
print('dim_date', c.sql('select min(company_date), max(company_date) from d').fetchone(), 'kept days', n('select count(*) from kd'), 'dates without a kept day', n('select count(*) from d where company_date not in (select day from kd)'))
print('unresolved month keys', n('select count(*) from sm where month_start not in (select company_date from d)'), 'day keys', n('select count(*) from kd where day not in (select company_date from d)'), 'month keys under the first-to-last-kept-day rule', n('select count(*) from sm where month_start < (select min(day) from kd)'))
print('fixture: kept days 20 October year 9 to 5 March year 10', c.sql(\"select count(*), count(*) filter (where month(company_date) not between 3 and 10), min(company_date), max(company_date) from dim_date(date '2009-10-20', date '2010-03-05')\").fetchone())"

echo "# P2 contracts"
cat > models/marts/probe_money.sql <<'EOF'
select event_id, {{ var('cash_expr', 'cash_usd') }} as cash_usd from {{ ref('stg_park_daily') }} {{ var('filter', '') }}
EOF
cat > models/marts/probe_money.yml <<'EOF'
version: 2
models:
  - name: probe_money
    config: {materialized: "{{ var('mat', 'table') }}", contract: {enforced: true}}
    columns:
      - {name: event_id, data_type: varchar}
      - {name: cash_usd, data_type: "decimal(18,2)"}
  - name: probe_notnull
    config: {materialized: table, contract: {enforced: true}}
    columns:
      - {name: event_id, data_type: varchar, constraints: [{type: not_null}]}
EOF
echo "select cast(null as varchar) as event_id" > models/marts/probe_notnull.sql
run "$DBT" run -s probe_money
for e in 'cash_usd::double' 'cast(cash_usd as decimal(18,0))' 'cast(cash_usd as decimal(18,4))'; do
  run "$DBT" run -s probe_money --vars "{cash_expr: '$e'}"
done
run "$DBT" run -s probe_money --vars "{cash_expr: 'cash_usd::double', filter: 'where false'}"
run "$DBT" run -s probe_money --vars "{cash_expr: 'cash_usd::double', mat: view}"
run "$DBT" run -s probe_notnull
rm models/marts/probe_money.* models/marts/probe_notnull.sql

echo "# P3 generic tests and test-paths"
cat > tests/dbt/generic/reconciles_exactly.sql <<'EOF'
{% test reconciles_exactly(model, left, right) %}
select * from {{ model }} where ({{ left }}) is distinct from ({{ right }})
{% endtest %}
EOF
cat > tests/dbt/generic/within_tolerance.sql <<'EOF'
{% test within_tolerance(model, left, right, relative, absolute) %}
select * from {{ model }} where abs(({{ left }}) - ({{ right }})) > greatest({{ relative }} * abs({{ right }}), {{ absolute }})
{% endtest %}
EOF
cat > models/marts/probe_balance.sql <<'EOF'
select event_id,
  ride_construction_usd + ride_runningcosts_usd + land_purchase_usd + landscaping_usd + park_entrance_tickets_usd
  + park_ride_tickets_usd + shop_sales_usd + shop_stock_usd + food_drink_sales_usd + food_drink_stock_usd
  + wages_usd + marketing_usd + research_usd + interest_usd as lines_usd,
  (cash_usd - bank_loan_usd) - lag(cash_usd - bank_loan_usd) over (order by statement_year * 8 + statement_month) as net_change_usd
from {{ ref('stg_finance_monthly') }}
qualify lag(event_id) over (order by statement_year * 8 + statement_month) is not null
EOF
cat > models/marts/probe_balance.yml <<'EOF'
version: 2
models:
  - name: probe_balance
    config: {materialized: table}
    data_tests:
      - reconciles_exactly:
          arguments: {left: lines_usd, right: "net_change_usd + {{ var('plant', 0) }}"}
          config: {severity: "{{ 'error' if target.name == 'company' else 'warn' }}"}
      - within_tolerance:
          arguments: {left: lines_usd, right: "net_change_usd + {{ var('drift', 0) }}", relative: 0.01, absolute: 1.00}
          config: {severity: warn}
EOF
run "$DBT" build -s probe_balance
echo 'test-paths: ["tests/dbt"]' >> dbt_project.yml
run "$DBT" build -s probe_balance
run "$DBT" build -s probe_balance --vars '{plant: 0.1}'
run "$DBT" build -s probe_balance --vars '{drift: 50}'
printf '    company:\n      type: duckdb\n      path: warehouse/company.duckdb\n      threads: 4\n' >> profiles.yml
run "$DBT" build -s +probe_balance --target company --vars '{plant: 0.1}'

echo "# P4 ephemeral model with unit and data tests"
cat > models/intermediate/int_probe_eph.sql <<'EOF'
select park_id, event_id, park_rating * 2 as rating_x2 from {{ ref('stg_park_daily') }}
EOF
cat > models/intermediate/int_probe_eph.yml <<'EOF'
version: 2
models:
  - name: int_probe_eph
    config: {materialized: ephemeral}
    columns:
      - {name: event_id, data_tests: [unique, not_null]}
unit_tests:
  - name: int_probe_eph_doubles
    model: int_probe_eph
    given:
      - input: ref('stg_park_daily')
        rows: [{park_id: p1, event_id: e1, park_rating: 3}]
    expect:
      rows: [{park_id: p1, event_id: e1, rating_x2: 6}]
EOF
run "$DBT" build -s int_probe_eph

echo "# P5 layer schema"
cat > macros/generate_schema_name.sql <<'EOF'
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}
EOF
echo "{{ config(materialized='table', schema='marts') }} select 1 as id" > models/marts/probe_mart.sql
run "$DBT" run -s probe_mart
"$PY" -c "import duckdb; print(duckdb.connect('warehouse/openrct2.duckdb', read_only=True).sql(\"select table_schema || '.' || table_name from information_schema.tables where table_name in ('probe_mart', 'stg_park_daily')\").fetchall())"

echo "# P7 review tests: both section 4.1 tests over stand-in marts (the game year stands in for company_year; var closed_year marks a year closed), then a one-row synthetic test with and without the override"
K="join (select session_id, seq as save_seq from 'data/sample/rehearsal/v1/save_written.parquet') w using (session_id) where (x.seq < w.save_seq or x.session_id not in (select loaded_save_session_id from 'data/sample/rehearsal/v1/session_start.parquet' where loaded_save_session_id is not null))"
echo "select park_id, make_date(2000 + game_year, game_month + 3, game_day) as company_date, game_year as company_year, park_rating, lead(total_admissions) over (partition by park_id order by game_ticks_elapsed) - total_admissions as admissions_increase from 'data/sample/rehearsal/v1/park_snapshot.parquet' x $K" > models/marts/fct_park_day.sql
echo "select park_id, make_date(2000 + game_year, game_month + 3, game_day) as company_date, (lead(total_customers) over (partition by park_id, ride_id order by game_ticks_elapsed) - total_customers) * price_1_tenths / 10 as ride_ticket_sales_usd from 'data/sample/rehearsal/v1/ride_snapshot.parquet' x $K and classification = 'ride'" > models/marts/fct_ride_day.sql
echo "select distinct park_id, company_year from {{ ref('fct_park_day') }} where company_year = {{ var('closed_year', -1) }}" > models/marts/obt_park_year.sql
cat > tests/dbt/review_visits_same_day_ride_revenue.sql <<'EOF'
{{ config(severity='warn', store_failures=true, schema='review') }}
with r as (select park_id, company_date, sum(ride_ticket_sales_usd) as ride_revenue_usd from {{ ref('fct_ride_day') }} group by all)
select p.park_id, p.company_year, corr(p.admissions_increase, r.ride_revenue_usd) as correlation, count(*) as paired_days
from {{ ref('fct_park_day') }} p join r using (park_id, company_date) join {{ ref('obt_park_year') }} y using (park_id, company_year)
where p.admissions_increase is not null and r.ride_revenue_usd is not null group by all
EOF
cat > tests/dbt/review_rating_lag_visits.sql <<'EOF'
{{ config(severity='warn', store_failures=true, schema='review') }}
with c as (select v.park_id, v.company_year, l.lag_days, corr(v.admissions_increase, r.park_rating) as correlation, count(*) as paired_days
  from {{ ref('fct_park_day') }} v cross join (values (7), (14), (28)) l(lag_days) join {{ ref('obt_park_year') }} y on y.park_id = v.park_id and y.company_year = v.company_year
  join {{ ref('fct_park_day') }} r on r.park_id = v.park_id and r.company_year = v.company_year and r.company_date = v.company_date - l.lag_days
  where v.admissions_increase is not null group by all)
select *, correlation = max(correlation) over (partition by park_id, company_year) as best_lag from c
EOF
Q="import duckdb, sys; c = duckdb.connect('warehouse/openrct2.duckdb', read_only=True); print(sys.argv[1], [(s + '.' + t, k, c.sql(f'select count(*) from {s}.{t}').fetchone()[0]) for s, t, k in c.sql(\"select table_schema, table_name, table_type from information_schema.tables where table_name like 'review_%' order by 1, 2\").fetchall()])"
run "$DBT" build -s fct_park_day fct_ride_day obt_park_year+; "$PY" -c "$Q" "no closed year:"
run "$DBT" build -s obt_park_year+ --vars '{closed_year: 9}'; "$PY" -c "$Q" "year 9 marked closed:"; rm models/marts/fct_park_day.sql models/marts/fct_ride_day.sql models/marts/obt_park_year.sql tests/dbt/review_[rv]*.sql
echo "{{ config(severity='warn', store_failures=true, schema='review') }} select park_id, count(*) as park_days from {{ ref('stg_park_daily') }} group by park_id" > tests/dbt/review_probe.sql
run "$DBT" build -s review_probe
mv macros/generate_schema_name.sql "$S/override.sql.off"; run "$DBT" build -s review_probe; rm tests/dbt/review_probe.sql; "$PY" -c "$Q" "synthetic test with, then without, the override:"

echo "# P6 semantic models in a model folder"
rm -f models/marts/probe_* models/intermediate/int_probe_eph.* macros/generate_schema_name.sql
cp "$R/metrics/catalog.yml" models/metric_catalog.yml
printf "select cast('2020-01-01' as date) as date_day\n" > models/metricflow_time_spine.sql
printf 'version: 2\nmodels:\n  - name: metricflow_time_spine\n    time_spine:\n      standard_granularity_column: date_day\n    columns:\n      - name: date_day\n        granularity: day\n' > models/metricflow_time_spine.yml
for m in stg_ride_snapshot stg_guest_boarded; do echo "select 1 as id" > "models/$m.sql"; done
run "$DBT" parse
run "$DBT" build
SWAP='import sys
from concurrent.futures import ThreadPoolExecutor
import dbt_semantic_interfaces.validations.semantic_manifest_validator as v
v.ProcessPoolExecutor = ThreadPoolExecutor
from dbt.cli.main import cli
cli.main(args=sys.argv[1:], prog_name="dbt")'
/usr/bin/time -p "$PY" -c "$SWAP" build --profiles-dir . --no-use-colors 2>&1 | grep -E 'PASS=|^real'
echo "scratch: $S"
```

**Observed output (P1 to P6 from the last of three complete runs on 2026-10-03; the two earlier runs, made before the P3 step and the output filter reached their final form, gave the same outcome at every step they shared. P7 and P8 come from two further complete runs of the final script the same day, after the third review round, with identical output; they repeated every P1 to P6 outcome, with timings up to 1.1 s faster):**

| Probe | Step | Exit | Observed |
|---|---|---|---|
| P1 | `dbt parse --no-partial-parse`, three times; `dbt build` | 0 | parse 3.07, 3.07 and 3.09 s; build 3.50 s, PASS=76 |
| P2 | contract with `cash_usd` as `decimal(18,2)`: model column as is | 0 | PASS=1 |
| P2 | the same column cast to DOUBLE, `DECIMAL(18,0)`, `DECIMAL(18,4)`; DOUBLE with zero rows (`where false`); DOUBLE as a view | 1 each | "data type mismatch" naming the produced type against `DECIMAL(18,2)`, in all five |
| P2 | `not_null` constraint on a null column | 1 | "NOT NULL constraint failed: probe_notnull__dbt_tmp.event_id" |
| P3 | generic tests in `tests/dbt/generic/`, default test path | 1 | "'test_reconciles_exactly' is undefined" and the same for `within_tolerance`; PASS=1 ERROR=2 |
| P3 | after `test-paths: ["tests/dbt"]`: no plant; 0.1-dollar plant; 50-dollar drift | 0, 0, 0 | PASS=3; `reconciles_exactly` WARN 2; `within_tolerance` WARN 1 |
| P3 | 0.1-dollar plant on the `company` target | 1 | `reconciles_exactly` FAIL 2; PASS=37 ERROR=1 |
| P4 | ephemeral model with a unit test and `unique` and `not_null` | 0 | PASS=3 |
| P5 | `generate_schema_name` override, `schema='marts'` | 0 | DuckDB lists `marts.probe_mart` beside `main.stg_park_daily` |
| P7 | both section 4.1 tests over stand-in marts, layer-schema override: no closed year; year 9 marked closed | 0, 0 | PASS=5, both landing tables created with 0 rows; then WARN 1 and WARN 3, `review.review_visits_same_day_ride_revenue` 1 row and `review.review_rating_lag_visits` 3 rows, all BASE TABLE |
| P7 | one-row synthetic test, `store_failures=true`, `schema='review'`: with the override; without it | 0, 0 | WARN 1 each; BASE TABLE `review.review_probe` with the override, `main_review.review_probe` without it, 1 row each |
| P8 | `dbt build --target dev --exclude test_name:rows_on_sample`, then the 14 stand-in counts | 0 | PASS=76; `dim_park` 1, `dim_session` 3, `dim_date` 122, `dim_ride` 29, `dim_item` 8 (10 in the 2026-10-15 `ci` build), `fct_park_day` 106 (105 after the ADR 0024 newest-session cut; `docs/FINDINGS.md` 2026-10-15 row), `fct_park_month` 3, `fct_ride_day` 3,074 (3,045 after the cut), `fct_ride_boarding` 0, `obt_park_month` 3, `obt_company_month` 3, `obt_park_year` 0, `obt_company_year` 0, `obt_ride_day` 3,074 (not built; the ride-day count lives in `fct_ride_day`) |
| P8 | `dim_date` rule on the sample; month and day keys joined to it; an October-to-March fixture | 0 | 1 March to 30 June of year 9 (shown as 2009), 106 kept days, 16 dates without one (105 and 17 after the cut); unresolved month keys 0, day keys 0 (1 month key under the first-to-last-kept-day rule: 1 March); fixture with kept days 20 October to 5 March: 62 rows, 1 October to 31 March, 0 dates from November to February; ride-day keys are not checked by this script (the first mart build tests them) |
| P6 | plain `dbt parse`; plain `dbt build`, with the catalog in `models/` | 2, 2 | `PermissionError: [Errno 1] Operation not permitted` at `os.sysconf("SC_SEM_NSEMS_MAX")` |
| P6 | `dbt build` with the thread-pool swap | 0 | PASS=79 in 5.04 s; the two stub models hold only an `id` column |

The first draft's probes, run earlier the same day, differed in two reported details that this run corrects: the undefined-test error appears at `dbt build`, not at `dbt parse`, and the claim that dbt warns about constraints on a view is dropped, because no view in this run carried a constraint.
