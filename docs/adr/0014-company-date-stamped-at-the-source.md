# ADR 0014: the company date is stamped at the source

- Date: 2026-10-03
- Status: Superseded by ADR 0023 (2026-10-09): company dates come from an upstream park registry feed.

## Bottom line

Proposed: the plugin stamps every event with its company year. It reads
two values stored once in the park's own save file (the company start year
and the game-year origin) and adds one field, `company_year`; the month and
day stay the game's. The plugin sends nothing until both values are stored:
no session start, no queued event, and never a blank stamp; a missing value
shows as a message in the game. The analytics plugin sets the values itself
on a park's first run, so one park ID is minted, stored, registered and
captured together. A wrong start is corrected downstream: a park registry
in the repo is the authority, dbt checks every stamp against it, a listed
correction (keyed by park, session and the wrong value) lets that stamp
pass while keeping it visible, models use the validated stamp, and the raw
files stay as landed. Autopilot parks stay in step by a run rule, not a
shared clock. The listener could also stamp every event, by holding a new
park's events until its registry row exists; it is cheaper today but needs
a holding store and a mid-session registry edit. The evidence is in
`docs/ai-dlc/reports/company-date-stamping--findings.md`.

## Context

The park company reports every park on one calendar (roadmap, "Business
rules: the park company"). Park 1's first game day is 1 March 2000 on that
calendar; the hand-played (managed) park sets the company clock, and only
one park is managed at a time; a park on autopilot runs headless one game
year per run. Each park has a company start year and a game-year origin,
and company year = company start year + (game year − game-year origin),
with the game's month and day. A game year is 8 months, March to October.
Roadmap NEXT 16 (the company-calendar item) requires every event to carry
its company date.

The project owner ruled on 2026-10-02 that company dates are stamped
upstream, as a real app stamps its events, and left open whether the
plugin or the listener stamps them. Today the plugin stamps the identity
fields and the game date when it creates an event and keeps the park ID in
park storage, inside the save file (ADR 0011, save lineage in park
storage). It mints that ID at start-up when storage has none
(`plugin/src/identity.ts`) and queues `session_start` straight after
(`plugin/src/main.ts`). The listener adds only its arrival time (ADR 0003,
the local socket and JSON Lines files standing in for a message queue).

Research on 2026-10-03 found that systems of record stamp a business date
beside the system date (Oracle OPERA's revenue date and posting date), that
an arrival-time lookup returns nothing when its reference row is missing at
lookup time (ksqlDB's stream-to-table joins, which advise loading reference
data first), and that corrections are appended and recomputed rather than
overwritten. In OpenRCT2 0.5.5, park storage travels inside every save,
autosave and copy; plugins cannot read files, options or environment
variables; and the in-game prompt exists only in a windowed game.

## Decision

Proposed, pending the project owner's ruling:

| Area | Choice |
|---|---|
| Who stamps | The plugin. |
| Field | `company_year` in the envelope. The contract marks it `required: false` only because events from earlier plugin versions lack it (a minor version of the contract set); every event from the version that adds it carries a valid value, and a dbt test requires that by plugin version. The company date is `company_year` with `game_month` and `game_day`. |
| Stored values | `company_start_year` and `game_year_origin` in park storage; `session_start` reports both as read. |
| Rule | `company_year` = start year + (game year − origin). A stored pair whose origin is after the current game year counts as missing. |
| No event without a date | `main()` mints or reads the park ID, then reads the two values. While either is missing, the emitter stays closed: no socket, no queue, no `session_start`. The plugin shows a visible message instead (the prompt in a windowed game, a console line headless). Once both values are written, the emitter opens and `session_start` takes `seq` 1. |
| Bootstrap | One path for every park: the analytics plugin's own first run. It mints the park ID, prompts for the start year and then the origin (current game year filled in), writes both to park storage and opens the emitter. A cancelled prompt leaves the emitter closed for the session; a menu item reopens the prompt and later views or corrects the values. No separate helper plugin. |
| Rehearsal parks and the benchmark fixture | Each old save is opened once in the windowed game with the plugin installed (through `make capture-data`), seeded by the prompt and saved; every later headless run loads that save. |
| Autopilot park | Inherits the values from its own save. |
| Registry | A dbt seed in `seeds/`: `park_id`, the two values, a rehearsal label and a note, filled from the seeding session's `session_start`. Its git history records what was believed when. |
| Correction | A correction seed holds rows of `park_id`, `session_id`, the wrong stamp value, the corrected value and a reason. Staging keeps the raw stamp and the corrected value (computed from the game date and the registry) as two columns and labels corrected rows. The error-level test passes a row when its stamp equals the registry value, or when a correction row matches its park, session and wrong stamp value and gives the registry value as the correction; any other mismatch fails, including a second, different wrong stamp in the same session without its own row. Downstream models, including the intermediate date mapping, use the validated stamp (the raw stamp once this test passes, or the corrected value on a corrected row), never a freshly recomputed date: recomputation is the test, not a source. Raw files are never rewritten; future events are fixed through the menu item. |
| Autopilot in step | A run for company year Y starts only after the managed park has begun Y. The year-end save does not end the game: the runner stops it after the save, not at the boundary, and the events recorded after the save are kept in raw; that abandoned post-save play is what meets the rule that an autopilot park never runs past its year end. dbt excludes them from the closed company year (ADR 0006: the next run resumes from the save, so they sit on an abandoned branch). The year-end close register blocks annual marts until every expected park has a complete, kept year. |
| First build step | A headless probe on copies: park storage survives a save made with the plugin absent. |

## Acceptance criteria for the build ticket

These are stated now and run by the build, not by this research.

- **Every event is dated, or nothing is captured.** Capture a park with
  empty storage, including a session where the prompt is cancelled: every
  event from `seq` 1 has a valid company date, or no event is sent.
- **One stable park ID per old save.** Each old rehearsal save without an
  ID ends with one stable `park_id` across seeding, registration and first
  capture.
- **Corrections pass and stay visible.** A deliberately wrong raw stamp
  with a correction row yields the registry's date in the models, keeps the
  raw stamp in staging, and lets the build pass; an unlisted mismatch fails
  the build. A session holding the known wrong stamp and a second,
  different wrong stamp fails: the known one passes on its row, the second
  has none. An uncorrected row reaches the models through its validated
  stamp, not a recomputed date.
- **Two parks on one calendar.** Both parks start from old saves (each
  origin is the game year its save was in). Park 1 is company years 2000 to
  2002; Park 2 starts on 1 March 2003, the March after Park 1's last managed
  year, while Park 1 runs on autopilot. The rehearsal must hold at least two
  company years shared by both parks, with both parks' source saves spanning
  at least two overlapping game years, so the formula is checked on both; a
  rehearsal with only one shared year fails this case. Every company year
  both parks run is checked on both parks against their own registry rows,
  and exactly one park is managed in any company year.
- **Year-end run-on never counts.** After a year-end run, no event after
  the year-end save advances the kept company timeline or allows an early
  close. The runner stops after the save, not at the boundary, so the test
  reads the captured events, not the time the runner stopped.

## The two options compared

Both options can meet the every-event requirement; they differ in where the
wait for missing values happens and who pays for it.

| | Plugin stamps (proposed) | Listener stamps |
|---|---|---|
| Every event dated | Yes: the plugin sends nothing until the values exist. | Yes, if the listener holds or rejects lines for a park with no registry row. Rejecting loses those events; holding needs a store before raw and a release step. |
| Who supplies the values, and when | The player, once per park, in the game before capture starts; each rehearsal save and the benchmark fixture need one windowed session. | Someone adds a registry row after the park ID exists, so for a new park during its first session (the player reads the new ID and edits the file while the game runs); a harness can write the row itself for headless parks. |
| Append-only raw | Raw holds only stamped lines, written once. | Met only if the holding store is itself append-only and release appends stamped copies to raw: two copies of each held line. |
| Reproducibility | The stamp is fixed when the event is created. | The stamp depends on the registry when the line arrived. |
| Replay and a real queue (ADR 0003) | Unaffected. | Replay strips and re-adds the field; a real queue needs the lookup and the hold in a subscriber. |
| Work now | Plugin change, plugin tests, a `make bench` re-run, windowed seeding of the existing saves. | Listener, config and harness changes; a holding store; no plugin change. |

The plugin option is proposed. It gains events that are complete when
created, a stamp that never depends on when the registry was edited, and a
listener that stays a pass-through for replay and a future real queue. It
costs a plugin change re-measured under ADR 0005's per-tick budget, a
windowed seeding session for each existing save, and no capture at all for
a session whose prompt is cancelled. The listener option gains no plugin
change and automatic registration for headless parks; it costs a holding
store and release step, a registry edit during a new park's first session,
and business logic in the listener. The project owner rules between them.

## Rejected alternatives

- **A null `company_year` when a value is missing.** It breaks NEXT 16's
  every-event requirement and leaves the gap in append-only raw data.
- **A separate seed-helper plugin.** It cannot know the park ID the
  analytics plugin mints, so it would need a copy of the identity code; one
  bootstrap in the analytics plugin keeps one ID path.
- **dbt derives the company date with no upstream stamp.** It is simplest,
  but the 2026-10-02 scope ruling requires an upstream stamp, and the
  events would lose the producer's own statement of its date.
- **A `capture-data` option that bakes the values into the built plugin,
  or installs a second helper file.** A value tied to a run, not a park,
  is stamped on whatever park the player loads, and a second file in the
  player's plugin folder needs its own install record (ADR 0009).
- **Shared storage (`plugin.store.json`).** It belongs to the game
  install, not the park, so in the player's own folder every park would
  read the same values.
- **Three company-date fields.** The month and day are the game's; one
  field keeps them single-sourced and still lets dbt check each row.
- **Seeding through the headless stdin console.** A third-party report on
  0.5.5 says it starts only on a terminal, and the plugin has already read
  its storage by then.

## Consequences

- The build slice changes the plugin (`plugin/src/identity.ts`,
  `plugin/src/emit.ts`, `plugin/src/main.ts`, `plugin/src/events.ts`) and
  its tests, re-runs `make bench` under ADR 0005's per-tick budget, bumps
  the contract set, and adds the registry seed, the correction seed, the
  agreement test and the staging columns; the intermediate date mapping
  (roadmap NEXT 3b) uses the validated stamp, never a recomputed date.
- A headless run on an unseeded save captures nothing. The benchmark
  fixture and both rehearsal saves must be seeded before the new plugin
  version runs on them, and the harnesses must report an empty capture as a
  failure.
- The prompt and menu item need a windowed check by the project owner
  (owner-later).
- The park-identity copy rule (roadmap NEXT 6) must also clear or reset the
  company values, because a file copy carries them.
- Loading an earlier save after a correction revives the earlier values;
  the agreement test reports it and a correction row covers it.
- **How we would know this is wrong:** the probe shows park storage lost
  when a park is saved without the plugin (the listener option then wins,
  or `capture-data` must keep the plugin installed between sessions); the
  prompt cannot be used in play; seeding each save by hand proves too
  costly against a harness-written registry row; or the agreement test
  fails often enough that corrections outnumber trustworthy stamps. Any of
  these reopens this record.
