# ADR 0004: dbt Core 1.x on DuckDB

- Date: 2026-09-27
- Status: Accepted

## Context

dbt now ships a v2 / Fusion engine alongside the 1.x line. The precedent
repo (`poker-analytics`) already runs a dbt 1.x + DuckDB warehouse
successfully, and dbt Core 1.x remains supported.

## Decision

Pin `dbt-core==1.11.15`, `dbt-duckdb==1.11.0`, and `duckdb==1.5.5` in
`pyproject.toml`. `dbt-core` stops one line short of the newest stable
1.12.x release because 1.12 added a `dbt-core-experimental-parser`
dependency whose build step fetches a prebuilt wheel straight from a GitHub
release, which does not install in a sandboxed build environment; 1.11.0
itself is yanked for dependency-bound issues, so this lands on 1.11.15, the
newest non-yanked 1.11.x release.

## Consequences

- The warehouse matches the precedent repo's toolchain line, so lessons
  learned there (profiles, model layering) carry over directly.
- Moving to dbt v2 / Fusion is a future migration, not a v1 concern; this
  ADR is the flag to revisit when that engine matures.
