# ADR 0016: dbt design — layered tables, a star on game-date keys, tests by metric-tree link kind

- Date: 2026-10-03
- Status: accepted 2026-10-03; the project owner's later review passed on 2026-10-22 with no corrections. Drafted by agents for the dbt design session, roadmap NEXT 3·0.
- Superseded in part by ADR 0019 (2026-10-07)
- Superseded in part by ADR 0022 (2026-10-09): the "Guest events" row and the clause naming the company-calendar build as the author of `stg_envelope`
- Superseded in part by ADR 0023 (2026-10-09)

## Bottom line

The warehouse uses three dbt layers, each a schema of tables rebuilt in full on every build: staging (one
model per event type that renames, casts, converts tenths of a dollar to dollars once, turns sentinels into
nulls and removes repeated deliveries), intermediate (save lineage, company dates, counter changes, keys) and
marts (five dimensions, four facts at park-day, park-month, ride-day and boarding grain, and wide reporting
tables whose columns carry the catalog's metric names). Facts key on the game date so a corrected
company-year stamp never changes a key. A metric-tree identity is tested exactly by a custom test that has no
tolerance argument; a hypothesis with a numeric check is tested at warn severity by a second custom test whose
tolerance the catalog validator cross-checks; the two observational hypotheses are warn-severity singular
tests that store their results for the year-end review. Every mart has an enforced contract and an exact
expected row count on the committed sample. The metric catalog splits
into three files by business process and moves into dbt only after the marts exist. No package is added. The
evidence is in `docs/ai-dlc/reports/dbt-design--findings.md` and the per-mart notes in
`docs/ai-dlc/reports/dbt-design--marts.md`. The project owner accepted the record provisionally on 2026-10-03,
with all five proposed resolutions of the conflicts with earlier records; staging and intermediate models may be
built now, and so may marts, because the project owner confirmed the requirements brief on 2026-10-03.

## Context

The skeleton's dbt project is deliberately bare: three staging views over the committed sample, unit tests and
four singular tests, one target. The roadmap's NEXT 3·0 item asks for the model design (grains, layers, the
star schema, naming) and the project setup (sources, materializations, test style), as an ADR, dbt rules for
`docs/CONVENTIONS.md` and a design note per mart. Three earlier records constrain it: ADR 0012 (Kimball design,
identity and hypothesis links, contracts on marts, a stated severity for every test), ADR 0013 (proposed: one
DuckDB file per environment, tables only in a published file) and ADR 0014 (proposed: the company year stamped
at the source and corrected downstream). The metric catalog (`metrics/catalog.yml`, on `develop` since 3a01f17,
confirmed by the project owner on 2026-10-03) defines 37 metrics and 2 helper metrics that the marts must serve.

Probes on the pinned stack (dbt-core 1.11.15, dbt-duckdb 1.11.0, DuckDB 1.5.5) on the committed sample
settled four facts this record rests on (`docs/FINDINGS.md`, 2026-10-03; the re-runnable script and its
observed output are appendix B of the findings report): an enforced contract fails a money
column whose decimal scale is wrong, even with zero rows; generic tests in `tests/dbt/generic/` load only when
`test-paths` names `tests/dbt`; severity can follow the dbt target; and semantic models in a model folder crash
plain `dbt parse` and `dbt build` in the agents' sandbox but pass with a thread-pool swap.

## Decision

