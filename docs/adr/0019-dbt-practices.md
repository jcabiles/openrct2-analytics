# ADR 0019: dbt practices — stated departures from dbt's defaults, contract-generated sources, no packages yet

- Date: 2026-10-07
- Status: Accepted, provisional until the project owner's review (verify: owner-later — a correction reopens the
  models built on it).
- Supersedes in part: ADR 0016 (`docs/adr/0016-dbt-design.md`). Where both records speak (staging order of
  repeats, materialization, names, packages), this record governs; the rest of ADR 0016 stands unchanged.

## Bottom line

The warehouse follows dbt Labs' published practice except where a departure is listed here with its reason.
The departures are deliberate: tables instead of views, singular staging names, repeats removed in staging in
the order the listener received them with ties broken by raw file and line, contracts on money-carrying staging models, layer schemas without a
developer prefix, Kimball `fct_`/`dim_`/`obt_` names, readable keys, integer game keys, envelope columns first and
full rebuilds, plus one dated exception to the contract-versioning gate. Each has a plain-language reason in section 1, "Why each departure is intentional". Source definitions are
generated from the data contracts, and drift between them fails the gate. Every model and column is described
with its unit and clock, and the site's pages are declared to dbt. Cheap safeguards guard event data, the star
schema and year-over-year numbers. The stack is called "DuckDB-first", never "portable". No dbt package is added
yet; dbt Labs' project linter is probed later. Team-scale tools (dbt Mesh, orchestrators, metadata services,
snapshots) are not built, and each paid dbt platform feature is named with what the repo shows instead.

## Context

The project owner asked for the dbt part of the repo to be current best practice and suited to work by AI
agents. Twelve research lanes, reconciled in `docs/ai-dlc/reports/dbt-practices--findings.md` (the "report"
below; package detail in `docs/ai-dlc/reports/dbt-practices--findings-appendix.md`), checked ADR 0016 against
dbt Labs' documentation and practitioner sources. They agreed with almost every ADR 0016 choice and found that
several of its departures from dbt's defaults were made but never written down (report, Bottom line and
section 16). The project owner accepted the recommended option on all 19 decisions on 2026-10-06 (report,
section 19, D1 to D19). This record holds the dbt-modeling rulings; ADR 0020
(`docs/adr/0020-agent-working-rules-for-dbt.md`) holds the rules for agents that build the project (D12).

Nothing in the report was run on the pinned stack (dbt-core 1.11.15, dbt-duckdb 1.11.0, DuckDB 1.5.5) unless it
says "repo run" (report, "How this was produced, and the sample"). Where a decision below rests on an unrun fact, the
first ticket that uses it runs a probe first.

Roadmap names used below: NEXT 3a is the staging slice, 3b intermediate, 3c marts, 3d the marts' trust tests,
3f the reviewer pages, NEXT 8 the observational pricing model, NEXT 15 the showcase site, NEXT 20 operating the
stack. R1 to R7 are the roadmap items the report added (report, section 19, "Roadmap items"): R1 is NEXT 21, R2 is NEXT 22,
R3 is NEXT 23, R4 is NEXT 20(e), R5 is the Recce bet (LATER), R6 is NEXT 24 and R7 is NEXT 25. "DP-n" is a row of the
report's adoption matrix (report, section 18); "D-n" is one of the 19 decisions.

## Decision

### 1. Departures from dbt's defaults

Each row is a place where this repo chose differently from dbt Labs' default advice. dbt's style guide calls
itself a suggestion (report, section 2), so a stated departure is allowed; an unstated one is not.

