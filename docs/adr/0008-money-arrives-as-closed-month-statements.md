# ADR 0008: money arrives as one statement per closed game month

- Date: 2026-09-30
- Status: Superseded in part by ADR 0039 (the "Why that moment" row)

## Bottom line

The plugin sends the park's money as one `finance_month` event (a monthly statement) per closed game
month: the 14 ledger lines for that month, plus cash and bank loan at the moment of reading. Everything
stays in the game's tenths of a dollar until the one staging conversion in dbt. The statement is read in
the day-1 callback, where the change in cash minus loan from one statement to the next equals the later
statement's 14 lines exactly. The price is that a statement still queued when the game quits during a
listener outage is lost with no count. The same change adds a `session_start` event and moves all five
contracts from 1.0.0 to 1.1.0 together, under the rule in ADR 0007, which stays as written.

## Context

The profit-and-loss statement (P&L) needs the game's ledger as raw data. The game keeps a history for
each of 14 expenditure types; index 0 is the current month and index 1 is the last closed one. Cash and
loan are separate park values. The schema 0 capture of 2026-09-26/27 showed that in all 14 month rollovers
cash minus loan moved by exactly the closed month's total, and the 2026-09-30 headless rehearsal showed
the same for its 2 consecutive pairs (see `docs/FINDINGS.md`, "Ledger reconciliation" and the part 2 rows).

## Decision

| Decision | Choice |
|---|---|
| Event | `finance_month`, one per session per closed game month, with `statement_year` and `statement_month` (the month before the envelope date, wrapping month 0 to month 7 of the previous year). |
| Content | The 14 ledger lines (index 1 of each history), `cash_tenths` and `bank_loan_tenths`, all integers in tenths of a dollar. |
| When | The day callback on day 1, the first moment the month is closed. Cash and loan are read in the same callback, so they equal that day's `park_snapshot` values. |
| Why that moment | At day 1 nothing has yet been booked to the new month, so the change in (cash − loan) from one statement to the next equals the later statement's 14 lines, to the tenth. |
| Unreadable month | If any history has fewer than 2 entries, no statement is sent and the optional `plugin_stats` field `finance_months_unread_total` goes up by 1. |
| Money units | Tenths of a dollar until one staging conversion to dollars, per column, in `stg_finance_monthly`. |
| Session start | `session_start` is each session's first event (`seq` 1), with the plugin API level, park name, scenario name, whether the game has a window, and game speed. |
| Version line | Four event types and five contracts move together to 1.1.0, a minor bump, because events and one optional field were added. `schema_version` stays 1 and the landing path stays `v1/`. |

## Rejected alternatives

- **Daily or mid-month running totals.** They would add volume and need a rule for which reading stands for
  the month. A statement read once at the close is already exact, and the running total adds nothing the
  P&L needs.
- **Resending older months at session start.** The history holds up to 16 months, so a session could
  resend what it can see. That would make every session repeat months the previous session already sent,
  and it is not needed for a timeline that is read as it happens. It stays possible later (see below).

## Consequences

- **Lost statements.** A statement still queued when the game quits during a listener outage is lost, and
  nothing counts it: the counter covers only a month the plugin could not read, not one it could not
  deliver. P&L work should detect missing months. The game's 16-month history could later fill such a
  gap, at the cost of a new event or a resend rule.
- **Repeated months.** A reload can give two statements for one park and month, one from each session. The
  contract allows this, and later intermediate models resolve it.
- **Date cheats.** A cheat that sets the game date back could mislabel a statement or repeat a month within a
  session (the label comes from the date, the figures from the history), and the contract's key then fails the
  capture, by design. The engine's date cheat was not tested.
- **Last-day blind spot.** An unread-month increment on a session's last day is never reported, the same
  blind spot `plugin_stats` already has for its last period.
- **One version line.** The shared version now spans five contracts and four event types. Adding fields
  is a minor bump for all of them together; a breaking change to any one is a major bump and a new
  landing path for all, as ADR 0007 set out. This ADR does not change that rule.
- **Loan side untested on real data.** The rehearsal's bank loan was 0 throughout, so only the cash side
  of the balance check has run on the plugin's own data. The schema 0 capture's balance held with a 100,000-tenths loan (`docs/FINDINGS.md`, "Ledger reconciliation").

## How we would know this is wrong

- A consecutive pair fails the balance check in a longer run: the day-1 reading is not always the
  closed month, and the read rule needs another look.
- Real play shows statements missing often enough that the P&L cannot detect and fill them from the
  16-month history: resending older months at session start becomes worth its volume.
- A run in which the loan changes fails the balance check. That would mean loan principal does not move
  cash and loan together, as `ARCHITECTURE.md` ("Where cash and counters diverge from the ledger")
  records from the engine source, and the statement would need the loan's change as its own line.
