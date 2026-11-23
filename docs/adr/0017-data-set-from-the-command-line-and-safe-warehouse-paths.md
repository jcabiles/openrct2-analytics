# ADR 0017: the data set comes from the command line, and no dbt path can reach a published file

- Date: 2026-10-03
- Status: proposed (amends ADR 0013; built; verify: owner-later)
- Superseded in part by ADR 0023 (2026-10-09)

## Bottom line

This record amends ADR 0013 (one DuckDB file per environment) in seven places, so that 0013 stays readable as it
was proposed. Every capture, pipeline and publish command names its data set on the `make` command line, a value
left exported in a shell is refused only by those commands, and no setting or symbolic link can make two data sets
share a landing folder. Before every dbt build that `make` starts, a guard refuses a warehouse path that passes
through a symbolic link, leaves its folder or reaches a published file, before anything opens it; this restates
0013's CI path check for every such build, and a dbt build typed by hand stays outside it. A publish run ID may
hold only letters, digits and dashes, and its candidate folder must be a real folder inside `warehouse/candidate/`.
The publish code lives in sibling `publish_*.py` modules in `src/openrct2_analytics/ingest/`, one module per behavior. A rotation stopped part-way is finished by
the next publish or rollback, replacing 0013's rule to remove a leftover `.new` file. The publish-time row check (the second half of 0013's Park-identity row) now takes its expected row counts from a
`meta` key in each model's YAML, as the project owner ruled on 2026-10-07. Every other part of ADR 0013
stands.

## Context

ADR 0013 left two things to the build: where the publish code lives, and how the `ci` target's path is kept off a
published file. Its Files-and-targets row asked for a check that the CI path resolves inside an allowed folder.
Writing the build spec showed two choices 0013 did not make: how a `make` command learns its data set, and which
commands need one. The spec's first review (2026-10-03) found that a `run-` prefix alone does not stop a run ID
with slashes from leaving `warehouse/candidate/`, and that 0013 should be amended by a new record rather than
edited. The second review (2026-10-03) found that a fixed file name and the read-only file mode stop a write
through a symbolic link only when DuckDB opens the file, not before; that a valid run ID's folder and a data-set
folder can each be a symbolic link; and that 0013's Publish row removes a leftover `.new` file that can hold the
only copy of the version a crash just replaced.

## Decision

