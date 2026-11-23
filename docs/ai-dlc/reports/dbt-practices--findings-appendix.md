# dbt practices research: Appendix A, package detail

This appendix holds the per-package facts behind section 7 of `docs/ai-dlc/reports/dbt-practices--findings.md`; the verdicts are in that report's adoption matrix.

## Appendix A. Package detail

Against the package bar: dbt Labs or known vendor, on the package hub, a release within six months, supports dbt-duckdb and Core 1.11. All as of 2026-10.

| Package or tool | Maintainer | Latest release | Core 1.11 | dbt-duckdb | Meets the bar? |
|---|---|---|---|---|---|
| dbt-project-evaluator | dbt Labs | 1.4.0; release date unverified (2026-09-25 per lane 2 is not established by the cited pages) | `>=1.10.6,<3` (https://hub.getdbt.com/dbt-labs/dbt_project_evaluator/latest/) | explicit, with dispatch setup (https://github.com/dbt-labs/dbt-project-evaluator) | **Possibly**: two lanes agree; not run |
| dbt-utils | dbt Labs | 1.4.1, 2026-06-28 | declared range includes 1.11 | not in `supported_adapters.env` (https://github.com/dbt-labs/dbt-utils/blob/main/supported_adapters.env); lane 3: macro-specific | No: DuckDB unverified |
| dbt-audit-helper | dbt Labs | 0.14.0, 2026-05-19 (lane 2; lane 3 unverified) | declared range includes 1.11 | not in its adapter list | No: DuckDB unverified |
| dbt-expectations (Metaplane fork) | Metaplane | 0.10.10, 2025-12-02 | declared range includes 1.11 | README lists DuckDB; test config lists only Postgres (https://github.com/metaplane/dbt-expectations) | No: conflicting; original Calogica project unmaintained |
| dbt-date | Calogica | last release 2024-04 (https://github.com/calogica/dbt-date) | range excludes v2 | not checked | No: unmaintained |
| Elementary | Elementary Data | 0.26.0, 2026-09-08 | declared range includes 1.11 | in its test matrix (https://docs.elementary-data.com/oss/oss-introduction) | On paper; rejected for needing run history |
| dbt_artifacts | Brooklyn Data | 2.11.1, 2026-09-23 | `>=1.3.0,<3.0.0` | absent from its list | No |
| codegen | dbt Labs | 0.14.1, 2026-05-07 (https://github.com/dbt-labs/dbt-codegen/releases, lane 3) | `>=1.1.0,<3.0.0` | not verified | No: DuckDB unverified; contract-generated sources do its job |
| Snowplow, GA4, Segment | vendors and dbt Labs | Segment hub page outdated | Segment pinned `>=1.3.0,<2.0.0` | GA4 BigQuery-only (https://github.com/Velir/dbt-ga4) | No |
| dbt-llm-evals | Paradime | v1.0.1 per lane 12; hub listing disputed | not checked | no (Snowflake, BigQuery, Databricks) | No |
| data-diff | Datafold | 0.11.1, 2024-02-20, archived 2024-05-17 | n/a | n/a | No: archived |
| Recce | DataRecce | 1.66.0, 2026-09-23 | reads dbt artifacts | local DuckDB documented (https://docs.reccehq.com/getting-started/oss-setup/) | Not a dbt package; a new Python dependency |
| dbt-metricflow | dbt Labs | 0.15.0, 2026-09-10 (https://pypi.org/pypi/dbt-metricflow/json) | `>=1.11,<1.13` | `dbt-duckdb` extra | Not a hub package; a Python dependency for R3 |
