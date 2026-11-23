# Spec: the launcher files each play, "sandbox" wording, and autopilot progress lines

**Bottom line.** This change has four parts.
1. The "OpenRCT2 Enterprise" launcher asks whether a play counts for the company or is sandbox play. After a clean capture it files the session by itself through a new `make auto-file`. It asks by name only about parks from older plays, and about a park already registered with the other choice.
2. The word "practice" becomes "sandbox" in live docs and printed messages; option values and stored values stay `practice`. The roadmap's future unlimited-money test park becomes "R&D Park".
3. `make autopilot-year` prints a line each game month, a warning after 60 seconds without events, and a finish summary with the source save, the game's profit and guest counts.
4. A new read-only `make autopilot-parks` prints the company parks as JSON for the Home App's Autopilot dropdown.

No plugin, contract, dbt model or stored value changes.

- Status: revised after review round 1, 2026-11-15. Slug `play-launcher-autofile`.
- Contract map: `docs/ai-dlc/contracts/play-launcher-autofile.md`. Findings: `docs/ai-dlc/ledger/play-launcher-autofile.md`.
- Related work: the safe-play slice of `docs/ai-dlc/roadmap/park-company.md` (ADR 0048, the launcher) and the autopilot-year slice (ADR 0049).
- Outcome measure: none (not a roadmap slice). The project owner's goal: "All I want is to be able to play by clicking that button."

## 1. Requirements (settled with the project owner on 2026-11-15)

- **R1 Launch question.** After the direnv checks pass and before the game opens, the launcher prints exactly:
  ```
  Where should this play count?
  1. Company — counts toward the company's results
  2. Sandbox — saved, but kept out of the company's results (a company park stays company)
  ```
  It reads `1` or `2` and asks again on any other answer. 1 maps to the choice `company`, 2 to `practice`.
- **R2 Automatic filing.**
  - Before `make play`, the launcher runs `make auto-file DATA_SET=company RECORD=yes`. That records the IDs of every session already converted or present in the raw captures, in the git-ignored file `local/auto-file/converted-before.json`.
  - After `make play DATA_SET=company` exits 0, it runs `make auto-file DATA_SET=company COUNT_AS=<company|practice>`.
  - After any other exit, it prints `This play was not filed. If the report above names a seq problem, do not file it; otherwise run: make auto-file DATA_SET=company COUNT_AS=<the choice>` with the real choice filled in. `make` reports every failing recipe as exit 2, so the capture's own 1, 2 and 130 cannot be told apart here (review 2026-11-15); after a refusal before the game opened, the rerun reports nothing waiting. Ctrl-C during play ends the Terminal shell itself, so nothing is printed then.
  - When the record step fails, the game is not opened, and the launcher prints `The game was not opened: noting the earlier recordings failed (see above). Nothing was played or filed.`
  - When no answer can be read at the question (end of input), it prints `No answer was read. Nothing was changed.` and exits 130.
  - The window's exit code is that of the last command run.
- **R3 This play's sessions** are the waiting sessions whose IDs are not in `converted-before.json`. A park with at least one such session is "this play's park". Each park is classified once, whatever other sessions it has. When the file is missing or unreadable, no park is this play's, so every unregistered park is asked (R4), and a line says why. A session from an earlier capture that stopped before converting is in the raw captures, so it is listed and later asked about as an earlier play's (whole-branch review, 2026-11-15). Known limit: a second launch before a failed filing is rerun replaces the file, so the rerun asks about that play's parks by name.
- **R4 Other waiting parks** that are not registered are asked about one by one, using the park name or, when it is missing, the ID:
  ```
  Park <name> (<id>) from an earlier play is waiting. Where should it count?
  1. Company
  2. Sandbox
  3. Don't file now
  ```
  Answer 3 files nothing (exit 2, "Nothing was changed") and prints the `make auto-file` line to rerun. Registered waiting parks keep their registration without a question.
- **R5 Conflict.** When one of this play's parks is already registered with the other choice, auto-file asks:
  ```
  Park <name> (<id>) is saved as <Company|Sandbox>, but this play was started as <Sandbox|Company>.
  1. File it as <its saved choice>
  2. Don't file now
  ```
  Answer 2 files nothing (exit 2) and prints the rerun line.
