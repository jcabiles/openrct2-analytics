# ADR 0054: the local dashboard is a five-page app fed by one data file

- Date: 2026-11-15.
- Status: Accepted 2026-11-15.

## Bottom line

`make dashboard` now serves a five-page dashboard app (Executive, Finance, Attractions, Pricing, Operations) instead
of the showcase website. On each page load after the development warehouse changed, the server copies the warehouse,
runs plain SQL over its marts into one data file, `data.js`, and serves the app's fixed files with it. The site build,
the export step, the page check and the sample restatement leave the dashboard path; `make site-company` keeps them.
Gain: a dashboard the project owner can use while playing, rebuilt in under a second. Cost: the pages compute their
sentences and totals in the browser from the marts, outside the site's page check, so a wrong total there is caught
only by the tests in `tests/test_dashboard.py` and `tests/test_dashboard_data.py`.

## Context

The first local dashboard (PR #146) served the showcase website filled from the working copy. The project owner
expected a dashboard app, not the website: "i thought this would be a user-friendly dashboard, not the webpage". Five
interactive page mockups were approved for build, with the note "We can redesign later. I approve this." The
mockups carried their figures as fixed values; the build must read them from the warehouse.

## Decision

- **One data file.** `src/openrct2_analytics/dashboard/data.py` opens the warehouse copy read-only, reads only the
  `marts` schema, and returns one dict that the server writes as `window.DASHBOARD` in `data.js`, stamped with the
  warehouse file's time. The app's files in `src/openrct2_analytics/dashboard/app/` are static and hold no figure,
  year, ride or park name.
- **Season cutoff.** A day counts only when its month has a monthly statement in the scope (the company statement for
  all parks, the park statement for one park) and the park day is kept. Days after the last statement, such as the
  first days of a season whose March has not closed, wait until their month closes.
- **Ride selection.** A ride is a `fct_ride_day` row classified `ride`, keyed by park and ride name (a rebuilt ride
  keeps its name), and shown only when it carried at least one rider on a counted day.
- **Every page states its sample** (parks, one player, game days) and says "Observational."
- **With one year of data** the pages render and say there is no earlier year to compare.
- **Server behavior kept:** the copy-and-WAL safety, the fingerprint (one rebuild per warehouse change), the last good
  build after a failure, the banner on every page, the practice-park and data-set warnings, the port refusals and
  `--detach`. `/` serves the Executive page.

## Rejected options

- **Keep the website and restyle it.** Gain: one set of pages. Cost: the website is a public story, not a working
  dashboard, and each rebuild ran the full Eleventy build and page check.
- **Query DuckDB from the browser.** Gain: pages could ask new questions. Cost: a browser DuckDB package, a new
  dependency, and the server would have to serve the warehouse copy.

## Consequences

- A rebuild takes about half a second on the 2026-11 company copy, against a full site build before.
- The data file is about 300 KB for two company years and grows with days and rides.
- The ride families come from a table of OpenRCT2 ride type numbers in `data.py`; a type outside it shows as "Other".
- `tests/dashboard_smoke.mjs` runs each page's scripts in Node against a data file and clicks every control; it does
  not check layout or drawing, which no test covers yet.