| Departure | dbt's default | This repo, and why | Gain | Cost | Report |
|---|---|---|---|---|---|
| Staging and intermediate are tables | Staging as views; intermediate ephemeral | ADR 0013 bars views from published files, and every build starts from an empty DuckDB file, so tables cost little; dbt's own docs give tables as the upgrade path | Every step is queryable when tracing a number | Larger files | §1, §2; DP-1, DP-17 |
| Singular `stg_<event_type>` names | `stg_<source>__<entity>s` | One source system (the plugin); event, contract and model already share one name. Rename if a second source system appears | One name across event, contract and model | Diverges from the guide's pattern | §1; DP-2 |
| Repeats removed in staging | Staging lists rename, cast, arithmetic and bucketing; it does not name removing repeats | Event packages (Snowplow, dbt-ga4) remove repeats in their first layer. Event-type staging models keep the first-received copy of each `event_id`: ordered by `received_at` (when the listener received it), never `emitted_at` (the game's clock). Ties at equal `received_at` are broken by `_raw_file`, then `_raw_line` (the tie-break row below). `stg_envelope` keeps every delivery, for landed-event counts (ADR 0016, `docs/CONVENTIONS.md`). `unique` on `event_id` is tested only after this step | Every model above staging sees each event once, chosen independently of the game's clock | One `row_number()` step per staging model | §1, §4; DP-3, DP-80; D13 |
| Contracts on money-carrying staging models | Enforced contracts belong on marts and public models | A contract fails a wrong decimal scale even on an empty table (repo run, ADR 0016) | Money types cannot drift before the marts | A data type on every money column | §1; DP-10 |
| Layer schemas without `target.schema` | Keep `target.schema` in `generate_schema_name` so developers do not overwrite each other | Safe only because each environment is its own DuckDB file (ADR 0013); a comment beside the macro says so | `marts.fct_park_day` means the same in every file | Breaks if ADR 0013 ever changes; the comment makes that visible | §2; DP-9 |
| `fct_`, `dim_` and `obt_` names | Marts named by plain entity | The star schema is a chosen Kimball convention; `obt_` marks the wide reporting tables built from the star | A reviewer reads the star at a glance | Not dbt Labs' own naming | §2, §3; DP-16 |
| Readable composite text keys | Hashed keys from `dbt_utils.generate_surrogate_key` | Hashing would add a package for one macro; text keys can be read while debugging | Keys are debuggable; no package | Longer key values | §3; DP-76; D14 |
| Integer game keys | Keys are strings | The game assigns identifiers such as `ride_id` as integers; a cast would add a step and hide the game's own value | Keys match what the game shows | Diverges from the guide's advice | `docs/CONVENTIONS.md` (dbt departures) |
| Envelope columns first | Columns grouped by type (ids, strings, numerics, booleans, dates) | Every staging model starts with the fields every event carries (`contracts/envelope.odcs.yaml`), then the payload | A reviewer finds `park_id`, `session_id` and `seq` in the same place in every model | Diverges from the guide's order | `docs/CONVENTIONS.md` (dbt departures) |
| Full rebuilds, no incremental models | Views, then tables, then incremental when builds are slow | A full rebuild reprocesses every session, the guarantee Snowplow gets by reprocessing any session that received a new event; incremental logic can miss late rows and leave stale output after a logic change. Revisit above 5 minutes per publish; before any switch, an incremental design must first produce the same output as a full rebuild, late-arriving data included | One audited code path; lineage changes never leave stale rows | Build time grows with history | §2, §13; DP-18, DP-64 |
| Tie-break on equal `received_at`: `_raw_file`, then `_raw_line`, never `emitted_at` | A deduplication orders by an event timestamp and leaves ties to the engine | Staging keeps the first-received copy of each `event_id`, ordered `row_number() over (partition by event_id order by received_at, _raw_file, _raw_line)`. `_raw_file` (the base name of the raw JSON Lines file) and `_raw_line` (the 1-based line number in it) are added to every row by `make convert` and were added to the envelope contract at 1.4.0; the plugin never sends them. `emitted_at` is the game's clock and can repeat after a save reload, so it never decides | The same input always keeps the same row, so a rebuild never changes which copy of an event is kept | Two required envelope columns, and a contract minor bump that rebuilt the committed sample | D13(a); ruled 2026-10-07 |
| Dated exception to the contract-versioning gate: `contracts/envelope.odcs.yaml` at 1.4.0 | Section 9 and `CLAUDE.md` "Never break" 6: a breaking change needs a major version bump, and a removed constraint can be read as one | The `unique` rule on `event_id` is removed in a minor bump. It corrects a rule that contradicted the contract's own description, which says events may repeat and consumers remove duplicates on `event_id`. Ruled 2026-10-07; not triggered by datacontract 1.2.2, which rates it INFO, so `scripts/check_contract_breaking.py` carries no exception code | The contract says what the listener delivers, and `unique` on `event_id` is tested only after staging removes repeats | The exception is named here only; if a later datacontract version rates the removal ERROR, the gate fails and this row is re-examined | Section 9; D19; ruled 2026-10-07 |

#### Why each departure is intentional

Every dbt default exists to solve a problem. Each departure below keeps the problem the default solves and
drops the mechanism, because this project does not have that problem or solves it another way. In plain terms:

1. **Tables, not views.** Views save disk by recomputing on every query, which suits a cloud warehouse where
   compute is cheap and storage is shared. Here every build starts from an empty local file and the published
   files cannot contain views (ADR 0013), so tables cost almost nothing. They also let a reviewer open any step
   and see the rows behind a number. The default's goal, a cheap and fresh warehouse, is still met.
2. **Singular names (`stg_ride_visit`).** dbt's `stg_<source>__<entity>s` pattern tells apart tables from many
   source systems. This project has one source, the plugin, so the source prefix would carry no information.
   The event, its data contract and its model share one name, which makes the three easy to match. The record
   says when to revert: a second source system.
3. **Repeats removed in staging.** The listener can deliver an event twice. Removing repeats in the first model
   means every later model sees each event once, which is what Snowplow's and Google Analytics 4's public dbt
   packages do. The kept copy is the first one *received*, never the first one *emitted*, because the game's
   clock can repeat after a save reload. `stg_envelope` keeps every delivery so landed-event counts stay honest.
4. **Contracts on money-carrying staging models.** dbt Labs reserves enforced contracts (a build-time check
   that column types match the declaration) for final tables. Money here is stored in tenths of a dollar and
   converted once, so a wrong decimal scale would corrupt every number built on it. A repo run showed the
   contract catches that, even on an empty table, so the check sits where the mistake would start.
5. **No developer name in schema names.** dbt adds the developer's name to schemas so teammates do not
   overwrite each other's tables. Each environment here is its own DuckDB file, so nothing can collide, and
   `marts.fct_park_day` means the same thing in every file. This holds only while ADR 0013 holds, so a comment
   beside the macro says so and the break is visible if that ADR ever changes.
6. **`fct_`, `dim_`, `obt_` names.** The marts are a Kimball star schema (fact tables surrounded by dimension
   tables), and the prefix states each table's role before anyone opens it. `obt_` marks the wide "one big
   table" reporting tables built from the star. dbt Labs' plain entity names say less about how a table may be
   joined or summed.
7. **Readable text keys, not hashes.** The usual tool is `dbt_utils.generate_surrogate_key`, which hashes
   columns into an opaque string. That needs a package for one macro, and `dbt_utils` does not list DuckDB as a
   supported adapter (section 10). A readable key can be checked by eye when a join goes wrong.
8. **Integer game keys.** The style guide says to keep keys as strings, which protects against numeric
   identifiers losing leading zeros or overflowing. The game assigns `ride_id` as a small integer and shows that
   same number to the player. Casting it would add a step and hide the value anyone checking against the game
   would look for.
9. **Envelope columns first.** The guide groups columns by data type. Every event here starts with the same
   envelope (`park_id`, `session_id`, `seq`, `event_id`, game date, `emitted_at`) defined once in
   `contracts/envelope.odcs.yaml`. Putting those first in every staging model means a reviewer always looks in
   the same place for the columns that decide whether the data can be trusted.
10. **Full rebuilds, no incremental models.** Incremental models process only new rows, which pays off when a
    rebuild is slow. They can also miss late-arriving rows and leave stale output after a logic change, and
    this project's raw data is replayed from game saves, so late and repeated rows are normal. A full rebuild
    is one audited code path that cannot go stale, and at this data size it is fast. The record sets the exit
    condition: above 5 minutes per publish, and only after an incremental design reproduces the full rebuild's
    output exactly, late data included.
11. **Tie-break on `_raw_file`, then `_raw_line`.** A deduplication that orders only by a timestamp is
    undefined when two copies share it, and the engine may keep either one on different runs. Two deliveries
    can share a `received_at`, so the order needs two more keys that never tie. The converter knows
    which raw file and which line each event came from, so it records both, and the raw file name that sorts first, then the lower line number, wins.
    The game's own clock stays out of it for the reason in paragraph 3.
12. **One dated exception to the versioning gate.** A removed constraint can be read as a breaking change, which needs a
    major bump. The `unique` rule on `event_id` contradicted the contract's own description, which says events may repeat and
    consumers remove duplicates. Removing it makes the contract agree with itself. The
    removal is therefore a minor bump, and the project owner ruled so on 2026-10-07. The tool the gate runs rates
    the removal as information, not an error, so nothing needs to be exempted in code; this row exists so the
    ruling and its reason are written down.

What the twelve share: each departure names the default, the reason it does not fit, what is gained, what it
costs and what would reverse it. A departure with no stated reason is a defect under this record.

Cloud-only and Fusion-only dbt features are intent only: this repo documents them and never adopts them, and
`docs/ai-dlc/roadmap/park-company.md` carries one LATER item to revisit them. This record sets aside dbt Mesh's
cross-project references (section 11) and, in section 12, dbt Catalog, the Semantic Layer API, dbt Copilot, dbt
Agents, dbt Wizard, the observability agent, Slim CI, the remote MCP server and the dbt v2 (Fusion) engine, of
which only a one-time parse is planned. ADR 0020 sets aside the hosted dbt agents, dbt Copilot, dbt Wizard and the
remote MCP server (its "Rejected alternatives"). Slim CI (`state:modified` with `--defer`) runs in dbt Core and is set
aside for a different reason: the committed sample builds in full in minutes (ADR 0012).

### 2. Sources generated from the contracts

The ODCS contract (the open data-contract standard file in `contracts/`) is the single authority for each
incoming event type; dbt's source properties are generated from it, never hand-copied (report,
section 1; D2; DP-5, DP-106).