| Area | Choice | Gain | Cost |
|---|---|---|---|
| Layers | `models/staging`, `models/intermediate`, `models/marts`, each its own schema in every DuckDB file through `+schema` and a `generate_schema_name` override; every model a table | A reader finds each layer by schema and can trace a number through relations that exist | Larger files; one override macro |
| Names | `stg_<event_type>`, `int_<grain>__<step>`, `dim_`, `fct_`, `obt_` (wide reporting table) | Event, contract and staging model share one name; the star reads as Kimball | Three staging renames when the parked staging rework runs |
| Guest events | Stage `guest_boarded`, `guest_refused` and `guest_arrived` when full capture part 2 lands; `guest_left` and `guest_snapshot` wait for a consumer after v1; guest identity is `session_id` + `guest_key` | Every staged type has a v1 consumer | Two contracted types unstaged until after v1 |
| Grains and keys | `fct_park_day`, `fct_park_month`, `fct_ride_day`, `fct_ride_boarding`; dimensions park, ride (one row per detected occupancy of a slot: `park_id` + `ride_id` + build month + first-seen tick), item, company date, session; keys on the game date; `dim_date` holds every company date from the first day of the earliest company month that contains a kept park-day or a kept statement to the last day of the latest such month, and never generates a date from November to February, so every fact's day or month-start key resolves and every company month present has all its days (on the committed sample, 122 dates); counter changes assigned to the earlier reading's day | Keys survive stamp corrections; a ride rebuilt in the same slot and month gets its own key when the replacement is detected; visits land in the month they happened | Key and time dimension are separate columns; the catalog's planned key text changes; one undetectable class: a replacement between two readings whose new ride, at the next reading, has the predecessor's type, object, classification and build month and at least its customer count, so the two rides share a key and the counter changes of that reading are wrong; closing it needs a ride creation tick or instance ID from the plugin, deferred to the capture roadmap (mart notes, `dim_ride`) |
| Clock | Every fact's time dimension is the company date (day or month); the game date sits beside it; no v1 mart uses the wall-clock hour | `CLAUDE.md` "Never break" 3 holds per mart | Company dates stay provisional on ADR 0014 |
| Money | One conversion in staging through a `tenths_to_usd` macro to `DECIMAL(18,2)`; nothing downstream reads `_tenths` | One definition of the conversion | One macro to open when reading staging |
| Published numbers | Every number the site shows is a column of an `obt_` table built only from the star, named exactly as its catalog metric; an average (metric 19) is stored as its sum and day count and divided at every grain | ADR 0015's mapping and the catalog name the same thing; no average of averages | Until MetricFlow, catalog formula and SQL column are two copies joined by tests; one extra sum column |
| Identity links | Custom generic test `reconciles_exactly`, no tolerance argument, error severity, across two tables or two independent sources | An identity can never acquire a tolerance | One custom test |
| Hypothesis links | Custom generic test `within_tolerance` at warn severity, tolerance in its YAML, checked against a structured catalog `tolerance`; observational hypotheses (metrics 18 and 19) become `review_` singular tests at warn severity with `store_failures`, returning rows only for closed company years | One numeric home for each tolerance; the observational checks run on every build and keep a dated result | About 20 lines in the catalog validator; two WARN lines on every build after the first year-end close; pytest fixtures for the lag cases |
| Test layers | Generic tests for keys and relationships; singular tests for one-off checks; unit tests for complex intermediate logic; enforced contracts (types, no constraints) on every mart and, in the staging rework, on staging models carrying money; project default severity `error`; severity by `target.name` where data sets differ; pytest-driven mutation tests; `rows_on_sample` on every mart on the `ci` target (which the warehouse-environments build, ADR 0013, creates; until then it runs on the default target), with an exact count from the committed sample, and the enforced contract alone for a mart the sample cannot fill | Each test kind catches what it is good at; lost or doubled rows fail, and no mart must hold rows its data cannot yet supply | A data type on every mart column; about 4 seconds per mutation test; 14 counts recounted on the `dev` target, `ci` once the warehouse-environments work (NEXT 14) adds it, whenever a sample rebuild changes the Parquet (findings report, section 6.2) |
| Materialization | No incremental models; every build is a full rebuild | The audited code path is the only path, and lineage changes never leave stale rows | Build time grows with history; revisit above 5 minutes per publish |
| Environments | ADR 0013's outputs unchanged; layer schemas identical in every file | `marts.fct_park_day` means the same everywhere | None beyond ADR 0013 |
| Metric catalog | Split into `metrics/finance.yml`, `metrics/admissions.yml`, `metrics/ride_operations.yml` in its own change after the catalog confirmation merges; move beside the marts after NEXT 3c builds them | Every file under 500 lines; files match marts | Two catalog scripts read a folder |
| Packages | None | No dependency to approve | Three small custom tests instead of `dbt_utils` |

`stg_envelope` is the staging model of the envelope's own contract (`contracts/envelope.odcs.yaml`); unlike the event-type staging models, it deliberately keeps every landed delivery, including repeated `event_id` deliveries, because its purpose is the landed-event count check, and `int_company_years__validated` removes exact repeats on `event_id` before judging agreement. It reads only the envelope columns from
every landed event type; the company-calendar build (branch `feat/company-calendar`) defines it. Some event types
deliberately have no staging model, such as `plugin_stats`.

Marts (fact and dimension tables, and the `obt_` tables built from them) waited for the project owner's
confirmation of the requirements brief (`docs/requirements-brief.md`), given on 2026-10-03; staging and
intermediate work could start before it.

### Accepted resolutions of the five conflicts (2026-10-03)

The project owner accepted each resolution as proposed in section 10 of the findings report:

1. **Duplicates.** Staging removes exact repeat deliveries (the same `event_id`); intermediate removes business
   duplicates (a reloaded day or month, repeated confirmed actions). `docs/CONVENTIONS.md` words the rule.
