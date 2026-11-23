# ADR 0013: one DuckDB file per environment, published by renaming an audited candidate

- Date: 2026-10-03
- Status: proposed, amended by ADR 0017 (research done 2026-10-03; the build slice follows; verify: owner-later)
- Superseded in part by ADR 0023 (2026-10-09)

## Bottom line

Development, CI and each published warehouse get their own DuckDB file, chosen by a dbt target that every
`make` command names. CI builds a temporary file from the committed sample and deletes it. A published
warehouse is built into a candidate file with the same file name in a folder unique to its run, audited by the
same `dbt build`, and published by one atomic rename. A publish holds an exclusive lock on its data set from
build to rename, and renames only when dbt exits 0, no write-ahead log file sits beside either file, every park in
the candidate's own tables belongs to that data set, and the candidate is not empty: every mart table has rows,
with at least one registered park and one session. No dbt target names a published path, the candidate is made
read-only on disk before the rename, readers open published files read-only, and the rename is the only write a
published path receives. A published file holds
tables only. Rehearsal and company data have
separate landing folders and separate published files. The mechanics were tested with one publisher on the
pinned dbt-core 1.11.15, dbt-duckdb 1.11.0 and DuckDB 1.5.5; the lock, the park and row checks, the path guards, the
read-only file mode and repeated rotation of the previous file are acceptance tests for the build. The evidence is in
`docs/ai-dlc/reports/warehouse-environments--findings.md` and `docs/FINDINGS.md`.

## Context

The stack has one warehouse file, `warehouse/openrct2.duckdb`. `make check` and `make transform` both build
it, and the dbt data root defaults to the committed sample, so every gate run points the local warehouse back
at the sample. ADR 0012 (data-team practices) adopted one DuckDB file per environment, with rehearsal data in
its own path and file, and left the mechanics and a publish swap to NEXT 14 (the warehouse environments
slice), because DuckDB cannot commit across files in one transaction.

The research found three facts that shape the mechanics:

- DuckDB lets one process write a file or many processes read it, never both, so environments cannot share a
  file without a development build locking readers out of production.
- dbt-duckdb names the database after the file and writes that name into every view that refers to another
  model, so a file renamed to a different name breaks those views.
- Today's models are views over Parquet with relative paths. A published file of such views changes when the
  Parquet changes, without a new audit, and works only from the repo's root folder.

## Decision