- **R6 Start year.** When a non-practice park is about to be registered and a company park is already registered, auto-file passes `START_YEAR`, the one accepted year, from `register_parks.next_start_year`. Every other start-year refusal is left to after-play, whose refusal text and rerun line are printed. The one exception is a company raw file holding a session never converted: `next_start_year` itself refuses it, so auto-file prints that refusal under its own prefix with exit 2, files nothing and keeps `converted-before.json` (review 2026-11-15). Examples: the park did not begin in game year 1; more than one new company park; an unconverted raw file.
- **R7 Shown before filing.** For each park about to be registered, one line is printed:
  `auto-file: park <name> (<id>) is new; registering it as <company park, start year <Y>|a sandbox park>.`
- **R8 No terminal.** When a question is needed and standard input is not a terminal, auto-file refuses with exit 2, "Nothing was changed", and the rerun line.
- **R9 Wording.**
  - "Practice park" becomes "sandbox park" in the live files listed in section 2.
  - Where a user types the option token, it stays `practice`, glossed once per place as "`practice` (shown as Sandbox)".
  - These are never changed:
    - `PRACTICE_NOTE` ("Throwaway practice park; not company data."), which is matched exactly at `registry_feed.py:82` and `site_company.py:156`;
    - code identifiers, option names and values, and test assertions on stored values;
    - accepted ADRs and past CHANGELOG entries (ADRs are superseded, not edited);
    - process records under `docs/ai-dlc/` other than the roadmap;
    - the meanings "best practice" and "practice-play".
- **R10 R&D Park.** In `docs/ai-dlc/roadmap/park-company.md` (lines 253, 263, 376 and 384 on `aad0aab`), the planned test park with unlimited money and every ride becomes "R&D Park". The agent sandbox keeps its name, and no other file changes for this requirement.
- **R11 Monthly line.** During the headless autopilot run, one line is printed when the first `park_snapshot` of a new game month lands:
  `autopilot: park <id> · <Month> <day>, year <Y> · <N> events · <m> min <s> s elapsed · about <k> min left`.
  - The estimate is (time since the first event ÷ game days done) × game days left of the planned run.
  - Until one full game day is done, the line ends `· estimating time left` instead.
- **R12 Stall warning.** After the first event, when 60 seconds pass with no event landing, this line is printed once per stall:
  `autopilot: no events for 60 s; the last game date seen was <Month> <day>, year <Y>. The run stops by itself at its time limit, <limit> min after it started.`
  The next landed event prints `autopilot: events are arriving again.`
- **R13 Finish summary.** The success report adds three lines just before the refurbish line (the one next step), which stays above the closing `autopilot-year:` line:
  - `Started from: <source file name> (game date <Month> <day>, year <Y>).`
  - `Profit: $<x> from <n> monthly statements (<Month> to <Month>, year <Y>), the game's total of all 14 statement lines, shown in dollars for display.` When the statements span two game years, both are named. With no statement, the line says `Profit: no monthly statement closed during this run.`
  - `Guests in the park: <a> at the start, <b> at the end.`

  The existing "To refurbish the park, load save/<dated>." line stays as the one next step.
- **R14 Profit definition.** Profit is the sum, over the run's `finance_month` events, of the 14 statement lines the plugin sends (`plugin/src/finance.ts:7-23`, each as `<type>_tenths`). This is the game's own total. It is computed in tenths and converted only for display.
- **R15 Dollar display.** Terminal messages may show game money in dollars. Nothing converted is stored. ADR 0052 records this exception to "Never break" rule 3.
- **R16 Park list.** `make autopilot-parks DATA_SET=company` prints one JSON object to standard output:
  `{"data_set": "company", "parks": [{"park_id", "park_name", "newest_backup": {"file", "modified_at"} | null, "source_problem": str | null, "needs_ready": bool}]}`.
  - It lists every registered company park that is not a practice park.
  - `newest_backup` is the newest archive copy, found as `autopilot_source` finds it, whether or not it is proven.
  - `source_problem` is null when `autopilot_source.find_source` proves a source; otherwise it holds that refusal's message.
  - `needs_ready` is true when the park has no landed autopilot session.
  - It writes nothing and takes no lock.

