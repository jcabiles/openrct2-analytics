# ADR 0038: company registry deliveries come from the register command

- Date: 2026-10-19.
- Status: Accepted 2026-10-19 (rehearsal kit slice); the fixed company start year 2000 is amended by ADR 0050 (`docs/adr/0050-company-start-year-from-the-register-command.md`), which adds `START_YEAR` for the second and later parks.
- Supersedes in part: ADR 0036 (`docs/adr/0036-rehearsal-registry-delivered-by-the-capture-command.md`), decision 2
  ("Company deliveries are unchanged"), and ADR 0023 (`docs/adr/0023-company-dates-from-a-park-registry-feed.md`),
  only where it says an outside process delivers the park registry feed. ADR 0036 had already ended that for the
  rehearsal data set; this record ends it for company.

## Bottom line

`make register-parks DATA_SET=company` writes the park registry delivery for every captured park the registry does not
list yet. The project owner runs it after a capture and before `make pipeline`. It writes through the existing landing
protocol in `ARCHITECTURE.md` ("Registry feed landing"). No registry delivery now needs an outside process or a
hand-typed park ID.

## Context

Company park IDs exist only after the capture has run, so nothing can write their delivery beforehand. Today a company
capture cannot pass `make pipeline`: `make contracts` and `make transform` both fail on an empty registry folder, and
no command writes a company delivery. The first company capture is a throwaway practice park, and its result is
wanted without typing IDs by hand. ADR 0036 solved this for the rehearsal data set inside the rehearsal capture
command and left company to an outside process that does not exist.

## Decision

1. **A separate command, `make register-parks`, writes company deliveries.** It reads the park IDs from the
   data set's `seq` audit and each park's first `session_start` game year, and writes one row per park not yet
   registered: company start year 2000, game-year origin from that first `session_start`, and the data set it was run
   for. With `PRACTICE=yes` the row's note says "Throwaway practice park; not company data."
2. **It copies the landing protocol of ADR 0036, not the code.** It writes the file as an `.incoming-` file in
   `registry/v1/`, checks it with `registry_feed.check_file`, and renames it into place, inside the landing lock.
3. **It refuses `DATA_SET=rehearsal`.** The rehearsal capture command stays the only writer into `data/rehearsal/`
   (`docs/CONVENTIONS.md`, ADR 0036).
4. **Deletion is unchanged.** ADR 0033 still governs the pre-go-live delete of company deliveries.

Gain: a company capture becomes ready for `make pipeline` with one command and no typed IDs, and a reader of the
registry decisions finds that no delivery needs an outside process. Cost: the repo holds a second writer of delivery
files, so a change to the landing protocol must update the protocol text, `rehearsal_land.py` and this command; the
command always writes company start year 2000, so a real park with another start year needs a later change; and one
more record to keep in mind.

## Rejected options

- **A hand-written CSV.** Gain: no code. Cost: the IDs must be copied from the capture by hand, and a typo silently
  re-dates every event of that park (ADR 0023's stated risk), with nothing to prove the file matches the capture
  (ADR 0036's reasons).
- **Growing `rehearsal_land.py` to also write company deliveries.** Gain: one writer. Cost: the file is already near
  the 500-line cap, and the landing is welded to the rehearsal capture's nine-step schedule, which a company capture
  does not have.

## Consequences

- `docs/CONVENTIONS.md` names `register_parks.py` among the `ingest/` modules, and `registry_feed.py`'s docstring and
  the registry contract's description say who lands each set. The contract version does not change: only wording moves.
- ADR 0036 and ADR 0023 each gain one status line pointing here, and no other edit.
