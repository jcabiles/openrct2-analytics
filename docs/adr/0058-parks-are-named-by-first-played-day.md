# ADR 0058: parks are named by their name and first-played day

- Date: 2026-11-19.
- Status: Proposed with the spec `docs/ai-dlc/specs/park-names.md`; it takes effect when the branch that builds it
  merges. It edits no other record.

## Bottom line

A park is shown as `<name> (first played <Mon D>)` everywhere a person reads it, for example
`Bumbly Bazaar (first played Nov 15)`. One module, `src/openrct2_analytics/ingest/park_label.py`, builds the label.
Typed phrases and commands keep the park ID.

## Context

Five places printed a park in five forms, and the filing questions showed a bare ID when a name was missing. Two parks
with one name could not be told apart.

## Decision

1. **The label is `<name> (first played <Mon D>)`.** `<Mon>` is the English three-letter month from a fixed table (never
   the system locale) and `<D>` is the day without a leading zero.
2. **"First played" is a wall-clock time.** It is the plugin's `emitted_at` (stored in UTC) of the park's earliest
   `session_start` (ties by `session_id`), taken over the converted `session_start.parquet` and the raw
   `events-*.jsonl` files of the data set together. It is converted to the local time zone of the machine that prints
   the label, one instant at a time (`park_label.to_local`), so daylight saving applies at that instant. The game date,
   the company date and file times are never read.
3. **The name is the latest `session_start` name** (converted first, else the latest raw one). A null, empty or
   all-space name is missing.
4. **Twins.** Parks with the same name (exact string) and the same shown `<Mon D>` are labelled
   `<name> (<Mon D>, <h:mm am|pm>)`, on a 12-hour clock. Those that also share the minute add the park ID after the
   time. Every park of the data set is compared, so a park has one label in every place at one moment; a label can
   change when a same-named park is first played later on the same day.
5. **Fallbacks.** A park with no first-played time is `<name> (<park ID>)`. A park with no name shows its ID in place of
   the name; with no time either, the label is the ID alone. A park the landing files say nothing about is its ID
   alone (`label_of`).
6. **Typed phrases and commands keep the ID:** the `READY` sentence, the `PARK=<id>` commands, the `scope:` and
   `confirmation:` lines of `make delete-company-data` and every "To file it, run" line.
7. **A label read that fails is named, never silent.** `make auto-file`, `make unfiled` and `make autopilot-parks` exit
   1 with their existing `io` message. The dashboard banner and the delete preview keep working, show the bare ID and
   add one line that names the problem.

## Consequences

- Gain: one rule, tested once, read by every place that shows a park; same-named parks are told apart.
- Cost: each command reads the converted Parquet and raw files for the labels, one small read per run; the day shown
  depends on the time zone of the machine that prints it.
- The park number of ADR 0057 is unchanged.