| Area | Choice | Gain | Cost |
|---|---|---|---|
| Files and targets | Four outputs in the committed `profiles.yml`, and no target ever names a published path: `dev` writes under `warehouse/dev/`; `ci` writes into a fresh temporary folder created for each run, and if its path stays an environment variable, the command validates that it resolves inside `warehouse/ci/` or that run's temporary folder and refuses before opening any file otherwise; `rehearsal` and `company` write only candidates at `warehouse/candidate/<run-id>/rehearsal.duckdb` and `warehouse/candidate/<run-id>/company.duckdb`, with a run ID from an environment variable with no default that only the publish command sets. The default target stays `dev`. | No dbt build can write a published file directly, even with a mistyped variable, and two runs never share a candidate. | Four outputs to keep in step, and a path check before every CI build. |
| Target selection | Every `make` command passes `--target`; nothing relies on `DBT_TARGET` or `DBT_ENGINE_TARGET`. | The environment is visible in every command, and a leftover shell setting cannot redirect a build. | A hand-typed `dbt build` uses `dev`; other environments go through `make`. |
| CI | `make check` builds the `ci` target into a `mktemp -d` folder from `data/sample/rehearsal` and removes it on exit through a `trap`, the same on a laptop and on GitHub Actions. | The gate never touches a real warehouse, and concurrent gate runs never collide. | The gate leaves no warehouse to query; `make transform` builds one. |
| Data root | `parquet_root` defaults to the committed sample only for `dev` and `ci`, following dbt's documented target switch; other targets get a placeholder folder that fails the build unless `make` passes an absolute Parquet path. | Sample data cannot be published by omission. | The failure names the placeholder folder rather than the missing variable. |
| One publisher at a time | The whole sequence from creating the candidate folder to the rename holds `warehouse/<name>.lock`, created with `O_CREAT \| O_EXCL` and removed on exit. A publish that finds the lock taken exits non-zero without building. A rollback takes the same lock. | Two publishers of one data set cannot interleave, so a candidate that its own run did not audit can never be renamed into publication. | A publish killed without cleanup leaves the lock behind, and every later publish of that data set refuses until the file is removed by hand; the refusal names the file. |
| Write and audit | Each publish creates a new candidate folder named by a unique run ID (for example a UUID) and runs one `dbt build` into it; the build's tests are the audit. The run removes its own candidate folder on exit. | What is tested is exactly what is published. | A full rebuild on every publish. |
| Park identity | After the build and inside the lock, the publisher runs `select distinct park_id` over the candidate's own tables and exits non-zero if any park is not listed for that data set in the committed park registry, `seeds/park_registry.csv`. The landing root is not read, because conversion can replace it between the build and the check. The registry seed carries a dbt `unique` test on `park_id`, so one park cannot be listed under both data sets. In the same step it refuses, naming the reason, unless every mart table in the candidate (every staging table until marts exist) has at least one row and the candidate holds at least one registered `park_id` and at least one `session_id`; the converter writes zero-row Parquet for event types with no events, so a build can pass with empty tables. | The check judges exactly the rows that would be published, so a rehearsal park's data that reached the company landing folder, or the reverse, can never be published, and neither can an empty warehouse. | Every park must be registered before its first publish. The registry is the shared home that NEXT 16 (the company calendar) proposes; NEXT 16 owns its other columns, and this slice needs only a `data_set` column beside `park_id` and the `unique` test. |
| Publish | Only when dbt exits 0, the park and row checks pass, and, checked inside the lock just before the rename, no `.wal` file sits beside the candidate or the published file. Before the rename the publisher sets the candidate to mode 0444 (read-only for everyone), so every published file is read-only on disk: a notebook or the DuckDB command line that opens it for writing, with or without the repo's helper, is refused by the operating system and cannot create a WAL after the check. A first publish has no published file, so it skips the previous file. A later publish rotates in three steps, each rename with `os.replace`: hard-link the current published file to `warehouse/previous/<name>.duckdb.new` (removing a leftover `.new` from a killed run first) [Interrupted-rotation recovery: ADR 0017 §Interrupted rotation, which owns it.]; rename the candidate over `warehouse/<name>.duckdb`; then rename `previous/<name>.duckdb.new` over `previous/<name>.duckdb`. A failure at the first step leaves everything untouched. A failure at the second leaves the old version published and `.new` as a spare copy of it. A failure at the third leaves the new version published, the older rollback in `previous/<name>.duckdb` and the version just replaced in `.new`, so no version is lost. | Readers move from one audited file to the next in one step; the previous file is the version just replaced, and rolling back is one rename. | An estimated 150 lines of publish code plus tests, and disk space for up to four copies per data set during a publish. |
| Published contents | Every relation in a published file is a table, and no published file holds a view. Staging models are tables in every target, marts are tables, and NEXT 3·0 (the dbt design session) may make intermediate models tables or ephemeral (inlined into the models that use them, so they leave no relation), never views. | The file opens and answers from any folder, a reader can trace a number from staging to a mart in DuckDB, and the gate builds the same relations a publish does. | Larger files (0.5 MB of views became 1.3 MB of tables on the sample), and every build copies all the data. |
| Readers | Published files are opened with `read_only=true` only, and no process in the repo opens them for writing: the repo's connection helper refuses a write-mode open of a published path. Readers use short-lived connections or reconnect after each publish, read with the pinned DuckDB, and check any new reader's version against the written format. Anyone with write permission on `warehouse/` can still change a file's mode on purpose and then write it; that is outside what this protocol guarantees. | A publish never waits for readers, readers never see half a file, and no accidental write changes a published file. | A long-running reader must reconnect to see new data, an ad-hoc write into a published file is refused, and a deliberate mode change is not prevented. |
| Rehearsal and company data | `data/rehearsal/{raw,parquet}/v1/` and `data/company/{raw,parquet}/v1/`; published files `warehouse/rehearsal.duckdb` and `warehouse/company.duckdb`; the publish command refuses to run without naming one. | Each data set has its own folders and its own file, and the park check stops a park that reached the wrong folder. | New landing defaults and a decision about existing local captures. |

**Capture data set (provisional, owner review queued).** Until the clean start, every capture command must name
its data set: bare `make listen` and `make capture-data` refuse and exit non-zero without one. The clean start
flips one documented default to `company`; after it, a bare capture lands in the company folders and a rehearsal
capture must name `rehearsal`. Gain: before the clean start no capture can be mislabeled silently, which matters
because raw captures are append-only. Cost: one more word on every capture command until the clean start; after
it, a rehearsal capture that forgets its data set lands in the company folders, where the park check blocks every
company publish until the capture is dealt with downstream.

## Build acceptance tests

The build of NEXT 14 is done only when these pass; none was run during the research.

1. Two publishers of one data set run with barriers at candidate removal, candidate creation, the WAL check and
   the rename. Only the candidate audited by the publishing run can become visible, and the second publisher
   exits non-zero at the lock.
2. A rehearsal park's valid Parquet sits in the company landing folder. A company publish fails before the
   rename, and the published company file is unchanged. When the landing Parquet is replaced between the build
   and the park check, the publish is still decided on the candidate's contents. A park listed under both data
   sets in the registry fails `dbt build`.
3. Versions 1, 2 and 3 are published, then rolled back. After each publish the previous file holds the version
   just replaced, and the rollback leaves version 2 published. Each file carries a stamp table naming its version,
   and the test checks the stamps, not just readability. A failure injected at each rotation step leaves the
   versions the Publish row names for that step, and the version that was published before the failure is
   always recoverable from `published`, `previous` or `previous/<name>.duckdb.new`.
