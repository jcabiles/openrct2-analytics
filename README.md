# openrct2-analytics

Every number on the project's site traces back to an event in a theme park game, and each step of that trail is checked.

- **Site:** https://jcabiles.github.io/openrct2-analytics/
- **How the AI agents worked:** Claude agents plan and write most of the code, OpenAI's GPT-6 Luna writes some small tickets, and models from all three vendors review the work. Independent review and the `make check` gate caught real defects before they merged; five are written up in [docs/review-catches.md](docs/review-catches.md).
- **A data highlight:** one month's operating profit is traced from the page back to the game's own ledger lines in [docs/showcase/trace-operating-profit.md](docs/showcase/trace-operating-profit.md).
- **Status:** work in progress. The site shows rehearsal (practice) data, not company play yet.

A portfolio analytics stack for a theme park game run as a business: an OpenRCT2
plugin streams game events to a Python + dbt + DuckDB warehouse, checked
against data contracts along the way. The game is played as a **Theme Park
Enterprise**, the project's name for one company that runs several parks on
one shared calendar and reports them as a single business.

## Play it yourself

Play OpenRCT2 on your Mac as one theme park company: open parks one at a time on a shared calendar, and
watch the company grow on a dashboard on your own computer. Setup takes about an hour of copying commands
into Terminal; no coding.

1. Set up your Mac: [Install by hand](docs/showcase/story/install-by-hand.md)
2. Play your first park: [How the game works](docs/showcase/story/how-the-game-works.md)
3. If something goes wrong: [Fix a problem](docs/showcase/story/fix-a-problem.md)

The same guide is the `/guide` page of the project's site. Players can stop here: the rest of this README is for developers.

## How to run it

You can capture your own OpenRCT2 play, measure the benchmark, and turn the
capture into checked tables from a clone of this repo.

**Prerequisites.** OpenRCT2 0.5.6 (the game build in use), [uv](https://docs.astral.sh/uv/) (it installs
the pinned Python 3.12 and the locked packages), and Node 24 (the version CI uses; it builds the plugin). Run `git init` first if
the folder is not a Git clone, then `make setup`. It creates the Python environment, installs the Node packages,
activates the repo's Git hook and checks the environment with `make doctor`. It is safe to re-run.

**Capture a session.** Every capture and pipeline command names the data set it works on, on the `make` command line:
`DATA_SET=rehearsal` or `DATA_SET=company`. A command with no data set refuses and changes nothing, and an exported
`DATA_SET` is refused too. The numbered steps below use `rehearsal`. A throwaway sandbox park uses `company`
instead (see "Practice session" below): that keeps it out of the rehearsal warehouse the v1 site reads, and
`make delete-company-data` removes it before the clean start.

1. Quit OpenRCT2 if it is running, then run `make capture-data DATA_SET=rehearsal` in Terminal.
2. The command builds the plugin, copies it into your OpenRCT2 `plugin` folder and starts a listener on
   `127.0.0.1:8765` (the only address the plugin sends to). Wait for the line that says to open OpenRCT2 now.
3. Open OpenRCT2 the usual way and play. The command prints "game seen" when it notices the game and "events
   arriving" when the first event lands. Nothing typed in the Terminal is read, so you do not need to touch it.
4. Quit the game. The command removes the plugin, converts the capture to Parquet (a columnar file format) under
   `data/rehearsal/parquet/` and prints a report.

**The report** covers this run: events landed by type; for each session, its full `session_id` and its
park, whether `session_start.headless` is false (a real windowed game), the first and last `seq` and whether the `seq`
audit passed, and the most lines the plugin reports dropping; the plugin's worst and mean tick cost against the limits in
`docs/adr/0005-plugin-per-tick-budget.md` (10 ms worst, 1.25 ms mean); the monthly statements received; and that the
plugin file was removed. It also shows the malformed-line count for the whole raw folder, not just this run, and warns
about `seq` problems in earlier runs without changing the exit code.

