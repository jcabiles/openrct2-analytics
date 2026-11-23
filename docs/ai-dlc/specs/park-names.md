# Spec: name parks by name, not only by ID

**Bottom line.** Every place the player is shown a park in the four surfaces the roadmap names (the dashboard banner,
the launcher's questions and lists, the delete preview and the autopilot list) shows it as
`<park name> (first played <Mon D>)`, for example `Bumbly Bazaar (first played Nov 15)`. When two parks share a name
and a first-played day, the time of first play is shown instead: `Bumbly Bazaar (Nov 15, 3:42 pm)`. One new module,
`src/openrct2_analytics/ingest/park_label.py`, owns the one rule for which name, which "first played" value and
which label a park gets; the four local formatters that print `<name> (<ID>)` today are deleted. "First played" is
a wall-clock time: the plugin's `emitted_at` of the park's earliest `session_start`, shown in the local time zone of
the Mac that prints it. Typed confirmations (`delete company park <id>`, the autopilot `READY` sentence) and the
commands the player copies keep the park ID, and the delete preview keeps the ID beside the new label. No data
contract, dbt model, export or Makefile line changes. Six tickets: a helper-first refactor, four surface tickets and
the doc lines.

Source names used below:
- "The roadmap" is the item "Name parks by name, not only by ID" in `docs/ai-dlc/roadmap/park-company.md` on
  `develop` at `0e0c3261`, lines 262-266, quoted verbatim in the Goal section. The base branch's copy of that file
  predates the item.
- "The map" is the contract map, `docs/ai-dlc/contracts/park-names.md`, written on `develop` without git access; the
  claims this spec relies on were checked against the code on this branch (section 11).
- "The code" is the code on branch `feat/park-names`, created from `origin/feat/say-the-park` at `2db7e558` (the base
  is chosen because "Say the park and its company year" edits the same filing lines; section 12).
- "The preflight" is the run authorization of 2026-11-19: "spec + build (auto-build; pass/fail settled 2026-11-18,
  roadmap :263)", and "any void condition (unresolved reviewer conflict, CONTRACT-DEFECT, open ledger row, accepted
  blocker or major after two fix rounds, anything needing the owner) parks that slice."
- Invariant 3 is "Never break" rule 3 in `AGENTS.md`: "every metric names its unit and its clock (game day, company
  date, or wall-clock hour)."

## Goal (roadmap, verbatim)

```
- [ ] **Name parks by name, not only by ID** (added 2026-11-17 by the project owner) — problem: the dashboard banner and the delete command name a park only by its ID (`k1794804620546-wenssk`), so three parks named Bumbly Bazaar cannot be told apart without a query. To settle in ideation: what tells same-named parks apart (first played date, game days played, last save file name), and every place a park ID is shown to the player (banner, launcher questions, delete preview, autopilot list). · outcome-link: outcome (b) · verify: agent ·
      pass/fail (settled with the project owner, 2026-11-18): every place a park is shown to the player (the dashboard banner, the launcher's questions, the delete preview and the autopilot list) names it as `<park name> (first played <Mon D>)`, for example `Bumbly Bazaar (first played Nov 15)`, where the date is the company-local date of the park's earliest `session_start`; when two parks share a name and a first-played date, the time of first play is added (`Bumbly Bazaar (Nov 15, 3:42 pm)`); the park ID stays in the delete preview and in typed confirmations; tests cover three same-named parks; `make check` passes.
      riskiest-assumption: set when it is specified · cheapest-test: set when it is specified · assumption-status: untested
      outcome-measure: outcome (b), parks named only by ID in the next novice test
      touches: settled in its spec
```

- **Goal (the problem):** the dashboard banner and the delete command name a park only by its ID, so three parks
  named Bumbly Bazaar cannot be told apart without a query.
- **Pass/fail (settled 2026-11-18):** the `pass/fail` line above, built exactly; requirements PN-R1 to PN-R14 below
  break it into checks.