| Area | Choice | Gain | Cost |
|---|---|---|---|
| How `make` picks the data set | `DATA_SET=rehearsal` or `DATA_SET=company` on the command line. For the commands that need one, a guard stops `make` before any recipe runs when `DATA_SET` comes from the environment or holds any other value. Other targets, `make check` among them, ignore it. | A forgotten export cannot pick a data set, cannot block the gate, and cannot carry shell text into a recipe. | One more word on every data-set command; a `DATA_SET` hidden in an exported `MAKEFLAGS` reads as a command-line value and is outside the guarantee. |
| Which commands need a data set | `make listen`, `capture-data`, `convert`, `contracts`, `transform`, `pipeline`, `publish` and `rollback`. The capture default is one constant in `config.py`, empty until the clean start (the switch to the real company after v1) sets it to `company`. Landing folders are `<root>/<set>/raw` and `<root>/<set>/parquet`, the data-set name always appended, and a root where two of those four folders (or their existing `v1` children) resolve to one folder, or where one lies inside another (a symbolic link), is refused before anything is written. | No pipeline step can silently use the other data set's folders, and no setting or link can send two data sets into one append-only raw folder. | Pipeline commands cannot default to rehearsal, which is what most runs use until the clean start. |
| Warehouse paths | The `ci` target's variable names only a folder; the file name is fixed as `ci.duckdb`, and `make check` creates that folder with `mktemp -d "${TMPDIR:-/tmp}/openrct2-ci.XXXXXX"`. Before every dbt build that `make` starts (`make check`, `make transform`, and the publish command's candidate folder and build), `src/openrct2_analytics/ingest/warehouse_guard.py` exits 2, before anything opens the file, when `lstat` finds a symbolic link in any component of the build's absolute path (the root's ancestors included), when the resolved path leaves that root (the root is always the top folder the build writes in: `warehouse/` for every project build, publish's candidate included, and the CI folder for `make check`; so `warehouse/` and `warehouse/candidate/` are checked on every call), or when the path is a published file or a file under `warehouse/previous/` (by resolved path or as the same file, a hard link included) or lies under `warehouse/previous/`. Publish also guards the published file and `warehouse/previous/<set>.duckdb` before it takes the lock. A dbt build typed by hand runs no recipe and is outside the guard; the published files' mode 0444 is what keeps it from writing one. | Every build `make` starts is refused before it opens a path that a link or a mistyped folder points at a published file, and one check serves the recipes, the publish code and the read-only connection helper. | About 40 lines of guard code plus tests; a `warehouse/` folder that is itself a symbolic link (to another disk, say) is refused; a hand-typed build keeps only the file-mode defense, which anyone with write permission on `warehouse/` can remove. |
| Candidate run IDs | Candidate folders are `warehouse/candidate/run-<run ID>/`. A run ID must fully match `[A-Za-z0-9-]{1,64}`. The publish command checks it before any filesystem call; the profile sends any other value to `invalid-run-id/`, a folder that never exists, so DuckDB fails at open (measured on dbt-core 1.11.15). Before taking its lock and again before creating the folder, publish runs the warehouse-path guard on it with root `warehouse/`, refusing a symbolic link at `warehouse/`, `warehouse/candidate/` or the folder, and `mkdir` refuses an existing entry. | No run ID, typed or generated, and no linked folder can point a publish's candidate build at a published path or outside its run folder. | A run ID cannot carry other characters, such as underscores or a timestamp with colons. |
| Where publish code lives | Sibling `publish_*.py` modules in `src/openrct2_analytics/ingest/` (one per behavior, with `publish.py` as the command-line entry), the lock shared with the converter in `ingest/lock.py` and the path guard in `ingest/warehouse_guard.py`. Ruled by the project owner on 2026-10-07 (decision D12 of the warehouse-environments build spec, shipped in PR #49). | The folder that owns file I/O keeps it; no new package boundary; each module stays within the worker shape limits and the file size limit. | `ingest/` grows by about eleven modules, and no single module holds all the publish code. |
| Rows required at publish (amends the second half of ADR 0013's Park-identity row) | Amendment, ruled by the project owner on 2026-10-07: 0013's Park-identity row requires at least one row in every mart table (every staging table until marts exist). That clause is replaced. Each model's YAML may carry `meta: {expected_min_rows: <n>}`, a whole number of zero or more, and the publish audit requires at least that many rows in every model whose key is above zero. A model without the key is exempt by declaration. The audit still refuses a candidate holding no registered `park_id` or no `session_id`. The key starts on the three staging models, each set to 1. The rest of the Park-identity row (the registry check and its `unique` test) stands. This carries out resolution 5 of ADR 0016. | A mart whose filling data does not exist yet no longer blocks a publish, a model that must hold rows says so beside its own definition, and an empty warehouse is still refused. | Each model that must hold rows has to declare it, so a new model that forgets the key is never row-checked; a reviewer checks the key when a model is added. |

## Interrupted rotation

This section replaces one clause of ADR 0013's Publish row, "removing a leftover `.new` from a killed run first",
which could delete the only copy of the version a crash had just replaced. The rule:

Inside the lock and before any other step, publish and rollback finish an interrupted rotation: when `warehouse/previous/<name>.duckdb.new` is the same file as `warehouse/<name>.duckdb` (`os.path.samefile`), they remove `.new`; when it is a different file, they rename `.new` over `warehouse/previous/<name>.duckdb`; when `warehouse/<name>.duckdb` is missing, they refuse with `rotation-leftover` and change nothing.

No crash in the rotation order leaves `.new` without a published file, so `rotation-leftover` means a file was
removed by hand; the refusal names both paths and the hand step `mv warehouse/previous/<name>.duckdb.new
warehouse/<name>.duckdb`, run after opening `.new` read-only to see which version it holds. Gain: a leftover file
is never an alarm to one command and rubbish to the other, and no version is discarded. Cost: about 15 lines of
publish code and four crash tests.

## Build acceptance tests

These replace ADR 0013's test 6, amend its test 8 (item 4 below) and add two; 0013's tests 1 to 5 and 7 stand.

1. (Replaces 0013's test 6.) The `check` recipe creates its folder under `$TMPDIR` and runs the guard before `dbt
   parse`. With `ci.duckdb` a symbolic link to a writable stand-in of either published file, the guard exits 2
   before anything opens it, and the stand-in keeps its bytes, mode and modification time with no `.wal` beside
   it; a hard link to a stand-in is refused too.
2. A candidate build with a run ID of `../..`, `a/b` or the empty string creates no file, and the publish command
   given such a run ID exits 2 before creating any folder or lock. With a valid run ID whose
   `warehouse/candidate/run-<run ID>` is a symbolic link out of the candidate folder, publish exits 2 before any
   build and leaves the link's target untouched. With `warehouse/` itself a symbolic link, publish exits 2 before
   creating a lock, candidate folder or DuckDB file through it.
3. A publish stopped with no cleanup right after each rotation operation (the hard link, the candidate's rename on
   a first and on a later publish, and the last rename) is finished by the next publish or rollback as
   "Interrupted rotation" states, and stamp tables show no version lost.

4. (Amends 0013's test 8 for the row check.) A candidate in which a model with `expected_min_rows` of 1 or more has
   too few rows fails the publish audit with reason `empty` naming the model; a zero-row model without the key
   passes; a candidate with no park rows or no session rows still fails even when no model carries the key.

## Rejected alternatives

- **The read-only file mode alone for the CI path** (this record's first draft). A write through a symbolic link
  is refused only when DuckDB opens the file, and a writable stand-in or a mode changed on purpose gets written.
- **A shell symbolic-link test in each recipe.** Three copies, and the publish code could not call it.
- **Wrapping every dbt command in a script, so hand-typed builds pass the guard too.** It replaces the plain `dbt`
  command the docs offer, for a case the file mode already covers.
- **Removing a leftover `.new` before linking** (ADR 0013's clause). It can delete the only copy of the replaced
  version.
- **A `run-` prefix with no character rule.** It stops a bare `..` but not a run ID holding slashes.
- **A guard on every `make` target.** An export left in a shell would stop `make check` and the benchmark.
- **One `make` target per data set and command.** Sixteen targets in place of eight, and the clean start's
  default flip has no natural form.
- **Auditing every mart (or every staging model) for rows, ADR 0013's first rule.** It demands rows in marts whose
  filling data may not exist yet, which ADR 0016 (resolution 5) rejected.
- **A table-name prefix or folder rule for the audited models.** NEXT 3·0 has not chosen mart names, so the rule
  would be a guess; a declared key sits beside the model it describes.
- **Editing ADR 0013 in place.** The house rule is that decisions are superseded, not edited, and 0013 is the
  version queued for the project owner's check.

## Consequences

- ADR 0013's changes are its status line, which says it is amended by this record, and one marker in its Publish
  row pointing to "Interrupted rotation" above.
- The build spec's decisions D4 to D7, D10, D12, D13 and D17 rest on this record, so they survive when the spec is
  removed after the build ships.
- **How we would know this is wrong:** a `make` command picks a data set nobody typed, `make check` refuses because
  of an exported `DATA_SET`, two data sets write one landing folder, a dbt build that `make` starts opens a path
  through a symbolic link or writes a file outside its run folder or the CI folder, a CI build changes a published
  file, or a publish or rollback discards a version. Any of these reopens this record.
