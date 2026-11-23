# ADR 0036: the rehearsal registry delivery is written by the capture command

- Date: 2026-10-18.
- Status: Accepted 2026-10-18 (two-park capture slice).
- Superseded in part by ADR 0038 (2026-10-19), for company registry deliveries.
- Supersedes in part: ADR 0023 (`docs/adr/0023-company-dates-from-a-park-registry-feed.md`), only where it says an
  outside process delivers the park registry feed. That now holds for the company data set alone.

## Bottom line

For the rehearsal data set, `make capture-rehearsal DATA_SET=rehearsal` writes the park registry delivery itself,
through the existing landing protocol in `ARCHITECTURE.md` ("Registry feed landing"). Company deliveries stay with an
outside process.

## Context

ADR 0023 and `ARCHITECTURE.md` say an outside process delivers the registry feed. The rehearsal park IDs exist only
after the capture has run, so no outside process can write the delivery beforehand, and a hand step afterwards would
leave a captured set that fails `make transform` until someone typed the IDs in.

## Decision

1. **The capture command builds the delivery in memory after proving the capture, writes it as an
   `.incoming-` file in `registry/v1/`, checks it with `registry_feed.check_file`, and renames it into place.** It is
   the first repo code to write a registry delivery.
2. **Company deliveries are unchanged.** An outside process still lands them, and ADR 0033 still governs their
   pre-go-live delete.

Gain: the departure from ADR 0023 is recorded where readers look for decisions, and a rehearsal capture lands ready
for `make pipeline`. Cost: one more ADR to keep in mind, and the repo now holds a second writer of delivery files, so
a change to the landing protocol must update both the protocol text and this command.

## Rejected options

- **A hand-written CSV.** Gain: no code. Cost: the IDs must be copied from the capture by hand, and a typo silently
  re-dates every event of that park (ADR 0023's stated risk), with nothing to prove the file matches the capture.
- **A dbt seed.** Gain: the file sits in the repo. Cost: ADR 0023 replaced the seed with a delivered feed because a seed
  is edited in place and loses the dated history; bringing it back for one data set would split company dates across
  two mechanisms.

## Consequences

- `docs/CONVENTIONS.md` names the command's four modules, and `registry_feed.py`'s docstring says who lands each set.
- ADR 0035 records the company-year close, so this record is 0036.
