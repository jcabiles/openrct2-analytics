# ADR 0055: one play that opened several new parks is filed by one `make auto-file` run

- Date: 2026-11-16.
- Status: Proposed with the spec `docs/ai-dlc/specs/file-several-parks.md`; it takes effect when the branch that
  builds it merges. It amends ADR 0050 (`docs/adr/0050-company-start-year-from-the-register-command.md`) decisions 6
  and 7 and ADR 0051 (`docs/adr/0051-launcher-files-each-play.md`) decisions 2, 3 and 4, and edits neither record.
  Decisions of those records not named here stand.

## Bottom line

A play that starts two or more new parks is now filed by one `make auto-file` run. The command asks about each new
park, checks everything for all of them, registers them one at a time in the order they were opened, and runs the
after-play steps once. If a later step fails, the message names the parks already filed and the exact command to
file the rest, and a rerun does not ask again or register a park twice. `make register-parks` still registers at most
one company park per run and `make after-play` still refuses several company parks. No data contract, dbt model,
plugin file, command line or Makefile target changes.

## Context

On 2026-11-15 a play opened two new parks and `make auto-file` did not file it: it handed both parks to one
after-play run, and after-play refuses several company parks because one `START_YEAR` cannot serve two of them (ADR
0050 decision 6). A fix that only lets the chain run would also
leave two new gaps: a failure after the first registration would still say that nothing was changed although a registry
row had landed, and a rerun would ask the same questions again.

## Decision

