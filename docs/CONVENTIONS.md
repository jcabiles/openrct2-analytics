# Conventions

**Bottom line.** This file is the rulebook for code in this repo. A written
rule here beats a golden example, and a golden example beats nearby code. If
an example breaks a rule, fix the example first. Every rule names the check
that enforces it, or says "judgment only" when a reviewer must check it by hand.

## 1. Precedence

- A rule in this file wins over any example file.
- A golden example (section 5) wins over other code in the repo.
- Nearby code is the weakest guide, because it may predate a rule.
- Check: judgment only.

## 2. The gate

`make check` is the one command. It first runs `make doctor` (`scripts/doctor.py`: the
venv uses a Python inside uv's managed folder, every file in each installed package's RECORD
exists, and the venv's Python imports `dbt` and the project; steps 1 to 32 below are numbered after it), then runs, in order, and
stops at the first failure:

1. `ruff format --check .` (formatting)
2. `ruff check .` (lint, including every limit in section 4)
3. `scripts/check_file_sizes.py` (the 500-line limit and its baseline)
4. `scripts/check_docs.py` (named paths, make targets, and golden examples exist)
5. `scripts/check_local_paths.py` (no tracked file holds an absolute local path)
6. `scripts/check_metric_catalog.py` (the metric catalog's house rules, section 4)
7. `mypy .` (strict typing over `src/`, `tests/`, and `scripts/`)
8. `pytest`
9. `npm run --silent plugin:build` (`tsc` compiles the plugin to ES5)
10. `node --test plugin/test/*.test.mjs` (the plugin's tests, run against a stand-in for the game)
11. `python -m openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal` (the contract check on the committed sample)
12. `python -m openrct2_analytics.ingest.registry_feed --data-root data/sample/rehearsal` (the registry feed check on the sample)
13. `python -m openrct2_analytics.ingest.save_files --data-root data/sample/rehearsal` (the save-file record check on the sample; the sample has no records, so it prints that and passes)
14. `python -m openrct2_analytics.ingest.play_mode_feed --data-root data/sample/rehearsal` (the play-mode label feed check on the sample; its one file is header-only, so it passes)
15. `scripts/generate_dbt_sources.py --check` (the dbt source file matches the contracts)
16. `scripts/check_dbt_rules.py` (the dbt house rules)
17. `scripts/check_contract_breaking.py` (the contract breaking-change check; it runs only while `CI` is set and prints a skip notice otherwise)
18. `scripts/check_metric_catalog_shape.py` (dbt's own parser reads the metric catalog as dbt 1.11 semantic models and metrics)
19. `python -m openrct2_analytics.ingest.warehouse_guard` (checks the temporary folder and its `ci.duckdb` before any build; steps 19 to 31 all run in that one folder, which `make check` creates under `$TMPDIR`, names in `OPENRCT2_CI_DIR`, and removes at exit, so the gate leaves no warehouse)
20. `dbt parse --target ci` (the dbt project parses over the sample)
21. `dbt build --target ci` (the models build on DuckDB over the same sample)
22. `python -m openrct2_analytics.showcase.export check` (the committed site exports match the fresh sample build)
23. `npm run --silent site:build` (the Eleventy site builds into the temporary folder)
24. `python -m openrct2_analytics.showcase.page_check` (the built page matches the served data)
25. `python -m openrct2_analytics.ingest.empty_extract` (writes a zero-row extract)
26. `dbt build --target ci` over that zero-row extract (every model builds on empty input)
27. `scripts/check_model_columns.py` (each built model's columns match its YAML, and no `_tenths` column is built outside staging)
28. `dbt docs generate --target ci` (the docs site and its overview build)
29. `scripts/check_exposures.py` (every `obt_` model has an exposure)
30. `scripts/check_cleaning_rule_counts.py` (every known cleaning filter has a row in `fct_cleaning_rule_count`)
31. `sqlfluff lint models tests/dbt` (SQL style, configured in `.sqlfluff`, with `target = ci` in `.sqlfluff` and `OPENRCT2_CI_DIR` set to the same folder)
32. `detect-secrets-hook --baseline .secrets.baseline` over every tracked file (secret scan)

Work is not done until `make check` exits 0. The git hook in `.githooks/`,
activated by `make setup`, runs the fast subset on every commit, including
commits nobody reviews: `git diff --cached --check` (trailing whitespace and
conflict markers), a private-key scan, and ruff format, ruff lint, and the
file-size check on the staged snapshot. Unstaged and untracked files never
affect it.

## 3. Module map

| Folder | Import rule | Check |
|---|---|---|
| `plugin/` | ES5 only in `plugin/src/`: TypeScript compiled to ES5, ES5 built-ins only, and only the `@openrct2/types` declarations; `plugin/src/performance.d.ts` declares what the game's types omit. The Node tests in `plugin/test/` are ES modules, not plugin code, so the ES5 rule does not apply to them | `tsc` and `node --test` in `make check` |
| `src/openrct2_analytics/domain/` | The template's banned list, with the config module renamed; `company_years.py` holds the company-year and autopilot-year rules as pure logic and `start_year_plan.py` the company start-year plan (their callers read Parquet and the registry and pass plain values in) | `src/openrct2_analytics/domain/ruff.toml` |
| `src/openrct2_analytics/ingest/` | The only code that opens sockets, reads or writes event files, installs and removes the plugin file in the player's OpenRCT2 folder, runs the game-check subprocess, runs the benchmark, publishes warehouse files, or checks warehouse paths before a dbt build (`publish.py` is the publish command and the other `publish_*.py` modules own its steps; `lock.py` owns the lock and the signal handling; `warehouse_guard.py` owns the path check; `delete_data.py` is the company data delete command and `delete_plan.py`, `delete_archive.py` and `delete_apply.py` own its plan, its archive and its file changes; `go_live.py` is the go-live command; `register_parks.py` writes company registry deliveries through the landing protocol and `results.py` prints the results tables; `auto_file.py` files a launcher play through after-play (a play that opened two or more new parks, company or Sandbox, is asked about each park, and its company parks are planned and registered one at a time first, by `several_parks.py`, which asks about each new park, checks the order answers and words a failure after a registration; `previous_park.py` words the note about the previous company park after a filing; `query_interrupt.py` turns DuckDB's interrupt error back into the interrupt; `start_year.py` holds the start-year reads that `register_parks.py` and the plan share; `auto_file_state.py` holds the record-file helpers of `auto_file.py`) and `autopilot_parks.py` prints the autopilot park list as JSON and `autopilot_menu.py` turns that JSON into the launcher's tab-separated menu lines; `site_company.py` is the command that builds the public site from the published company warehouse and `site_company_land.py` owns its landing by folder rename, its re-check of the published file and its build stamp); `bench_setup.py`, `bench_run.py`, `bench_play.py`, `bench_judge.py`, `bench_guests.py`, `bench_boardings.py`, `bench_verdict.py`, and `bench_sample.py` own settings and fixture checks, refusals and isolated run folders; benchmark execution; launching and stopping one session; one-run judgment; the guest completeness rules; the boarding coverage rule; the three-run verdict; and sample rebuilding respectively; `rehearsal_capture.py` is the rehearsal capture command (its refusals, then one call to the chain and one to the landing), `rehearsal_chain.py` plays its nine-session chain across two parks, `rehearsal_land.py` proves the capture in the work folder and is the only module that writes into `data/rehearsal/`, and `rehearsal_helper.py` holds the text of the speed helper plugin written into each run's own plugin folder; `save_watch.py` watches the game's save folders during a capture and appends the save-file records, `save_files.py` finds, reads and checks those records (it is also their check command), and `save_pairing.py` is the pure rule that pairs the records with `save_written` events and renders the report's "Save files" section; `save_backup.py` copies each company park's last recorded save after a healthy capture and words the warning before play; `autopilot_year.py` is the autopilot-year command (`make autopilot-year`; ADR 0049) and `autopilot_source.py` (the park's last recorded save in the backup archive, with its proof), `managed_years.py` (the managed days read from converted Parquet, and the raw session index with its per-file cache, which `unfiled.py` and the dashboard read), `autopilot_run.py` (the headless run in its own work folder and its checks), `autopilot_land.py` (the landing under the company landing lock, label first) and `autopilot_report.py` (the success report) own its steps; `play_mode_feed.py` checks the play-mode label feed; `park_label.py` is the one home of a park's display label, name and first-played time, which `auto_file.py`, `unfiled.py`, `autopilot_parks.py`, `dashboard.py` and `delete_plan.py` call (no other module builds one); `unfiled.py` lists the parks with play waiting to be filed; `landing_paths.py` is the one place that turns a configured landing, registry or save-file folder into an absolute path (a relative folder is joined to the project folder, an absolute one is used as is); may import `domain` and `config` | judgment only |
| `src/openrct2_analytics/config.py` | Reads environment variables; `state.py` is the second module, for the state folder only | judgment only |
| `contracts/` | **Contract.** One envelope contract plus one per event type; the plugin, `src/openrct2_analytics/ingest/` and `models/staging/` follow it | The contract runner (`make contracts`), which checks the Parquet through throwaway DuckDB views; `make check` runs it on the committed sample. `contracts/reference/` holds three contracts that are not event types: the park registry feed, which `python -m openrct2_analytics.ingest.registry_feed` checks (`make check`, `make contracts` and `make transform` run it), and the save-file observation records, which `python -m openrct2_analytics.ingest.save_files` checks (`make check` and `make contracts` run it), and the play-mode label feed (`session_play_mode.odcs.yaml`), which `python -m openrct2_analytics.ingest.play_mode_feed` checks (`make check`, `make contracts` and `make transform` run it, and so does the publish contract step) |
| `models/staging/` | Every contracted event type except `plugin_stats` and `weather_change` (ADR 0034, `docs/adr/0034-weather-change-staged-later.md`) has one `stg_<event_type>` table, named exactly as its contract (ADR 0022, `docs/adr/0022-staging-every-event-type.md`). Staging also holds `stg_envelope`, the staging model of the envelope's own contract (`contracts/envelope.odcs.yaml`); unlike the event-type staging models, it deliberately keeps every landed delivery, including repeated `event_id` deliveries, because its purpose is the landed-event count check. The event-type staging models rename, cast, `tenths_to_usd`, sentinel to null, and keep the first-received delivery of each `event_id`, with a warn-level test that flags repeat deliveries whose payloads differ; no joins. `stg_park_registry` stages the park registry feed and `stg_session_play_mode` stages the play-mode label feed (one row per labeled session); neither is an event type, so the "named exactly as its contract" sentence does not cover them. `stg_session_start` left-joins `stg_session_play_mode` on `session_id` to add `play_mode` (`managed` when no label row matches); this is a deliberate departure from the no-join rule, because the roadmap names `staging.stg_session_start` as the place of the column (ADR 0049), and it is the only staging model that joins another staging model. Until `weather_change` is staged, `stg_envelope` carries its deliveries | judgment only |
| `models/intermediate/` | `int_<grain>__<step>` tables: save lineage, company dates, counter changes, keys, and removal of business duplicates (resolving reloaded days and months, collapsing repeated confirmed actions) | judgment only |
| `models/marts/` | `dim_`, `fct_` and `obt_` tables; `obt_` tables read only `dim_` and `fct_`; the only layer the site reads. Marts follow `docs/requirements-brief.md`, which the project owner confirmed on 2026-10-03 (ADR 0016) | judgment only (planned check: `ref` names by prefix) |
| `src/openrct2_analytics/showcase/` | Build-time pieces of the showcase site: `export.py` writes or checks the committed JSON exports in `site/_data/` from the warehouse's marts, using the allowlist `site/exports.toml` (the sample record `sample.json` also reads `staging.stg_session_start`, because the session counts and the player flag live there and no mart holds them), `page_check.py` checks the built showcase page against the served data, and `page_check_guide.py` checks the built player guide page; `export.py` opens the warehouse read-only and imports the signal handling in `src/openrct2_analytics/ingest/lock.py` | `showcase.export check` and `showcase.page_check` in `make check` |
| `site/` | The Eleventy site: the showcase page `index.njk` and the player guide `guide.njk`, with their includes in `site/_includes/`, the figure registry `figures.mjs` (a figure region is live or pending, and every sentence about a figure comes from it), `eleventy.config.mjs`, `site/assets/css/` (stylesheets; colour literals only in `tokens.css`), `site/assets/js/` (shared browser modules that draw and wire controls; no text of four words or more, no network, no font or image file; ADR 0043), the export allowlist `exports.toml` and the committed exports in `site/_data/`; it reads only those exports, never the warehouse; its build output `site/_site/` is git-ignored | `npm run site:build` and `showcase.page_check` in `make check` |
| `metrics/` | YAML only: the metric catalog, three files by business process (`finance.yml`, `admissions.yml`, `ride_operations.yml`), each at most 500 lines (ADR 0016's "under 500 lines" is read as at most 500, the gate's one definition, rule 1f). They sit outside dbt's resource folders, so dbt never reads them directly; the shape check copies them into a temporary dbt project | `scripts/check_metric_catalog.py` (which also holds the 500-line limit) and `scripts/check_metric_catalog_shape.py` in `make check` |
| `docs/acceptance/` | The v1 acceptance scenarios in `scenarios.yml`, which cite catalog metrics by name; and the walkthrough results files `walkthrough-<YYYY-MM-DD>.md`, written by the project owner, never by agents | `tests/test_acceptance_scenarios.py` in `make check` (the scenarios file only) |
| `tests/` | May import anything in `src/`. `tests/dbt/` holds dbt singular tests (`.sql`), because dbt's default test folder is `tests/`; pytest ignores them | none needed |
| `tests/dbt/` | Singular tests, including the `review_` tests of observational hypotheses (warn severity, stored rows); generic tests go in its `generic` folder, which dbt finds only once `dbt_project.yml` sets `test-paths: ["tests/dbt"]` | `dbt build` (a generic test outside the test path fails at build, not at parse) |

When you add a folder with a boundary, give it its own `ruff.toml` that uses
`extend` and `banned-api`, like `src/openrct2_analytics/domain/ruff.toml`.

## 4. Rules

| Rule | Why | Check |
|---|---|---|
| Code is formatted by ruff. | One style; diffs show logic, not whitespace. | `ruff format --check` |
| No unused imports or names, no undefined names. | Dead code misleads readers. | ruff `F` |
| No swallowed errors: no bare or blind `except`, and no `except ...: pass` of any exception type. | A hidden failure surfaces later as a mystery bug. | ruff `BLE`, `S110` (with `check-typed-exception`) |
| A deliberate fallback states its reason in a comment. | `contextlib.suppress` and an `except` that logs and returns both pass the linter. | Judgment only |
| Cyclomatic complexity is at most 10 per function. | Each path needs a test; split instead of raising it. | ruff `C901` |
| At most 6 arguments, 4 of them positional. | Longer lists want a dataclass; more positional values get misordered. | ruff `PLR0913`, `PLR0917` |
| At most 12 branches, 6 returns, and 50 statements per function. | Backstops for long, flat functions. | ruff `PLR0912`, `PLR0911`, `PLR0915` |
| No magic numbers or strings in comparisons outside tests. | A named constant states what the value means. | ruff `PLR2004` |
| No `global` statements. | Hidden shared state breaks tests and reuse. | ruff `PLW0603` |
| Every function is fully typed, with no `Any` in signatures. | Types are the contract callers rely on. | mypy `strict`, ruff `ANN` |
| Public modules, classes, and functions have Google-style docstrings. Tests, `__init__`, and dunder methods are exempt; the class docstring documents `__init__` arguments. | Callers read the contract without reading the body. | ruff `D` (convention `google`, `D105` and `D107` ignored) |
| Errors raise; they are never logged and dropped. | Callers decide on fallbacks, explicitly. | Judgment only (partly `BLE`) |
| Settings come from environment variables through `config.py`, or `state.py` for the state folder only. | No hardcoded values or scattered `os.environ` calls. | Judgment only |
| Tests use real objects; mock only the network, paid APIs, and the clock. | A test of a mock proves nothing about the code. | Judgment only |
| Python, TypeScript, CSS, SQL, and `.mjs` files stay at or under 500 lines, including `plugin/` TypeScript and the plugin's Node tests. A file in the size baseline (section 8) may shrink but never grow. Generated files are exempt. | Large files hide duplicate logic. | `scripts/check_file_sizes.py` |
| A path or `make` target named in `CLAUDE.md`, `ARCHITECTURE.md`, or this file exists. | A dead pointer sends the next reader to code that is gone. | `scripts/check_docs.py` (it checks existence, not that the prose is true) |
| No tracked text file holds a private machine path: a path to a folder on this machine (a home, temporary or volume folder, a Windows drive path, a local file link). | A committed machine path leaks who wrote it and breaks on every other machine. | `scripts/check_local_paths.py` |
| No new dependency without approval, and `uv.lock` is committed. | Every package is a long-term cost. | Judgment only |
| No private keys are committed. | Leaked keys cannot be un-leaked. | `.githooks/pre-commit` key scan |
| No trailing whitespace or leftover conflict markers. In Markdown, end a hard line break with a backslash, not two spaces. | Both hide in diffs and break later merges. | `.githooks/pre-commit` (`git diff --cached --check`) |
| Every metric in the catalog files (`metrics/*.yml`) carries the house fields (unit, clock, grain, owner, status, role, source models, what it excludes, and its roadmap source) with allowed values; the catalog files together list exactly the metrics of its list, each name once, and each file holds both top-level keys and is at most 500 lines; every reference and column it names exists or is marked planned; a money metric reads only `_usd` columns; each tree or guardrail metric has one parent and a link that is an identity link (reconciled exactly, never with a tolerance) or a hypothesis link (claim, direction, lag, evidence that says "observational", rival explanations, review and check, plus a tolerance when it checks equality within a margin); a year-over-year metric divides by its own prior year; each additional link of a tree metric is a full hypothesis link (with the same fields) to another existing metric, never its tree parent; every guardrail metric, and only a guardrail metric, carries a threshold that states a number, a unit, a direction (at least or at most) and that it is a project decision; and no metric turns a closed month into a zero month. | A metric without a unit and a clock cannot be compared, and a tolerance on an identity hides a real mismatch. | `scripts/check_metric_catalog.py`, with its rules in `scripts/metric_catalog_rules.py` (each problem prints as `rule <number><letter>`) |
| The catalog files in `metrics/*.yml` parse as dbt 1.11 semantic models and metrics. | The house check cannot see dbt's own semantic rules, such as a primary entity on every semantic model. | `scripts/check_metric_catalog_shape.py`; inside Claude Code's sandbox it skips only while `CI` is unset, and CI refuses the skip |
| Every dbt model is a table, in the schema named after its layer (`staging`, `intermediate`, `marts`); `+materialized: table` in `dbt_project.yml` sets it, and the publish audit refuses a view. | Published files hold tables only (ADR 0013), and a reader finds a layer by schema. | Judgment only (planned check: the layer configs in `dbt_project.yml`) |
| Every dbt model's YAML states its grain ("one row per …") and its key; a fact's key uses the game date, not the company date. | A registry correction must not change keys. | Judgment only |
| Staging does first-received dedupe on `event_id` (the delivery with the earliest `received_at`, then `_raw_file`, then `_raw_line`, is kept); intermediate removes business duplicates (a reloaded day or month, repeated confirmed actions). | Every model above staging sees each event once, and business rules stay in the layer that may join. | Judgment only |
| A published average is stored as its sum and its count; every coarser grain divides summed sums by summed counts. | An average of averages weighs a short month like a long one. | Judgment only |
| No model outside `models/staging/` reads a `_tenths` column; every `_tenths` input becomes a `_usd` output through the `tenths_to_usd` macro. | One money conversion (`CLAUDE.md` "Never break" 3). | Rule d of `scripts/check_dbt_rules.py` (rules in `scripts/dbt_rules.py`) fails a `_tenths` column read outside `models/staging/`; judgment only that every `_tenths` input becomes `_usd`, except `value_tenths`, which staging keeps under its own name; `scripts/check_model_columns.py` also fails a built `_tenths` column outside staging (including through `select *`) |
| Every mart has an enforced contract with a `data_type` on each column; money is `decimal(18,2)`. No constraints. | Types and column sets cannot change silently, even on an empty table. | dbt enforces a declared contract at build; judgment only that every mart declares one |
| A metric-tree identity is tested at error severity, across two tables or two independent sources; until the planned generic `reconciles_exactly` is built, each identity is a singular test in `tests/dbt/`, and an identity against the park's previous statement exempts the first kept statement. | An identity reconciles exactly (ADR 0012). | Judgment only |
| A hypothesis with a numeric check is tested with `within_tolerance` at warn severity; its tolerance equals the catalog's. | One tolerance, checked in both homes. | Judgment only (planned check in `scripts/check_metric_catalog.py`) |
| An observational hypothesis is a `review_` singular test at warn severity with `store_failures: true`; it returns rows only for closed company years and has no tolerance. | Its result is kept for the year-end review and never fails a build (ADR 0012). | Judgment only |
| A published column is named exactly as its catalog metric. | The site's mapping and the catalog name the same thing (ADR 0021). | Judgment only (planned check: catalog names against the `obt_` YAML) |
| Test severity: the project default is `error`; a `warn` test states it; a severity that differs by data set reads `target.name`, and on `dev` also `parquet_root` (ADR 0031 and ADR 0035: the missing-day test and the year-close test warn on `ci` and on `dev` over the committed sample, and error elsewhere; both call the macro `sample_warn_severity`). | Every test has a stated severity (ADR 0012). | Judgment only |
| Complex intermediate logic ships with a dbt unit test; a source input uses `format: sql`, and each same-typed column gets a distinct value. | Logic is tested on fixed inputs; the double comparison and column swaps hide faults (`ARCHITECTURE.md`). | Judgment only |
| Every mart's row count on the committed sample equals its entry in the expected-row table (findings report, section 6.2); a mart the sample cannot fill is listed at 0 with the real data that fills it. | A test on an empty table proves nothing, and an exact count catches lost or doubled rows. | `rows_on_sample` (`tests/dbt/generic/rows_on_sample.sql`) at error severity, applied to `fct_park_month`, `obt_park_month`, `obt_company_month`, `obt_park_year`, `obt_company_year`, `obt_ride_month`, `obt_ride_year`, `int_park_years__year_close`, `int_park_years__registry_mapped`, `int_park_days__company_calendar`, `int_park_days__kept`, `int_game_actions__labeled`, `fct_park_day`, `dim_date`, `dim_park`, `int_ride_days__kept`, `dim_item`, `dim_ride`, `fct_ride_day` and `fct_cleaning_rule_count`; it counts rows only on the `ci` target over the committed sample and passes on the zero-row build, the `dev` target and the publish targets |
| Every model that removes repeat deliveries (`delivery_rank = 1`), keeps only kept-timeline rows (`timeline_status = 'kept'`, or `<>` / `!=` `'abandoned'`), sets a game placeholder to null (`nullif` with -1, 255, 1275 or 65535) or computes a counter change (`counter_change`) has a row for that rule in `fct_cleaning_rule_count`; `dim_date` and `dim_park` are exempt for the `kept` filter, with reasons in the script, and a stale exemption fails. | A cleaning rule a reviewer cannot see counted is a rule nobody can check (ADR 0006). | `scripts/check_cleaning_rule_counts.py` |
| Every dbt model and column has a description that states its unit and clock; a model's description also says which business question it answers. | The docs site and AI assistants read descriptions, so a missing unit or clock is a wrong number later (ADR 0019). | Rule b of `scripts/check_dbt_rules.py` fails a model or column description with no unit or no clock; judgment only for the business question; `scripts/check_model_columns.py` also fails a built column with no YAML entry |
| A mart joins at most four to five concepts; more move to an intermediate model. | A narrow mart is easier to trace and test (ADR 0019). | Judgment only |
| Every seed has a description and `column_types`, and notes its source. | Types, meaning and origin are explicit, not guessed from the file. | Judgment only |
| A macro is for a transformation applied identically everywhere (for example `tenths_to_usd`); otherwise readable SQL, even repeated, wins. Guidance and its sources: `docs/ai-dlc/reports/dbt-practices--findings.md`, section 1. | A macro hides logic from the reader (dbt's own advice). | Judgment only |
| No incremental models, and no dbt packages without approval. | Every build is a full, audited rebuild (ADR 0013), and a package is a dependency. | Rule d of `scripts/check_dbt_rules.py` fails when a `packages.yml` or `dependencies.yml` exists; judgment only for incremental models |
| Every plugin payload builder fills one reusable object per event type and writes every field on each fill; no task builds an array or object per item or per day beyond what the API returns. | A new payload object per event is the day-start allocation that part 2 removed (ADR 0018); a field left from the previous fill would leak one event's value into the next. | `plugin/test/allocation.test.mjs` (payload identity and live-object tests); judgment only for short-lived per-poll allocation |
| Scratch work stays in `scratch/`. | Debug output never enters history. | `.gitignore` |
| Throwaway probe code and its evidence live in the git-ignored `data/bench/probes/`, which counts as outside the repo (the project owner's ruling, 2026-10-04); every spike checks that `git ls-files data/bench/probes` is empty. | Probes never become shipped code, and the sandbox cannot write elsewhere. | Judgment only |

The dbt rows come from ADR 0016 (`docs/adr/0016-dbt-design.md`) and ADR 0019
(`docs/adr/0019-dbt-practices.md`); their evidence,
and the expected-row table, are in `docs/ai-dlc/reports/dbt-design--findings.md`.

The thresholds, and the reason for each, also sit beside the settings in
`pyproject.toml`. Preview-only ruff rules (PLR0904 public methods, PLR0914
locals) are off until they stabilize in the locked ruff.

### dbt SQL style

These rules adopt dbt Labs' published style where it does not conflict with
this repo's rules; where it does, the repo rule wins and the row names it. The
SQL rules cover `models/` and `tests/dbt/`. Sources and the comparison with
current code: `docs/ai-dlc/reports/dbt-style--findings.md`.

| Rule | Where a repo rule wins | Check |
|---|---|---|
| 1. SQL keywords and functions are lowercase; commas trail; indentation is four spaces; every alias uses `as`; SQL lines are at most 80 characters, a hard limit in `.sqlfluff`. | None. | `sqlfluff lint` in `make check` (section 2), configured in `.sqlfluff` |
| 2. A model with several steps reads its `source()` and `ref()` inputs in CTEs named for them, gives each later CTE one purpose and a descriptive name, and ends with a select from the final CTE. | A single-source staging pass-through may be one direct select (dbt Labs uses CTEs even there). | Judgment only |
| 3. Joins spell out their type, columns read from joined relations are qualified, and relation names are descriptive. | Staging has no joins. | Judgment only |
| 4. Each model has one YAML file beside its SQL, named as the model. | The grain sentence, the key, and unit and clock suffixes on column names (rows above, with the exceptions below) apply in full. | Judgment only |
| 5. Money conversion lives only in the `tenths_to_usd` macro, tested on positive, negative, null and large values. | Conversion happens once, in staging (row above). | Judgment only |
| 6. Every model tests its key with `unique` and `not_null` and each foreign key with `relationships`; one-off checks are singular tests in `tests/dbt/`; complex intermediate logic has a unit test; marts carry enforced contracts. | Facts key on the game date; identity and hypothesis links get their own tests (rows above). | `dbt build` runs them; judgment only that each exists |
| 7. dbt Labs' style guide applies except the departures listed in ADR 0019. | Names are `stg_<event_type>`, `int_<grain>__<step>`, `dim_`, `fct_` and `obt_`; every model is a table rebuilt in full; no dbt packages (section 3, rows above, and "dbt departures and portability" below). | Judgment only |

Two exceptions to the clock suffix: a point-in-time value in a snapshot model
(a count or a rating) takes its clock from the model's grain, so
`guests_in_park`, `total_admissions` and `park_rating` need none; and a period
total or a balance in a statement model takes its period or moment from the
grain, so `wages_usd` (the month's total) and `cash_usd` (at the reading) in a
monthly statement model need none.

### dbt departures and portability

dbt Labs' style guide calls itself a suggestion; this repo follows it except
where a departure is written down. ADR 0019 (`docs/adr/0019-dbt-practices.md`,
section 1) lists all twelve departures with a plain-language reason for each. Three
of them affect how models are written:

- Model names are singular (`stg_park_snapshot`, `fct_ride_day`), not plural,
  because the event, its contract and its staging model share one name.
- Game keys may be integers (for example `ride_id`); the guide's advice to
  keep keys as strings does not apply to identifiers the game assigns.
- Staging models list the envelope columns (the fields every event carries,
  from `contracts/envelope.odcs.yaml`) first, then the payload, instead of
  the guide's order by column type.

SQL is DuckDB-first. Shared staging, intermediate and mart SQL uses dbt's
cross-database macros for dates, casts and types; DuckDB-only syntax
(`read_parquet`, list and struct functions, `GROUP BY ALL`) stays at the
source and export edges. Documents say "DuckDB-first", never "portable",
because the project has not been run on a second adapter. Review enforces
this rule; no gate check does.

The other departures from dbt's defaults are in ADR 0019; the rules for agents
that build the dbt project are in ADR 0020
(`docs/adr/0020-agent-working-rules-for-dbt.md`).

## 5. Golden examples

These are the files to copy when adding a new file of the same kind.
`scripts/check_docs.py` fails when a file here is over its cap.

The template's examples are placeholders, marked with a `TEMPLATE-EXAMPLE`
line. A fresh clone passes with them. Once your own code of the same kind
exists, the check fails until this table points at one of your real files.
For a test example (`test_*.py`, `*.test.ts`, `*.test.tsx`), the same kind is
another test of that name pattern anywhere under its folder. For any other
example, it is a non-test file with the same suffix in the example's own
folder, not a subfolder. Deleting only the marker line does not help: the
check also recognizes the unchanged template example by its content. Editing
a marked example without finishing the job also fails.

The first real module in a golden example's own folder means you repoint that
row at the real file. That is intended, not a false red, because a template
placeholder is a weak example to copy. After repointing, delete the
placeholder's `TEMPLATE-EXAMPLE` marker line.

| Kind | File | Cap | Check |
|---|---|---|---|
| Configuration | `src/openrct2_analytics/config.py` | 200 lines | `scripts/check_docs.py` |
| Pure logic | `src/openrct2_analytics/domain/company_years.py` | 300 lines | `scripts/check_docs.py` |
| Test | `tests/test_listener.py` | 300 lines | `scripts/check_docs.py` |
| Plugin module | `plugin/src/emit.ts` | 150 lines | `scripts/check_docs.py` |
| Plugin test | `plugin/test/plugin.test.mjs` | 500 lines | `scripts/check_docs.py` |
| dbt staging model | `models/staging/stg_save_written.sql` | 60 lines | `scripts/check_docs.py` |

## 6. Names

Use these words with these meanings. Add project terms here as they appear.

- **gate**: `make check`, the one command that decides whether work is done.
- **domain**: the `src/openrct2_analytics/domain/` folder, which holds pure logic with no I/O.
- **golden example**: a file listed in section 5, which new files copy.
- **baseline**: an exempted, pre-existing violation (section 8).
- **event**: one JSON record the plugin emits for a single thing that happened in the game (a ride built, a guest action, a transaction).
- **envelope**: the fields every event carries regardless of type — `park_id`, `session_id`, `seq`, `event_id`, game date, and `emitted_at` — defined in the envelope contract. `received_at` is set by the listener, and the two lineage fields (`_raw_file`, the base name of the raw JSON Lines file the row was converted from, never a path, and `_raw_line`, its 1-based physical line number in that file) are added by the converter; all three are envelope fields in `contracts/envelope.odcs.yaml`, and staging passes them through.
- **rehearsal capture command**: `make capture-rehearsal DATA_SET=rehearsal`, which plays nine headless sessions of two parks in a work folder, checks the result, and only then lands the raw capture and the park registry delivery into `data/rehearsal/` (ADR 0036).
- **session**: one continuous play session of a park, from the plugin loading to the game closing or the plugin unloading.
- **park**: one OpenRCT2 save file's theme park, identified by `park_id`.
- **preview**: the see-through build-mode ghost piece the game places while the mouse moves; it is never a player action. From plugin 0.8.0 the plugin drops previews (flag bit 64) before they are sent and counts them (ADR 0042); rows from earlier plugins are labeled `preview`, and `int_game_actions__labeled` keeps them out of `is_player_action`.
- **schema 0**: the envelope and event shapes as captured on 2026-09-27, before the first versioned contract bump.
- **game day**: in-game calendar time, as tracked by OpenRCT2's date system, distinct from wall-clock time.
- **tick**: one OpenRCT2 simulation step; the unit the plugin's per-tick performance budget is measured against.
- **work queue**: the oldest-first queue in `plugin/src/work.ts` that spreads queued lines and capture work across ticks.
- **allowance**: the 4 ms limit over all plugin time in one tick that the work queue uses before starting another step.
- **step**: one oldest pending unit of work, named by its kind: a queued line hand-off (`line`), a ride-list read or one ride snapshot (`ride_list`, `ride`), a guest-list copy or one guest's daily check (`guest_list`, `guest`), one recorded arrival (`arrival`) or one recorded boarder (`boarder`). The seat poll and a boarder's reads are reported as steps (`poll`, `boarder_read`, `guest_fields`) but run outside the queue.
- **continuous task**: a work-queue task fed between days (arrivals and boarders) rather than at the day callback; it is never skipped, and the day-scoped tasks (rides and guests) are.
- **reusable payload**: the one payload object a builder refills for every event of its type; the emitter copies its fields, so it is never queued itself.
- **worst-tick source**: the step kind, `day_callback`, `weather` (the per-tick weather check, timed as a tick part, not a work step) or `other` that holds the most time in a period's worst tick, from `worst_tick_kind_ms`.
- **guest key**: the integer the plugin mints for each guest first seen in a session, counted from 1; entity IDs are reused slots, so the key, with `session_id`, is the guest's identity.
- **cohort**: the random sample of up to 100 arriving guests (each joins with probability 0.5 while a place is free) that gets one `guest_snapshot` a game day until it leaves.
- **boarding poll**: the seat poll the plugin runs every 20 ticks; a seat whose guest ID changed since the last completed poll is a new boarding, at 20-tick resolution.
- **save ID**: the ID minted for one save and stored with its writing session and queue facts in park storage.
- **benchmark**: the headless measurement on a copy of the benchmark fixture run by `make bench`; `make bench-sample` uses the same harness to rebuild the rehearsal sample.
- **ride snapshot**: one daily `ride_snapshot` event for a ride, stall, or facility.
- **listener**: `src/openrct2_analytics/ingest/listener.py`, the loopback TCP server that lands each event line in a dated JSON Lines file (`make listen`).
- **converter**: `src/openrct2_analytics/ingest/convert.py`, which turns the raw JSON Lines into one Parquet file per event type, typed from the contracts (`make convert`).
- **`seq` audit**: the converter's per-session check that `seq` starts at 1, has no gap or repeat, and carries one `park_id`; it writes `seq_audit.parquet` and exits non-zero on a violation.
- **`plugin_stats`**: the plugin's own daily health event: timing for the period since the previous day, plus running counts of dropped and failed sends.
- **rehearsal extract**: the small committed sample in `data/sample/rehearsal/`, converted from headless runs on a copy of the benchmark park; it is never company data.
- **`session_start`**: the event a session sends first (`seq` 1, unless the plugin's queue drops it before the first hand-off; plugin 0.1.0 sessions have none): plugin API level, park name, scenario name, whether the game has a window, and game speed.
- **`finance_month`**: the event that carries one monthly statement.
- **monthly statement**: the 14 ledger lines for one closed game month plus cash, bank loan and the money already booked to the new month (`new_month_booked_tenths`, absent from statements sent by plugins before 0.6.0, counted as 0) at the reading in the day-1 callback of the next month, all in tenths of a dollar.
- **hand-off**: the moment the plugin writes an event's line to the socket; `seq` and `event_id` are stamped then, so a line dropped from the queue never uses a number.
- **warm-up period**: the first `plugin_stats` period of a session, which starts at plugin start and includes startup work; it is reported and never judged against the budget.
- **capture command**: `make capture-data` (`src/openrct2_analytics/ingest/capture.py`), which installs the plugin, listens while the player plays, removes the plugin, then converts and reports.
- **install record**: `installed-plugin.json` in the capture folder: the install path, the SHA-256 of the installed bytes and the time. It is the only proof that a plugin file is the capture command's own; a file without a matching record is never overwritten or deleted.
- **game check**: `src/openrct2_analytics/ingest/game_check.py`, which asks the operating system whether the game runs, by `pgrep`'s exit-code contract: 0 running, 1 not running, anything else cannot tell.
- **this run**: for the capture report, the sessions with any event received at or after the capture command started.
- **metric catalog**: the three files `metrics/finance.yml`, `metrics/admissions.yml` and `metrics/ride_operations.yml`, which together define each of the park company's metrics (unit, clock, grain, owner, status, source models, links) in dbt 1.11's semantic-model and metric YAML shape; `docs/requirements-brief.md` says what the company needs from it.
- **north-star metric**: the single metric the company steers by, operating profit per company year (`operating_profit`), reconciled to the ledger.
- **guardrail metric**: a metric paired with the north star that must not get worse while the north star improves: guest visits and average park rating.
- **identity link**: a metric-tree link that is an exact sum or difference, reconciled by a dbt test with no tolerance.
- **hypothesis link**: a metric-tree link that is a claim about cause (with direction, lag, evidence marked observational, rival explanations, and the check that reviews it), not an identity.
- **operating day**: a simulated game day on which a park ran on the kept timeline; closed months never count.
- **kept**: a row on the timeline that save lineage keeps (ADR 0006); marts read kept rows only.
- **staging model**, **intermediate model**, **mart**: a dbt model in `models/staging/`, `models/intermediate/` or `models/marts/`; a mart is a `dim_`, `fct_` or `obt_` table.
- **one big table**: an `obt_` table, a wide table built only from the star for one consumer (the site).
- **identity test**: `reconciles_exactly`, the generic test of an identity link; it has no tolerance argument.
- **tolerance test**: `within_tolerance`, the warn-severity generic test of a hypothesis link with a numeric check.
- **review test**: a `review_` singular test that stores an observational hypothesis's result for the year-end review.
- **environment**: a dbt target with its own DuckDB file: `dev`, `ci`, `rehearsal` or `company`.
- **data set**: `rehearsal` or `company`, named with `DATA_SET=` on the `make` command line; each has its own landing folders, `data/<set>/raw/`, `data/<set>/parquet/` and `data/<set>/registry/` (the park registry feed) and `data/<set>/save_files/` (the save-file records), and its own published warehouse file.
- **candidate**: the warehouse file one publish builds in `warehouse/candidate/run-<run ID>/` and audits before it is renamed over the published file.
- **publish**: `make publish DATA_SET=<set>`, which builds a candidate, audits it, makes it read-only and renames it over `warehouse/<set>.duckdb`, keeping the replaced file for `make rollback`.
- **park registry**: the dated CSV deliveries (append-only, except a pre-go-live delete (ADR 0033)) in `data/<set>/registry/v1/`, which say which data set each park belongs to and the company year it starts in; the current model `int_park_registry__current` is built from them, and a publish refuses a park that is not registered for its data set.

Check: judgment only.

## 7. Judgment-only list

A reviewer checks these by hand, because no tool here can:

1. Whether a class is needed, or a function or dataclass would do.
2. Whether names carry real meaning, not just the right case.
3. Whether a docstring is true, not just present.
4. Whether two files implement the same behavior twice.
5. Whether tests assert real behavior rather than a mock's return value.
6. Whether a new abstraction has at least two real callers.
7. Whether a fallback is a stated decision or a swallowed error.
8. Every other row marked "judgment only" in section 4.
9. Any change to `BASELINE` or `MAX_LINES` in `scripts/check_file_sizes.py`.
   The hook runs the staged copy of that script, so a commit can loosen its
   own check.
10. Whether a golden example is a lightly edited template placeholder.
    `scripts/check_docs.py` recognizes only an unchanged one.
11. Whether a `models/staging/` model does only rename, cast, `tenths_to_usd`, sentinel to null, and first-received dedupe on `event_id`, with no joins; and whether an identity test compares two independent sides rather than a column with its own formula.
12. Whether every dbt model's YAML states its grain, "one row per …".
13. Whether a change to the event shape updates the contract, the plugin, the converter (which reads the contracts), and staging in the same PR; staging may lag only where an ADR defers it (ADR 0034 defers `weather_change`).

## 8. Exceptions

A pre-existing violation that cannot be fixed now is exempted in place with a
`# BASELINE(YYYY-MM-DD): reason` comment next to the `noqa` that silences it.
The count from `grep -rn "BASELINE(" src tests` may fall but never rise. It
is zero today.

A file already over 500 lines when the limit arrives goes in the `BASELINE`
list inside `scripts/check_file_sizes.py`, with its line count and a
`BASELINE(YYYY-MM-DD)` comment. The script fails if it grows, and asks you to
lower the entry when it shrinks. The list is empty today.

Check: `scripts/check_file_sizes.py` for the size list; judgment only for the
`noqa` count (the reviewer runs the grep).

## 9. Changing a rule

- Change a rule only with evidence from real code in this repo.
- Ship the rule's check in the same change, or mark the row "judgment only".
- Never loosen a threshold to get the gate green. Fix the code, or baseline it.
- Record a decision in `docs/adr/` only when all three hold: it is hard to
  reverse, surprising without context, and the result of a real trade-off.
  (Source: Matt Pocock's `domain-modeling` skill, MIT.)
