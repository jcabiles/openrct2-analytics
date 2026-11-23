# ADR 0032: failed tests on production runs reach the project owner through the shared sender

- Date: 2026-10-16.
- Status: Accepted 2026-10-16 (ruled by the project owner).
- Builds on:
  - ADR 0031 (`docs/adr/0031-missing-game-day-test.md`): the first test whose failure needs a person to replay a save.
  - ADR 0017 (`docs/adr/0017-data-set-from-the-command-line-and-safe-warehouse-paths.md`): production commands name
    their data set on the command line.
- Built by: the alert outbox item in the roadmap NEXT list (`docs/ai-dlc/roadmap/park-company.md`). Nothing in this
  record is built yet.

## Bottom line

When a production run has a failed dbt test, it sends one email digest to the project owner.

- **Which runs alert.** A production run is `make transform`, `make pipeline` or `make publish` with a real data set.
  `make check` never sends.
- **How it sends.** The repo calls the existing shared email sender at runtime and never copies it. The sender's
  location comes from the environment variable `OPENRCT2_ALERT_SENDER`.
- **What the repo passes.** The repo passes facts only. The sender owns the layout and the recipient, and no address
  is ever in the repo or on its command lines.
- **What happens after a send.** Each digest is written to a git-ignored local outbox before it is sent. Its outcome
  is read from the `delivery` field of the sender's receipt, never from its exit code. Only a digest that provably was
  not sent is ever resent automatically. A digest with an unknown outcome is listed for a person to check.
- **What a send never changes.** A failed send never changes dbt's exit code.
- **Read the sender first.** Because the sender's formatting changes often, every change to this path starts by
  reading the current sender.

## Context

- **Who reads the alert.** The reader is whoever runs the pipeline and must act on a failure. For ADR 0031's test,
  that means replaying a named save for a named game month. The alert must carry enough to do that from a phone.
- **The shared sender already exists.** It is a small script with a wrapper that posts to a Google Apps Script web
  app (a script hosted by Google that sends the mail). Other tools use it too. Its recipient comes from its own local
  configuration today, and any recipient it is handed is checked against a fixed allow-list before anything is sent. The
  project owner reformats it often. A copy in this repo would drift from it within weeks.
- **What the sender does today.** Its behaviour was read on 2026-10-16. Read it again before relying on any line
  below.
  - **It never retries.** A retried request would run the Apps Script send again and duplicate the email.
  - **A blocked recipient** gives exit 3 and a `blocked_send` receipt. The check runs before the web request, so
    nothing was sent.
  - **Any other failure** gives exit 4 and a receipt whose `delivery` is `unknown`. This covers a timeout, any non-zero
    exit of the wrapper, and an unreadable token or a malformed payload, both of which the wrapper rejects before
    sending. The email may or may not have been sent.
  - **Exit 0 alone proves nothing.** A request that returns, with exit 0, prints a JSON receipt whose `delivery` is
    `confirmed` or begins with `unconfirmed:`. `unconfirmed:` means a 2xx answer that was not JSON, or one that
    reported failure. A status-page answer would also arrive this way and suggests the send never ran, but no send
    has shown one yet.
  - **`confirmed` means accepted, not delivered.** It means only that Google accepted the request.
  - **It shares a daily ceiling.** Another of the sender's callers counts every receipt against a limit of 10 sends a
    day, so alerts compete with that caller.
- **Past test sends failed.** In past sessions, test sends from sandboxed agent sessions failed until a send
  declared both Google hosts, `script.google.com` and its redirect host `script.googleusercontent.com`. The sandbox's
  network filter refused the two hosts one at a time. That is the cause as observed in past session transcripts, not
  a proven one. One failure at the redirect host probably sent the email anyway: it took as long as a full send. So a
  failed command does not mean "not sent".

## Decision

1. **Reuse the shared sender, called at runtime, never copied.** The repo runs the sender found at the path in
   `OPENRCT2_ALERT_SENDER`. That variable is read in `src/openrct2_analytics/config.py`, the one place that reads
   environment variables (`docs/CONVENTIONS.md:63`). It passes `--subject`, a `--run-id` prefixed `openrct2-`, and the
   body on standard input.
   - **Never `--to`.** The repo never passes `--to`, so no address appears in the repo, in its settings or in a
     process listing.
   - **No path committed.** The sender's path is a private machine path and is never committed.
   - **Where the address lives.** The repo never holds or passes the address, and there is no fallback that does. The
     shared sender reads its recipient from an environment variable in its own configuration, and that value is never
     committed. Until the sender does so, that change is a project-owner follow-up outside this repo
     (`docs/ai-dlc/specs/missing-day.md`, open point O1, resolved).