1. **Each new park is asked, and the answers must match the order the parks were opened (amends ADR 0051 decision
   2).** A new park is a waiting, unregistered park with a session missing from `converted-before.json` and no stored
   answer (decision 5). With one new park nothing changes: it takes `COUNT_AS` without a question. With two or more,
   each is asked, whatever `COUNT_AS` is: `Park <name> (<id>), <n> game days played, is new in this play. Which is
   it?` with the options "Opened first", "Opened second" and so on, then "Sandbox". The game days are the distinct
   game dates in the park's converted `park_snapshot` rows. Every answer is collected before anything is written. A
   park from an earlier play keeps its question from ADR 0051 (Company, Sandbox, Don't file now), and a registered
   park keeps its registration. Each "Opened n" must equal the park's place among the asked parks by its first
   recorded `session_start` (earliest `emitted_at`, ties by park ID), Sandbox parks counted; a wrong or repeated
   number is refused (exit 2, "Nothing was changed.") with the rerun line. Gain: the order that sets each company start
   year is confirmed by the player and checked against the data, so a swapped pair cannot give a park the wrong year.
   Cost: one question per new park when a play opens several.
2. **The chain registers company parks itself, one at a time, before one after-play call (amends ADR 0051 decision 3
   and ADR 0050 decision 6).** When two or more company parks are to be registered, `make auto-file` first plans every
   company park's start year with one pure function, treating each earlier park as registered, so park n gets the year
   `next_start_year` would give after parks 1 to n-1. It then runs every refusal check for all parks before the first
   write: the registry feed check, a park registered as another data set, a staged delivery left over, a company raw
   file holding a session never converted (applied to park 2 and later even when the registry holds no company park
   yet), a typed-year park whose first session is not in game year 1, the number of free delivery names for the parks
   to register, and a waiting list that changed while the player was answering (added or removed parks). It then
   prints one "is new" line per park with its own year, registers the parks one at a time through the code of
   `make register-parks` (one delivery file each, each year checked again under the landing lock), and runs
   after-play once with every waiting park listed and no `START_YEAR`; after-play's register step then finds nothing
   to register. The first company park of the company takes no year (2000) and a Sandbox park takes none. One company
   park with any number of Sandbox parks keeps ADR 0051's single after-play call. Gain: one writer of registry rows
   and one year rule, with every refusal that can be known before the first write given before it. Cost: the plan and
   the check run in auto-file and read the registry and Parquet once more than before.
3. **One register run still takes at most one non-sandbox park, and after-play keeps its refusal (amends ADR 0050
   decision 6).** `make register-parks` and `make after-play` keep their rule and their texts. "Register one with
   `make register-parks PARKS=...` first" is no longer the only way to file a play of several company parks, because
   `make auto-file` chains the runs. Gain: the commands the player types by hand stay as they were. Cost: the same
   rule lives in two places, the command that refuses and the chain that avoids it.
4. **After the first registration of an auto-file run, a refusal or failure leaves the earlier rows written and exits 1
   (amends ADR 0050 decision 7).** Exit 2 keeps meaning that nothing changed, so a refusal, a held landing lock, a failed
   delivery check, an input or output error or after-play's own exit 2 after a registration landed is reported as exit 1,
   and an interrupt as 130. Auto-file learns what landed by reading the registry again, so it also counts a delivery
   renamed into place just before an interrupt and parks that after-play registered itself. The run prints the failure,
   `auto-file: already registered by this run: park <name> (<id>) as <how>[; ...].` and
   `To file the rest, run: make auto-file DATA_SET=company COUNT_AS=<x>` with the note to run it from the Terminal
   window, not the launcher, which starts a new play. After an after-play failure its own line stands and auto-file adds
   one line saying that after-play stopped. The phrase "Nothing was changed" is printed only before the first
   registration and never after one: after-play gains an optional argument that drops it from its refusal lines when
   auto-file says a registration landed, and its output at the default is unchanged. `make register-parks` keeps
   ADR 0050 decision 7: its every refusal leaves the folder tree unchanged. Gain: the player is never told a false
   "nothing changed" and knows the command that finishes the filing. Cost: a failed filing has two exit codes (2 before
   the first registration, 1 after), and the message has to be kept true when after-play gains a refusal.
5. **The stored answers live beside the record file and leave with it (amends ADR 0051 decision 4).** When any per-park
   question was asked, the answers of the run (park ID to `company` or `practice`; answers to the earlier-play,
   conflict and several-new-park questions, never a `COUNT_AS` choice or a kept registration) are written to the git-ignored `local/auto-file/answers.json` through a temporary file
   and a rename, just before the first registration, or just before the after-play call on the single-call path. It is
   removed with `converted-before.json` after exit 0, on the "nothing is waiting" path and by `--record`. A rerun gives
   a waiting park its stored answer with no question, and a registered park whose stored answer equals its
   registration gets no conflict question, which is what a Sandbox answer needs under `COUNT_AS=company`. A run
   that ends with no registration landed removes the file, so its rerun asks again; one that landed a park keeps it.
   An unreadable file is ignored with the line `auto-file: answers.json could not be read; asking again.` and the
   unregistered parks of this play are then asked about with the earlier-play question. A registered
   park keeps its year and gets no second row; an unregistered park gets the year `next_start_year` gives at the
   rerun, which equals the planned year when no data changed in between. A launcher run between the failure and the
   rerun runs `--record`, which removes the answers, and the park still waiting is then asked about as an earlier
   play's. Gain: a rerun asks nothing twice and files only what is left. Cost: one more local file, which is not a data
   contract and lives only between a failed filing and its successful rerun.

## Rejected options

- **A per-park year in `PARKS` or letting after-play register several company parks.** Gain: one registration call.
  Cost: ADR 0050 already rejected it, because two company parks could then share a year and the parser grows.
- **Asking only for the order and reading Sandbox from `COUNT_AS`.** Gain: a shorter question. Cost: with two new parks
  one `COUNT_AS` cannot tell which is the throwaway, and a wrong guess lands a company row that only a hand delete
  removes (ADR 0033).
- **Counting the registered parks in a loop to know what landed.** Gain: no second registry read. Cost: it misses a
  delivery renamed before an interrupt and parks after-play registered itself.

## Consequences

- `AGENTS.md`, `ARCHITECTURE.md`, `README.md` and `docs/CONVENTIONS.md` describe the chain and the new module split:
  `start_year_plan.py` in `domain/` holds the pure year plan, and `start_year.py` and `several_parks.py` in `ingest/`
  hold the year reads, the questions and the chain.
- A mistyped year that landed is still fixed only by `make delete-company-data` before go-live (ADR 0050 decision 8).
- Park rows landed by a failed run stay in the registry until the rerun files the rest; a delete removes them.
- A park with an earlier unfiled session is ranked by that older session (decision 1), so a truthful answer about this
  play can be refused; whether to rank by this play's session instead is open: awaiting project owner.
- The real-play check, one filing of a play that opened two new parks on the project owner's Mac (macOS, OpenRCT2
  0.5.6, the company data set), is not run by agents: open: awaiting project owner.
- An interrupt inside an after-play step is reported as that step's failure (exit 1, plus the filed-parks lines), as
  `after_play.py` already maps every failed step to 1; only an interrupt of auto-file itself exits 130.
- The autopilot year rule (`autopilot_year.py`) reads registrations through `managed_years.company_registrations`, which
  skips a registry row whose data set is not `company`; `make register-parks` writes only `company`, so only a
  hand-written row of another data set is ignored, and the dbt model of park years still maps every row.