- **Work check:** `verify: agent`; the agent check is the tests named below and `make check` passing.
- **Outcome measure:** outcome (b), parks named only by ID in the next novice test (read by "Re-run the blind novice
  test", not by this slice).
- **Riskiest assumption, set here as the roadmap asks:** a first-played time can be read for every park the four
  surfaces show, including a park whose recording was never converted. Cheapest test: PN-R3's raw-only test.
  Status: untested until PN-T1 runs.

## 1. Requirements

Each requirement names its source. Acceptance criteria are tagged `check:` (a command or named test that proves it)
or `judgment:` (what a reviewer must look at).

### 1.1 The one rule (helper module `park_label.py`)

**PN-R1. The label text.** For a park with a name and a known first-played time, the label is
`<name> (first played <Mon D>)`. `<Mon>` is the English three-letter month (`Jan` ... `Dec`) from a fixed table,
not from the system locale; `<D>` is the day without a leading zero. Source: roadmap pass/fail.
- `check:` `tests/test_park_label.py::test_label_names_the_first_played_day` asserts
  `Bumbly Bazaar (first played Nov 15)` for a park first played 2026-11-15 local time, and `Nov 5` (no leading zero)
  for the 5th.
- `check:` `tests/test_park_label.py::test_every_month_has_its_english_name` asserts all twelve names for a park
  first played on the 1st of each month; it runs everywhere.
- `check:` `tests/test_park_label.py::test_month_ignores_the_locale` calls `locale.setlocale(locale.LC_TIME, ...)`
  with the first installed of `de_DE.UTF-8`, `fr_FR.UTF-8` and `es_ES.UTF-8`, restores the old value in a `finally`,
  and asserts `Dec` for a December date (those locales print `Dez`, `déc.` and `dic`). It is skipped where none is
  installed, and the builder records it red against a plant that uses `strftime("%b")`.

**PN-R2. "First played" is one value with one clock.** A park's first-played time is the `emitted_at` of its
earliest `session_start` (ties by `session_id`), taken over the converted `session_start.parquet` and the raw
`events-*.jsonl` files of the data set together. It is a wall-clock time (invariant 3): the plugin's producer clock,
stored in UTC (`contracts/envelope.odcs.yaml`, `emitted_at`: "Producer wall-clock time, UTC"), converted to the local
time zone of the machine that prints the label, converting each instant on its own (PN-R7). The day shown is the
local calendar day of that instant. Source:
roadmap ("the company-local date of the park's earliest `session_start`"; its example time `3:42 pm`); the reading
of "company-local" is choice C1 in section 13.
- `check:` `tests/test_park_label.py::test_day_is_the_local_day_not_the_utc_day`: a `session_start` at
  `2026-11-16T02:10:00Z` with the zone fixed at UTC-8 gives `first played Nov 15`.
- `check:` `tests/test_park_label.py::test_earliest_session_start_wins` plants two converted sessions and one raw
  session of one park, the raw one earliest, and gets the raw one's day.
- `judgment:` the helper's docstring names the clock ("wall-clock, plugin `emitted_at`, local time zone") and the
  reviewer confirms no other clock (game date, company date, file time) is read for it.

**PN-R3. Raw-only parks get a first-played time.** A park whose sessions were never converted takes its
first-played time and name from its raw `session_start` lines. To do this, the raw reader in `managed_years.py`
(`RawFile`, `RawSession`, `raw_session_index`) also keeps each `session_start` line's `emitted_at` per
(session, park), parsed as an ISO 8601 time, for every `session_start` line whose `park_id` is a string, whether or
not it carries a name (today the line is dropped when it has no name, `managed_years.py:98`). A value that does not
parse, is not a string, or carries no UTC offset (a naive time cannot be compared with the aware times of the
converted files) gives that session no time, and the line still counts as read as today. Raw starts are ordered like
the converted ones, with one added rule: a start with no time sorts after every start with a time. For the name
(latest wins) ties between starts with no time go to the greater `session_id`; for first played, a start with no
time is never the first-played time, and ties between timed starts go to the smaller `session_id`. Source: roadmap
("every place a park is shown", which includes the unfiled list of parks never converted); the map's open question
"first-played source for raw-only parks".
- `check:` `tests/test_park_label.py::test_raw_only_park_gets_its_first_played_day`.
- `check:` `tests/test_managed_years_raw.py::test_raw_index_keeps_session_start_time`,
  `::test_nameless_session_start_keeps_its_time`, `::test_unparsable_emitted_at_gives_no_time` and
  `::test_emitted_at_without_offset_gives_no_time` (the last two assert `has_unreadable_line` is unchanged by them).
- `check:` `tests/test_park_label.py::test_untimed_raw_start_sorts_after_timed_ones` and
  `::test_untimed_raw_starts_tie_by_session_id_descending`.

**PN-R4. One name rule.** A park's name is the `park_name` of its latest converted `session_start` (by `emitted_at`
descending, then `session_id` descending, the rule of `managed_years.waiting_parks`, `managed_years.py:284-297`);
a park with no converted `session_start` takes the name of its latest raw `session_start` by the same order. A name
that is null, empty or only spaces counts as missing (the rule of `autopilot_menu._field`, `autopilot_menu.py:34`).
`save_backup.park_names` (`save_backup.py:85-96`) moves into `park_label.py` and keeps its name, `park_names`, and
its signature, with the `session_id` tiebreak added; `save_backup.py` (`:283,393`) and `autopilot_parks.py` (`:109`)
import it by that name from `park_label`. `tests/test_save_backup.py:164,357` (which patch `save_backup.park_names`)
and `tests/test_autopilot_source.py:17,235` (which import it from `save_backup`) keep working because `save_backup`
still holds the imported name, so no assertion in them changes. Source: the brief's "one rule for which name"; the
map section 2 (five readers that disagree).
- `check:` `tests/test_park_label.py::test_latest_session_start_names_the_park` (a renamed park takes its newest
  name) and `::test_blank_name_counts_as_missing`.
- `check:` `git grep -n "def park_names" src/` prints exactly one line, in `park_label.py`.
- `check:` `tests/test_save_backup.py`, `tests/test_autopilot_parks.py` and `tests/test_autopilot_source.py` pass with
  no line edited in them by PN-T1.

