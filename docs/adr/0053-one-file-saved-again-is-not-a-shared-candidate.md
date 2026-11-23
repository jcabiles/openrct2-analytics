# ADR 0053: one file saved again later is not a shared candidate

- Date: 2026-11-15.
- Status: Accepted 2026-11-15. Amends ADR 0037 (`docs/adr/0037-save-file-records-outside-the-event-envelope.md`),
  item 2, only where it says which events share a candidate file.

## Bottom line

Saving the same park file twice in one play session no longer fails the capture. Two save events now share a file
only when one write record of that file lies inside both events' 5-second windows. Before this change, a file that was
a candidate of any other event counted as shared, even when the two saves were minutes apart, so every session that
saved over one file name more than once exited 1 and made no backup copy. No data contract, dbt model or plugin file
changes.

## Context

ADR 0037 pairs each `save_written` event with the one file written within 5 seconds after it. It fails an event whose
candidate file "is a candidate of another event", to refuse a pairing that could belong to either of two saves. Read
literally, the rule compares file names only. A company session on 2026-11-13 saved over `save/Crazy Castle` at three
moments 2.5 minutes and 28 seconds apart; each write landed within 0.05 seconds of its own event, and no write lay in
two windows, yet all three events failed as one two-candidate window. The capture exited 1 and skipped the backup copy
that ADR 0048 makes after a healthy run. Saving over one file name is the game's normal "Save" behavior, so the old
rule failed most manual play.

## Decision

- An event's candidates and the record that stands for each are unchanged: every distinct file with a `created` or
  `modified` record in `[emitted_at, emitted_at + 5 s]`, represented by its latest such record.
- An event pairs when it has exactly one candidate file and none of its in-window records lies in another event's
  window. A record held by two windows still fails both events as a two-candidate window, as before, so two saves less
  than 5 seconds apart that leave one write remain a failure. Two saves less than 5 seconds apart that leave two
  writes, each inside only its own save's window, now pair one write each.
- Records of one file tied on modified time keep the first in record-file order, as before, so the record that stands
  for a file does not depend on the process.
- All in-window records of the paired file count as paired, as before.

## Rejected options

- **Pair each write to the nearest event.** It would pair two saves 3 seconds apart that left a single write, guessing
  which save the file holds. Gain: fewer failures. Cost: a wrong pairing would back up a file as the later save when it
  holds the earlier one. The ambiguity stays a failure.

## Consequences

- A session that saves over one file name several times passes the save-file check and gets its backup copy.
- The 2026-11-13 session stays recorded as failed in its printed report; its next healthy `make play` run makes the
  park's first backup.
- Covered by `tests/test_save_pairing.py`: the same file saved again outside the earlier window pairs each save, and
  one write inside two windows still fails while a later save of the same file pairs.