- The probe of `datacontract export dbt-sources <contract>` (datacontract-cli, a dependency, pinned at 1.2.2; the older `--format` flag was removed in 1.0.13) failed: the output carries no Parquet location (`config.external_location`) and adds `dbt_expectations` tests that need a package (`docs/FINDINGS.md`, the 2026-10-09 D2 probe row). `scripts/generate_dbt_sources.py` therefore writes the source YAML from the contracts. It generates sources only; the staging model YAML is maintained by hand.
- `datacontract dbt sync` is not used. Hand-written mart contracts stay apart from generated content, because sync with `--prune` removes contract-managed content the contract no longer holds.
- The gate fails when the committed source YAML differs from what the contracts generate.
- Source tests: `not_null` on the envelope fields at the source; `unique` on `event_id` only in staging, after
  repeats are removed, because the contract allows repeat deliveries (ADR 0006; D1; DP-6).
- Each staging model selects named columns, never `select *` from a source, and its YAML names the contract
  version it accepts. A gate check compares each staging model's declared version with the version in its contract
  file, so a new contract version fails the gate instead of drifting in; the check lands in NEXT 3a (D13a, D13; DP-81).

Gain: no hand-copied schema and no new dependency; a contract change reaches dbt in one step. Cost: the generator script is
repo code to maintain; generated and hand-written files need clear owners.

