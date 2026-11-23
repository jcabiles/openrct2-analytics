# AI-Org state — openrct2-analytics
domain:       engineering
artifact_dir: docs/ai-dlc
active:       sandbox-hide
report_tier:  auto
conventions:  docs/CONVENTIONS.md
process:      agents push feat/*, fix/*, chore/* branches and open PRs against develop; an agent merges into develop only after its reviewer passes and make check is green; the overnight director merges its own PRs into develop under the same rule (director merge: self-when-green, project owner, 2026-11-18); never push main; merges into main are the project owner's
hotspots:     plugin/src/main.ts (sole event producer) · contracts/ · pyproject.toml + uv.lock · package.json + package-lock.json · dbt_project.yml · Makefile · src/openrct2_analytics/ingest/convert.py (seq audit; never-break rules 1 and 2) · models/staging/ (the one money conversion; never-break rule 3)

verify:
  check: make check

invariants:
  - Every event carries `park_id`, `session_id`, `seq`, `event_id`, game date, and `emitted_at`; `seq` has no gaps or duplicates within a session. (From contract v1; the 2026-09-27 capture is schema 0.)
  - Raw captures are append-only; every fix happens downstream in dbt. The one exception: before go-live, `make delete-company-data` archives and then rewrites or removes company raw captures and registry deliveries (ADR 0033).
  - Money stays in the game's tenths of a dollar until one staging conversion; every metric names its unit and its clock (game day, company date, or wall-clock hour).
  - Build previews and client-side predictions never count as player actions.
  - Never commit RollerCoaster Tycoon files, game screenshots or video frames, the GPL type definitions, or private machine paths. Game footage lives on a video hosting site and the site links to it (ADR 0047).
  - The contract is versioned: adding fields is a minor bump; a breaking change is a major bump and a new landing path.
  - Analyses state their sample (parks, players) and say "observational" unless an experiment design backs a causal claim.
  - The plugin compiles to ES5 and stays within its measured per-tick cost budget.

director:
  base: develop
  merge: self-when-green
  hazards:
    - readiness: load average 3.0 or higher means no benchmark ticket this run
    - run-rule: a benchmark ticket runs as a wave of one, with no other worker in flight
    - pre-ruling: any step that touches real saves, old park backups or game data parks unless authorizations.md names it
