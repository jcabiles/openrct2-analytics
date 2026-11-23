# The stack

**Game events travel through a short line of steps to a website that reads only tested tables. Every step is guarded by a check, and a failed check stops the line where it fails.**

This file holds the words of two page sections, "Extracting data from the game" and "Data and analytics infrastructure". The page build renders each passage below in place, so these words are edited here, never in the page templates. A passage starts at its `passage` marker and runs to the next one. The last group of passages, fault by fault, feeds the page's failure simulator.

<!-- passage: ex-h -->
Extracting data from the game

<!-- passage: ex-lead -->
A TypeScript plugin runs inside OpenRCT2 0.5.6 and never changes the park. The build compiles it to ES5, the older JavaScript the game runs. It sends each event as one line of JSON over a local network connection to a Python listener, which saves it in a dated file that is never edited.

<!-- passage: ex-group-once -->
Once per play session, or on each save

<!-- passage: ex-audit-h -->
Sequence numbers: no gaps, no repeats

<!-- passage: ex-audit -->
Every event carries `park_id`, `session_id`, `seq`, `event_id`, the game date and `emitted_at`. The `seq` field is a sequence number. Within a session, it must increase by one for each event. Try removing or repeating an event to see the audit fail.

<!-- passage: ex-serials-label -->
One session’s seq values

<!-- passage: verdict-pass-h -->
Passes: one to eight, no gaps, no repeats.

<!-- passage: verdict-pass -->
The converter writes Parquet (a columnar data file) and an audit file. The run then continues to the contract checks.

<!-- passage: verdict-gap-h -->
Stops the run: seq jumps from four to six.

<!-- passage: verdict-dup-h -->
Stops the run: seq three appears twice.

<!-- passage: verdict-both-h -->
Stops the run: seq jumps from four to six, and seq three appears twice.

<!-- passage: verdict-fail -->
The Parquet and the audit file are still written, and `make convert` exits non-zero. `make pipeline` then stops at convert on every later run until that session is removed and recaptured.

<!-- passage: ex-budget-h -->
The plugin’s tick budget

<!-- passage: ex-budget -->
The plugin shares the game’s 25 ms tick (40 ticks a second at normal speed), so it carries a budget: a worst single tick under 10 ms and a mean under 1.25 ms.

<!-- passage: meter-worst-label -->
Worst single tick: 5.260 milliseconds against a 10 millisecond limit, on a 0 to 12 millisecond scale.

<!-- passage: meter-mean-label -->
Highest mean per tick: 0.1491 milliseconds against a 1.25 millisecond budget, on a 0 to 1.5 millisecond scale.

<!-- passage: meter-worst-title -->
Worst single tick, 13 October 2026

<!-- passage: meter-mean-title -->
Highest mean per tick, 13 October 2026

<!-- passage: meter-worst -->
5.260 ms

<!-- passage: meter-mean -->
0.1491 ms

<!-- passage: ex-bench -->
Benchmark: three 35-day runs on a park of 1,938 guests, 13 October 2026.

<!-- passage: ex-first-design -->
In a benchmark of the same park on 28 September 2026 (three 35-day runs, OpenRCT2 0.5.5), the first design’s worst tick was 95.6 ms. The redesign put the work in a queue.

<!-- passage: ex-first-design-evidence -->
Evidence: first-design benchmark, 28 September 2026.

<!-- passage: infra-h -->
Data and analytics infrastructure

<!-- passage: infra-lead -->
Raw events become reporting tables through a line of `make` targets, and every block is guarded by a check. A failed check stops the line where it fails; this page keeps reading the last export that passed.

<!-- passage: track-h -->
From game event to published table

<!-- passage: track-intro -->
Blocks are steps, gold bars are checks, lamps show each block’s state, and the train is one batch of events. The shaded box shows work in DuckDB (the warehouse database). dbt (a tool that builds and tests SQL tables) builds the models. Then `make publish` audits a candidate file and replaces the published file. `make contracts` runs three checks: the event contracts, the park registry feed and the save-file records.

<!-- passage: track-main-label -->
The pipeline, in order, from game event to published table