**What it refuses.** The command refuses, prints "Nothing was changed." and exits 2 when the OpenRCT2 folder or its
`plugin` folder is missing (open the game once so it creates them); when a setting such as `OPENRCT2_LISTENER_PORT` is
invalid; when the game is running or cannot be checked, including when it is opened while the plugin is still
building; when the listener's port is busy; when the plugin's file name, or its temporary name
`.openrct2-analytics.js.capture-tmp`, already holds a file this command did not install (the message names the file;
move it out of the folder to continue); when an install record from an earlier run names a different OpenRCT2 folder
(the message names it); or when another plugin file in the folder already registers `openrct2-analytics`. A failed
plugin build exits 2 too.

**Exit codes.**

| Code | Meaning |
|---|---|
| 0 | At least one event landed and every session of this run passed the `seq` audit. |
| 1 | A capture problem: no event landed, a `seq` violation in this run, the converter failed, the plugin could not be removed, the game opened by `make play` did not start, or a backup copy failed. The raw capture is kept. |
| 2 | Refused before any change. |
| 130 | Stopped by Ctrl-C, a closed Terminal or SIGTERM. |

Through `make`, any failure shows as make's own non-zero code; run the Python command directly to see these codes.

**Stopping early.** Ctrl-C or closing the Terminal removes the plugin and keeps the raw capture without converting; run
`make convert DATA_SET=rehearsal` later to convert it. If the game is still connected at that moment, the last few lines of the session
may be lost; quitting the game normally loses nothing. If a run is killed outright, the next `make capture-data DATA_SET=rehearsal` removes
the plugin file it left behind. The command never overwrites or deletes a plugin file it did not install, and it never
changes your own saves; a company run adds dated backup copies beside them (below).

**Play the company park from the Dock.** `make launcher` builds the "OpenRCT2 Enterprise" app in
`~/Applications`; double-click it to record, file and review a play. The player guide explains how a play works:
[How the game works](docs/showcase/story/how-the-game-works.md) covers the app's questions, how a play is filed, which save to load to continue a park, how a second park joins and autopilot. `AGENTS.md` (`make launcher`,
`make play`) keeps the full behaviour. Recovery from an error is in [Fix a problem](docs/showcase/story/fix-a-problem.md).

**Practice session (one throwaway park, company data set).** Do these steps in this order.

1. Quit OpenRCT2 if it is running.
2. Run `make capture-data DATA_SET=company` in Terminal. Wait for the line that says to open OpenRCT2 now.
3. In OpenRCT2, start a new scenario.
4. Save under a new name. Never save over a save from another park or scenario.
5. Build at least one ride and one single-item stall (a stall that sells one item, such as a burger bar). Play until
   guests have boarded the ride and left the park.
