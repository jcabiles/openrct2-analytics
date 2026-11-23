# openrct2-analytics

The repo facts, commands, constraints and the ticket procedure every agent shares are in `AGENTS.md`:

@AGENTS.md

This file keeps only what is specific to Claude Code.

## Process

Claude pushes feature branches and opens PRs against `develop`, the integration branch, and merges a PR into `develop` only after its reviewer passes and `make check` is green. Codex and Gemini commit only and never push or merge (see `AGENTS.md`). Only the project owner merges `develop` (or anything else) into `main`.

Every commit ends with the `Agent-Vendor:` and `Agent-Model:` trailers (see `~/.claude/AGENTS.md`).