<!-- passage: track-branch-label -->
The branch to this page

<!-- passage: track-encl -->
In DuckDB: dbt, then make publish

<!-- passage: track-spur-h -->
After the dbt tests: this page’s copy

<!-- passage: recon-kicker -->
Run by the dbt tests

<!-- passage: recon-show -->
Show the full check

<!-- passage: recon-hide -->
Hide the full check

<!-- passage: recon-h -->
Reconciliation check: profit against the game’s finance screen

<!-- passage: recon-lead -->
The warehouse rebuilds profit from raw game events, and that figure must match the game’s own finance screen.

<!-- passage: recon-term -->
Matching a trusted outside total like this is called a reconciliation check.

<!-- passage: recon-rule -->
For each park and month, operating profit plus capital spending plus interest must equal the change in cash less bank loan, to the cent. A mismatch stops the build.

<!-- passage: recon-first -->
A park’s first month: no earlier statement to compare.

<!-- passage: track-note -->
Once the dbt tests pass, `make site-export` copies reporting tables into JSON files (plain-text data files) for this page. `make check` compares that copy with a fresh build of the committed sample. The page never reads the published warehouse.

<!-- passage: fault-intro -->
Each one is a documented failure. Pick one to see which check catches it and what keeps running.

<!-- passage: fault-clear-res -->
All blocks clear. Pick a failure to stop the pipeline.

<!-- passage: callout-clear-sub -->
The diagram shows the passing path.

<!-- passage: callout-clear-guard-h -->
How it stays clear

<!-- passage: callout-clear-guard -->
Checks run before the next block. They include the `seq` audit, contract checks, registry and save-file checks, and dbt tests. The dbt tests include a reconciliation check against the game’s finance screen. The publish audit and page export check run on their respective paths.

<!-- passage: callout-clear-reader -->
The last export that passed. This page reads committed JSON exports of three marts, never the published warehouse.

<!-- passage: fault-listener-label -->
Stop the listener

<!-- passage: fault-listener-res -->
**Listener stopped.** Absorbed upstream at Game and plugin.

<!-- passage: fault-listener-h -->
Failure: the listener stopped

<!-- passage: fault-listener-sub -->
Absorbed upstream at Game and plugin; nothing new lands.

<!-- passage: fault-listener-guard -->
The plugin’s own line queue. It keeps a bounded queue of lines and keeps reconnecting; past that it drops the oldest and counts each one in `lines_dropped_total`, so a drop leaves a trace but no `seq` gap.

<!-- passage: fault-listener-keeps -->
The game and the plugin. In a measured listener outage nothing was lost: the lines queued, then arrived after the restart, and the drop counter stayed at zero.

<!-- passage: fault-listener-reader -->
This page is unchanged: it reads the committed export. One limit: a monthly statement still queued when the game quits during an outage is lost, and the reconciliation test then fails the build.

<!-- passage: fault-seq-label -->
Send an event with a seq gap

<!-- passage: fault-seq-res -->
**Seq gap at the audit.** Caught at the seq audit.

<!-- passage: fault-seq-h -->
Failure: a seq gap in one session

<!-- passage: fault-seq-sub -->
Caught at the seq audit; the Parquet is written but not checked.

<!-- passage: fault-seq-guard -->
The `seq` audit in `make convert`. It exits non-zero on a gap, a repeat, a first value other than one, or more than one `park_id` in one session.

<!-- passage: fault-seq-keeps -->
The Parquet and the audit file are still written. `make pipeline` then stops at convert, so contracts and dbt do not run, on every later run until that session is removed and recaptured.

<!-- passage: fault-seq-reader -->
This page is unchanged: it reads the committed export.

<!-- passage: fault-unknown-label -->
Ship an unknown field

<!-- passage: fault-unknown-res -->
**Converter schema error.** Caught by the converter.

<!-- passage: fault-unknown-h -->
Failure: an event carries an unknown field

<!-- passage: fault-unknown-sub -->
Caught by the converter; no Parquet is written.

<!-- passage: fault-unknown-guard -->
The converter in `make convert` reads every field’s name, type and required flag from the contracts. An unknown field, a missing required field or a wrong JSON type is a schema error that stops the run before it writes anything.