4. The renamed file is opened read-only from a folder outside the repo, and every relation it holds is
   queried; it holds no views.
5. Before the clean start, bare `make listen` and `make capture-data` exit non-zero without writing a capture.
6. A CI build whose path resolves to either published file refuses before opening it.
7. With a barrier after the WAL check, no writer leaves a WAL beside the newly published file: the repo's own
   connection helper refuses a write-mode open of a published file, and a write-mode open from a plain `duckdb`
   command line, outside the helper, is refused by the operating system; no WAL appears.
8. A publish from an empty landing root, which builds tables with no rows, is refused before the rename with a
   reason naming the empty check, and the published file is unchanged.

## Conditions enforced elsewhere

This record separates and publishes files; the roadmap's data-lifecycle conditions are enforced by other
slices, and nothing here checks them.

- **v1 uses headless copies of at least two old parks on one company calendar** (roadmap Bottom line): the
  two-park rehearsal spike (NOW), NEXT 16 (company dates and the park registry) and NEXT 6 (the two-park
  rehearsal sample and year-end close test).
- **Rehearsal data never counts as company data** (roadmap Scope rulings): this record, through data-set
  folders, files, the path guards and the park check on the candidate.
- **Rehearsal data is labeled everywhere it appears** (roadmap Scope rulings): the showcase website (NEXT 15)
  and the metric catalog (NEXT 13) own the visible data-set label on every published number. Their acceptance
  check: every chart, table and README number states its data set (rehearsal or company). The site's switch to
  company data after v1 (roadmap Bottom line) is the website's acceptance condition at that time.
- **The committed extract is preview-free** (Scope rulings, "Data in git"): full capture part 3 (NEXT 1), whose
  preview control must pass before v1. **Its replacement after the clean start** is a stated follow-up of the
  clean start (roadmap 2d): the clean-start slice replaces `data/sample/rehearsal/` and CI builds from the new
  extract.
- **The clean start follows v1, a passing dress rehearsal and backups** (roadmap Business rules): the clean
  start step (2d, done by the project owner), after the dress rehearsal (2c) and v1's acceptance test
  (NEXT 19). Until a company park is registered, the park check fails every company publish.

## Rejected alternatives

- **Environments as schemas in one file.** dbt Labs recommends schemas for cloud warehouses, but DuckDB's
  single-writer lock would let any development build lock the website out of production.
- **Publishing in place with `COPY FROM DATABASE` or `ATTACH`.** Any open reader blocks the write, and the copy
  fails on a non-empty file (measured), so readers would need closing before every publish.
- **One fixed candidate path per data set.** A second publisher can replace the candidate between the first
  one's audit and its rename, so an unaudited file is published.
- **A candidate with its own file name, plus a `ref` override.** This is the Snowflake recipe; keeping the
  published file's name avoids overriding a dbt built-in.
- **A candidate in a system temporary folder.** It may sit on another disk, where a rename fails or becomes a
  copy that is not all-or-nothing.
- **Ephemeral staging models.** With no marts yet, a published file would hold nothing, and a reader could not
  trace a number through staging.
- **Selecting environments by exported environment variables.** A forgotten export silently changes the target,
  and the variable's name differs between the current docs and older releases.
- **Slim CI and a self-hosted runner** stay rejected for the reasons in ADR 0012.

## Consequences

- The build step of NEXT 14 can start. It delivers the outputs, the `make check`, `make transform` and publish
  commands, the lock, the park check, the data-root guard, staging as tables, the landing folders, the capture
  refusal, the acceptance tests above, and the matching updates to `CLAUDE.md` and `ARCHITECTURE.md`. Where the
  publish code lives is its choice: `src/openrct2_analytics/ingest/` owns file I/O today, and a new folder would
  need its own boundary file.
- Inputs for other slices: NEXT 3·0 keeps every relation in a published file a table; NEXT 2e (keeping the
  warehouse current) decides when publishing runs and writes its service note; NEXT 15 (the website) follows
  the reader rules and checks its DuckDB version; NEXT 16 (the company calendar) extends
  `seeds/park_registry.csv`, which the NEXT 14 build creates with `park_id` and `data_set` if NEXT 16 has not.
- One question waits for the project owner: whether the captures already in `data/raw/` move to the rehearsal
  folders. The capture data set above is settled provisionally and queued for the project owner's review.
- Not tested: Windows, renames across disks, warehouses larger than the committed sample, more than one
  publisher, the path guards, and every build acceptance test above.
- **How we would know this is wrong:** a reader sees a half-published or empty file, a published file is empty or writable, holds a
  view or a relation that fails outside the repo, a publish renames a candidate its own run did not audit, a
  published file changes other than by the publisher's rename, or a sample or rehearsal row appears in the
  company warehouse. Any of these reopens this record.