### 3. Documentation, the docs site and exposures

Every model and column is described, with its unit and clock, from NEXT 3a on; a gate check enforces coverage
(D4; DP-14). A model's description also says which business question it answers (DP-95). From NEXT 3c the gate
runs `dbt docs generate`; an `__overview__` block opens the site and shows the existing bus matrix (the table of
business processes against shared dimensions, from `docs/requirements-brief.md`) (DP-39, DP-73). Each site page
group is declared as a dbt exposure (a declared downstream use), and a check fails when a reporting (`obt_`)
table has none (DP-40); the pricing model later gets an `ml` exposure (section 7).

Gain: lineage is visible without cloning, and the same descriptions are what an AI assistant needs to answer
correctly (report, section 9, a measured +17 to +23 points of text-to-SQL accuracy in one study). Cost: about a
line per column, about 10 lines per page group, two check scripts and one gate step.

### 4. Event-data checks

Adopted from D13 (report, section 4):

- (a) Named staging columns and the accepted contract version, in NEXT 3a (section 2 above).
- (b) Session rows carry "first `seq` is 1" and "has a session-start event" flags, in NEXT 3b (DP-83).
- (c) Counter changes are computed within one kept save branch (ADR 0011), ordered by `seq`, with a test that no
  change spans two branches, in NEXT 3b (DP-84). A change computed across a reload would show a large false drop.