6. During play, do one plain Save Game (over this session's own save), one Save Game As, and let one autosave happen. The review then sees which kinds
   of save the capture pairs with a file.
7. Do not save and reload around the first day of a game month.
8. Play past the first day of a game month. After it begins, let the game run for about five seconds (the plugin
   spreads each day's ride snapshots over the ticks that follow the day's start), then pause, read the stall's total
   customers in its window, write the first `stall_total_customers` row in the notes file (format under "Run the rest
   of the pipeline"), and unpause. After the next month begins, wait the same five seconds, pause, read it again and
   write the second row. The final save comes right after this second reading, still paused (step 11). For example, in a scenario that starts in March: first
   reading right after 1 April begins, second reading right after 1 May begins, final save right after the second
   reading. This session keeps a second monthly statement; see "What to expect" below.
9. Stay paused after the second reading.
10. Write the ride's total profit and the cash in the notes file, with the game date shown on the screen.
11. Make the final save with Save Game As under a new name, while still paused. Waiting for an autosave also works.
12. Quit the game without unpausing it.
13. Keep the capture's closing report, including its "Save files" section, and paste that section into the review.

The steps fix the order because the warehouse keeps only what happened before a session's last save: a value written
after that save has no kept row to compare it with, so both stall readings, the ride's total profit and the cash are
read before the final save. At least one monthly statement must be kept: with none before the last save,
`make publish` fails. The exact cash test compares consecutive kept statements, so the first kept statement cannot
fail it; the two-reading procedure always keeps a second one.

**Run the rest of the pipeline.** `make capture-data` converts but does not run the contract check or dbt. Run
`make pipeline DATA_SET=rehearsal` afterwards: it runs `make convert`, then `make contracts`, then `make transform`
(which builds the development warehouse, `warehouse/dev/dev.duckdb`), and stops at the
first step that fails. `make convert` reads every capture in the data set's raw folder, so once any session there has a `seq`
problem, `make pipeline` stops at convert on every later run too; the Parquet is still written, and the capture
report's warning names the session. `make check` is the repo's full test gate; it needs no game, builds its warehouse in a temporary folder and leaves none behind.

After a practice session (the park is registered as a sandbox park; `PRACTICE=yes` is the option that marks it), run these four commands in this order:

```
make register-parks DATA_SET=company PRACTICE=yes
make pipeline DATA_SET=company
make publish DATA_SET=company
make results DATA_SET=company
```

`make register-parks` goes first because `make contracts` and `make transform` both run the registry feed check,
which fails on an empty registry folder. It writes the registry row (the file that tells the warehouse which data set
a park belongs to) for each captured park the registry does not list yet, and needs no typed IDs.
`make results` prints the park days, months, rides and stalls, sessions, cleaning rule counts and the plugin's tick
cost; a table that was not built prints "not built". Add `PUBLISHED=yes` to read the published file instead of the
development warehouse.

**The notes file.** Keep the values from steps 8 and 10 in `data/company/notes/practice-notes.csv`. Everything under
`data/company/` stays out of Git. The file is not a dbt source and has no contract; the review compares it with the
warehouse by query. Write the month as the game shows it (`March` to `October`), not as a number. The two
`stall_total_customers` readings give the stall's customers for the month (the second reading minus the first), which
the review compares with the warehouse's stall customer count. That count is purchases, not unique customers: a guest
who buys twice counts twice. The plugin interface exposes only `ScRide.totalCustomers` and `ScRide.totalProfit` for a
stall, and the game source appears to raise the count once per purchase; an in-game check of a stall's count is still
open. The notes file once held a `stall_items_sold` row; it was replaced because the plugin has no items-sold field.

```csv
item,name,value,unit,game_year,game_month_name,game_day
ride_total_profit,Merry-Go-Round 1,412.50,usd,1,May,1
stall_total_customers,Burger Bar 1,46,customers,1,April,1
stall_total_customers,Burger Bar 1,57,customers,1,May,1
cash,,10234.00,usd,1,May,1
```

**What to expect.**

- The reading and the kept ride snapshot are taken moments apart, so they can differ by the purchases made in between.
- The two-reading procedure always keeps a second monthly statement. On a capture made before the month-start cash
  fix (plugin 0.6.0) the exact cash test (`assert_park_month_cash_change_reconciles_exactly`) can stop the pipeline;
  captures made with plugin 0.6.0 or later are expected to pass it (the 2026-10-21 two-park rehearsal passed it on 69 statements), and the 2026-10-19 practice run passed it on 5 monthly
  statements. When it stops, `make transform` exits non-zero naming that test, and the models after it are not built.
  `make publish` then fails at its dbt step and leaves the published file as it was. `make results` still prints,
  listing those tables as "not built".
- With no monthly statement before the last save, `make publish` fails with
  `publish failed: empty: model obt_company_month expected 1 rows and actual 0`, and `make results` shows the month
  tables built but empty.
- With no ride, no single-item stall, or no guest who boarded and left, `make publish` fails on the row floor of the
  model that stayed empty: `stg_guest_left`, `stg_guest_boarded`, `fct_ride_day`, `dim_ride` or `dim_item`.
- If `make convert` (the first step of `make pipeline`) stops on the `seq` audit, because a session has a gap, a repeat
  or a first `seq` other than 1, run `make delete-company-data` (it prints a plan and the exact `CONFIRM` phrase to
  type), then capture again.

**Publish the warehouse.** `make publish DATA_SET=rehearsal` builds that data set's warehouse into a candidate file under
`warehouse/candidate/`, checks it (the contracts, the `seq` audit, no views, the expected row counts, and every park
registered for the data set by the park registry feed in `data/<set>/registry/v1/`), makes it read-only and swaps it in as
`warehouse/rehearsal.duckdb`. Readers open that file read-only. The file it replaces is kept for one step back:
`make rollback DATA_SET=rehearsal` makes it the published file again. A publish that fails a check before the swap prints one line,
`publish failed: <reason>: <detail>` or `publish refused: <reason>: <detail>`, and leaves the published file as it was; a
park missing from the registry fails as `unregistered-park`, and a company park is registered by
`make register-parks` (ADR 0038). A publish killed outright leaves a lock file that the next publish names; `ARCHITECTURE.md`,
"Environments and publishing", has the steps to remove it.

**Measure the benchmark.** `make bench` builds the plugin and runs three
35-day headless measurements on copies of the benchmark fixture; it takes
about 25 minutes. It needs the benchmark park (`OPENRCT2_BENCH_PARK`), the
RollerCoaster Tycoon 2 folder (`OPENRCT2_GAME_PATH`) and the OpenRCT2 executable
(`OPENRCT2_BINARY`), but none has to be exported: each comes from an exported value,
else the git-ignored `local/game-settings.env`, else a default (the macOS app location;
the `game_path` in the game's own `config.ini`; the park has none). `AGENTS.md`, "Game settings", has the
file format. `OPENRCT2_USER_DIR` is optional; `OPENRCT2_BENCH_DIR` optionally
chooses its work folder. The park must be the benchmark park (SHA-1 prefix
`a65dba74`) or the command refuses. It also refuses when `OPENRCT2_BENCH_DIR`
is the player's OpenRCT2 folder or inside it (or the reverse), and when
`--any-park` is combined with `--sample`. It refuses before writing when its
safety checks fail and writes the verdict in that work folder. `make bench-sample`
uses the same settings to rebuild `data/sample/rehearsal/` from three chained
36-callback sessions; allow an estimated 25 minutes. Neither command runs in
CI or changes the fixture or the player's OpenRCT2 folder.

**Where the files go.** The OpenRCT2 folder defaults to `~/Library/Application Support/OpenRCT2` on macOS,
`$XDG_CONFIG_HOME/OpenRCT2` (else `~/.config/OpenRCT2`) on Linux and `%USERPROFILE%\Documents\OpenRCT2` on Windows.
Set `OPENRCT2_USER_DIR` to use another folder. Raw events land in `data/<set>/raw/`, Parquet in `data/<set>/parquet/` and the
install record in `data/capture/` (`OPENRCT2_CAPTURE_DIR`). The park registry feed, which the rehearsal capture command delivers for the rehearsal data set and `make register-parks` delivers for company, sits in `data/<set>/registry/v1/`. None of these are committed.

`make delete-company-data` previews company deletion; its exact `CONFIRM` phrase archives
originals before changing them. Archives live under `OPENRCT2_STATE_DIR/archive`, outside
the repo. `OPENRCT2_STATE_DIR` defaults to the platform application-data folder for
`openrct2-analytics`: `~/Library/Application Support/openrct2-analytics` on macOS,
`$XDG_DATA_HOME/openrct2-analytics` (or `~/.local/share/openrct2-analytics`) on Linux,
and `%LOCALAPPDATA%/openrct2-analytics` on Windows. After go-live, only rebuildable
files can be removed. See ADR 0033 and ARCHITECTURE.md.

**Platform status.** macOS is tested with the real game (`docs/FINDINGS.md`, "Pipeline skeleton, part 3"). Windows and Linux use OpenRCT2's standard folders above and
are untested.

**Options.** Run the command directly (`uv run python -m openrct2_analytics.ingest.capture`) to pass options.
`--game-process NAME` sets the game's process name when it differs from the default (`OpenRCT2` on macOS, `openrct2` on
Linux, `openrct2.exe` on Windows). `--game-check-command` (one shell-quoted string), `--port`, `--plugin-file` and
`--poll-seconds` exist for the tests; `--port` moves the listener away from the one address the real plugin reaches.

Not affiliated with OpenRCT2 or the RollerCoaster Tycoon owners.
