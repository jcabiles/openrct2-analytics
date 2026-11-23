{% docs __overview__ %}

# OpenRCT2 analytics warehouse

This warehouse holds the park, ride and finance events captured from the game, modeled into tested fact and dimension tables and month summaries. Every number published from it is tested against the game's own values.

## Bus matrix (built models)

A bus matrix lists which dimensions (the "by what" tables) each fact table (one row per measured event) can be sliced by. A mark means the fact's YAML has a `relationships` test to that dimension; "through `dim_ride`" means it reaches the dimension by way of `dim_ride`, which has its own `relationships` test to it.

| Fact | What it holds | `dim_park` | `dim_ride` | `dim_item` | `dim_date` |
|---|---|---|---|---|---|
| `fct_park_day` | admissions, weather | x | | | x |
| `fct_park_month` | finance | x | | | x |
| `fct_ride_day` | ride and stall operations, no sales | x | x | through `dim_ride` | x |

The built summary tables and the facts each reads:

| Summary table | Reads |
|---|---|
| `obt_park_month` | `fct_park_month`, `fct_park_day` |
| `obt_company_month` | `fct_park_month`, `fct_park_day` |
| `obt_park_year` | `obt_park_month`, `fct_park_month`, `int_park_years__year_close` |
| `obt_company_year` | `obt_park_year` |
| `obt_ride_month` | `fct_ride_day`, `dim_ride`, `dim_date` |
| `obt_ride_year` | `fct_ride_day`, `dim_ride`, `dim_date` |

Stall sales are planned and not built; the ride-day facts carry no sales today.

## One number, traced

April's operating profit as the page shows it is $6,649.90 (US dollars, company month April of company year 2000). One line per hop, from the game to the page:

1. The game emits a `finance_month` event for April, with money in tenths of a dollar (66,499 in total).
2. `contracts/finance_month.odcs.yaml` defines the event and its fields.
3. `stg_finance_month` converts tenths to dollars, once, for every money column.
4. `int_statements__labeled` marks the statement as kept and gives it its company date, 2000-04-01.
5. `fct_park_month.operating_profit` adds ten ledger lines to $6,649.90.
6. `site/_data/park_month.json` serves that row unchanged.
7. The operating profit page draws it as the April bar.

Each hop's check is in `docs/showcase/trace-operating-profit.md`.

## Planned page groups

- Executive reporting, declared by the exposure `executive_reporting`: yearly and monthly visitors, revenue, profit and costs per park and for the company.
- Ride profitability, declared by the exposure `ride_profitability`: profit by ride type and ride statistics.
- Stall profitability, declared by the exposure `stall_profitability`: purchases (not unique customers) and profit drivers per single-item stall.
- The stack is described here in words, not declared: versioned data contracts with a CI gate, separate development, test and production warehouses, layered dbt models ending in a star schema, trust tests, interactive dashboards, and direct DuckDB query access.
- The operating profit page, declared by the exposure `operating_profit_page`, is built today.

## About the sample

The committed sample is rehearsal data: one park and three headless game sessions (runs with no window and no player). Everything here is observational; it shows the pipeline works, not that any change in the park caused any change in profit.

{% enddocs %}
