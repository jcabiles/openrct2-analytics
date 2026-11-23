# ADR 0024: the kept timeline is chosen per session from session starts and save cuts

- Date: 2026-10-11; revised 2026-10-12 to the project owner's rulings on the first review of the 3b-1 spec.
- Status: Accepted (2026-10-12). The project owner approved the 3b-1 spec (`docs/ai-dlc/specs/save-lineage.md`) as a
  whole at Gate 2. Its rules come from the project owner's Gate 1 ruling of 2026-10-11 for roadmap NEXT 3b-1 (the
  save-lineage part of the intermediate layer) and the rulings of 2026-10-12 that revised it. Decision 3a's clause
  is the Gate 2 ruling on Open point 9; decision 2b's reading of ADR 0006 `:40` is the Gate 2 ruling on Open point 10;
  decision 4a carries the grouping ruling on Open point 11. Decisions 3b, 4b, 5b and 7 are inferences, marked below,
  confirmed by the project owner's Gate 2 approval of the spec, 2026-10-12.
- Fills gaps in: ADR 0006 (`docs/adr/0006-plugin-records-facts-dbt-decides-validity.md`) and ADR 0011
  (`docs/adr/0011-save-lineage-is-recorded-in-park-storage.md`). It supersedes neither and changes no rule of either,
  which holds under decision 2b's reading of ADR 0006 `:40`, confirmed at Gate 2.

## Bottom line

The warehouse decides which game events are on the kept timeline with one table that has one row per play session.
Each session that loaded a save points to the session that wrote it. The kept branch is the chain of sessions that
leads back from the most recently started session of each tree; orphans of one park that loaded the same unplaceable
save form one tree. Every session off that chain is abandoned with everything played in it. Every session on the chain
is cut at a save: the newest session at its own last save, so play after the last save is never kept, as the
requirements brief says, and every earlier session at the save the next session loaded (Gate 2 ruling, Open point 9).
Any event is then labeled kept or abandoned by joining on its session and comparing its `seq`. Nothing is deleted;
every build recomputes every label, and the build fails when two kept sessions of one park cover the same game time.
What is given up: the newest session's play since its last save never counts, and when a session's two saves were
each loaded by a different later session, only the branch leading to the newest session is kept.

## Context

ADR 0006 assigns the timeline to dbt: it "builds the timeline tree, keeps the latest branch from each save, and labels
every row kept or abandoned; marts read only kept rows" (`:40`), and labels were chosen because they are "reversible
and countable" (`:60-62`). ADR 0011 gives each save an exact cut, the landed `save_written` event's own `seq` (`:29`),
and a fallback, floor plus waiting lines plus one, when that event does not land (`:30`). Neither record says what a
branch is, what "latest" compares, what happens when the saved session cannot be found, or whether play after the last
save is kept. The confirmed requirements brief answers the last: kept means "on the save branch the player continued"
(`docs/requirements-brief.md:97-98`), and "the events a session records after its last save that no later session
continues from, are labeled and kept out of every metric" (`:289-291`). The committed sample is one straight chain of
three sessions and exercises none of the other cases (`data/sample/rehearsal/README.md`, "Save lineage"). The project
owner ruled the missing rules on 2026-10-11 (direction A and the Gate 1 lines of `docs/ai-dlc/specs/save-lineage.md`)
and, after the first spec review, revised them on 2026-10-12; this record writes them down with the inferences needed
to build them.

## Decision

1. **One session-grain lineage model, joined downstream** (Gate 1, direction A). One intermediate table,
   `int_sessions__lineage`, has one row per session seen in any event. Every model that needs the kept timeline joins
   it on `session_id`. No model labels every event of every type (an all-events model is out of scope).