## 2. Placement plan

| New rule or piece | Owner | Reused or extended | Layer |
|---|---|---|---|
| Launch question, the record step, the tail after play | `launcher/play-company.command` (existing) | the existing direnv checks and the close prompt | launcher (zsh) |
| Recording converted IDs, classifying parks, the questions, the new-park lines, the start year, the call to after-play | new `src/openrct2_analytics/ingest/auto_file.py`, beside `after_play.py` | `play_status.read_status` (`after_play.py:83`); `register_parks.registered_parks` (`register_parks.py:74-97`); `after_play.main` (`after_play.py:185`) | ingest (Python) |
| The refusals that must run before any question | `after_play.py`: lines 75-84 of `_to_register` move into a public `check_can_start(data_set, project_dir) -> Status`, which `_to_register` calls (no behaviour change) | the existing refusals | ingest |
| Discarding typed input | `capture_session.py:247`: `_discard_typed_input` becomes public `discard_typed_input`; callers are renamed | existing function | ingest |
| The accepted next start year | `register_parks.py`: new public `next_start_year(feed, parquet_dir, raw_dir) -> int \| None`, holding the stale-raw check and `_floor` that `start_years` runs today (`register_parks.py:240-260`); `start_years` calls it, so the rule has one home. The file is 469 lines against the 500-line gate: if it would pass 500, the start-year functions move to a new `start_year.py` in the same ticket. | `_floor`, `_registered_company_parks` | ingest |
| Optional per-event and per-poll hooks | `bench_play.py`: `CountingLander(raw_dir, on_landed=None)`, called with the parsed dict only after a line has landed; `play(..., watch=None)` calls `watch.tick()` once per poll in `_wait_for_stop` | `CountingLander.land` (`bench_play.py:114-121`), `_wait_for_stop` (`:143-155`) | ingest; off by default |
| Monthly line, stall warning, time left | new `src/openrct2_analytics/ingest/autopilot_progress.py` | `say` (`capture_session.py:122-129`) | ingest |
| Profit, statement months, guests, `display_usd` | `autopilot_progress.py`: `summarize(events) -> RunSummary`, run on the raw events `autopilot_run.py` already reads after play (`autopilot_run.py:248`) | `_raw_events` | ingest |
| Wiring | `autopilot_run.py` (`:236-242`): passes `watch=`; `RunResult` gains `summary` | | ingest |
| Summary lines | `autopilot_report.py`: `ReportFacts` gains `source_file`, `source_date` and `summary`; `report()` (`:40-58`) prints R13 | | ingest |
| Park list JSON | new `src/openrct2_analytics/ingest/autopilot_parks.py` | `autopilot_source.find_source` and its newest-copy rule (`autopilot_source.py:75`, made public as `newest_copy`); `autopilot_year._archive_dir` (`:104`, made public as `archive_dir`); `managed_years.landed_autopilot_sessions` (`:152`); `registry_feed.latest_rows`; park names from `session_start` as `play_status` reads them | ingest |
| `auto-file` and `autopilot-parks` targets | `Makefile` (hotspot, one ticket) | the guard that refuses exported values, for `COUNT_AS` and `RECORD` | build |
| Printed messages, reworded (R9) | `register_parks.py` (messages and help), `after_play.py:88`, `site_company.py:168`, `autopilot_year.py:181`, `Makefile` help text | | ingest, build |
| Docs, reworded (R9, R10) | `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `docs/CONVENTIONS.md`, `docs/ai-dlc/roadmap/park-company.md` | | docs |
| Docs, new | `docs/adr/0051-launcher-files-each-play.md`, `docs/adr/0052-dollars-in-terminal-text.md`, a `CHANGELOG.md` entry, the `AGENTS.md` and `ARCHITECTURE.md` entries for the new commands | | docs |

Dependents that change in the same change:
- `tests/test_makefile_play.py:38-46`, which pins the launcher text.
- `tests/test_site_company.py:210`, which asserts `"practice park p2"`.
- Every caller of `_discard_typed_input`.
- The callers of `play`: `bench_run.py:125`, `rehearsal_chain.py:178`, `autopilot_run.py:236`, and their tests, which must pass unchanged.

No contract changes. No dependency is added.

## 3. Behaviour of `make auto-file`

The module is `python -m openrct2_analytics.ingest.auto_file --data-set company (--record | --count-as <company|practice>)`. Its seams are `ask` (default `input`), `file_with` (default `after_play.main`), `is_terminal` and `project_dir`.

1. **Record mode** (`--record`) writes the sorted session IDs of `session_start` in the converted Parquet and of the raw `events-*.jsonl` files, or an empty list, to `local/auto-file/converted-before.json`, replacing any earlier file. It exits 0.
2. **Refusals before anything else.**
   - These are refused: a data set other than `company`; neither or both of `--record` and `--count-as`; a `--count-as` value other than `company` or `practice`.
   - The Makefile refuses an exported `COUNT_AS` or `RECORD`, or one holding a dollar sign, as it does `PARKS`.
   - Then `after_play.check_can_start` runs: the rehearsal data set, a present landing lock, and a warehouse being built are each refused (exit 2) before any question.
3. **Read** the waiting sessions from the status that check returned, the registry with `registered_parks`, and `converted-before.json`. With nothing waiting, it prints `auto-file: nothing is waiting to be filed.` and exits 0.
4. **Classify each park once** (R3), then choose in `play_status` order:
   - a registered park keeps its registration, and R5 applies when it is one of this play's parks;
   - an unregistered park of this play takes `--count-as`;
   - any other unregistered park is asked (R4).

   `discard_typed_input` runs once before the first question. An invalid answer repeats the question. An end of input or Ctrl-C exits 130 and changes nothing.
5. **Start year.** If a non-practice park would be registered, take `register_parks.next_start_year`. A non-null value is passed on as `--start-year`.
6. **Show and file.** Print the R7 lines, then call `file_with(["--data-set", "company", "--parks", <PARKS>] + (["--start-year", Y] if Y else []))`. Return its exit code unchanged, so after-play's own refusal and rerun lines are what the player sees.
7. **After filing.** `converted-before.json` is removed only after exit 0. A failed filing keeps it, so the rerun line classifies the same parks the same way.
8. **Exit codes:** 0 filed or nothing waiting; 1 a step failed; 2 refused (including R8 and the "Don't file now" answers); 130 interrupted.

## 4. Behaviour of the autopilot progress lines

- **The watch.** `AutopilotProgress(park_id, planned_days, limit_seconds, say, clock=time.monotonic)` provides two calls, both under one lock:
  - `on_landed(event)` runs on the listener thread. It records `clock()` as the time of the last event, never `emitted_at`.
  - `tick()` runs on the main thread at each 0.2-second poll.
- **Typed reads.** `on_landed` reads `event_type`, `game_year`, `game_month`, `game_day` and `guests_in_park` only after checking their types. A missing or mistyped field is skipped, so the hook never raises on any landed line. A test feeds landed lines with missing fields and shows that landing continues.
- **Game date** comes from `park_snapshot` events (March is month 0). Days done counts the distinct dates seen. Days left is `planned_days` minus days done, never below 0.
- **Stall.** `tick()` compares `clock()` with the last event time. The warning starts only after the first event, because autopilot allows 300 seconds for startup (`autopilot_run.py:71`).
- **Totals.** `summarize(events)` runs after the run, on the raw events `autopilot_run.py` already reads. It returns:
  - the 14-line profit in tenths;
  - the statement count;
  - the first and last statement (year, month);
  - `guests_in_park` of the first and last `park_snapshot`.

  The summary rides in `RunResult` and then `ReportFacts`, before `report()` removes the work folder.
- **Display.** `display_usd(tenths: int) -> str` is the one display conversion. For example, `-1234` becomes `-$123.40` and `0` becomes `$0.00`.

## 5. Constraints (repo "Never break" rules that apply)

- **Rule 1, seq and required fields:** untouched. Progress reads events and never writes them.
- **Rule 2, raw append-only:** untouched. auto-file only runs after-play.
- **Rule 3, money:** profit stays in tenths in code and in `RunResult`. Dollars appear only in terminal text, through `display_usd` (ADR 0052).
- **Rule 5:** the launcher keeps the no-`/Users/`, no-`/home/`, no-`~` rule.
- **Rule 8:** no plugin change.
- **Data-set rule:** `DATA_SET`, `COUNT_AS`, `RECORD` and `PARKS` come only from the command line.
- **Engineering standards:** no catch-and-continue, one home per rule, files under 500 lines.

## 6. Out of scope

- No change to stored values, option names, the registry note, contracts, the plugin or dbt.
- No automatic publish or site build.
- No change to `make capture-data` or `make play`.
- The Home App panel, which lives in the project owner's vault, not this repo.
- Profit before the run's own statements, such as a full calendar year from the kept timeline.
- Closing out older finished records.

## 7. Test seams and golden paths

- **auto-file:** imitate `tests/test_after_play.py` fixtures (temp project, converted Parquet and registry rows). `file_with` is a recording fake, so no `make` runs. Cases:
  - nothing waiting;
  - this play only;
  - an older park asked;
  - one park in both an older and a new session (asked nothing, takes `--count-as`);
  - a conflict, answered 1 and answered 2;
  - "Don't file now";
  - a second company park given its start year;
  - the R7 lines;
  - a missing `converted-before.json`;
  - no terminal (R8);
  - Ctrl-C;
  - a held landing lock refused before any question;
  - the before-file kept after a failed filing and removed after success.
- **check_can_start:** the existing `tests/test_after_play.py` refusal tests pass unchanged.
- **next_start_year:** imitate `tests/test_register_parks_start_year.py`, and show that `start_years` gives the same answer.
- **Hooks off by default:** a `bench_play` test with a fake game shows `play` unchanged without `watch`. The bench, rehearsal and autopilot tests pass unchanged.
- **Progress:** feed `on_landed` and `tick` a fake monotonic clock. Cases:
  - month lines;
  - "estimating time left";
  - the time-left value;
  - no stall before the first event;
  - the stall at 60 seconds, once only;
  - the recovery line;
  - landed lines with missing fields.
- **summarize and display_usd:** cases:
  - statements in one year and across two years;
  - no statement;
  - guests;
  - negative and zero amounts.
- **Profit field list:** a test reads `plugin/src/finance.ts` and asserts that `EXPENDITURE_TYPES`, with `_tenths` added, equals the module's 14 fields.
- **Report:** imitate `tests/test_autopilot_year.py` for the new summary lines.
- **autopilot-parks:** imitate `tests/test_play_status.py`, where standard output holds only the JSON. Cases:
  - no backup;
  - a proven source;
  - an unproven newest backup (`newest_backup` set, `source_problem` set);
  - a practice park left out;
  - `needs_ready` true, then false.
- **Launcher:** update `tests/test_makefile_play.py` for the question text, the mapping from answer to choice, the record step, the tail after play for exits 0, 1, 2 and 130, and the no-path rule.
- **Makefile:** `tests/test_makefile_guards.py` for exported `COUNT_AS` and `RECORD`.
- **Wording:** `tests/test_site_company.py:210` is updated to the new message. A grep check in the ticket shows that no live file listed in section 2 still says "practice park", apart from the kept tokens.
- **Golden files:** new modules imitate `after_play.py` (argparse, exit-code map, signal handling) and `play_status.py` (JSON-only standard output).

## 8. Verify by

- `make check` passes in the worktree.
- `python -m openrct2_analytics.ingest.auto_file` runs on a temp project with a scripted answer and the real after-play. It registers the waiting park as practice and builds that project's dev warehouse. This is done by hand with the module's `project_dir` argument from Python; it is not part of the gate.
- `python -m openrct2_analytics.ingest.autopilot_parks --data-set company` prints valid JSON on the same project.
- Two checks need the project owner's Mac (macOS, OpenRCT2 0.5.6, the company data set). They are recorded as `open: awaiting project owner` rows, not claimed as passed:
  - the opt-in real-game autopilot test;
  - one real launcher play.

## 9. Definition of done

Done means all of these hold:
- every requirement R1-R16 passes its test;
- `make check` exits clean;
- nothing outside the placement plan changed;
- the docs listed in section 2 and ADRs 0051 and 0052 describe the new behaviour in the same change;
- the checks that need the real game or the launcher are named as owner checks, with their conditions.