- (d) Not adopted: a `unique` test on `(session_id, seq)`, because `make convert` already stops the pipeline on a
  `seq` gap or repeat (DP-82).
- The warning for repeat deliveries whose payloads differ stores its failing rows (`store_failures: true`) and is
  named for what to review (D1; DP-4).

Gain: replays and counter resets cannot produce false changes, and session quality is visible per row. Cost: two
columns, one test and one stored table per build. Items (b) and (c) rest on inference; no published dbt model
covers game-save replay (report, section 16, Gaps).

### 5. Star-schema safeguards

Adopted from D14 for NEXT 3c and 3d (report, section 3):

- Day-start balances (`cash_usd`, `guests_in_park`) are semi-additive: they add across parks, never across days.
  Their descriptions say "do not sum across days", and a singular test fails if an `obt_` column sums them over
  days (DP-74).
- `fct_ride_day` joins `fct_park_day` through `park_day_key` only to read park attributes (weather); a singular
  test fails if a ride-level sum includes a park-day measure (DP-75).
- Readable keys (section 1) and the bus matrix on the docs site (section 3).
- Marts join at most four to five concepts; more move to intermediate (DP-19).

Gain: blocks the two classic star-schema double counts. Cost: a description line per balance and two tests.

### 6. Year-over-year safeguards

Adopted from D15 for NEXT 3c and 3d (report, section 5). Year-over-year stays in SQL, as ADR 0016 decided,
because MetricFlow cannot yet shift by a company year (DP-90).

- Every comparison carries the day count of both windows.
- With no prior-year data, the result is null, never zero.
- Year-to-date cuts the prior year at the same day of the company year.
- Tests: no date from November to February in any window, and equal day counts on like-for-like comparisons.
- Company-wide comparisons show the park count on each side, which states the sample (`CLAUDE.md` "Never
  break" 7). First-season parks stay in company-wide metrics; the 2026-10-03 catalog ruling stands (DP-89 is
  rejected).

Gain: no misleading growth figure, and the sample is stated beside each comparison. Cost: two count columns per
metric, one park-count column and two tests.

### 7. The data-science boundary

dbt builds tidy tables; it does not train models (D7; DP-49, DP-50; report, section 12). For the observational
pricing model (NEXT 8):

- SQL first; a Python model only for what SQL cannot do.
- dbt builds a feature table and a label table, each row with a snapshot date; labels come from after it. A
  singular test fails when a feature's source date is later than its snapshot date.
- Training and scoring run outside dbt; scores return as a declared source with tests and an `ml` exposure.
- Results state their sample and say "observational" (`CLAUDE.md` "Never break" 7).

Gain: `make check` stays fast, and future data cannot leak into features. Cost: two extra tables, one test and a
scoring script outside dbt.

### 8. Portability: "DuckDB-first"

Shared staging, intermediate and mart SQL uses dbt's cross-database macros for dates, casts and types.
DuckDB-only syntax (`read_parquet`, list and struct functions, `GROUP BY ALL`, Python models) stays at the source
and export edges. Documents call the stack "DuckDB-first", never "portable", because no run on a second adapter
exists (D18; DP-108; report, section 13). One DuckDB file per environment stays (ADR 0013): marts are DuckDB
tables, and Parquet appears only at the input and export edges; the `external` materialization is used only for
deliberate exports (DP-104, DP-105).

Gain: the portability intent is reviewable without claiming what was never proved. Cost: review discipline,
with no gate check; a "portable" claim would need a run on a second adapter.

