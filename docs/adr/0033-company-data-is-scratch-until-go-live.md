# ADR 0033: Company data is scratch until go-live

- Date: 2026-10-17.
- Status: Accepted 2026-10-17 (ruled by the project owner at Gate 1 for the company data delete roadmap item).
- Supersedes in part: ADR 0023 (`docs/adr/0023-company-dates-from-a-park-registry-feed.md`), its "deliveries are append-only" rule, for company data before go-live only.
- Supersedes in part: ADR 0027 (`docs/adr/0027-bad-registry-deliveries-move-to-rejected.md`), its "never edited or exempted" rule, for company data before go-live only.

## Bottom line

Before go-live, `make delete-company-data` may archive and then rewrite or remove
company raw captures and registry deliveries: all company data, one park, or one
session, after an exact typed confirmation. Copies are verified by SHA-256 before
any original changes. After either go-live marker exists, raw captures and
registry deliveries are permanent; only rebuildable files may be deleted.

Rehearsal and ordinary ingestion retain their existing rules. Two safety rules
belong to this decision. First, the command refuses before any lock or write,
previews included, when `data/company` is a symlink or does not resolve to the
company folder under the resolved data root, so it can never reach rehearsal data
through an alias. Second, it refuses when the archive folder or the dated run
folder is a symlink, or when the resolved archive folder lies inside the project
folder or the data root, so a verified copy always lands outside the data it
protects.

## Rationale and consequences

Throwaway play must be removable before publishing starts, without turning a
mistake into silent loss. An external verified archive and a manifest permit
manual recovery. Derived files are removed first and never archived: conversion,
transformation, and publishing rebuild them from the retained originals.

`OPENRCT2_STATE_DIR` defaults to the platform application-data folder for
`openrct2-analytics`: `~/Library/Application Support` on macOS,
`$XDG_DATA_HOME` or `~/.local/share` on Linux, `%LOCALAPPDATA%` on Windows.
Archives live in its `archive/` folder. Its `go-live-company.json` marker and a
second `company/go-live.json` beside company data independently prohibit raw
deletion. Unreadable or corrupt marker evidence fails closed.

`make go-live` refuses until the roadmap's "A way around the seq stop in make
pipeline" exists. Otherwise one permanent seq gap could block every later run.
The marker writer ships and is tested directly so that permanent-state deletion
rules are already enforced. ARCHITECTURE.md documents crash recovery and limits.
