# ADR 0045: site data holds the department exports

- Date: 2026-11-02
- Status: Accepted; superseded in part by ADR 0056 (the count of served files)

## Bottom line

`site/_data/` grows from three files to six. The three new files, `ride_month.json`, `ride_year.json` and `park_month_revenue.json`, carry the figures of the Operations and Attractions department panels and the Finance revenue mix. This amends the three-file bound that the site page port set for itself (the page-port work held `site/_data/` to exactly three served JSON files, each with a fixed name, columns and shape): that bound limited the page port's own scope and does not limit later items.

## Context

The page port leaves `site/exports.toml` and `site/_data/` unchanged, so the site served only `park_month.json`, `park_year.json` and `company_year.json`. The department-figures item adds the marts `obt_ride_month` and `obt_ride_year` and the revenue lines and shares of `obt_park_month`, and the panels that read them need those columns served as committed JSON.

## Decision

1. **Three allowlist entries are added to `site/exports.toml`, and nothing else in it changes.** Each copies columns as delivered; the export computes nothing. The columns are those a served panel reads, plus the key, label and period columns needed to show them.
2. **No visit-based column is exported.** `guest_visits` and every `_per_visit` column stay out of the served files.
3. **The files are written by `make site-export` and compared with a fresh sample build by `make check`**, as for the existing three.
4. **Any test that pins the list of files in `site/_data/` lists the six files.**

## Consequences

- Gain: the panels can read ride and revenue figures without any computation in the page.
- Cost: three more committed files to regenerate whenever a ride or park-month mart column changes; the export comparison in `make check` fails until they are.
- The page port's three-file bound on `site/_data/` is amended, not superseded: its other limits stand.