2. **Parents, trees and the kept path.**
   a. A session that loaded a save is a child of the session that wrote it. A root, or orphans of one park that
      loaded the same unplaceable save (decision 4a), with every session descending from them, is one tree, ADR
      0006's "timeline tree".
   b. The kept branch is the ancestor path of the most recently started session: that session, its parent, its
      parent's parent, and so on to a session with no parent (ruling of 2026-10-12, replacing Gate 1's comparison of two
      sessions that load one save). "Most recently started" means the latest `session_start` `emitted_at`; equal times
      go to the greater `session_id`. That tie-break is arbitrary but stable: a session ID begins with its start time
      in milliseconds (`ARCHITECTURE.md`, "Session IDs print in full"), so a tie means equal prefixes and the random
      suffix decides, which carries no time but gives the same answer on every build. ADR 0019 calls `emitted_at` the
      game's clock and bars it from choosing which copy of an event is kept, because it can repeat after a save reload
      (`docs/adr/0019-dbt-practices.md:62`). Here it orders the `session_start` events of different sessions, not copies
      of one event, and the staging model defines it as the producer's wall-clock send time
      (`models/staging/stg_envelope.yml:64`), which loading a save does not rewind; where two are still equal, the
      tie-break decides. This reads ADR 0006's "keeps the latest branch from each save" (`:40`) as: a session's own
      play past a save is also a branch from that save, a session is cut only once, and the latest branch is the one
      that holds the most recent play. ADR 0006 is silent on a session whose two saves were each loaded by a different
      session; under this rule only the branch leading to the newest session is kept. Gate 2 confirmed this reading
      (spec Open point 10); the claim that this record changes no rule of ADR 0006 rests on it.
   c. (Ruling of 2026-10-12.) The rule applies within each tree. A park can hold more than one tree (a continuation whose
      `session_start` was lost, an orphan, a second new game), and decision 4 keeps every root and a lone orphan.
      Orphans sharing a loaded save form one tree, so each tree keeps the ancestor path of its own most recently
      started session, its frontier. In a park with one tree,
      the usual case, that is the park's most recently started session. A session with no `session_start` has no
      start time and sorts before every session with one. Only a session that belongs to a tree can be a frontier: a
      session in a parent loop (its own parent, or two sessions naming each other) is reached from no root or orphan,
      belongs to no tree and fails a build test, so the walk up from a frontier never follows a loop.
3. **Every session on the kept path is cut at a save** (ruling of 2026-10-12; `docs/requirements-brief.md:289-291`).
   a. A tree's frontier is cut at its own last landed `save_written`. A session with no save and no fallback, such as
      a frontier that never saved, contributes nothing to the kept timeline. A cut at a save is the landed
      `save_written` event's `seq` (ADR 0011 `:29`) or, when that event was lost, the stored floor plus waiting lines
      plus one, labeled estimated (`:30`; Gate 1). *Gate 2 ruling (spec Open point 9):* a kept-path session followed by
      another kept-path session is cut at the save that session loaded, not at its own last save, because its play
      after that save is on a branch the player abandoned.
   b. *Inference, confirmed at Gate 2:* a lost event is recognized when the loading session reports a
      `loaded_save_session_id` that is a session in the data and both a floor and a waiting count. A park-storage
      failure can pair a new save ID with an older save's session, floor and waiting count
      (`contracts/save_written.odcs.yaml`, the `save_written`
      description); it lands here too, with a cut that may be too early, and nothing in the data tells the two apart.
4. **Roots, orphans and overlapping kept sessions.**
   a. A session whose loaded save is null is a root; this includes a session with no `session_start` event, whose
      loaded save is unknown. A session whose loaded save is not null but cannot be placed (no `save_written` for it,
      and decision 3b does not apply) is an orphan, flagged and kept when it, or a session descended from it, is its tree's frontier.
      Orphans with `load_status` `orphan`, the same `park_id` and the same `loaded_save_id` form one tree (Gate 2
      ruling, spec Open point 11). Its `tree_root_session_id` is the group's earliest-started orphan: the least by
      `session_start` `emitted_at`, with equal times the smaller `session_id` is the earlier (the mirror of decision 2b). The latest-started
      session is the frontier; for two lone orphans it is the later-started orphan, and the earlier is abandoned with
      everything played in it; in general the kept path is the frontier's ancestor path, which may run through either
      orphan. The two cannot overlap as kept sessions. The tree's root can be an abandoned sibling of
      the kept session.
   b. A lineage test fails the build when one park has two kept-path sessions over overlapping game dates (ruling of
      2026-10-12). It catches the shapes decision 4a leaves open: a continuation whose `session_start` was lost becomes
      a root beside its real parent, and an orphan whose parent is present leaves the parent's own path kept.
      *Inference, confirmed at Gate 2:* overlap is compared on `game_ticks_elapsed`, the game clock in ticks that a
      load restores from the save, because a save made partway through a game day leaves that date on both sides of a
      normal cut. Two sessions overlap when each one's first kept tick is strictly below the other's last kept tick;
      two ranges that share exactly one tick do not. A resumed session is shown to start one tick after its save only
      for saves a plugin makes (`docs/architecture/openrct2-facts.md`, "Saving"; `docs/FINDINGS.md`, autopilot year-end
      row), not for autosaves and menu saves, so a shared tick is not treated as overlap.
5. **The event label.**
   a. An event is kept when its session is on the kept path, the session has a cut, and the event's `seq` is below
      the cut. Every other event is abandoned. The label has two values, kept and abandoned (ADR 0006); estimated and
      orphan are session flags, not labels.
   b. *Inference, confirmed at Gate 2:* the `save_written` event that sets a cut has `seq` equal to the cut, so it is
      labeled abandoned. ADR 0011 says only that all lower sequences were created before the save (`:29`); the save
      event itself marks the cut and is recorded in the lineage table.
