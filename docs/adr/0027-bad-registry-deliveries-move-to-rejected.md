# ADR 0027: a bad registry delivery is moved to `rejected/`, never edited or exempted

- Date: 2026-10-09
- Status: Accepted, as a run ruling of 2026-10-09 on the spec for roadmap NEXT 16 (the company calendar); shipped in PR #59.
- Superseded in part by ADR 0033 (2026-10-17), for company data before go-live.

## Bottom line

A registry feed file that fails its data contract is moved out of the feed's `v1/` folder into a sibling `rejected/`
folder by the outside process that delivers the feed. No repo command edits, deletes or exempts a landed file. What is
given up is automatic recovery: a bad file that lands stops every build until someone moves it.

## Context

ADR 0023 makes the feed append-only: corrections are new dated deliveries, and no landed file is edited. That leaves open
what happens when a file fails its contract anyway, for example because the pre-landing check was skipped. The checks run
fail-closed, so one bad file stops `make contracts`, `make transform` and the publish.

## Decision

1. The outside process runs `registry_feed --file <path>` on a file under a non-matching name and renames it into `v1/`
   only if the check passes, so nothing failing lands.
2. A file that lands anyway makes the checks fail and name it. The cure is the outside process moving it to
   `data/<set>/registry/rejected/`, outside the feed glob, with a one-line reason file beside it.
3. The snapshot and every check read only `v1/`.
4. This is landing hygiene, not a correction: corrections stay append-only dated deliveries.

## What was given up

A bad landed file stops every build until it is moved, and the outside process owns one more step.

## Rejected alternatives

- **A repo-side exemption list.** It would be a second record of what the feed means, outside the feed.
- **Editing or deleting the landed file in place.** It breaks append-only landing and loses what was believed when.

## Consequences

- `ARCHITECTURE.md` ("Environments and publishing", "Registry feed landing") states the landing steps.
- **How we would know this is wrong:** bad files land often enough that the manual move becomes routine. The check would
  then move to a quarantine step in the repo, which reopens this record.