<!-- passage: fault-unknown-keeps -->
The raw file is kept as it landed. Adding the field to its contract is a minor version bump; the next `make convert` then writes it.

<!-- passage: fault-unknown-reader -->
This page is unchanged: it reads the committed export.

<!-- passage: fault-contract-label -->
Ship a value outside its contract’s range

<!-- passage: fault-contract-res -->
**Contract check failed.** Caught at make contracts.

<!-- passage: fault-contract-h -->
Failure: a value breaks its contract

<!-- passage: fault-contract-sub -->
Caught at make contracts; held at Parquet.

<!-- passage: fault-contract-guard -->
`make contracts` checks each Parquet file against its ODCS contract (the event contracts share one version): ranges and quality rules. Any result other than exactly passed fails, warnings included.

<!-- passage: fault-contract-keeps -->
The Parquet exists; dbt does not build. A breaking contract change without a major version bump is caught earlier still, in CI.

<!-- passage: fault-contract-reader -->
This page is unchanged: it reads the committed export.

<!-- passage: fault-registry-label -->
Land a malformed registry delivery

<!-- passage: fault-registry-res -->
**Registry feed check failed.** Caught at make contracts.

<!-- passage: fault-registry-h -->
Failure: a malformed registry delivery

<!-- passage: fault-registry-sub -->
Caught at make contracts by the registry feed check.

<!-- passage: fault-registry-guard -->
Each park registry delivery is checked under an `.incoming-` name before it is renamed in. One that lands anyway makes `make contracts`, `make transform` and publish fail closed, naming the file, until it is moved to `rejected/`.

<!-- passage: fault-registry-keeps -->
Raw files and Parquet are untouched; dbt does not run.

<!-- passage: fault-registry-reader -->
This page is unchanged: it reads the committed export.

<!-- passage: fault-books-label -->
Simulate a failed reconciliation check

<!-- passage: fault-books-res -->
**Reconciliation check failed.** Caught by the dbt tests.

<!-- passage: fault-books-h -->
Failure: profit does not match the finance screen

<!-- passage: fault-books-sub -->
Caught by the dbt tests; held at dbt models. make publish fails too.

<!-- passage: fault-books-guard -->
Reconciliation tests such as `assert_park_month_cash_change_reconciles_exactly` compare each mart with the game’s finance screen; a mismatch stops the build.

<!-- passage: fault-books-keeps -->
`make transform` exits non-zero naming the test, and the models after it are not built. `make publish` fails at its dbt step and leaves the published file as it was.

<!-- passage: fault-books-reader -->
This page is unchanged: it reads the committed export.

<!-- passage: fault-publish-label -->
Publish a bad candidate

<!-- passage: fault-publish-res -->
**Publish audit failed.** Caught by the publish audit.

<!-- passage: fault-publish-h -->
Failure: a bad publish candidate

<!-- passage: fault-publish-sub -->
Caught by the publish audit, before the swap.

<!-- passage: fault-publish-guard -->
The audit checks row floors per model, no views, every park registered and no stray `.wal` file. A failure prints `publish failed` with the reason and removes the candidate and the lock.

<!-- passage: fault-publish-keeps -->
Before the renames, a failure leaves the published file unchanged. `make rollback` steps back one version if a bad file ever lands.

<!-- passage: fault-publish-reader -->
This page is unchanged: it reads the committed export. It never reads the published file.

<!-- passage: fault-export-label -->
Commit a stale site export

<!-- passage: fault-export-res -->
**Export check failed.** Caught by the export check.

<!-- passage: fault-export-h -->
Failure: a stale export was committed

<!-- passage: fault-export-sub -->
Caught by the export check; held at Site export.

<!-- passage: fault-export-guard -->
`showcase.export check` rebuilds the marts and compares; it names the first differing header key, row key and column.

<!-- passage: fault-export-keeps -->
It runs inside `make check`, so the gate fails and nothing merges.

<!-- passage: fault-export-reader -->
This page keeps the last export that passed; it is not rebuilt from stale data.
