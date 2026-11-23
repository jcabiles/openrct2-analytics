# Agent tickets

Small, fully specified tickets that Codex, Gemini or Claude may pick up without the ai-org
build process. The procedure is in `AGENTS.md`, "Working an agent ticket". Claude or the project
owner adds tickets here; only a reviewer checks a box, after the fix is reviewed and merged.

Each ticket names its id (used for the branch `ticket/<id>`), the bug or task, how to confirm it
(a command or a test that fails today), and where it came from.

<!-- - [ ] **<id>**: <the bug or task in one sentence>. Confirm: <command or failing test>. Source: <roadmap item or spec path>. -->

Retired on 2026-11-15: "after-play-park-prompt" (the shipped launcher filing, ADR 0051, and the roadmap block "Player-friendly game for strangers" replace it; start years stay automatic) and "dashboard-company-summary" (it targeted the dashboard code that the five-page app, ADR 0054, replaced).