2. **ADR 0014's corrected stamp.** Staging passes `company_year` through unchanged; `int_company_years__validated`
   joins the registry and correction seeds, so staging keeps its no-joins rule.
3. **Wide views.** The site's wide reporting objects are tables (`obt_`), built only from the star; ADR 0012's
   "wide views only for the site" reads as wide tables.
4. **The catalog's planned wording.** `park_day_key` is built from the game date, not the company date, and a
   counter's rise is assigned to the earlier reading's day.
5. **Rows in every published mart.** ADR 0013's publish check requires rows in every mart whose filling data
   exists (findings report, section 6.2) and still refuses a wholly empty warehouse.

### Follow-ups on other branches

- ADR 0014 (`docs/adr/0014-company-date-stamped-at-the-source.md`), branch `feat/company-calendar`: staging
  passes the raw `company_year` stamp through; the corrected value moves to `int_company_years__validated`
  (resolution 2).
- ADR 0013 (`docs/adr/0013-one-duckdb-file-per-environment.md`), branch `feat/warehouse-environments`: the
  publish-time row check requires rows only in marts whose filling data exists, and still refuses a wholly empty
  warehouse (resolution 5).

### Follow-ups: SQL linting

The project owner ruled on 2026-10-03 that dbt Labs' SQL style applies where it does not conflict with this
record (rules in `docs/CONVENTIONS.md`, section 4, "dbt SQL style"; evidence in
`docs/ai-dlc/reports/dbt-style--findings.md`) and approved `sqlfluff` and `sqlfluff-templater-dbt` as
dependencies, gated once the existing SQL is clean. All steps are done (2026-10-03):

1. Done: `uv add --dev sqlfluff sqlfluff-templater-dbt`; `uv.lock` pins 4.4.0 of both.
2. Done: `sqlfluff fix models tests/dbt` plus comment rewrapping, layout only; `dbt build` passed afterwards.
3. Done: `sqlfluff lint models tests/dbt` runs in `make check` as a failing step. The warning stage was skipped
   because the lint was already clean when the step was added.

## Rejected alternatives

- **Ephemeral or view intermediate models.** Ephemeral models leave nothing to query when tracing a number;
  views are barred from published files by ADR 0013.
- **Keys on the company date** (the catalog's wording before this record). A listed stamp correction would
  change the key of every row it touches.
- **Incremental models.** Each publish and CI build starts from an empty file, so incremental logic would run
  only in development; save lineage can relabel old rows.
- **Constraints inside model contracts.** A second mechanism beside key tests, which fails the build before a
  test can report the offending rows.
- **Tolerances as project variables.** A third place to keep in step with the catalog and the test.
- **Splitting the catalog into semantic models and metrics.** The metrics file alone would stay about 845
  lines.
- **Moving the catalog into dbt now.** Two of its semantic models name planned models, so the real project
  would need stubs.
- **Review queries in `analyses/` for metrics 18 and 19.** dbt only compiles analyses, so nothing would run
  them or keep their result.
- **A results model for metrics 18 and 19.** A fourth kind of mart that no page reads, with its own contract
  and expected-row entry.
- **A `has_rows` test on every mart.** It fails on the committed sample for the boarding and annual marts,
  whose data does not exist yet, and proves less than an exact count.
- **MetricFlow for the same-park year-over-year test.** A new dependency; v1's year-over-year is tested in SQL
  on `obt_park_year` and `obt_company_year` instead.

## Consequences

- NEXT 3a and 3b (staging and intermediate) specify against this record now; NEXT 3c and 3d (marts and their
  trust tests) also follow the requirements brief, confirmed on 2026-10-03. The staging rework stays parked; when it runs, it
  renames the three staging models, adds staging contracts and deletes the two `information_schema` singular
  tests they replace.
- `dbt_project.yml` gains layer configs, `test-paths: ["tests/dbt"]` and the default severity, in the first
  build slice that adds a mart.
- Applied with the 2026-10-03 ruling: the dbt rules in `docs/CONVENTIONS.md` (from the findings report's
  appendix A), the catalog's planned key and counter wording, and a status note on ADR 0012. ADR 0014 and
  ADR 0013 change on their own branches (the follow-ups above). Not yet made: the catalog spec's offset-filter
  test moves to the governed-metrics bet.
- Open for the project owner: whether `make` routes every dbt call through the thread-pool wrapper when the
  catalog moves into dbt, or waits for an upstream fix.
- **How we would know this is wrong:** a published number changes without a code or data change; a stamp
  correction changes a mart key; a full rebuild of real data takes more than 5 minutes; or a reviewer cannot
  trace a number from a mart back through an intermediate table to its event. Any of these reopens this record.
