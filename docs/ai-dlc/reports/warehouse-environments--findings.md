# Where development stops and production starts: warehouse environments — research findings
status: research complete; blind-reviewed three times (2026-10-03) and every review's findings folded in · date: 2026-10-03 · initiative: park-company (roadmap NEXT 14, the warehouse environments slice, research step)

## Bottom line
- **The adopted pattern works on the pinned tools, and its single-publisher mechanics are tested.** One DuckDB file per environment, chosen by a dbt target, plus a production publish that renames an audited candidate file over the published one, both worked on dbt-core 1.11.15, dbt-duckdb 1.11.0 and DuckDB 1.5.5 in a local experiment on 2026-10-03 (`docs/FINDINGS.md`). The rename took about 0.1 ms, and a reader that had the old file open kept reading it without an error. The experiment ran one publisher at a time; the safeguards added after review (a lock, a per-run candidate folder, a park and row check on the candidate, path guards, a read-only file mode and a rotation that keeps every version recoverable) are acceptance tests for the build.
- **Today's gate overwrites the only warehouse.** `make check` runs `dbt build` against `warehouse/openrct2.duckdb`, the same file `make transform` builds, and the data root defaults to the committed sample. Every gate run therefore points the local warehouse back at the sample. Moving the gate to a temporary CI file fixes this.
- **The rename is safe only under three rules, and the experiment broke each one on purpose.** First, the candidate must have the same file name as the published file, in its own folder inside `warehouse/`, because dbt-duckdb names the database after the file and writes that name into every view that refers to another model. Second, no write-ahead log (a `.wal` file, DuckDB's journal of changes not yet saved into the main file) may sit beside either file. Third, every relation in a published file must be a table, because today's views store a relative Parquet path and read whatever Parquet is there at query time, so the audit stops holding after publication.
- **More rules come from the blind reviews, not the experiment.** Only one publish per data set may run at a time, enforced by an exclusive lock file held from build to rename, because two publishers sharing one candidate could publish a file nobody audited. The publish checks that every park in the candidate's own tables belongs to the data set being published, because folder names alone do not prove where a capture came from and the landing folder can change after the build; the same check refuses a candidate with an empty mart table, no registered park or no session, because a valid build can produce empty tables. No dbt target may name a published path, and nothing but the publisher's rename writes one, because a direct write could leave a WAL beside the published file and break it. The publisher makes the candidate read-only on disk (mode 0444) before the rename, so a notebook or command line outside the repo's code cannot open a published file for writing either; someone with write permission on the folder can still change the mode on purpose, which the protocol does not guard against.
- **Readers need two habits:** open the published file read-only (the file itself is read-only on disk, and the repo's connection helper refuses anything else), and reconnect to see a new version. A process that keeps any connection open keeps seeing the old file, even through a second connection.
- **Rehearsal and company data stay apart by folder, by file and by a park check.** Each has its own landing folders and its own published file (`warehouse/rehearsal.duckdb`, `warehouse/company.duckdb`); dbt's data root no longer falls back to the committed sample outside development and CI; and a publish fails when its candidate holds a park that the committed park registry does not list for that data set. Who labels each published number with its data set is assigned to the website and the metric catalog (ADR 0013).
- **What changes:** ADR 0013 records these mechanics as proposed, with eight acceptance tests for the build, and the build step of NEXT 14 may start. Every capture command names its data set until the clean start, a provisional answer queued for the project owner's review; one question about existing captures waits for the project owner (section 7).

## How this was produced
One research lane ran on 2026-10-03: a Claude Opus agent with web access and the repo, working alone. Official documentation came first (docs.getdbt.com, the dbt-duckdb README, duckdb.org, the POSIX standard and the Python docs), then dated posts on write-audit-publish. Where the docs and the pinned versions could differ, the installed packages' source code was read. The publish mechanics were then tested by running them: a copy of this repo's dbt project (its three staging models, plus two probe models added only to the copy) and short DuckDB scripts ran in a scratch folder outside the repo, with the repo's own virtual environment. Nothing in the repo tree changed during the experiment. Three blind reviews by a model from another family (Codex) followed on 2026-10-03; their findings and resolutions are in `docs/ai-dlc/ledger/warehouse-environments.md` (removed at close-out; read it with `git show d144e37:docs/ai-dlc/ledger/warehouse-environments.md`), and the safeguards they prompted are design, not measurement.

Each claim carries its source URL and an "as of" date. "As of 2026-10" means the page was read then; a page's own last-updated date is given where it shows one. Evidence strength: **strong** (several primary sources agree, or a primary source plus a measurement here), **moderate** (one primary source, or a measurement here alone), **weak** (one secondary source, or inference). "Measured" means this lane's experiment: one machine (Apple silicon, 8 cores, macOS 26.5.2), the committed sample, observational. Each mechanic ends with a verdict: **adopted**, **adapted** (used in a stated, changed form), or **rejected** (with the reason).

## Decisions at a glance

| Mechanic | Verdict | Form here |
|---|---|---|
| One file per environment, chosen by a dbt target | adopted | `dev`, `ci`, `rehearsal` and `company` outputs in the committed `profiles.yml`, each its own DuckDB file |
| How a target is chosen | adopted | Every `make` target passes `--target`; the profile's default stays `dev` |
| CI builds a temporary file from the committed sample | adopted | `make check` builds the `ci` target into a `mktemp -d` folder and removes it afterwards, the same on a laptop and on GitHub Actions |
| Data root per environment | adapted | `parquet_root` defaults to the committed sample only for `dev` and `ci`; other targets fail unless it is passed |
| Write-audit-publish | adopted | One `dbt build` into a fresh candidate file (write and audit), then a rename over the published file only when dbt exits 0 |
| One publisher at a time | adopted | An exclusive lock file per data set, `warehouse/<name>.lock`, held from build to rename |
| Same file name for candidate and published file | adopted | `warehouse/candidate/<run-id>/<name>.duckdb`, in a folder unique to the run, is renamed to `warehouse/<name>.duckdb` |
| WAL check before the rename | adopted | Inside the lock, publishing refuses while a `.wal` file sits beside either file; the candidate is set read-only (mode 0444) before the rename, so no writer can open a published file |
| Rollback | adopted | A hard link of the published file to `previous/<name>.duckdb.new`, renamed over the previous file only after the candidate is published, keeps the version just replaced on every publish after the first; rolling back is one rename |
| Published files hold tables only | adapted | Staging and marts are tables in every target; intermediate models may be tables or ephemeral, never views |
| Rehearsal and company data | adopted | Separate landing folders and published files, plus a park check of the candidate's tables against the committed registry, whose `park_id` is unique, before publication |
| Schemas inside one file | rejected | DuckDB's single-writer lock would let every development build lock readers out of production |
| Copying into the production file in place | rejected | It needs every reader closed, and it fails on a non-empty file |
| Slim CI and a self-hosted runner | rejected already | ADR 0012 records why |

## 1. dbt targets and file paths

### 1.1 One file per environment, chosen by a dbt target — adopted
**In plain terms.** dbt keeps a list of named destinations, called targets, in `profiles.yml`. Each environment gets its own target, and for DuckDB a target is simply a different file. Choosing the environment means choosing the target.

**The evidence.**
- dbt separates environments with targets in one profile; a `dev` target is the usual default, and a `prod` target is used to deploy (https://docs.getdbt.com/docs/core/dbt-core-environments, last updated 2026-08-26, as of 2026-10; https://docs.getdbt.com/docs/core/connect-data-platform/connection-profiles, as of 2026-10). **Strong.**
- dbt Labs recommends "different schemas within one database" as the cheapest separation in a cloud warehouse (same environments page). That does not carry over to DuckDB: one process holding a file read-write excludes every other process, readers included (https://duckdb.org/docs/current/connect/concurrency.html, v1.5.2 docs, as of 2026-10). Measured: while one process held a file read-write, a read-only open from a second process failed with "Could not set lock on file". **Strong.**
- dbt-duckdb sets the database name to the file name without its extension, so `<folder>/dbfile.duckdb` becomes `dbfile` (https://github.com/duckdb/dbt-duckdb, as of 2026-10). In the installed dbt-duckdb 1.11.0, a `database` field that differs from the file name is rejected unless it names an attached database (`dbt/adapters/duckdb/credentials.py`). **Strong.**
- A MotherDuck tutorial uses the same shape, one profile whose `dev` and `prod` outputs differ only in `path` (https://motherduck.com/blog/duckdb-dbt-e2e-data-engineering-project-part-2/, undated, as of 2026-10). **Weak.**

**Best practice and pitfall.**
- Best practice: one output per environment, each with its own file, and development as the default, so a bare `dbt build` can never touch a published file.
- Pitfall: environments as schemas in one file. A development build would lock the website and every other reader out of production for as long as it runs.

**Verdict: adopted.** Four outputs, none of which names a published path: `dev` writes under `warehouse/dev/`; `ci` writes into a fresh temporary folder for each run, and any path variable it reads must resolve inside `warehouse/ci/` or that folder or the command refuses before opening; `rehearsal` and `company` write only candidates, `warehouse/candidate/<run-id>/rehearsal.duckdb` and `warehouse/candidate/<run-id>/company.duckdb`, with a run ID that only the publish command sets (section 2). Gain: no dbt build can write a published file directly, and two runs never share a candidate. Cost: four outputs to keep in step, a path check before each CI build, and the development file shows only what was last built there, not what is published.

### 1.2 How `make` and CI choose a target — adopted
**In plain terms.** Each `make` command names its environment itself, so nobody has to remember to set a variable, and a setting left over in one shell cannot redirect the next command.

**The evidence.**
- `--target` works with every dbt command and overrides the profile's default (connection-profiles page above). **Strong.**
- The flags reference names `DBT_ENGINE_TARGET` as the environment variable for `--target`, and says command-line options win over environment variables, which win over `dbt_project.yml` (https://docs.getdbt.com/reference/global-configs/about-global-configs, last updated 2026-09-16, as of 2026-10). The pinned dbt-core 1.11.15 reads `DBT_ENGINE_TARGET` first and the older `DBT_TARGET` second (`dbt/cli/params.py`). Measured: `DBT_TARGET=ci` built the CI file, `DBT_ENGINE_TARGET=ci` won over `DBT_TARGET=dev`, and `--target prod` won over `DBT_TARGET=ci`. **Strong.**
- `env_var()` works in `profiles.yml`, with an optional default (https://docs.getdbt.com/reference/dbt-jinja-functions/env_var, last updated 2026-09-08, as of 2026-10). Measured: an output whose path is an `env_var()` with no default fails with "Env var required but not provided" only when that output is selected; a `dev` build ran with the CI variable unset. **Strong.**
- Changing `--vars`, or the content or environment variables of `profiles.yml`, makes dbt re-parse the whole project (https://docs.getdbt.com/reference/parsing, last updated 2026-07-15, as of 2026-10). A separate `--target-path` (dbt's artifacts folder) per environment keeps each environment's saved parse and run results apart. **Moderate**: the docs state the trigger; the remedy is inference.

**Best practice and pitfall.**
- Best practice: `make` passes `--target` on every dbt call, and the CI file's path comes from a variable with no default, so a mistake fails at once.
- Pitfall: relying on an exported `DBT_TARGET` or `DBT_ENGINE_TARGET` in a shell or in direnv. A forgotten export silently points the next build at another environment, and the variable's name differs between the current docs and older releases.

**Verdict: adopted.** The GitHub Actions workflow needs no change: its job already runs `make check`, which will choose `ci` itself. Per-environment `--target-path` folders (for example `target/ci`) are optional; they also give the run-history table planned in NEXT 2e (keeping the warehouse current) one folder per environment to read. Gain: the environment is visible in every command. Cost: a plain `dbt build` typed by hand still uses `dev`, so anything else must go through `make`.

### 1.3 The data root follows the target — adapted
**In plain terms.** The models read Parquet files from a folder named by a dbt variable, `parquet_root`. Today that folder defaults to the committed sample, so a production build that forgot to name its folder would publish sample data without any error.

**The evidence.**
- The `target` variable is available in Jinja, and dbt's own example switches a source's database on `target.name`, with an `invalid_database` fallback for any other target (https://docs.getdbt.com/reference/dbt-jinja-functions/target, last updated 2026-04-23, as of 2026-10). **Strong.**
- Measured: in `models/staging/_sources.yml`, `var('parquet_root', 'data/sample/rehearsal' if target.name in ['dev', 'ci'] else 'invalid-parquet-root')` rendered; a production build without the variable failed while creating the staging views (dbt exit 1), and `dev` still built with no variable. dbt's `exceptions.raise_compiler_error` is not available while this YAML renders (measured: "'exceptions' is undefined"). Removing the default altogether fails at parse with "Required var 'parquet_root' not found", at the cost of plain `dbt` commands in development. **Moderate.**

**Best practice and pitfall.**
- Best practice: the command that chooses the target also chooses the landing folder, as an absolute path for anything published, and no target outside `dev` and `ci` has a default.
- Pitfall: a silent default. Even with the guard, a failed build leaves a half-built candidate file on disk (measured), so the publish step must trust dbt's exit code, never the file's existence.

**Verdict: adapted** from dbt's documented target switch: `dev` and `ci` default to the committed sample; `rehearsal` and `company` fail unless `make` passes their own Parquet folder. Gain: sample data can no longer be published by omission. Cost: the failure comes at view creation rather than at parse, with a "No files found" message that names the placeholder folder instead of the missing variable.

## 2. Publishing a production file: write-audit-publish by rename

### 2.1 Write and audit into a candidate — adopted
**In plain terms.** Build the new warehouse where nobody reads it, run every test on it, and only then make it the one people read. If anything fails, readers keep the last checked version.

**The evidence.**
- Write-audit-publish was popularized by Netflix in a 2017 DataWorks Summit talk: write where consumers do not read, audit, then publish (https://lakefs.io/blog/data-engineering-patterns-write-audit-publish/, published 2023-05-30, updated 2025-08-08, as of 2026-10). **Moderate.**
- dbt Core has no built-in write-audit-publish. An open feature request, opened 2026-09-29, describes building to staging relations, testing there, and publishing the whole set together "so downstream consumers never see a partial mix of stale and refreshed models" (https://github.com/dbt-labs/dbt/issues/16509, as of 2026-10). **Moderate.**
- The long-standing dbt recipe on Snowflake is build, test, then swap: build in a `stage` database, then run `ALTER DATABASE prod SWAP WITH stage` (https://discourse.getdbt.com/t/performing-a-blue-green-deploy-of-your-dbt-project-on-snowflake/1349, 2020-07-01, as of 2026-10). **Moderate.**
- DuckDB "only supports writing to a single attached database in a single transaction" (https://duckdb.org/docs/current/sql/statements/attach.html, as of 2026-10), so a publish that writes several files cannot be one transaction; renaming one file can be all-or-nothing (section 2.2). **Strong.**
- Measured: one `dbt build` into the candidate, models and every dbt test together, took about 3.9 seconds of wall time on the committed sample.

**Best practice and pitfall.**
- Best practice: run one `dbt build` into a new candidate folder unique to the run, so that the build and its tests are the audit, and publish only when it exits 0.
- Pitfall: auditing something other than what gets published, for example testing the development file, or rebuilding after the tests ran.

**Verdict: adopted.**

### 2.2 Publish by atomic rename, under three rules — adopted
**In plain terms.** On macOS and Linux, renaming a file over another is instant and all-or-nothing: anyone who opens the path gets either the whole old file or the whole new one. Three mistakes break it, and the experiment made each one on purpose.

**The evidence.**
- POSIX `rename()`: when the new name already exists, it "shall remain visible to other threads throughout the renaming operation and refer either to the file referred to by new or old before the operation began"; the call fails across file systems; and a file another process still has open keeps its contents until it is closed (https://pubs.opengroup.org/onlinepubs/9799919799/functions/rename.html, as of 2026-10). Python's `os.replace` replaces an existing destination and "may fail if src and dst are on different filesystems" (https://docs.python.org/3/library/os.html#os.replace, as of 2026-10). Measured: the rename took 94 to 117 microseconds. **Strong.**
- **Rule 1, the same file name.** dbt-duckdb writes the database name into views that refer to other models: a probe view was stored as `... FROM openrct2.main.stg_park_daily` (measured). A candidate built as `openrct2_candidate.duckdb` and renamed to `openrct2.duckdb` failed on that view with `Catalog "openrct2_candidate" does not exist!`; a candidate with the same file name in a sibling folder worked (measured). The Snowflake recipe meets the same trap and overrides `ref` so views carry no database name (Discourse post above); keeping the name avoids the override. **Strong.**
- **Rule 2, no WAL.** DuckDB keeps changes not yet saved into the main file in a `.wal` file beside it; the file is deleted on a normal exit and is needed for recovery after a crash (https://duckdb.org/docs/current/operations_manual/footprint_of_duckdb/files_created_by_duckdb.html, as of 2026-10), and automatic saving starts only once the log reaches 16 MiB (https://duckdb.org/docs/current/configuration/overview.html, as of 2026-10). Measured: after a writer died without closing, renaming only the main file published a file with no tables at all; a stale `.wal` left beside the published path made every open of the new file fail with "INTERNAL Error: Failure while replaying WAL file"; and after a normal `dbt build`, no `.wal` remained. **Strong** for the mechanism; **moderate** for the exact error, seen on one version.
- **Rule 3, the same disk.** The candidate folder sits inside `warehouse/`, so the rename never crosses file systems (POSIX above). **Strong.**
- **One publisher at a time.** The blind review showed that a fixed candidate path lets a second publisher delete and recreate the candidate after the first one's audit, so the first could rename an unaudited file; the experiment ran one publisher only. Opening a lock file with `O_CREAT` and `O_EXCL` fails when the file exists, and the macOS `open(2)` manual page says this "may be used to implement a simple exclusive-access locking mechanism" (read 2026-10-03; POSIX specifies the same flag, https://pubs.opengroup.org/onlinepubs/9799919799/functions/open.html). Giving each run its own candidate folder, with the same file name inside, removes the shared path as well. **Moderate**: documented behavior, not tested here.

**Best practice and pitfall.**
- Best practice: take `warehouse/<name>.lock` with `O_EXCL`, and exit non-zero if it is taken; build `warehouse/candidate/<run-id>/<name>.duckdb`; check the parks in the candidate's tables and refuse a candidate with an empty mart table, no registered park or no session; refuse while a `.wal` sits beside either file; set the candidate to mode 0444; on any publish after the first, hard-link the current published file to `warehouse/previous/<name>.duckdb.new`; rename the candidate over the published file; then rename `.new` over `warehouse/previous/<name>.duckdb`, and release the lock on exit. A failure at any step leaves the version that was published recoverable. The blind reviews showed that removing the old previous file before linking erases the rollback copy if the link fails, that replacing the previous file before the candidate's rename loses the older version if that rename fails, that a WAL check is safe only when nothing can open a published path for writing, and that a passing build can still be empty. Measured: rolling back was one rename of the kept file.
- Pitfall: a shared candidate path, a candidate with a different name, a rename that leaves its WAL behind, or a candidate in a temporary folder on another disk. These publish an unaudited file, break views, publish an empty file, or turn the rename into an error or a slow copy that is not all-or-nothing. A plain hard link also fails when the previous file already exists, which is every publish after the second.

**Verdict: adopted**, with the lock, the per-run folder and the rotation order added after review; ADR 0013 states their acceptance tests. Gain: readers switch from one audited file to the next in one step, and neither a bad build nor a second publisher reaches them. Cost: an estimated 150 lines of publish code plus its tests, disk space for up to four copies of each warehouse during a publish (published, previous, the new previous link and candidate), and a lock left by a killed publish that must be removed by hand.

### 2.3 Readers during and after the swap — adopted
**In plain terms.** People reading the warehouse never block a publish and never see half a file. They do keep seeing the old version until they reconnect.

**The evidence.**
- DuckDB lets many processes read a file in read-only mode, or one process read and write it (concurrency page above). **Strong.**
- Measured: a reader process with the old file open kept reading the old data after the rename, with no error, while a new connection from another process saw the new data. Inside the reader's process, a second connection opened while the first was still open also returned the old data; only after every connection in that process had closed did a new one see the new file. No official DuckDB page found explains this; the Python page says only that a database instance closes with its last connection (https://duckdb.org/docs/current/clients/python/dbapi.html, as of 2026-10). **Moderate.**
- Measured: publishing in place is blocked by any reader. With one read-only reader open, a read-write open of the published file and an `ATTACH` of it for writing both failed with "Could not set lock on file". With no reader, `COPY FROM DATABASE` (DuckDB's whole-database copy, https://duckdb.org/docs/current/sql/statements/copy.html, as of 2026-10) into the existing file failed with `Table with name "t" already exists!`. **Moderate.**

**Best practice and pitfall.**
- Best practice: every reader (the website, notebooks, the DuckDB command line) opens the published file read-only and uses short-lived connections, or reconnects after each publish. No process in the repo opens a published file for writing; the repo's connection helper refuses a write-mode open of a published path, and the file's read-only mode makes the operating system refuse one from anywhere else.
- Pitfall: a long-running server that holds one connection forever and never shows new data; and anything that writes into the published file in place, such as stored test failures or an ad-hoc table, which changes audited data and needs a write lock that no reader may hold.

**Verdict: adopted** as rules for NEXT 15 (the website) and for any notebook.

### 2.4 What a published file holds: tables, not views over Parquet — adapted
**In plain terms.** Today every model is a view, a saved query that reads the Parquet files each time someone asks. A view publishes the question, not the answer: if the Parquet changes after the audit, the published numbers change without a new audit. A view that names a relative path also works only from the repo's root folder.

**The evidence.**
- Measured: the staging views store relative paths, such as `FROM "data/sample/rehearsal/v1/park_snapshot.parquet"`, and the published file opened from another working folder failed with "No files found that match the pattern". With views, replacing the Parquet after publication changed a published count from 108 rows to 10; with the same models built as tables the count stayed 108, and the file opened from any folder. On the committed sample the table build was 1.3 MB and the view build 0.5 MB. **Moderate**: one small build.
- `ARCHITECTURE.md` already records that dbt builds views that bind the Parquet files at build time, so the files must exist then. **Strong** (repo fact).

**Best practice and pitfall.**
- Best practice: every relation in a published file is a table, so the audited answer is what gets published and every relation answers from any folder.
- Pitfall: a published file of views over Parquet, which lets unaudited changes through and gives readers in other folders errors.

**Verdict: adapted.** A published file holds tables only. Staging models are tables in every target, marts are tables, and the dbt design session (NEXT 3·0) may make intermediate models tables or ephemeral (inlined into the models that use them, leaving no relation), never views. Staging is a table rather than ephemeral because it is the only layer today, so ephemeral staging would publish an empty file, and because the deep-dive goal has a reader trace a number through staging to a mart in DuckDB. Gain: the file opens and answers from any folder, and the gate builds the same relations a publish does. Cost: on the committed sample the file grew from 0.5 MB to 1.3 MB, and every build copies the data instead of pointing at it. The build's acceptance test opens the renamed file from outside the repo and queries every relation.

### 2.5 Writer and reader versions — adopted as a rule
**In plain terms.** A DuckDB file opens in the same or a newer DuckDB version; an older version may fail to open a newer file.

**The evidence.**
- Newer DuckDB versions read files from older ones; older versions read newer files on a best-effort basis only; the `STORAGE_VERSION` option of `ATTACH` (since 1.2.0) and the `storage_compatibility_version` setting choose the written format; storage version 68 belongs to v1.5.x (https://duckdb.org/docs/current/internals/storage.html, as of 2026-10). **Strong.**
- The default `storage_compatibility_version` is v0.10.2 (configuration page above). Measured: the pinned DuckDB 1.5.5 reported v0.10.2. **Strong.**

**Best practice and pitfall.**
- Best practice: build and read with the pinned DuckDB from the project's environment, and check any new reader's DuckDB version (the website tool in NEXT 15) against the written format before adopting it.
- Pitfall: a reader built on an older DuckDB than the file's format, for example a website tool that bundles its own engine, which may fail to open the published file.

**Verdict: adopted** as a rule; no setting changes now.

## 3. CI, the committed sample, and rehearsal and company data

### 3.1 CI builds a temporary file from the committed sample only — adopted
**In plain terms.** The automatic check builds a throwaway warehouse from the small sample in the repo and deletes it afterwards, on a laptop and on GitHub alike.

**The evidence.**
- dbt's hosted CI builds each pull request in a temporary schema unique to it and drops the schema when the pull request closes (https://docs.getdbt.com/docs/deploy/continuous-integration, last updated 2026-09-01, as of 2026-10). For DuckDB, the equivalent of a temporary schema is a temporary file. **Moderate.**
- GitHub Actions' `RUNNER_TEMP` folder is "emptied at the beginning and end of each job" (https://docs.github.com/en/actions/reference/workflows-and-actions/variables, as of 2026-10); `mktemp -d` gives a laptop the same, so one recipe serves both. **Strong.**
- Today, `make check`'s dbt step and `profiles.yml` point at `warehouse/openrct2.duckdb`, and `parquet_root` defaults to `data/sample/rehearsal` (`Makefile`, `profiles.yml`, `models/staging/_sources.yml`), so each gate run replaces what `make transform` built there. Measured: a build of the `ci` target into a `mktemp -d` file produced a 0.5 MB file and left the development and candidate folders untouched. **Strong.**

**Best practice and pitfall.**
- Best practice: `make check` creates the temporary folder, passes its path to the `ci` target (refusing before opening if the path resolves outside `warehouse/ci/` or that folder, so it can never name a published file), passes `parquet_root` as the committed sample explicitly, and removes the folder on exit, after success or failure. A shell `trap` does the removal, and writing the folder variable as `${dir:?}` stops an empty variable from ever turning into a removal of `/`.
- Pitfall: a CI file at a fixed path in the repo. A crashed run leaves it behind, and two gate runs at once, such as a laptop run beside an agent's run, collide on DuckDB's file lock.

**Verdict: adopted.** The contract check already reads only `data/sample/rehearsal`, so CI stays independent of any private data. Gain: the gate can no longer overwrite the development warehouse. Cost: `make check` no longer leaves a warehouse behind to query, so ad-hoc queries over the sample need `make transform`.

### 3.2 Rehearsal and company data in separate folders and files — adopted
**In plain terms.** Practice data and the real company's data never share a folder or a warehouse file, and a publish checks every park's identity, so a rehearsal number that lands in the wrong folder still cannot reach a company report.

**The evidence.**
- The roadmap rules that rehearsal data is "labeled rehearsal everywhere it appears, and never counts as company data" (`docs/ai-dlc/roadmap/park-company.md`, Scope rulings), and ADR 0012 adopts a separate landing path and file for it. **Strong** (repo rule).
- The landing folders are already settings: `OPENRCT2_RAW_DIR` and `OPENRCT2_PARQUET_DIR` in `src/openrct2_analytics/config.py`, defaulting to `data/raw` and `data/parquet`. A breaking contract change opens a new versioned landing path (`CLAUDE.md`, "Never break" item 6), so the data set's folder belongs above the version folder. **Strong** (repo fact).
- Two published files can be opened together even with the same file name: `ATTACH ... AS alias` gives an attached database an explicit name (https://duckdb.org/docs/current/sql/statements/attach, cited by the blind review). The same-name constraint of section 2.2 was observed when renaming a candidate whose views name their own database; table-only files attach under any alias. Different names are chosen so that a file's name shows its data set, not because DuckDB requires them. **Moderate**: documentation only, not tested here.
- Folder names alone do not prove where data came from: a capture that lands in the wrong folder by mistake is still a valid capture, and `dbt build` tests neither which parks it holds nor which data set its Parquet root belongs to (blind review). A publish therefore checks every distinct `park_id` in the candidate's own tables, after the build and inside the lock, against the data set's parks in a committed registry. It does not read the landing root, because conversion replaces the Parquet folders and could swap them between the build and the check (second blind review). The registry's `park_id` carries a dbt `unique` test, so one park cannot belong to both data sets. **Strong** (repo rule and the reviews' counterexamples).
- Folders and the park check keep the data apart; they do not put the word *rehearsal* on a chart. The visible label on every published number is owned by the showcase website (NEXT 15) and the metric catalog (NEXT 13), whose acceptance check is that every chart, table and README number states its data set (ADR 0013, "Conditions enforced elsewhere"). **Strong** (repo rule).

**Best practice and pitfall.**
- Best practice: `data/rehearsal/raw/v1/` and `data/rehearsal/parquet/v1/` beside `data/company/raw/v1/` and `data/company/parquet/v1/`; published files `warehouse/rehearsal.duckdb` and `warehouse/company.duckdb`; a publish command that refuses to run without naming one; and, before the rename, a park check that fails the publish when any `park_id` in the candidate's tables is not listed for that data set in `seeds/park_registry.csv`. That registry is the shared home NEXT 16 (the company calendar) proposes: NEXT 16 owns its columns, and this slice needs only a `data_set` column beside `park_id` and a `unique` test on `park_id`.
- Pitfall: a silent default data set for captures. A headless rehearsal run or a test session that lands in the company folder stays there, because raw captures are append-only, and every later fix has to happen in dbt.

**Verdict: adopted.** Gain: rehearsal and company numbers stay apart in their folders and files, and a park that reaches the wrong folder fails the publish before the rename. Cost: the landing settings get new defaults, every park must be registered before its first publish, and existing local captures need a decision (section 7). Until the clean start, every capture command must name its data set, and bare `make listen` and `make capture-data` refuse without one; the clean start flips one documented default to `company` (provisional, owner review queued; section 7).

## 4. Where sources disagree
- **Schemas or files.** dbt Labs recommends schemas inside one database because that is cheapest in a cloud warehouse; DuckDB's file lock makes separate files the safe choice here. Resolved for files, as ADR 0012 already chose.
- **The environment variable for the target.** The current flags reference names `DBT_ENGINE_TARGET`; older material and the pinned release's fallback use `DBT_TARGET`. Both work on dbt-core 1.11.15 (measured); `make` avoids both by passing `--target`.
- **Database names inside views.** The Snowflake recipe overrides `ref` so views carry no database name; here the candidate keeps the published file's name instead, which needs no macro override. Both work. The name rule is less code, and it costs one check in the publish step.
- **Which docs page covers the pinned version.** The DuckDB setup page on docs.getdbt.com now says it applies to dbt v2.0 and later (https://docs.getdbt.com/docs/local/connect-data-platform/duckdb-setup, last updated 2026-09-16, as of 2026-10). For the pinned 1.x line this report relies on the dbt-duckdb README and the installed source, which agree with that page on the file-name rule.

## 5. Gaps and thin evidence
- Windows was not tested. `os.rename` fails there when the destination exists, and no source found says how `os.replace` behaves while another process has the destination open. The project runs on macOS and on GitHub's Linux runners.
- No official DuckDB page found describes how a process keeps reusing an open file (section 2.3) or the exact error a stale WAL causes (section 2.2); both rest on one measured run on DuckDB 1.5.5.
- A rename across file systems was not tried; POSIX and the Python docs say it can fail.
- The experiment is observational: one machine, the committed sample (108 park days), the three staging models and two probe models. A multi-year warehouse may save its log to the main file during a long build, which does not change the rules but was not seen here.
- Not researched here: the website tool's DuckDB version (NEXT 15), when production builds run (NEXT 2e), and materializations per layer (NEXT 3·0).
- The experiment ran one publisher at a time and rotated the previous file once. Concurrent publishers, the lock, three successive publishes, the failure-safe rotation, the park and row checks, the read-only file mode, the path guards and the capture refusal are build acceptance tests in ADR 0013, not measurements.

## 6. What changes on the roadmap
- NEXT 14 gains one sentence: the research is done, and the build step may start. The roadmap already labels that build `verify: owner-later` (agents build and review it; the project owner checks it afterwards).
- The clean start (roadmap 2d) gains one sentence: a follow-up of the clean start replaces the committed rehearsal extract in `data/sample/rehearsal/`, and CI builds from the new extract.
- The build step should deliver: the four outputs in `profiles.yml`; `make check` on the `ci` target with a temporary file; `make transform` on `dev`; a publish command that takes the data set's lock, builds its candidate in a per-run folder and runs the publish checks (dbt's exit code, the park check on the candidate, the WAL check, the row check, the read-only mode, the rotated previous file, the rename); the CI path guard and the connection helper that refuses write-mode opens of published files; staging as tables; the data-root guard; the separate landing folders and the capture refusal; `seeds/park_registry.csv` with `park_id`, `data_set` and a `unique` test on `park_id` if NEXT 16 has not created it; the eight acceptance tests in ADR 0013; and updates to `CLAUDE.md` and `ARCHITECTURE.md`. `.gitignore` already ignores `*.duckdb` and `*.duckdb.wal`.
- Inputs for other slices are recorded in ADR 0013, not edited into their roadmap paragraphs: NEXT 15 (the website) and NEXT 13 (the metric catalog) own the visible data-set label on every published number; NEXT 3·0 (the dbt design session) keeps every relation in a published file a table; NEXT 2e (keeping the warehouse current) decides when the publish command runs and gives it a service note; NEXT 15 (the website) reads read-only with short connections and checks its DuckDB version; NEXT 16 (the company calendar) extends the shared park registry with its own columns.

## 7. Questions for the project owner
1. **Captures already on the project owner's machine.** The files in `data/raw/` and `data/parquet/` come from real-play checks on copies of the benchmark park, before the clean start. Should they move to the rehearsal folders (a move, not an edit, so raw data stays append-only), or stay out of both data sets? If the answer is to move them, the project owner runs these steps (agents never move raw captures): move `data/raw/v1/` to `data/rehearsal/raw/v1/` and `data/parquet/v1/` to `data/rehearsal/parquet/v1/`, keep the tracked `data/raw/.gitkeep` placeholder where it is, then run `make pipeline DATA_SET=rehearsal`.
2. **Where real play lands after the clean start (provisional, owner review queued).** Provisional answer: until the clean start, every capture command must name its data set, and bare `make capture-data` and `make listen` refuse without one; the clean start flips one documented default to `company`. Gain: no capture is mislabeled silently before the clean start. Cost: one more word per command until then, and after it a rehearsal capture that forgets its data set lands in the company folders, where the park check blocks company publishes until it is dealt with. The project owner may instead keep the explicit name after the clean start too.