2. **The repo passes facts, and the sender owns the layout.** For each failed test the digest carries:
   - the test and the model it checks;
   - the data set and the game month;
   - the failing-row count and the command that reproduces the failure, read for every failed test from dbt's run
     results;
   - the failing rows themselves only where the test stores them. Today that is the two missing-day tests (for ADR
     0031's test: park, month, day, sessions on each side and save). A failed test that stores no rows is listed with
     its name, model, count and reproduce command, and the reader reruns it to see the rows;
   - the save to replay, where the test names one.

   The repo adds no styling, so the project owner's formatting changes apply without a repo change.
3. **One digest per production run.** A run with failed tests sends exactly one email that lists every failed test,
   never one email per test, so alerts cannot use up the shared daily ceiling. A digest is sent only for error-level
   failures; warnings are listed inside any digest that is sent, and a run with only warnings sends nothing.
4. **Production runs only.** The digest is wired to `make transform`, `make pipeline` and `make publish` with
   `DATA_SET=rehearsal` or `DATA_SET=company`. It never runs on target `ci`, never from `make check` and never from
   pytest. The repo's dbt test helper already strips every `OPENRCT2_*` variable from dbt's environment
   (`tests/test_dbt_environments.py:52`), so pytest never sees the sender variable.
5. **Write to a git-ignored local outbox before sending.** Each digest is written to the outbox before the sender
   runs, and is then marked with one of three outcomes:
   - **`sent`** only when the receipt's `delivery` is `confirmed`.
   - **`not_sent`** only when there is proof that nothing left the machine. Today that means either:
     - the receipt is a `blocked_send` receipt (exit 3), which the sender writes before any web request; or
     - the sender never started: the variable is unset, or the path is missing or cannot be run.
   - **`unknown`** in every other case, including every other non-zero exit and every `unconfirmed:` receipt.
6. **Outcome from the receipt's `delivery` field, never the exit code.** Exit 0 can carry an unconfirmed send, so the
   exit code alone never marks a digest `sent`.
7. **Automatic resend only for a proven `not_sent`.** The next production run resends `not_sent` digests. It prints
   each `unknown` digest for a person to check and never resends one, because a resend could duplicate an email that
   did arrive.
8. **A failed send never changes dbt's exit code.** The production command exits with dbt's own code, whatever
   happened to the email. A send problem is printed and left in the outbox.
9. **Read the current sender before any change to this path.** Every future change to the alert path starts by
   reading the current shared sender and its wrapper, because their formatting, exit codes and receipt fields change
   often. The roadmap's general run-start section carries this instruction for any email or alert work, and the roadmap item that builds the outbox repeats it.

## What was given up

- **No proof of delivery.** `confirmed` means Google accepted the request, not that the email arrived or was seen.
- **Some lost alerts need a person.** A digest whose send failed in an ambiguous way waits for a person instead of
  healing itself. Until the sender reports typed outcomes, most failures are `unknown`.
- **Detail waits for the next run.** One digest per run means a run with many failures sends one long email, and an
  unknown digest is only listed on the next production run.
- **Dependence on files outside the repo.** The repo depends on a sender it does not version. A sender change can
  break the alert path without any change here, which is why decision 9 exists.

## Consequences

- **The outbox is built later.** It is a separate roadmap item that comes after the missing-day test. That item
  chooses the outbox folder, which must be git-ignored. It also chooses how the digest reads failing rows from dbt's
  results.
- **Agent sessions must declare both hosts.** A production run started from a sandboxed agent session must declare
  both Google hosts on the command. Otherwise the send fails, as observed in past sessions.
- **Improvements on the sender's side are follow-ups for the project owner, outside this repo.** None of them blocks
  the outbox.
  - typed outcomes and separate exit codes from the sender (`not_sent`, `unknown`, `accepted`), which would let the
    outbox prove more failures were not sent;
  - a duplicate guard on the Apps Script side, keyed on an alert ID, which would make resends safe;
  - a sender that runs outside the sandbox on a schedule;
  - a heartbeat line in an existing daily email, so that silence can be told apart from a broken path;
  - a mail filter that keeps alerts out of spam.