**PN-R5. Same name, same day: the time form.** When two or more parks have the same name (exact string match) and
the same shown `<Mon D>`, each of them is labelled `<name> (<Mon D>, <h:mm> <am|pm>)`: 12-hour clock, hour without a
leading zero (`12` for noon and midnight), minutes with two digits, lowercase `am` or `pm`. Parks compared are every
park the helper finds in the data set (converted or raw), not only the parks one surface lists, so a park has the
same label in every surface at one moment (choice C3). Comparing the shown `<Mon D>` and not the full date means two
same-named parks first played on Nov 15 of different years also get the time form (choice C3).
The shown name is always exactly as stored, never trimmed or case-folded. For the same-name tie rule, names are
compared after collapsing each run of whitespace to one space and trimming both ends, and never case-folded, so
`Alpha` and `Alpha ` tie (changed at the whole-branch review, ledger WB-5). A name that is only spaces is missing
(PN-R4) and never a twin. Source: roadmap
("when two parks share a name and a first-played date, the time of first play is added (`Bumbly Bazaar (Nov 15,
3:42 pm)`)"; "tests cover three same-named parks").
- `check:` `tests/test_park_label.py::test_three_same_named_parks` (the planted data of section 9) asserts exactly:
  `Bumbly Bazaar (Nov 15, 3:42 pm)`, `Bumbly Bazaar (Nov 15, 6:10 pm)`, `Bumbly Bazaar (first played Nov 16)`.
- `check:` `tests/test_park_label.py::test_noon_and_midnight` (`12:05 pm`, `12:05 am`).
- `check:` `tests/test_park_label.py::test_twin_outside_the_listed_parks_still_adds_the_time`.
- `check:` `tests/test_park_label.py::test_names_are_not_trimmed_before_the_twin_test`.

**PN-R6. Fallbacks.** Taken in order; each matches a form the code prints today (choice C4):
1. Twins that also share the minute: `<name> (<Mon D>, <h:mm am|pm>, <park ID>)` (the ID is what tells parks apart
   today, `auto_file.py:118-120`). The ID form applies only to the parks that share name, shown `<Mon D>` and minute;
   a third twin in another minute of that day keeps the time form without the ID.
2. A park with no known first-played time: `<name> (<park ID>)`, today's form (`auto_file.py:120`,
   `unfiled.py:252`).
3. A park with no name: the park ID stands in for the name (`auto_file.py:120`, `autopilot_menu.py:54`); with no
   first-played time either, the label is the park ID alone (the launcher's rule, `play-company.command:104-105`).
   A park with no name never counts as a twin.
4. A park the helper has no facts about (seen only in the registry, the warehouse or the failed-session audit, or in
   raw events that are not `session_start`): the park ID alone. One function in `park_label.py`,
   `label_of(labels, park_id)`, returns `labels[park_id]` or the bare ID; no surface writes `labels.get(id, id)`
   itself (PN-R8). A data set with no `session_start.parquet` gives no converted facts and no error: `park_facts`
   checks that the file exists before it calls `start_year.first_sessions`, which raises on a missing file
   (`start_year.py:33-47`).
- `check:` `tests/test_park_label.py::test_twins_in_the_same_minute_show_the_id`,
  `::test_id_form_only_for_the_same_minute_group`, `::test_no_first_played_keeps_name_and_id`,
  `::test_no_name_uses_the_id`, `::test_no_name_and_no_time_is_the_id`, `::test_missing_parquet_gives_no_facts`, and
  one test per unknown-park source, `::test_registry_only_park_is_its_id`, `::test_warehouse_only_park_is_its_id`,
  `::test_failed_audit_only_park_is_its_id`, `::test_park_with_only_non_start_raw_events_is_its_id` (the last gives
  the park a `ParkFacts` with no name and no time).

**PN-R7. One time zone seam.** The only conversion to local time is `park_label.to_local(dt)`, which returns
`dt.astimezone()` for the one instant `dt`, so the offset in force at that instant (daylight saving included) applies.
The zone is never read once and reused: `datetime.now().astimezone().tzinfo` is today's fixed offset and shows the
wrong hour, and near midnight the wrong day, for a park first played before a daylight-saving change. `labels` calls
`to_local` for each park's first-played instant; no other function converts. Tests reach the zone only through the
module: an opt-in fixture `fixed_local_zone` in `tests/conftest.py` (not autouse) patches `park_label.to_local` to
convert into a given UTC offset or `ZoneInfo`, and the tests that assert a label use it by name. No test sets `TZ` for
other tests. Source: the house rule "mock only true externals (the clock)" (`~/.claude/rules/engineering-standards.md`,
Tests).
- `check:` `tests/test_park_label.py::test_to_local_applies_the_offset_of_each_instant` sets `TZ=America/Los_Angeles`
  with `monkeypatch.setenv` and `time.tzset()` (restored afterwards), leaves `to_local` unpatched, and asserts that
  `2026-10-16T06:30:00Z` gives 23:30 on Oct 15 and `2026-12-16T06:30:00Z` gives 22:30 on Dec 15. A fixed-offset form
  gives the same offset for both and fails whichever month the test runs in.
- `check:` `git grep -n "astimezone\|tzlocal\|time.tzname\|local_zone" src/openrct2_analytics/ingest/park_label.py`
  prints only the line in `to_local`.
- `judgment:` no surface module converts a time or reads a zone itself.

**PN-R8. No sixth formatter.** After the slice, the only code that builds a park's display label is
`park_label.py`. Deleted: `auto_file._Park.label` (`auto_file.py:118-120`), the label f-string and `'Park'` fallback
in `unfiled.render` (`unfiled.py:252`), the name fallback of `autopilot_menu._line` (`autopilot_menu.py:54`) and the
launcher's `label="$fields[2] ($fields[1])"` comparison (`play-company.command:105`). Also deleted, because they feed
only the old formatter: the `names` mapping of `unfiled.find_unfiled`, the `names` parameter and fill of
`_unconverted_by_park`, and `ParkUnfiled.park_name` (`unfiled.py:52,129-146,199-211`). `auto_file._Park.name` stays
(PN-R9). Source: the brief ("delete the local formatters it replaces, never add a sixth"); house rule "Delete, don't
duplicate".
- `check:` `git grep -n "or 'Park'" src` and `git grep -n "self.name or self.park_id" src` print nothing,
  `git grep -nF '[[ $fields[2] == $fields[1] ]]' launcher` prints nothing, and
  `git grep -n "park_name\|park_names" src/openrct2_analytics/ingest/unfiled.py` prints nothing.
- `judgment:` no changed module looks a park up in a label mapping with its own fallback (`labels.get(id, id)`,
  `labels.get(id) or id`); each calls `label_of` (PN-R6 item 4).
- `judgment:` the reviewer greps the changed modules for any other f-string that joins a park name and ID for display
  and finds none.

### 1.2 The four surfaces

**PN-R9. Filing questions and lines (`make auto-file`, shown in the launcher window).** Every line that names a park
through `_Park.label` uses the helper's label: the earlier-play question, the conflict question, the new-park
question, the order refusal and missing-row refusal of `several_parks.check_order`, "Don't file now was chosen for
park ...", the "is new" line and the "already registered by this run" line. `_classify` (`auto_file.py:131-140`)
stops taking names from `play_status` sessions and gives each `_Park` its label from one helper call per run over the
company landing folders (`label_of` for each park ID). `_Park` keeps its `name` field, now filled from
`park_label.park_names` (one name rule, `None` when missing), beside the new `label` field: the "Say the park and its
company year" branch prints `<name> joins the company as Park <n>` from `_Park.name` (its spec R7, ticket STP-T4),
and a name stripped here would break it. The label read happens in `_classify`, before any question or registration;
an `OSError`, `ValueError` (which includes `UnicodeDecodeError`) or `duckdb.Error` from it is already caught by the
handler of `auto_file.main` (`auto_file.py:414`) and printed as `auto-file failed: io: <error>.` with exit 1 and
nothing changed, so the labels have no fallback and no silent path. Source: roadmap ("the launcher's questions").
- `check:` `tests/test_auto_file.py::test_earlier_play_question_names_the_first_played_day` and
  `tests/test_auto_file_several_parks.py::test_three_same_named_new_parks_are_told_apart` (three same-named new parks
  in one play: each question shows its own label; the answers file and registrations are unchanged).
- `check:` the assertions section 4 lists for these files pass in their new form, and
  `tests/test_auto_file_park_number.py` (owned and run by PN-T2) passes with only its four "is new" lines changed to the new label and nothing else in it edited.
- `check:` `tests/test_auto_file.py::test_park_label_read_error_stops_before_any_registration` plants an unreadable
  `session_start.parquet` and asserts exit 1, the `auto-file failed: io:` line and no registration call.
- `judgment:` the "To file it, run" and rerun lines still print commands with no label inside them.

**PN-R10. The unfiled list (`make unfiled`, shown in the launcher and read by the dashboard).** Each park line reads
`- <label>: ...` with the helper's label; the three line kinds and the status words are unchanged. `find_unfiled`
fills each `ParkUnfiled` with its label; `render` prints it. Source: roadmap ("the launcher's questions"; the
launcher shows this list before "File the waiting play now").
- `check:` `tests/test_unfiled.py::test_list_names_parks_by_first_played_day` and
  `tests/test_unfiled_raw_names.py::test_never_converted_park_shows_its_raw_first_played_day`.
  The label is read inside `find_unfiled`, so a read error is part of the check and surfaces as its failure today
  (exit 1 with the message on standard error from `make unfiled`; "Play waiting to be filed could not be checked"
  in the dashboard banner), never as a silent bare ID.
- `check:` `tests/test_makefile_play.py` is not edited and still passes: its `- Park 1 (1): ...` strings are canned
  output of a stand-in `make unfiled`, not output of `render`.

**PN-R11. The autopilot list (launcher answer 3).** `make autopilot-parks` adds one field to each park object,
`park_label` (a string, never null), the helper's label; the existing fields, `park_name` included, are unchanged
(an added JSON field, as the rest of its documented shape). `autopilot_menu.py` no longer reads `park_name`
(`_line` drops its key check, its type check and the `_field(name, park_id)` fallback, `autopilot_menu.py:42-54`),
prints `park_label` as field 2 of each tab-separated line, and refuses input whose `park_label` is missing, not a
string or only spaces (exit 1, as for any other shape problem). The launcher
shows field 2 as the park's label in `N. <label>`, `Not ready: <label>: <reason>` and "This is the first autopilot
run for <label>". The `READY` sentence it prints (field 4) still holds the park ID. Source: roadmap ("the autopilot
list"; "the park ID stays ... in typed confirmations").
- `check:` `tests/test_autopilot_parks.py::test_each_park_has_its_label`.
  A label read error in `autopilot_parks` is caught by its existing handler (`autopilot_parks.py:154`) and exits 1
  ("a file could not be read"), which the launcher already reports as a list that cannot be read; no fallback.
- `check:` `tests/test_autopilot_menu.py::test_field_two_is_the_label`, `::test_missing_label_is_refused` and
  `::test_blank_label_is_refused`; the three existing tests that use `park_name` (section 4) are rewritten to
  `park_label`.
- `check:` `tests/test_launcher_autopilot.py` passes with menu lines `1. Alpha Park (first played Oct 1)` and
  `Not ready: Beta Park (first played Oct 2): no proven backup` (stand-in JSON carrying `park_label`), and the
  first-run prompt still prints the `READY` sentence with the ID.

**PN-R12. The dashboard banner.** The practice-park warning (`dashboard.py:128-133`) becomes one sentence per
practice park: `Practice park <label> is included in these figures; remove it with make delete-company-data
PARK=<id>.` (today's wording, one park per sentence, so two same-named Sandbox parks are told apart by the label
and the command beside it, and a label that contains a comma breaks nothing). `_warnings(copy)` keeps only the
other-data-set warning and hands back the practice park IDs, which `Build` carries (`Build.practice`). The labels
are not read in `Dashboard._build`: `_build` runs only when the warehouse changes, so a label read there goes stale
when a new session lands, and an error from it would escape `refresh()` or blank the figures. They are computed in
the `_refresh_unfiled` path (`dashboard.py:242-282`), outside its `except UnfiledError` early return so the read runs whether or not `find_unfiled` raised, keyed on the same landing files (`unfiled.input_key`) plus the
build, and only when the current build has a practice park, from the helper over the company landing folders
(`play_status.landing`); never from the original warehouse. The sentences are kept on the dashboard beside
`unfiled_line` and the banner prints them after the build's warnings. The unfiled-play banner line counts parks and
names none, so it does not change.
- Fallback: a label read that raises one of the errors `UnfiledError` lists (`duckdb.Error`, `OSError`,
  `ValueError` (which includes `UnicodeDecodeError`), `ConfigError`) leaves the figures untouched, shows each
  practice park by its bare ID in the same sentence, and adds one banner line, `Park names could not be read: <error>;
  practice parks are shown by ID.`, logged once to standard error like the unfiled line; the read is not retried
  until the keyed files change. A missing `session_start.parquet` is not an error (PN-R6 item 4): the sentence shows
  the bare ID with no extra line.
- Source: roadmap ("the dashboard banner"; its problem statement quotes a bare ID).
- `check:` `tests/test_dashboard_park_labels.py` (a new file; it reuses `_ready` and `make_warehouse` the way
  `tests/test_dashboard.py` does) asserts the label form with planted converted `session_start` rows; a two-park case
  with two same-named practice parks asserts both sentences, each with its own label and `PARK=<id>`; a case with
  a new session landing after the first build asserts the label updates without a warehouse change; a case with an
  unreadable `session_start.parquet` and a case with a raw file ending in a torn character each assert page status
  200, the figures served, the bare-ID sentence and the `Park names could not be read:` line.
- `check:` `tests/test_dashboard.py` is not edited: its case at line 168 has no landing files and still asserts
  `Practice park p2 is included in these figures; remove it with make delete-company-data PARK=p2.`, which is now the
  bare-ID fallback; and `tests/test_dashboard_unfiled.py`, including
  `test_a_raw_file_ending_in_a_torn_character_gives_the_could_not_check_line`, passes unchanged.
- `judgment:` the reviewer confirms the dashboard still opens only its warehouse copy and the landing files it
  already reads for the unfiled line.

**PN-R13. The delete preview.** `make delete-company-data` (preview and apply) prints, right after the unchanged
`scope:` line, one line per park the plan selects: `park <id>: <label>` (for `PARK=`, that park; for `SESSION=`,
each park the session's raw lines carry). The `scope:` line, the refusal texts and the `confirmation:` line keep the
ID unchanged. Source: roadmap ("the delete preview"; "the park ID stays in the delete preview and in typed
confirmations"); choice C5.

The labels are read once, by `print_plan(plan, company)`, which runs only after every safety check of the delete
command has passed; `named_plan` and `delete_apply.build_plan` read no label (`named_plan` runs twice, at
`delete_data.py:67` before the checks and in `build_plan` at `delete_apply.py:70`, so a read there would add a
Parquet read ahead of the checks). `named_plan` records the selected park IDs on the plan (`Plan.parks`) from the
mapping it already builds. `print_plan` builds `LandingDirs(raw=company / "raw", parquet=company / "parquet")` from
its `company` argument, the folder the plan was built from; it never calls `config.landing_dirs`, which reads
`OPENRCT2_DATA_DIR` and so points at the wrong folder in tests. `delete_data.py` passes `root / "company"` at its two
`print_plan` calls (`:209,:244`).
- Fallback: a label read that raises `duckdb.Error`, `OSError` or `ValueError` (which includes
  `UnicodeDecodeError`, for a raw line that is not UTF-8) prints each selected park as `park <id>: <id>` and then
  one line, `park names could not be read: <error>; parks are shown by ID.`; the preview, its counts and the
  `confirmation:` line still print and the exit code is unchanged. A park the helper has no facts about prints
  `park <id>: <id>` with no extra line.
- `check:` `tests/test_delete_plan.py::test_preview_names_the_park_with_its_id` (park scope) and
  `::test_session_preview_names_its_park` (session scope), each planting its data under the `company` folder it
  passes and not setting `OPENRCT2_DATA_DIR`.
- `check:` `tests/test_delete_plan.py::test_preview_survives_a_raw_file_that_is_not_utf8` and
  `::test_preview_survives_an_unreadable_parquet` assert the bare-ID lines, the `could not be read` line, the
  unchanged `scope:` and `confirmation:` lines and no exception.
- `check:` `git diff` of `delete_plan.py` leaves the `confirmation:` and `scope:` f-strings unchanged.

### 1.3 Whole slice

**PN-R14. Gate and tests.** Every new test fails before the change it proves (house rule); `make check` passes on
the finished branch; no file passes 500 lines. Source: roadmap ("`make check` passes"); `scripts/check_file_sizes.py`.
- `check:` `env -u VIRTUAL_ENV make check` exits 0.
- `check:` `wc -l` of every changed Python file is at most 500 (`auto_file.py` is 427 lines on the base and
  "Say the park" plans 445; this slice adds at most 5 net lines to it).
- `judgment:` each ticket report lists the red run of each new test.

## 2. Design

### 2.1 Placement plan

| Part | Owner (one home) | Code reused | Dependents | Layer |
|---|---|---|---|---|
| Name rule, first-played time, label text, zone | new `src/openrct2_analytics/ingest/park_label.py` | `start_year.first_sessions` (`start_year.py:33-47`, "the one home of rank parks by their first recorded session") for the converted earliest start; `managed_years.raw_session_index` for raw; `save_backup.park_names` moved in (same name) | `auto_file.py`, `unfiled.py`, `autopilot_parks.py`, `save_backup.py`, `dashboard.py`, `delete_plan.py` | `ingest/` (reads landing files; `docs/CONVENTIONS.md:67` puts file reading there) |
| Raw `session_start` time | `managed_years.py` (`RawFile`, `RawSession`, `raw_session_index`) | the existing per-file cache | `park_label.py`, `unfiled.py` (unchanged use) | `ingest/` |
| Filing labels | `auto_file.py` (`_Park`, `_classify`) | `several_parks` already takes labels as a mapping (`several_parks.py:88-125,216-219`) | none new | `ingest/` |
| Unfiled list labels | `unfiled.py` (`ParkUnfiled`, `find_unfiled`, `render`) | the helper | launcher, dashboard banner text (counts only) | `ingest/` |
| Autopilot list | `autopilot_parks.py` (JSON field), `autopilot_menu.py` (field 2), launcher | the helper | launcher | `ingest/`, `launcher/` |
| Practice-park warning | `dashboard.py` (`_warnings` keeps the IDs; the sentences are built in the `_refresh_unfiled` path) | the helper | dashboard pages | `ingest/` |
| Delete preview | `delete_plan.py` (`Plan.parks`, `print_plan`), `delete_data.py` (two call sites) | the helper; the plan's own park mapping for session scope | `delete_data.py` (prints the plan) | `ingest/` |

Public surface of `park_label.py` (names are the builder's to refine; the behaviour is fixed by PN-R1 to PN-R7):
- `park_names(parquet_dir) -> dict[str, str | None]` (moved from `save_backup`, same name and signature, PN-R4).
- `park_facts(landing: LandingDirs) -> dict[str, ParkFacts]`, `ParkFacts(name: str | None, first_played: datetime |
  None)` in UTC (PN-R2 to PN-R4); a missing `session_start.parquet` gives no converted facts (PN-R6 item 4).
- `labels(facts) -> dict[str, str]` (PN-R1, PN-R5, PN-R6; converts through `to_local`).
- `label_of(labels, park_id) -> str`: the label, or the bare park ID for a park the mapping lacks (PN-R6 item 4).
- `to_local(dt) -> datetime` (PN-R7): the one conversion, per instant.

Gain: one place to change the label, tested once for every surface. Cost: one module of about 120 lines and one
Parquet read plus one raw-index read per command run (the raw index is cached per file, `managed_years.py:74`).

### 2.2 Behaviour after the change

- A park is shown the same way in the launcher, the filing questions, the unfiled list, the dashboard warning, the
  autopilot list and the delete preview at one moment, because the twin check runs over every park of the data set.
- A park's label can change over time: when a same-named park is first played later on the same day, both parks
  switch to the time form (PN-R5). This is the rule the roadmap settled; it is recorded so reviewers do not read it
  as a bug.
- Nothing is written: the helper only reads; no file, lock or warehouse is opened beyond what each command already
  opens (the dashboard reads the converted Parquet and raw files it already reads for the unfiled line, in the same
  `_refresh_unfiled` path and only when a practice park is shown).
- Every label read that can fail has a named result. `make auto-file`, `make unfiled` and `make autopilot-parks`
  fail as the command already fails on a landing-file read error (exit 1, message). The dashboard banner and the
  delete preview show the bare park ID and one line that names the problem (PN-R12, PN-R13). No path swallows the
  error.

## 3. Files to change

| File | Ticket | Change |
|---|---|---|
| `src/openrct2_analytics/ingest/park_label.py` (new) | PN-T1 | PN-R1 to PN-R7 |
| `src/openrct2_analytics/ingest/managed_years.py` | PN-T1 | raw `session_start` time (PN-R3) |
| `src/openrct2_analytics/ingest/save_backup.py`, `src/openrct2_analytics/ingest/autopilot_parks.py` | PN-T1 | `park_names` moved out; both import it (PN-R4); the autopilot field is PN-T4 |
| `tests/conftest.py` | PN-T1 | opt-in `fixed_local_zone` fixture (PN-R7) |
| `tests/test_park_label.py` (new), `tests/test_managed_years_raw.py` | PN-T1 | PN-R1 to PN-R7 tests |
| `src/openrct2_analytics/ingest/auto_file.py`, `tests/auto_file_support.py`, `tests/test_auto_file*.py` (eight files, section 4, including `tests/test_auto_file_park_number.py` from say-the-park) | PN-T2 | PN-R9 |
| `src/openrct2_analytics/ingest/unfiled.py`, `tests/test_unfiled.py`, `tests/test_unfiled_raw_names.py` | PN-T3 | PN-R10 |
| `src/openrct2_analytics/ingest/autopilot_parks.py`, `src/openrct2_analytics/ingest/autopilot_menu.py`, `launcher/play-company.command`, `tests/test_autopilot_parks.py`, `tests/test_autopilot_menu.py`, `tests/test_launcher_autopilot.py` | PN-T4 | PN-R11 (and the PN-R4 import, done in PN-T1) |
| `src/openrct2_analytics/ingest/dashboard.py`, `src/openrct2_analytics/ingest/delete_plan.py`, `src/openrct2_analytics/ingest/delete_data.py` (two call sites), new `tests/test_dashboard_park_labels.py`, `tests/test_delete_plan.py` | PN-T5 | PN-R12, PN-R13 |
| `AGENTS.md`, `ARCHITECTURE.md`, `docs/CONVENTIONS.md`, `CHANGELOG.md`, a new ADR | PN-T6 | section 10 |

`autopilot_parks.py` changes in two waves (an import line in PN-T1, the field in PN-T4); one owner per wave.
`several_parks.py` needs no code change (it already takes labels); its tests are owned by PN-T2.

## 4. Contracts, interfaces and what regenerates

- **No data contract changes.** No ODCS file, no envelope field, no plugin file, no dbt model, no `site/exports.toml`
  entry; `make site-export` is not needed. No hotspot file is edited.
- **`make autopilot-parks` JSON gains `park_label`** (additive; the menu helper is its only reader in the repo).
  `AGENTS.md` documents the field.
- **The launcher's tab-separated menu interface** (`autopilot_menu.py:1-12`) keeps four fields; field 2 changes
  meaning from "display name, or the ID" to "the park's label", which is never empty (zsh `read` merges empty
  fields, `autopilot_menu.py:7`).
- **Typed text stays:** `delete company park <id>` (`delete_plan.py:42`) and `<id> is profitable and its scenario
  challenge is complete` (`play_mode_feed.py:50`); every printed `make ... PARK=<id>` command keeps the ID.

**Test assertions that change** (line numbers checked at this branch's `HEAD`, `3acf8a5b`). The rule: only an assertion
that prints a park's label changes, and it changes to the label PN-R1 to PN-R6 give the park its test plants; no
assertion about a command line, a count or a status word changes. The lists below name every such assertion; a line
not listed and not printing a label stays as it is.

- Filing, old form `Park <name> (<id>)` or `park <name> (<id>)`, new form the label (PN-T2; every file is owned by
  PN-T2). The `auto_file_support.py` fixture plants `session_start` at `2026-10-DD 10:00:00+00` (`:65-67`), with `DD`
  the park's 1-based row, so with the zone fixed at UTC a park's label reads `<name> (first played Oct <DD>)`.
  - `tests/auto_file_support.py:148-157` (`_new` and `_filed` build the expected lines);
  - `tests/test_auto_file.py:30,34,129,179,185,264,284,285`;
  - `tests/test_auto_file_answers.py:35,37,38,40,41,251,288,290,406,412`;
  - `tests/test_auto_file_chain.py:121`;
  - `tests/test_auto_file_chain_guards.py:160,161,163,182,185,186,188,257`;
  - `tests/test_auto_file_chain_rerun.py:38,40,42`;
  - `tests/test_auto_file_earlier_park.py:74`;
  - `tests/test_auto_file_several_parks.py:32,35,82,83,111,113,143,173,191,252,335` (`:58` is the helper that
    wraps the label it is given; `:316` passes its own labels to `several_parks.check_order`; both stay).
  - A test that plants two same-named parks on one day gets the time form and must assert it.
- Unfiled list, old form `- <name or Park> (<id>): ...`, new form `- <label>: ...` (PN-T3):
  `tests/test_unfiled.py:25,135,153-155,174,275,281,313,314,326,360,374,420` and
  `tests/test_unfiled_raw_names.py:38,39,50,51`. A park with no name and no time is now the bare ID
  (PN-R6 item 3); `tests/test_makefile_play.py:284-292,357,367` are canned output of a stand-in `make unfiled`, not
  of `render`, and do not change.
- Autopilot list (PN-T4). The stand-in JSON gains `park_label`, and menu lines read `1. <label>` and
  `Not ready: <label>: ...`:
  - `tests/test_launcher_autopilot.py:15-22` (fixtures), `:30,38,39,77,101,107,109,134,138,139,162,166,369,380,387,416,
    427`; the case at `:83-88` (name equal to ID shows the bare ID) is deleted, because that rule now lives in the
    helper and is tested in `tests/test_park_label.py` (PN-R6 item 3);
  - `tests/test_autopilot_menu.py:73-79,124,188` (the blank-name fallback test, the required-keys parametrization and the
    non-string case move from `park_name` to `park_label`; the fixtures `:21,26` and the cases `:77,91,144` that
    override `park_name` carry `park_label` instead);
  - `tests/test_autopilot_parks.py:74-82` (the `_park` helper gains `park_label`, so every test comparing whole park
    objects expects it) and `:39` plants the name its label test reads; `:147` (`park_name` is null) stays.
  - Tests that plant through `plant()` (`tests/autopilot_fixtures.py:31`, `T0 = 2026-11-12T19:00Z`) expect
    `first played Nov 12` with the zone fixed at UTC, not `Oct`.
- Dashboard (PN-T5): no existing assertion changes (PN-R12); the new cases are in `tests/test_dashboard_park_labels.py`.
- Delete preview (PN-T5): no existing assertion changes; the `park <id>: <label>` line is new (PN-R13).

## 5. Test seams

- `park_label.labels(facts)` converts through `park_label.to_local` only: unit tests pass `ParkFacts` and use the
  opt-in `fixed_local_zone` fixture (a fixed `datetime.timezone` offset, no tzdata dependency). Only
  `test_to_local_applies_the_offset_of_each_instant` leaves `to_local` unpatched and sets `TZ` (with `time.tzset()`,
  restored afterwards); it needs the system time zone database for `America/Los_Angeles` and is skipped, with the
  reason, where `ZoneInfo` cannot load it.
- `park_label.park_facts` reads planted Parquet (DuckDB `COPY ... TO`, as `tests/auto_file_support.py:60-70` does)
  and planted raw JSON Lines in a temporary folder.
- The zone: the opt-in `fixed_local_zone` fixture of PN-R7, used by name (or `pytestmark`) in the test modules that
  assert a first-played day. No autouse fixture and no `TZ` for other tests (`tests/test_capture.py:439`,
  `tests/test_convert.py:195` and `tests/test_listener.py:63` set their own). The subprocess tests
  (`test_makefile_play.py`, `test_launcher_autopilot.py`) print no computed label: their stand-ins supply the text.
- Surfaces: `auto_file` through its existing support module; `unfiled.find_unfiled`/`render` directly;
  `autopilot_menu.main` with JSON on standard input; the launcher with its stand-in `make`; the
  dashboard through `Dashboard.refresh()` and `Dashboard.page()` on a planted warehouse copy plus planted landing
  files (`tests/test_dashboard_park_labels.py`); `delete_plan.print_plan` captured with `capsys`.
- Every test plants its own data; no test reads `data/company/`, `warehouse/`, `local/` or a real save.

## 6. Golden paths

- New helper module: `src/openrct2_analytics/ingest/start_year.py` (small read-only helpers with one stated home,
  shared by several commands).
- Labels passed as a mapping: `several_parks.check_order` and `announce` (`several_parks.py:105-125,216-219`).
- Raw reading and caching: `managed_years.read_raw_file` and `raw_session_index` (`managed_years.py:77-130`).
- Tests: `tests/test_unfiled_raw_names.py` (planted raw names), `tests/auto_file_support.py` (planted Parquet),
  `tests/test_dashboard_unfiled.py` (planted landing files under a dashboard).
- `docs/CONVENTIONS.md` and `~/.claude/rules/engineering-standards.md` outrank every golden path.

## 7. Out of scope

- The dashboard pages' park picker and ride labels (`dashboard/data.py:269,352`) and the public site: they already
  show names, the roadmap's four surfaces do not name them, and "Show the company year on the dashboard" edits
  `data.py` (choice C2).
- Refusal, progress and report lines of lower-level commands that print `Park <id>` or a park ID (`register_parks.py`,
  `start_year.py` refusals, `after_play.py`, `autopilot_year.py:206,246`, `autopilot_progress.py:140`,
  `autopilot_source.py`, `autopilot_report.py`, `save_backup.py:163`, `capture_report.py:286,296`, where :286 prints a park name and :296 a park ID): they keep today's
  text (choice C2).
- The "joins the company as Park n" line of "Say the park": its text is settled by its own item.
- Backup file names (`save_backup.file_label`), `make play-status` JSON, `dim_park.park_name` and the registry.
- The typed phrases and every printed command (PN-R11, PN-R13).
- "Remove or hide a Sandbox park without the Terminal", which builds after this slice and reuses the helper for its
  switch.

## 8. Constraints

- Invariants ("Never break" in `AGENTS.md`), verbatim:
  - Every event carries `park_id`, `session_id`, `seq`, `event_id`, game date, and `emitted_at`; `seq` has no gaps or duplicates within a session. (From contract v1; the 2026-09-27 capture is schema 0.)
  - Raw captures are append-only; every fix happens downstream in dbt. The one exception: before go-live, `make delete-company-data` archives and then rewrites or removes company raw captures and registry deliveries (ADR 0033).
  - Money stays in the game's tenths of a dollar until one staging conversion; every metric names its unit and its clock (game day, company date, or wall-clock hour).
  - Build previews and client-side predictions never count as player actions.
  - Never commit RollerCoaster Tycoon files, game screenshots or video frames, the GPL type definitions, or private machine paths. Game footage lives on a video hosting site and the site links to it (ADR 0047).
  - The contract is versioned: adding fields is a minor bump; a breaking change is a major bump and a new landing path.
  - Analyses state their sample (parks, players) and say "observational" unless an experiment design backs a causal claim.
  - The plugin compiles to ES5 and stays within its measured per-tick cost budget.
- How they bind here: rule 2, the slice only reads raw files; rule 3, "first played" is named as a wall-clock time
  in its docstring, the ADR and `AGENTS.md`.
- No new dependency (`zoneinfo` and `datetime` are standard library; tests use fixed offsets).
- No change to the `Makefile`, `contracts/`, `models/`, `plugin/`, `pyproject.toml` or `package.json`.
- Every file at or under 500 lines.
- Committed text never names the project owner.

## 9. Verify by (planted data)

One planted company data set, used by `tests/test_park_label.py::test_three_same_named_parks` and by the surface
tests that need three twins, with the zone fixed at UTC-8:

| Park ID | Name | Earliest `session_start` `emitted_at` (UTC) | Where | Expected label |
|---|---|---|---|---|
| `pa` | Bumbly Bazaar | 2026-11-15T23:42:00Z | converted | `Bumbly Bazaar (Nov 15, 3:42 pm)` |
| `pb` | Bumbly Bazaar | 2026-11-16T02:10:00Z | raw only | `Bumbly Bazaar (Nov 15, 6:10 pm)` |
| `pc` | Bumbly Bazaar | 2026-11-16T18:00:00Z | converted | `Bumbly Bazaar (first played Nov 16)` |
| `pd` | Electric Fields | 2026-11-14T17:00:00Z | converted | `Electric Fields (first played Nov 14)` |

`pb` is Nov 16 in UTC and Nov 15 locally, so the table proves the local day, the raw source and the time form at once.

- `check:` `env -u VIRTUAL_ENV .venv/bin/python -m pytest tests/test_park_label.py tests/test_managed_years_raw.py`
- `check:` `env -u VIRTUAL_ENV .venv/bin/python -m pytest tests/test_auto_file_several_parks.py tests/test_unfiled.py tests/test_autopilot_menu.py tests/test_launcher_autopilot.py tests/test_dashboard.py tests/test_dashboard_park_labels.py tests/test_dashboard_unfiled.py tests/test_delete_plan.py`
- `check:` `env -u VIRTUAL_ENV make check`

## 10. Definition of done

- PN-R1 to PN-R14 each pass their `check:` criteria; `judgment:` criteria are recorded by the reviewer.
- Docs updated in the same change (house rule "a change that invalidates a doc updates that doc"):
  - `AGENTS.md`: the `make unfiled`, `make auto-file`, `make autopilot-parks` (`park_label`), `make launcher`,
    `make dashboard` and `make delete-company-data` paragraphs name parks by label as built.
  - `ARCHITECTURE.md`: one sentence on `park_label.py` as the one home of a park's display label.
  - `docs/CONVENTIONS.md:67`: `park_label.py` in the `ingest/` module list.
  - A short ADR (next free number at build time): parks are shown by name and first-played day; "first played" is
    the earliest `session_start` `emitted_at` in the local time zone; the twin and fallback rules; typed phrases keep
    the ID.
  - `CHANGELOG.md` "Unreleased": one line.
- The ledger `docs/ai-dlc/ledger/park-names.md` has no open row.

## 11. Map claims checked

The map was written without git access; each claim this spec relies on was checked on `2db7e558`:
- Confirmed: `auto_file.py:118-120` formatter; `unfiled.py:252` formatter and `'Park'` fallback; `autopilot_menu.py:34,
  54`; the launcher comparison at `play-company.command:105`; `save_backup.py:85` name reader;
  `managed_years.py:284-297`; `play_status.py:108-122`; `dashboard.py:128-133` and the pinned
  `tests/test_dashboard.py:168`; `dashboard/data.py:269,352`; `delete_plan.print_plan` at line 266-268.
- Corrected: `fix/reword-unfiled` does not edit `unfiled.py`; it edits `dashboard.py`, `launcher/play-company.command`
  (line 76), `tests/test_dashboard_unfiled.py`, `tests/test_makefile_play.py`, `AGENTS.md`, `ARCHITECTURE.md` and
  `CHANGELOG.md`. `feat/dashboard-company-year` edits `dashboard/data.py`, `tests/test_dashboard.py` and
  `tests/test_dashboard_data.py`. `feat/say-the-park` has built the move to `auto_file_state.py` and
  `dim_park.park_number`; its filing line (its ticket STP-T4, owning `auto_file.py` and `play_status.py`) is not
  built yet.
- Not pinned: no test asserts the `scope: park=` line literally (`grep "scope: park=" tests/` prints nothing).
- New: `start_year.first_sessions` already ranks parks by earliest `session_start` `emitted_at`; the helper reuses it.

## 12. Build order against other branches

| Branch | Shared files | Order |
|---|---|---|
| `feat/say-the-park` (base, `2db7e558`) | `auto_file.py`, `tests/test_auto_file_answers.py` (its STP-T4) | PN-T2 starts after STP-T4 is merged into the base or `develop` |
| `feat/early-park-warning` (stacked on say-the-park) | `auto_file.py` | PN-T2 after it, or rebase PN-T2 onto it |
| `fix/reword-unfiled` (`d08de813`) | `dashboard.py`, `launcher/play-company.command`, `AGENTS.md`, `ARCHITECTURE.md`, `CHANGELOG.md` (it also edits `tests/test_makefile_play.py`, which this slice leaves alone) | PN-T4, PN-T5 and PN-T6 after it merges (PN-T3 edits none of these files, so it does not wait on it) |
| `feat/dashboard-company-year` (`5fed15e2`) | `tests/test_dashboard.py` and `dashboard/data.py` (this slice edits neither: its new dashboard tests are in `tests/test_dashboard_park_labels.py`) | none; PN-T5 does not wait on it |
| "after-play refuses a session that failed its seq audit" (no branch yet; Group 2 item 1) | likely `managed_years.py` (`RawFile.has_unreadable_line`) | PN-T1 after it, per the roadmap's Group 2 order |

PN-T1 builds first: it edits no file another branch edits and is the only ticket that can start before any other
branch merges. PN-T2 waits on STP-T4; PN-T4, PN-T5 and PN-T6 wait on `fix/reword-unfiled`; PN-T3 waits on PN-T1
only.

## 13. Choices made without the project owner

Each follows behaviour the repo already has; none changes the settled pass/fail.

- **C1. "Company-local date" is the local calendar day of the wall-clock `emitted_at`, in the time zone of the
  machine that prints the label.** Reason: the settled example adds a time of day (`3:42 pm`), which only the wall
  clock has; a company date (`dim_park.first_company_date`, `models/marts/dim_park.sql:79`) has no time of day and
  exists only after a park is registered and built, while the launcher asks before registration. The machine's local
  zone is what the dashboard already shows (`dashboard.py:233` reads the file time with `datetime.fromtimestamp`,
  naive local, printed at `:139,:290`). Gain: one clock for every surface, readable before registration. Cost: the
  same park shows a different day on a Mac set to another zone.
- **C2. The four named surfaces only.** The dashboard park picker, the site and lower-level refusal lines keep their
  text (section 7). Reason: the pass/fail lists the four surfaces in parentheses, and those other places already
  show names or are diagnostics that print commands. Gain: a slice of six tickets that leaves `dashboard/data.py` to
  the branch editing it. Cost: a refusal from `start_year.py` still says `Park <id>` in the launcher window.
- **C3. Twins are compared across every park of the data set, on the shown `<Mon D>`.** Reason: one label per park
  in every surface, as "one rule" requires (`start_year.first_sessions` is likewise data-set wide). Gain: a park
  never changes label between two screens at one moment. Cost: a park listed alone can still show the time form.
- **C4. Fallbacks reuse today's forms** (PN-R6): the ID when twins share the minute, `<name> (<ID>)` with no
  first-played time, the ID for a missing name (`auto_file.py:120`, `unfiled.py:252`, `autopilot_menu.py:34`,
  `play-company.command:105`). Gain: no new wording. Cost: the rare fallback still shows an ID.
- **C5. The delete preview adds `park <id>: <label>` after `scope:`** and changes no existing line. Reason: the
  pass/fail keeps the ID in the preview; adding a line leaves the scope line and the confirmation phrase byte for
  byte. Gain: no pinned delete test changes. Cost: one more line in the preview.
- **C6. `save_backup.park_names` moves into the helper, keeping its name, with a `session_id` tiebreak.** Reason: "one rule for which
  name"; `managed_years.waiting_parks` already breaks ties that way. Gain: the backup file name and the label read
  the same name. Cost: a park whose two latest starts share an `emitted_at` exactly may get a different backup file
  name than today.
- **C7. The autopilot JSON carries the label** rather than the menu helper reading data. Reason: `autopilot_menu.py`
  reads only standard input and writes no file (`autopilot_menu.py:1-12`); `autopilot_parks.py` already reads the
  names. Gain: the menu helper stays a pure translator. Cost: one more documented JSON field.

## 14. Needs project owner

None. Each open point above is settled by existing behaviour and recorded as a choice. Reviewers may still escalate
C1 (the time zone reading of "company-local") or C2 (the scope of surfaces); either escalation parks the slice under
the preflight's void conditions.
