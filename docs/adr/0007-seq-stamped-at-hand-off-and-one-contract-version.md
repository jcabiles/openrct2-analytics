# ADR 0007: `seq` is stamped at hand-off, and the three contracts share one version line

- Date: 2026-09-30
- Status: Accepted

## Bottom line

The plugin stamps `seq` and `event_id` when it writes a line to the socket, so a line dropped from its
queue never uses a number and a gap in landed data means loss after hand-off. Drops are counted in a
daily `plugin_stats` event, a second event type that carries the plugin's own health. The three contracts
(the envelope, `park_snapshot`, `plugin_stats`) share one version, and `schema_version` names the
landing folder `v<N>/`. Every event carries `plugin_version`. The converter records `seq` problems in an
audit file and exits non-zero instead of refusing to convert, and the contract check reads Parquet
through DuckDB views because datacontract-cli 1.2.2 cannot type-check Parquet. This ADR also corrects an
engine fact: OpenRCT2 0.5.5 runs plugins in QuickJS-ng, not Duktape.

## Context

CLAUDE.md rule 1 requires every event to carry an envelope and `seq` to have no gaps or repeats within a
session, and rule 2 says raw captures are append-only, so no fix can be applied to the raw files. The
first slice sends one event type through every layer, which fixes these shapes for later slices.

Facts the design rests on:

- The plugin queues lines while the listener is down and drops the oldest past 1,000. In 0.5.5,
  `ScSocket::write` returns true only when part of a line was sent, and false when the whole line was
  sent (`ScSocket.hpp` at v0.5.5).
- datacontract-cli 1.2.2 returns a warning for every type check on a `local` Parquet server, and its
  command-line tool exits 0 on a warning (reproduced 2026-09-30).
- DuckDB reads a timestamp ending in `Z` as zoneless, and casting it shifts it by the machine's time zone
  offset (12:00Z read back as 19:00 under America/Los_Angeles). Sampled type inference over JSON rounds a
  later decimal in an integer column silently.
- The game binary contains "quickjs" and no "duktape"; the switch to QuickJS-ng shipped in 0.5.0.
  ADR 0002 and one FINDINGS row still say Duktape.
- In 0.5.5 a park load frees the plugin's script context and runs the plugin file again (`ScriptEngine.cpp`).

## Decision

| Decision | Choice |
|---|---|
| `seq` and `event_id` | Stamped at hand-off to the socket; the counter advances only after `write` returns. If `write` throws, the line stays queued and `seq` does not advance. |
| Dropped lines | The plugin counts them, and reports the running totals in `plugin_stats`, cumulative so a lost stats line loses no count. |
| Plugin health | Its own daily event, `plugin_stats`, with its own contract, emitted just before that day's `park_snapshot`. |
| Version line | The envelope, `park_snapshot` and `plugin_stats` contracts carry one version and are bumped together. `schema_version` is the shared major version, and the listener lands each line under `v<schema_version>/`, so a breaking change to any one contract moves all events to a new landing path. |
| `plugin_version` | Required on every event, from one constant that is also the `version` given to `registerPlugin`. |
| `seq` problems | The converter always writes the Parquet and `seq_audit.parquet` (one row per session), then exits non-zero when any session has a gap, a repeat, a first `seq` other than 1. Schema errors still stop the run and write nothing. |
| Contract check | A runner creates a throwaway DuckDB file with one view per contract schema object over the Parquet, runs each contract against it, and fails unless every result is exactly "passed". The converter enforces exact types; the views let the check run type-family checks for real. |
| Engine fact | OpenRCT2 0.5.5 runs plugins in QuickJS-ng. ES5 output stays a project rule under ADR 0002, which is not edited. |

## Rejected alternatives

- **Stamp `seq` at creation.** A queue overflow would then leave gaps that look like loss after
  delivery, and the audit could not tell the two apart. Drops would still need counting.
- **Stop the converter on a `seq` violation.** Raw data cannot be repaired, so refusing to convert leaves
  no recovery path. An audit file makes the loss visible and lets dbt label affected sessions (ADR 0006).
- **A version per contract.** Three version lines would need a rule for which combination the landing
  path names. One line is simpler and costs an occasional version bump for a contract that did not change.
- **Put plugin health in `park_snapshot`.** It would mix a game fact with a producer fact, and the health
  fields would ride every future event type's contract. Its own event keeps each contract to one subject.
- **Check the contracts against Parquet directly.** datacontract-cli 1.2.2 returns a warning instead of a
  result for every type check, so the check would pass without checking types.
- **Let DuckDB infer the JSON types.** Types would depend on row order, and a decimal in an integer field
  could round without a signal. Types come from the contracts instead.

## Consequences

- A gap or repeat in landed data means loss or reuse after hand-off, not a plugin queue drop. Queue drops
  appear only in `plugin_stats` totals.
- The last `plugin_stats` period of a session is never reported, because stats are emitted only at the
  next day callback. Lines still queued when the plugin stops are lost without a count (ADR 0003).
- Later event types join the same version line. A breaking change to any contract starts a new landing
  folder for all of them.
- The plugin creates all its mutable state inside `main()`, because 0.5.5 runs the file again on every
  park load.
- ADR 0002 says the plugin runs in Duktape; that sentence is out of date, and this ADR is the current
  statement. The ES5 rule it supports still stands.

## How we would know this is wrong

- A `seq` gap appears in a run where `plugin_stats` shows no drops and no partial sends (one partial send can lose two events, because the cut line runs into the next one): the loss is
  somewhere else, and hand-off stamping hides its source.
- A contract needs a breaking change while the other two do not: one shared line forces a landing-path
  move for unchanged events, and per-contract versions become worth their cost.
- A datacontract-cli release type-checks Parquet correctly: the DuckDB views become an unneeded layer.
- A future OpenRCT2 release stops running `main()` again on a park load: the "all state in `main()`"
  rule loses its reason, though it stays harmless.
