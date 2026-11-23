# ADR 0051: the launcher asks where a play counts and files it after the game

- Date: 2026-11-15.
- Status: Proposed with the play-launcher spec (`docs/ai-dlc/specs/play-launcher-autofile.md`); it takes effect when the
  branch that builds it merges. Builds on ADR 0038 (`docs/adr/0038-company-registry-deliveries-from-the-register-command.md`)
  and ADR 0050 (`docs/adr/0050-company-start-year-from-the-register-command.md`) and changes neither.

## Bottom line

The "OpenRCT2 Enterprise" launcher now asks once, "Where should this play count?", with the answers Company and
Sandbox. It records which sessions are already converted, plays, and then files the new parks itself with a new command,
`make auto-file`, which runs the after-play steps. The player no longer types `PARKS="<id>:company,..."` after each play.
A play that fails still prints the one command that files it by hand. The stored value for a Sandbox park stays
`practice`, and no data contract, dbt model, plugin file or event contract changes.

## Context

After every play the player had to read the waiting parks, pick `company` or `practice` for each, and type the
`make after-play` command with `PARKS` and, for a later company park, `START_YEAR`. A wrong or forgotten choice
registers a park in the wrong set, and a company registry row is fixed only by hand before go-live (ADR 0033). The
launcher already knows the one fact the player has in mind before the game opens: whether this play is company play or
a throwaway.

## Decision

1. **The launcher asks first, then records, plays and files.** After the direnv checks it prints the question and reads
   `1` (Company) or `2` (Sandbox), asking again on any other answer. It then runs
   `make auto-file DATA_SET=company RECORD=yes`, and only when that succeeds `make play DATA_SET=company`, and after a
   play that exits 0 `make auto-file DATA_SET=company COUNT_AS=<company|practice>`. Gain: the choice is made once,
   before play, by the person who knows it. Cost: one question before every play, including plays of an already
   registered park, which then keep their registration.

   Amendment, 2026-11-17: the question gains a third answer, "Run autopilot on a finished park". Decisions 2 to 5 stand.
2. **A play's parks are the parks with a session that was not converted before the play.** `RECORD=yes` writes the
   sorted IDs of every converted session, and of every session in the raw captures, to the git-ignored
   `local/auto-file/converted-before.json`. After the play a
   park with a waiting session missing from that file takes `COUNT_AS`. Any other unregistered park is asked about
   one by one, and a registered park keeps its registration unless it is this play's park and was saved with the other
   choice, when the player is asked. Listing raw sessions keeps a capture that stopped before converting (Ctrl-C or a
   closed Terminal) out of this play: the next capture converts it, and it is then asked about as an earlier play's.
   Gain: one answer covers the play without guessing from park names. Cost: one read of the raw folder per launch, and
   a second launch before a failed filing is rerun replaces the record, so the rerun asks about that play's parks by
   name instead of using the earlier answer.
3. **Filing is the after-play steps, unchanged.** `make auto-file` builds the `PARKS` list (and `START_YEAR` from
   `register_parks.next_start_year` when a company park registers after the first), prints one line per park about to
   be registered, and calls the after-play module in the same process, returning its exit code. Every other refusal is after-play's own text. Gain: one writer of
   registry rows and one rule for the start year (ADR 0050). Cost: a second command that has to be kept in step with
   after-play's arguments.
4. **The record file is removed only after exit 0.** A failed filing keeps it, so the rerun classifies the same parks
   the same way. Without a usable record no park counts as this play's and every unregistered park is asked about; a
   line says why.
5. **Every failed play prints the filing line.** `make` reports every failed recipe as exit 2, so the launcher cannot
   tell the capture's own exit codes 1, 2 and 130 apart. After any play that did not exit 0 it prints
   `This play was not filed. If the report above names a seq problem, do not file it; otherwise run: make auto-file DATA_SET=company COUNT_AS=<the choice>`.
   After a refusal before the game opened, the rerun reports that nothing is waiting. Gain: no recording is lost by a
   wrong guess about the failure. Cost: the line is also printed when nothing was recorded. Ctrl-C during play ends the
   Terminal shell, so nothing is printed then.
6. **No terminal, no guess.** When a question is needed and standard input is not a terminal, `make auto-file` refuses
   with exit 2 and the rerun line. The answers "Don't file now" refuse the same way. Gain: nothing is filed by default.
   Cost: an unattended run cannot file a park it has to ask about.
7. **The word is Sandbox for people, `practice` in storage.** Messages and documents say "sandbox park". The option
   token `practice`, the value `:practice`, `COUNT_AS=practice`, the registry note "Throwaway practice park; not company
   data." and every stored value stay as they are, so no data is rewritten. Gain: no contract or data change. Cost: two
   words for one thing, glossed where a user types the token.

## Rejected options

- **Asking after the play.** Gain: the player can decide knowing how the play went. Cost: a closed Terminal window or a
  forgotten answer leaves the park waiting, and the whole point is to stop that.
- **Guessing the choice from the park name or the registry.** Gain: no question. Cost: a new park has neither, and a
  wrong guess lands a company row that only a hand delete removes.
- **Renaming the stored value to `sandbox`.** Gain: one word. Cost: a data and contract change for a display word, and
  a rewrite of the registry note that other code matches exactly.

## Consequences

- `make auto-file` and `make autopilot-parks` are new commands, documented in `AGENTS.md` and `ARCHITECTURE.md`.
- The launcher text is pinned by `tests/test_makefile_play.py`.
- ADR 0038 and ADR 0050 are unchanged; the registry rows are written by `make register-parks` as before.