6. **Labels are reversible and recomputed on every build** (ADR 0006 `:60-62`; Gate 1). The lineage table and every
   labeled model are tables rebuilt in full (`dbt_project.yml`, `+materialized: table`); no label is stored between
   builds, and staging keeps every event. A labeled model keeps every row with its label: `int_statements__labeled`
   holds every monthly statement as kept or abandoned, and a mart selects the kept rows (ruling of 2026-10-12, which
   matches ADR 0006 `:40` and `:60-62`).
7. *Inference, confirmed at Gate 2:* **counter changes stay inside one session's kept rows, and each change belongs
   to the earlier reading.** ADR 0019 D13(c) computes counter changes within one kept save branch, ordered by `seq`
   (`docs/adr/0019-dbt-practices.md`, section 4). `seq` restarts in every session (`models/staging/stg_envelope.yml`,
   `seq`), so changes are computed per session over kept rows only. A snapshot is read at the start of the game day,
   so the rise from one kept reading to the next is assigned to the earlier reading's date, as the marts design does
   (`docs/ai-dlc/reports/dbt-design--marts.md`, `fct_park_day` and `fct_ride_day`); the last kept reading of each
   session has a null change, even where the counter continued across a clean reload.
8. **A monthly statement takes its company date from its own month** (Gate 1). Its company year is the park's company
   start year plus (`statement_year` minus the game-year origin), from the current registry row
   (`int_park_registry__current`, ADR 0023 decisions 2 and 8), never from the game year of the day-1 event that
   carried it; the date is the `company_date` macro on that year, `statement_month` and day 1.

## What was given up

The newest session's play since its last save never counts, even though it is the latest play, and a session played
without saving contributes nothing. When a session's two saves were each loaded by a different later session, only the
branch leading to the newest session is kept, although the other was the only branch from its own save. "Most recently
started" follows the latest play, not the best or longest branch. Of two lone orphans of one unplaceable save, only the
later-started is kept, whatever the player continued; the other's play counts nowhere. A park with two independent trees over
the same game time cannot build until this rule changes, because raw captures are append-only; for example, a
continuation whose `session_start` was lost can be a root beside its real parent. An estimated cut can be wrong when
the queue dropped lines ahead of the lost save event (ADR 0011 `:30`): a cut late enough that the parent's kept
events go past the child's first kept tick fails the build through decision 4b, but a
cut late by less, which ends on or before that tick, is not caught, and two kept sessions that share exactly one tick
pass. `plugin_stats.lines_dropped_total` counts those drops but is not used to flag an estimate: read at the end of a
session it includes drops made after the save, and a per-save reading needs one more join. The park-storage failure of
decision 3b cannot be told from a lost event. A session whose only save lost its `save_written`, loaded by a session
that reports no waiting count, drops whole from the kept timeline: its loader is an orphan, so the session is its own
frontier with no landed save. Each save costs two days of daily change: the save day's own snapshot is dropped and the
kept reading before it, its session's last, has a null change (decision 7), so the committed sample has 102 daily
changes over 108 game days.

## Rejected alternatives

- **One labeled model over every event** (direction B). It needs its own duplicate removal, because `stg_envelope`
  keeps every delivery (`models/staging/stg_envelope.yml`), and builds a table the size of all events.
- **Lineage inside each kept model** (direction C). The kept-path rule would be written once per event type.
- **The later-started of two sibling sessions wins, compared per parent** (this record's first draft, from Gate 1's
  fork rule). It made children of two different saves compete and abandoned a later session continuing the losing
  child's branch, which is not the branch the player continued (`docs/requirements-brief.md:97-98`).
- **One kept path per park, from the park's most recently started session only.** It would drop every other root or
  orphan tree from the kept timeline with no test failing.
- **Keep the newest session's play after its last save until a later session loads that save** (Gate 1's default). It
  contradicts the requirements brief (`:289-291`) and would publish the run-on days of an autopilot year-end save.

## Consequences

- The 3b-1 build adds `int_sessions__lineage`, `int_statements__labeled`, the `timeline_status` and `counter_change`
  macros, and their tests, including the overlap and kept-session tests (`docs/ai-dlc/specs/save-lineage.md`).
- Cutting every session at a save drops one day of each session in the committed sample: 105 of its 108 daily park
  snapshots are kept, and 102 of them have a daily change (the spec's Verify-by), so 3c's daily marts expect two days
  without a change at each save.
- No ADR body is edited; ADR 0006 and ADR 0011 gain no status line, because under decision 2b's reading of ADR 0006
  `:40` nothing in them is replaced.
- **How we would know this is wrong:** a real capture shows a kept branch that is not the one the player continued; a
  lost-save cut differs from the cut later found in the raw file; or the overlap test fails on a park whose sessions do
  not overlap in play.
