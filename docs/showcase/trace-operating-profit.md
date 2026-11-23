# Trace: April's operating profit, from the page back to the game

**Bottom line.** The showcase page shows an April bar of $6,649.90 (US dollars, company month April of company year
2000). That figure is built from ten ledger lines the game itself recorded, in nine steps: each step below names its file,
April's value there and the check that covers it. Hop 1's drawn bar and its label are judged in a browser; `page_check` checks the embedded value the chart reads. Every other
hop names a command or test that fails if the value
changes. The same trace applies to every other bar. The sample behind it is observational: one
park and three headless game sessions with no player, so it shows the pipeline works, not that any change in the park
caused any change in profit.

A "headless" session is a game run with no window and no player. A "hop" is one step in the chain from the page back to the game.
Operating profit is the sum of the ten ledger lines for running the park (ticket, food, shop, running-cost, wage,
stock, marketing and research lines). It leaves out construction, land, landscaping and interest.

## Hop 1. The page

`site/index.njk` assembles the page from the templates in `site/_includes/`. Its park-years table lists company year 2000 with "3 of 8" statements kept, a status of not closed, and operating profit $14,117.20 labelled "not yet reconciled". Under "Closed company years" the page shows "No company year has closed yet." and no table, because the sample holds one park and three months.
The chart rows are embedded in the page as JSON, the same rows fill the month table (`#park-month-table`), and `site/assets/park-month-chart.mjs`, the restyled Plot chart in the Finance view, draws one bar per row; Plot stacks the bars of one company month, and with one park each month holds one bar, so no value is changed (the chart picks each park's first row by comparing a row's `park_id` with the previous row's). The Finance view's range brush and park switch redraw the chart with the rows they choose; they do not change a value. The April bar is the second of three bars, labelled Apr 2000 (company date 2000-04-01; the bar and its label are
drawn in the reader's browser, so they are judged in a browser; `page_check` checks the embedded value). Its embedded row holds the value 6649.9: the
page writes the row as a JSON number, which equals the served file's 6649.90 by number but not as text. The park-year row's Months checked cell shows 2; the first month is not counted (see hop 4).
Proof: `.venv/bin/python -m openrct2_analytics.showcase.page_check --site <built site> --served-dir site/_data`.

## Hop 2. The served files

`site/_data/park_month.json` holds the April row: `statement_company_date` 2000-04-01, `operating_profit` 6649.90.
`site/_data/park_year.json` holds the one roll-up row: `company_year` 2000, `statements_kept` 3,
`statements_expected` 8, `close_status` "open", `months_checked` 2, `operating_profit` 14117.20.
`site/_data/company_year.json` holds no rows. These files are written from the warehouse by `make site-export`
(`src/openrct2_analytics/showcase/export.py`), and `make check` runs `export check`, which rebuilds the rows from the
warehouse and fails if any file differs by one value.

## Hop 3. The park-year mart

`models/marts/obt_park_year.sql` sums `operating_profit` over the kept months of each park and company year. April's
$6,649.90 is one of three months: 4,073.60 (March) + 6,649.90 (April) + 3,393.70 (May) = $14,117.20, the year's total.
`statements_kept` is 3, and `months_checked` is 2 because the first month has nothing to be checked against. The
page's table takes its statement count and company year from the mart columns `statements_kept` and `company_year`,
not from text typed into the page. The test `tests/dbt/assert_obt_park_year_reconciles_exactly.sql` recomputes
the same sums from `obt_park_month` and fails if the two disagree.

## Hop 4. The fact mart

`models/marts/fct_park_month.sql` has one row per park and closed game month. Its `operating_profit` column adds
ten `_usd` columns: `park_ride_tickets_usd` 5,736.00 + `food_drink_sales_usd` 1,177.30 + `shop_sales_usd` 3,483.00 +
`park_entrance_tickets_usd` 0.00 + `ride_runningcosts_usd` -281.00 + `wages_usd` -2,716.00 + `shop_stock_usd` -389.50 +
`food_drink_stock_usd` -359.90 + `marketing_usd` 0.00 + `research_usd` 0.00 = $6,649.90. April's other columns:
`capital_spending` 0.00, `interest_usd` 0.00, `net_cash_change_usd` 6,649.90 and `months_since_previous_statement` 1.

Three checks guard this model. The identity test `tests/dbt/assert_park_month_cash_change_reconciles_exactly.sql`
requires that operating profit plus capital spending plus interest equals the change in cash less loan, less the money already booked to the new month, from the
previous month, with no month missing in between. The exact-count test `rows_on_sample`
(`tests/dbt/generic/rows_on_sample.sql`) requires 3 rows on the sample. The unit test
`fct_park_month_keeps_the_kept_timeline_and_computes_the_previous_statement_columns` in
`models/marts/fct_park_month.yml` feeds small invented inputs through the model.

The first month has no earlier statement to reconcile. March, this park's first statement, has a null
`net_cash_change_usd` and is exempt from the identity: its $4,073.60 bar and its share of the $14,117.20 year total are
tied to the game's ledger lines but not to the cash balance. April's cash less loan rose from 234,902.70 to
241,552.60, a change of 6,649.90, which equals its operating profit.

## Hop 5. The kept label and the company date

`models/intermediate/int_statements__labeled.sql` gives each statement a label and a date. The macro
`macros/timeline_status.sql` labels an event `kept` when its session is on the kept path and its `seq` is below the
session's cut point; April is `kept`. The company year is `company_start_year + (statement_year - game_year_origin)`,
computed in `models/intermediate/int_park_years__registry_mapped.sql`, which `int_statements__labeled.sql` joins on
`park_id` and `statement_year`. The registry feed row in
`data/sample/rehearsal/registry/v1/park_registry_2026-10-21_01.csv` gives company start year
2000 and game-year origin 9, and April's `statement_year` is 9, so its company year is 2000. The call in
`models/intermediate/int_statements__labeled.sql` passes day 1; `macros/company_date.sql` turns `statement_month` 1 into
month 1 + 3 = 4 and uses the day it is given, so the date is
2000-04-01. The cut point comes from `int_sessions__lineage` (joined as `lineage`), and the company year is null unless
`mapping_status = 'mapped'`; April is mapped.
Proof: the registry feed check (`.venv/bin/python -m openrct2_analytics.ingest.registry_feed --data-root
data/sample/rehearsal`, run by `make check`) checks the registry file against its contract, the identity test of
hop 4 fails if a statement between two kept statements is dropped, and `rows_on_sample` fails on any lost row of the
sample, and the unit test
`int_statements__labeled_u12_dates_from_statement_year` (`models/intermediate/int_statements__labeled.yml:163`)
feeds a year-model row with start year 2000 and origin 9 and expects company year 2000.

## Hop 6. The money conversion

`models/staging/stg_finance_month.sql` is the one place money changes unit, using `macros/tenths_to_usd.sql`: it
multiplies each game value (tenths of a dollar) by 0.1, one ledger field at a time.
Proof: the unit test `stg_finance_month_converts_every_money_column_to_usd` (`models/staging/stg_finance_month.yml`)
converts all 17 money columns from invented values, and `tests/test_dbt_tenths.py` checks the macro is exact and keeps
nulls. For April:

| Field (tenths) | Tenths | Dollars |
|---|---|---|
| `park_ride_tickets_tenths` | 57,360 | 5,736.00 |
| `food_drink_sales_tenths` | 11,773 | 1,177.30 |
| `shop_sales_tenths` | 34,830 | 3,483.00 |
| `park_entrance_tickets_tenths` | 0 | 0.00 |
| `ride_runningcosts_tenths` | -2,810 | -281.00 |
| `wages_tenths` | -27,160 | -2,716.00 |
| `shop_stock_tenths` | -3,895 | -389.50 |
| `food_drink_stock_tenths` | -3,599 | -359.90 |
| `marketing_tenths` | 0 | 0.00 |
| `research_tenths` | 0 | 0.00 |

The tenths sum to 66,499, which is $6,649.90. April's `ride_construction_tenths`, `land_purchase_tenths`,
`landscaping_tenths` and `interest_tenths` are all 0.

## Hop 7. The contract

`contracts/finance_month.odcs.yaml` (version 1.8.0) defines the `finance_month` event. Its rule for the statement
month says the statement month is the month before the event's own game date: April's statement (`statement_month` 1)
arrives on day 1 of game month 2 (May). The contract also requires every statement to be read on game day 1.
Proof: the contract check (`.venv/bin/python -m openrct2_analytics.ingest.contracts --data-root data/sample/rehearsal`,
run by `make check`) fails if the sample Parquet breaks the contract.

## Hop 8. The event

The sample file `data/sample/rehearsal/v1/finance_month.parquet` holds April's event: `event_id`
s1792587801446-3lzf29-1482, `seq` 1482, `game_year` 9, `game_month` 2, `game_day` 1, `statement_year` 9,
`statement_month` 1, and the ten tenths values of hop 6 plus `cash_tenths` 2,415,526. The plugin code that emits it is
`statementForToday` in `plugin/src/finance.ts` (line 42). On day 1 it reads index 1 of each of the game's expenditure
histories, which is the month that just closed (the reasoning is in
`docs/adr/0008-money-arrives-as-closed-month-statements.md`), and `plugin/src/main.ts` (line 54) emits it as a
`finance_month` event.
Proof: the contract check of hop 7 covers the Parquet's fields, and `node --test plugin/test/*.test.mjs` (run by
`make check`) covers the plugin side. The Parquet is the converted form (`make convert`) of the raw JSON Lines capture
under the data set's raw folder, data/<set>/raw/ (not committed), and is never edited (`CLAUDE.md`, "Never break" 2); each
Parquet row's `_raw_file` and `_raw_line` name its source line.

## Hop 9. Re-running it

From the root of a worktree after `make setup`:

- `make check` runs the whole chain, including the export comparison, the site build and the page check.
- `make site-export` rebuilds the served files, and `git diff --exit-code site/_data` then exits 0.
- To query April yourself, build the sample on the `ci` target, then read `marts.fct_park_month` where
  `statement_month = 1`. `OPENRCT2_CI_DIR` is the scratch folder the `ci` target writes its warehouse to:

  ```sh
  export OPENRCT2_CI_DIR="$(mktemp -d "${TMPDIR:-/tmp}/trace-ci.XXXXXX")"
  .venv/bin/dbt build --profiles-dir . --target ci \
      --target-path "$OPENRCT2_CI_DIR/target" --log-path "$OPENRCT2_CI_DIR/logs" \
      --vars "{parquet_root: data/sample/rehearsal}" \
      --select +obt_park_year --indirect-selection buildable
  ```
- The balance check in `data/sample/rehearsal/README.md` ("Balance check") gives the same April and May figures from
  the raw file alone.

All figures above were read from a build of the sample on the `ci` target. The sample is one park, three headless
sessions and no player, so every statement here is observational.
