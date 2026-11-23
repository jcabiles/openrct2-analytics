# ADR 0030: build `dim_date` from kept months, not `dbt.date_spine`

- Date: 2026-10-15.
- Status: Accepted 2026-10-15 by the project owner (shipped with data-layer PR 1, #75).
- Builds on: ADR 0019, section 10 (`:254`), which specifies `dbt.date_spine` for date generation.

## Bottom line

`dim_date` builds dates in SQL from the data the company has kept, not with `dbt.date_spine`. It spans every company date
from the first day of the earliest company month with a kept park-day or kept statement through the last day of the
latest such month, while dropping November through February because parks are closed then. A recursive query steps one
day at a time, so each company month in range has all its days and every fact's day or month-start key resolves. With no
kept data, a null bound stops the recursion before its first row and the table is empty.

## Context

The calendar needs to cover whole company months containing kept park-days or kept statements, including months between
the first and last qualifying months. Dates in November through February are excluded. The recursive form is already
used in `int_sessions__lineage.sql`.

## Decision

Build `dim_date` in SQL from kept data instead of using `dbt.date_spine`. This records a departure from ADR 0019,
section 10 (`:254`), which specifies `dbt.date_spine`; ADR 0019 is unchanged. Use a recursive query with dbt's
cross-database date macros to step from the first day of the earliest qualifying company month through the last day of
the latest. Drop every date from November to February. Each company month present therefore has all its days, every
fact's day or month-start key resolves, and a company year with March and October present has its 245 days. The bounds
come from kept data itself. A null bound stops recursion before the first row, leaving an empty table without a guard.

## What was given up

The model maintains a small recursive query instead of relying on a core macro. It generates and drops about 120 winter
dates per spanned year.

## Consequences

A future time spine for MetricFlow (roadmap NEXT 23) must work with a season-only calendar or add its own.