### 9. Contract versioning gate

A gate step runs `datacontract breaking` on each contract file changed against `origin/develop`; a breaking
change without a major version bump fails. A planted breaking change tests the step. If the gate already
enforces this, NEXT 3a records that and skips the step (D19; DP-112; report, section 1). The step makes the
version bump of `CLAUDE.md` "Never break" 6 a check; the new landing path a major bump requires stays a review
item. dbt model versions are used only after v1, only for a breaking change to a mart whose consumers cannot
migrate at once (DP-111).

Gain: a breaking contract change can no longer land as a minor bump. Cost: one gate step and its test.

### 10. Packages: none yet

No dbt package is added (DP-27 to DP-34, DP-68 to DP-70; report, section 7 and Appendix A). The bar is: dbt Labs
or a known vendor, on the package hub, a release within six months, and stated support for dbt-duckdb and Core
1.11. Until a package is approved, the forbidden-pattern gate check (ADR 0020) fails on any `packages.yml`.
Dates are generated with core `dbt.date_spine`, which needs no package (DP-92).

| Package or tool | Verdict | Reason |
|---|---|---|
| dbt-project-evaluator (dbt Labs' project linter) | Probe later (R2) | Two lanes agree it states DuckDB and Core 1.11 support; release date unverified. Adopted only if it passes on the pinned stack and replaces the custom checks, and only with the project owner's package sign-off (D3) |
| dbt-utils | Rejected | DuckDB not in its supported adapter list; support is macro by macro |
| dbt-audit-helper | Rejected | DuckDB not in its adapter list |
| dbt-expectations (Metaplane fork) | Rejected | DuckDB support conflicting between its README and test configuration; the original project is unmaintained |
| dbt-date | Rejected | No release since 2024-04 |
| Elementary | Rejected | Its anomaly tests need run history the full rebuild does not keep |
| dbt_artifacts | Rejected | No DuckDB support; stores artifacts a rebuild does not need |
| codegen | Rejected | DuckDB unverified; contract-generated sources do its job |
| Snowplow, GA4 and Segment packages | Rejected | BigQuery-only, outdated or tied to their own event format; their layering is borrowed instead |
| dbt-llm-evals | Rejected | Needs warehouse AI functions; no DuckDB |
| data-diff and Datafold Cloud | Rejected | Archived, or a hosted service |
| Recce (Python tool, not a dbt package) | LATER bet (R5) | Local output diffs need a saved baseline build and a new dependency |
| dbt-metricflow (Python tool, not a dbt package) | Roadmap item R3 | Runs the metric catalog locally; waits for the project owner's dependency sign-off (D5) |

Gain: no dependency to approve, and every rejection has a stated reason. Cost: three small custom tests instead of
`dbt_utils`, and a gate script that dbt-project-evaluator might later replace.

### 11. Not built

| Item | Why not | Revisit when | Report |
|---|---|---|---|
| dbt Mesh (several projects with access rules) | No ownership boundaries in a one-project repo; cross-project `ref` needs a paid platform | Real ownership splits appear | §13; DP-63 |
| Orchestrators (Dagster, Airflow) | `make` runs the pipeline; a scheduler is a service to operate | `make` is outgrown (existing LATER bet) | §13; DP-65 |
| Metadata services (DataHub, OpenMetadata, OpenLineage) | Each is a service to run; the docs site covers lineage | A second consumer needs searchable metadata | §8; DP-66 |
| dbt snapshots | They cannot be rebuilt and ignore `--full-refresh`, which would make a second source of truth against "raw is append-only, every fix downstream"; the repo has no mutable source | Never, under the current invariants | §3; DP-21 |
| dbt function resources (UDFs) | DuckDB is not on their adapter list; the `tenths_to_usd` macro already does the one conversion | DuckDB appears on the list and a need arises | §13; DP-71 |
| Lakehouse formats (DuckLake, Iceberg, MotherDuck) | No sharing, multi-user or scale need; DuckDB lists both extensions as best-effort | A concrete sharing or scale need (LATER bet) | §13; DP-110 |
| Reverse ETL, BI tools (Lightdash, Rill, Evidence), Ossie semantic files | No consumer to sync to; ADR 0021 picks hand-built Eleventy; the Ossie spec is pre-1.0 and dbt 1.11 cannot read it | A consumer or a stable spec appears | §10, §11, §13; DP-45, DP-48, DP-67 |
| Data Vault, Activity Schema, a second all-events model, a calendar derived in dbt | The star is what reviewers expect; `stg_envelope` already reads every event type's envelope; ADR 0014 stamps the company date at the source | A record changes | §3, §4, §5; DP-72, DP-85, DP-87 |

### 12. Enterprise equivalents

The paid dbt platform features cannot run offline in this repo. Each is named with what the repo shows instead
(DP-55, DP-102; report, sections 8, 10, 13 and 14).

| dbt platform feature | What this repo shows instead |
|---|---|
| dbt Catalog | The generated docs site with exposures (section 3) |
| Semantic Layer API | `mf query` on the local MetricFlow, after R3 |
| dbt Copilot, dbt Agents, dbt Wizard | Coding agents working under the gate and the rules of ADR 0020 |
| Observability agent | A run summary read from `run_results.json` and `manifest.json` (R4, part of NEXT 20) |
| Slim CI (`state:modified` with `--defer`) | A full rebuild in the local gate (ADR 0012) |
| dbt v2 (the Fusion engine) | A one-time dbt v2 parse of the project, recorded in `docs/FINDINGS.md` during R1; the stack stays on dbt Core (ADR 0004) |
| Remote MCP server | The local dbt MCP server, deferred to the governed-metrics bet (ADR 0020) |

## Rejected alternatives

- **Applying dbt Labs' naming, materialization and package advice wholesale.** It assumes a cloud warehouse where
  views are free and many sources exist; section 1 lists each departure instead.
- **Treating dbt's style guide as not applying at all** (the earlier wording in `docs/CONVENTIONS.md`). It hid
  which departures were chosen; the guide now applies except where this record departs.
- **Hand-written source YAML.** A second copy of each raw-event schema beside the contract.
- **Company-wide year-over-year limited to parks open in both years** (DP-89). It contradicts the 2026-10-03
  catalog ruling; the park count on each side gives the reader the mix instead.
- **MetricFlow `offset_window` for year-over-year** (DP-90). It shifts by a calendar year, which lands on the
  wrong day of an eight-month company year.
- **Slim CI, a jaffle-shop pre-commit mirror and a second SQL formatter** (DP-35, DP-38). The gate already runs
  everything and runs SQLFluff.

## Consequences

- NEXT 3a gains: the sources probe and generator, source and staging key tests, named staging columns with the
  accepted contract version and its gate check, the stored duplicate warning, macro argument docs (with `validate_macro_args` if it
  parses on dbt 1.11.15, else dropped and noted), the schema-macro comment, description coverage, and the
  contract versioning gate step (D1, D2, D4, D13a, D19).
- NEXT 3b gains session flags and branch-bounded counter changes (D13b, D13c); NEXT 3c and 3d gain the docs site,
  exposures, the bus matrix and the safeguards of sections 5 and 6 (D4, D14, D15); NEXT 8 follows section 7.
- Roadmap items written, not yet built: R1 (dbt 1.12 upgrade with the dbt v2 parse; ADR 0004 gains a note when it
  runs), R2 (dbt-project-evaluator probe), R3 (MetricFlow), R4 (run summaries in NEXT 20), R5 (Recce, LATER), R6
  (guest-visit fact) and R7 (the coding-agent evaluation suite in ADR 0020).
- `docs/CONVENTIONS.md` now says dbt Labs' style guide applies except the departures listed here, and states the
  style-guide departures and the DuckDB-first rule.
- **How we would know this is wrong:** a full rebuild of real data takes more than 5 minutes; a contract change
  reaches dbt without the gate noticing; a published growth figure compares windows of different lengths; a
  reviewer finds a departure from dbt's defaults that this record does not list; or the project owner's review
  corrects a ruling. Any of these reopens this record.
