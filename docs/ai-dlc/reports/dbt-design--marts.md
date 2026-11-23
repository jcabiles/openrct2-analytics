# dbt design: one design note per mart — research findings
status: drafted by agents; accepted provisionally with ADR 0016 by the project owner on 2026-10-03 (verify: owner-later); cross-family reviews applied · date: 2026-10-03 · initiative: park-company (roadmap NEXT 3·0, the dbt design session) · companion to `docs/ai-dlc/reports/dbt-design--findings.md` and `docs/adr/0016-dbt-design.md`

## Bottom line
- **Accepted provisionally on 2026-10-03; marts may be built, because the project owner confirmed the requirements brief on 2026-10-03.** Only the marts in `models/marts/` are built so far (`fct_park_day`, `fct_park_month`, `fct_ride_day`, `dim_date`, `dim_park`, `dim_ride`, `dim_item`, `obt_park_month`, `obt_company_month`, `obt_park_year` and `obt_company_year`); the rest are designs. Each note is the design a mart's build spec starts from, and it is reviewed before that mart is built (ADR 0012, "Design review").
- **Nine star-schema tables serve all 39 catalog names** (37 metrics plus 2 helper metrics in `metrics/catalog.yml`, merged to `develop` at 3a01f17 and confirmed by the project owner on 2026-10-03): five dimensions (park, ride, item, company date, session) and four facts (park-day, park-month, ride-day, ride boarding). A small set of wide reporting tables built from them holds every number the site publishes, because ADR 0015 (proposed) makes each published number a mart column.
- **Every fact keys on the game date, not the company date.** Under ADR 0023 (company dates come from the park registry feed) a corrected registry row changes a row's company date; a key built on the game date stays the same, and the company date is carried as an attribute and as the time dimension.
- **One clock per measure, named.** Every fact here runs on the company date (day or month), with the game date beside it. None of the 39 names uses the wall-clock hour; the plugin's own health data (`plugin_stats`) would be the only wall-clock mart and is not designed here.
- **A guest cohort mart is designed but deferred.** No catalog metric needs it; it waits for the satisfaction and length-of-stay work after v1 (roadmap NEXT 9 and 10).

## How to read a note
Each note follows the four-step design ADR 0012 adopted from Kimball (business process, grain, dimensions, facts) and adds what this repo needs: the key, the clock, the sources, the catalog metrics served, and the tests. Metric numbers are the rows of section 7 of `docs/requirements-brief.md` (1 to 37, as confirmed on 2026-10-03); the two helpers are numbered 38 and 39 here, in their catalog order. "Kept" means a row on the kept timeline after save lineage (ADR 0006); marts read kept rows only. Every column is a table column (ADR 0013, proposed); every money column is `DECIMAL(18,2)` in dollars, converted once in staging (`CLAUDE.md` "Never break" 3). Test severity is `error` unless the note says `warn`. Every mart also carries `rows_on_sample` with the count listed in section 6.2 of the findings report; a mart the sample cannot fill (boardings, the two annual tables) is checked there by its enforced contract alone.

## Coverage: which mart serves each catalog name
**All 39 names have a serving mart, a stored grain, a unit and a clock.** "Month and year tables" means `obt_park_month`, `obt_company_month`, `obt_park_year` and `obt_company_year`. Every clock is the company date; the stored grain says whether by day or by month, and the year tables re-aggregate it by company year. Money is in dollars, `DECIMAL(18,2)`, costs negative as the ledger signs them. Checked name by name against `metrics/catalog.yml` on `develop` (3a01f17); metrics 34 to 37 were added with the confirmation of 2026-10-03.

| # | Catalog name | Inputs (fact) | Published in | Stored grain | Unit | Clock |
|---|---|---|---|---|---|---|
| 1 | `operating_profit` | `fct_park_month`: 2 + 10 | month and year tables | park × company month | usd | company date (month) |
| 2 | `operating_revenue` | `fct_park_month`: 3 + 4 + 5 + 6 | month and year tables | park × company month | usd | company date (month) |
| 3 | `ride_revenue` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 4 | `food_drink_revenue` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 5 | `merchandise_revenue` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 6 | `entrance_revenue` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 7 | `ride_revenue_by_ride` | `fct_ride_day` (rides, photo sales excluded) | `obt_ride_day` | ride occupancy × game day | usd | company date (day) |
| 8 | `food_drink_revenue_by_item` | `fct_ride_day` (food and drink stalls, by `item_code`) | `obt_ride_day` | stall occupancy × game day | usd | company date (day) |
| 9 | `merchandise_revenue_by_item` | `fct_ride_day` (merchandise stalls and photo sales, by `item_code`) | `obt_ride_day` | ride or stall occupancy × game day | usd | company date (day) |
| 10 | `operating_costs` | `fct_park_month`: 11 + 12 + 13 + 14 + 15 | month and year tables | park × company month | usd | company date (month) |
| 11 | `ride_running_costs` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 12 | `staff_wages` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 13 | `stock_costs` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 14 | `marketing_costs` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 15 | `research_costs` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 16 | `capital_spending` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 17 | `interest_costs` | `fct_park_month` | month and year tables | park × company month | usd | company date (month) |
| 18 | `guest_visits` | `fct_park_day.admissions_increase` | month and year tables, summed | park × game day | count of visits | company date (day) |
| 19 | `average_park_rating` | `fct_park_day.park_rating` | month and year tables as `park_rating_sum` and `operating_days`; the average is `park_rating_sum` ÷ `operating_days` at every grain, never summed or averaged across rows | park × game day | engine units, 0 to 999 | company date (day) |
| 20 | `operating_days` | `fct_park_day`, rows counted | month and year tables, summed | park × game day | simulated game days | company date (day) |
| 21 | `revenue_per_visit` | 2 ÷ 18 | month and year tables, divided after summing | park × company month | usd per visit | company date (month) |
| 22 | `ride_revenue_per_visit` | 3 ÷ 18 | month and year tables, divided after summing | park × company month | usd per visit | company date (month) |
| 23 | `food_drink_revenue_per_visit` | 4 ÷ 18 | month and year tables, divided after summing | park × company month | usd per visit | company date (month) |
| 24 | `merchandise_revenue_per_visit` | 5 ÷ 18 | month and year tables, divided after summing | park × company month | usd per visit | company date (month) |
| 25 | `revenue_per_operating_day` | 2 ÷ 20 | month and year tables, divided after summing | park × company month | usd per operating day | company date (month) |
| 26 | `ride_profit` | `fct_ride_day.profit_usd` (rides) | `obt_ride_day` | ride occupancy × game day | usd | company date (day) |
| 27 | `stall_profit` | `fct_ride_day.profit_usd` (stalls, by `item_code`) | `obt_ride_day` | stall occupancy × game day | usd | company date (day) |
| 28 | `stall_units_sold` | `fct_ride_day.units_sold` (single-item stalls) | `obt_ride_day` | stall occupancy × game day | count of items | company date (day) |
| 29 | `ride_popularity` | 38 ÷ 39 | `obt_ride_day`, recomputed from the two helper columns at any grain | ride occupancy × game day | boardings per open day | company date (day) |
| 30 | `same_park_guest_visits_yoy` | 18 this and the prior company year | `obt_park_year`, `obt_company_year` | park × closed company year; eligible parks together | fraction of the prior year | company date (year) |
| 31 | `same_park_operating_revenue_yoy` | 2 this and the prior company year | `obt_park_year`, `obt_company_year` | park × closed company year; eligible parks together | fraction of the prior year | company date (year) |
| 32 | `same_park_operating_profit_yoy` | 1 this and the prior company year | `obt_park_year`, `obt_company_year` | park × closed company year; eligible parks together | fraction of the prior year | company date (year) |
| 33 | `same_park_operating_costs_yoy` | 10 this and the prior company year | `obt_park_year`, `obt_company_year` | park × closed company year; eligible parks together | fraction of the prior year | company date (year) |
| 34 | `company_guest_visits_yoy` | 18 this and the prior company year, all parks | `obt_company_year` | closed company year; all parks together | fraction of the prior year | company date (year) |
| 35 | `company_operating_revenue_yoy` | 2 this and the prior company year, all parks | `obt_company_year` | closed company year; all parks together | fraction of the prior year | company date (year) |
| 36 | `company_operating_profit_yoy` | 1 this and the prior company year, all parks | `obt_company_year` | closed company year; all parks together | fraction of the prior year | company date (year) |
| 37 | `company_operating_costs_yoy` | 10 this and the prior company year, all parks | `obt_company_year` | closed company year; all parks together | fraction of the prior year | company date (year) |
| 38 | `ride_boardings` (helper) | `fct_ride_boarding`, rows counted into `fct_ride_day.boardings` | `obt_ride_day` | ride occupancy × game day | count of boardings (a lower bound) | company date (day) |
| 39 | `ride_open_days` (helper) | `fct_ride_day.is_open_day`, counted | `obt_ride_day` | ride occupancy × game day | simulated game days | company date (day) |

---

## Dimensions

### `dim_park`
- **Business process:** shared by every process (conformed).
- **Grain:** one row per `park_id`. **Key:** `park_id` (text, minted by the plugin and kept in park storage).
- **Attributes:** latest `park_name` (not unique, so never a key), `scenario_name`, `climate` (candidate region for NEXT 6), `data_set` (rehearsal or company, ADR 0013), `company_start_year` and `game_year_origin` (ADR 0023's registry feed), first and last company date seen. Type 1: a changed name overwrites.
- **Clock:** none on the row; first and last seen are company dates.
- **Sources:** `stg_park_registry` through `int_park_registry__current` (ADR 0023, roadmap NEXT 16), `stg_session_start`, `int_park_days__kept`.
- **Metrics served:** the `park` entity of every catalog semantic model.
- **Tests:** `unique` and `not_null` on `park_id`; `relationships` from every fact's `park_id`; every `park_id` in a fact is in the registry (this is the in-dbt half of ADR 0013's park check).

### `dim_ride`
- **Business process:** ride operations and stall sales (conformed together, because rides, stalls and facilities share one ID space; requirements brief section 11).
- **Grain:** one row per detected ride occupancy: one ride, stall or facility from the first to the last kept reading of its slot before the slot is reused, as far as the boundary rule below can see a reuse (the next bullet but one lists the replacements it cannot see). **Key:** `ride_key` = `park_id` + `ride_id` + `build_date_months_elapsed` + `first_seen_ticks`, joined as one text column, where `first_seen_ticks` is the `game_ticks_elapsed` of the occupancy's first kept `ride_snapshot`. The slot number alone fails because the game reuses a slot after demolition (`contracts/ride_snapshot.odcs.yaml`); the build month alone fails when a ride is demolished and replaced in the same slot in the same game month. Two detected occupancies of one slot can never share a first reading, because each reading has its own tick.
- **Where an occupancy starts** (`int_ride_days__kept`, on kept readings in tick order per `park_id` and `ride_id`): at the slot's first reading, or at a reading whose `build_date_months_elapsed`, `ride_type`, `ride_object` or `classification` differs from the previous reading's, or whose `total_customers` is lower than the previous reading's (the contract defines it as the ride's lifetime count; a new ride starts at 0, and the rewind a reload can cause is already gone from kept readings, so the count falls only when the slot holds a new ride). Counter changes never cross an occupancy boundary: the last reading of an occupancy gets null changes.
- **Undetectable replacements, stated rather than hidden:** the rule sees a new ride only through the fields `ride_snapshot` sends. Its boundary signals are a changed `build_date_months_elapsed`, `ride_type`, `ride_object` or `classification`, and a fall in `total_customers`. Other fields were considered and are not signals: `total_profit_tenths` also falls under running costs on a ride that was never replaced; the three ratings read -1 while a ride is unrated (the contract's placeholder), and stalls have none; that a replacement tested before the next reading already shows ratings again is inference, not probed: it rests on one premise, that the game rates a ride when its test run finishes, so the -1 lasts only until then; `ride_name` can be given the old name; `age_months` follows from the build month. So any replacement between two kept readings whose new ride, at the next reading, has the predecessor's type, object, classification and build month and a `total_customers` at or above the predecessor's last reading is not detected, whatever either ride carried. The never-ridden replacement is only one member of that class: an identical ride B that reaches A's last count (25 in the test below) before the next reading merges with A in the same way. **Effect:** A and B share one `ride_key` and one `dim_ride` row; on the reading after the replacement, `fct_ride_day`'s counter changes are B's reading minus A's (customers, and any revenue derived from them, undercounted by A's last count plus A's rise after its last reading; the profit change wrong in either direction); boardings of both rides attach to that one key, so they stay on the right slot but cannot be split between A and B. **What would close it** (a proposed capture experiment; that the plugin can emit this is inference, not probed: it rests on one premise, that the plugin API lets the plugin observe a ride being built, or read a per-ride creation value, within the per-tick budget): a ride creation tick or ride instance ID emitted by the plugin on every `ride_snapshot` (for example, recorded when the plugin observes a ride being built), deferred to the capture roadmap. Cost: a plugin change and its per-tick measurement, a minor bump of the `ride_snapshot` contract, and no fix for captures made before that plugin version. Gain of the current rule: a key that cannot collide among detected occupancies and needs no game change. Cost: one window function over the slot's readings, and this undetectable class.
- **The test that proves the grain:** a dbt unit test on `int_ride_days__kept` with one slot read on four days: ride A (type 1, object `rct2.ride.burgb`, build month 40) with `total_customers` 0, 10, 25 on days 1 to 3; ride B (the same type, object and build month) with `total_customers` 0 on day 4. Expected: two `ride_key` values, A's with `first_seen_ticks` of day 1 and B's of day 4, three ride-day rows for A and one for B, and null counter changes on A's day 3. A second case changes only `ride_object` on day 4 and also expects two keys. A third case pins the undetectable class: B with `total_customers` 25 on day 4, the same type, object and build month as A, expects one `ride_key` and four ride-day rows, so a future plugin field that closes the gap must change this expectation on purpose. `unique` on `ride_key` in `dim_ride` and on `ride_day_key` in `fct_ride_day` then hold on the result.
- **Attributes:** fixed for an occupancy: `classification` (ride, stall or facility), `ride_type`, `ride_object`, build month, `shop_item` and `shop_item_secondary` (nulls where the game sends 255), latest `ride_name` (type 1). Attributes that change from day to day (ratings, prices, age, status, reliability) stay on `fct_ride_day`, so no type 2 history table is needed.
- **Clock:** none; first and last seen are company dates.
- **Sources:** `stg_ride_snapshot` through `int_ride_days__kept`.
- **Metrics served:** the `ride` entity; `ride_type` and age splits of 26.
- **Tests:** `unique` and `not_null` on `ride_key`; `accepted_values` on `classification`; the occupancy unit test above. The first draft's `warn` test on a changed `ride_object` is dropped, because such a change now starts a new occupancy.

### `dim_item`
- **Business process:** stall sales; one item of ride operations (on-ride photos).
- **Grain:** one row per `item_code` seen: a single item, a two-item pair written `<shop_item>+<shop_item_secondary>` in read order, or `on_ride_photo` (catalog spec, "Item keys"). **Key:** `item_code`. Built in data-layer PR 2 as integer codes only, keyed `shop_item`, one row per code seen on a kept ride-day; the text `item_code`, names and item groups wait for the item rules.
- **Attributes:** item name and `item_group` (`food_drink` or `merchandise`) from a seed of the game's shop item codes, with its source noted (`docs/CONVENTIONS.md` §3, `seeds/` row); `is_single_item`.
- **Clock:** none.
- **Sources:** a planned item-code seed; observed codes from `int_ride_days__kept`.
- **Metrics served:** the `item_code` and `item_group` splits of 8, 9, 27 and 28.
- **Tests:** `unique` on `item_code`; `not_null` and `accepted_values` on `item_group`; a pair whose two items fall in different groups fails until NEXT 7 rules (catalog spec).

### `dim_date`
- **Business process:** shared calendar.
- **Grain:** one row per company date. `dim_date` holds every company date from the first day of the earliest company month that contains a kept park-day or a kept statement to the last day of the latest such month, and never generates a date from November to February, so every fact's day or month-start key resolves and every company month present has all its days. Whole months are chosen over keying a month fact to its first kept day because every covered month then has all its days, so the 245-day test below holds for any covered company year, and every park's statement for one month keys to the same date, which `obt_company_month` needs to add parks together. On the committed sample this is 122 rows, 1 March to 30 June of year 9 (findings report, section 6.2 and probe P8). **Key:** `company_date` (DATE).
- **Attributes:** `company_year`, `company_month` (3 to 10), month name, day of month, day of season (1 to 245), `is_month_end`. No game-year column: one company date maps to a different game year in each park, so the game date lives on the facts.
- **Clock:** company date.
- **Sources:** generated in SQL from the months of the kept park-days in `int_park_days__kept` and the statements in `int_statements__labeled` whose `timeline_status` is `kept` (no package).
- **Metrics served:** the year and month grains of every metric. It may become MetricFlow's time spine when the catalog moves into dbt; whether a season-only spine works with `offset_window` is untested.
- **Tests:** `unique` on `company_date`; every month is between 3 and 10; each company month present has all its days (31 or 30); 245 days in each company year whose March and October are both present; `relationships` from every fact's date key, `fct_park_month`'s month start included (probe P8 joins the sample's month and day keys to the generated dates: 0 unresolved; the probe does not cover ride-day keys, which the first mart build tests).

### `dim_session`
- **Business process:** every process, as context. Not needed by the 39 names; required by NEXT 6 (managed or autopilot labels).
- **Grain:** one row per `session_id` seen in any event, left-joined to `stg_session_start` (lineage columns from `int_sessions__lineage`), because a plugin 0.1.0 session or one whose `session_start` was dropped has none (`ARCHITECTURE.md`, stage 5). **Key:** `session_id`.
- **Attributes:** `park_id`, `plugin_version`, `headless`, `game_speed`, the loaded-save fields, `operating_mode` (managed, autopilot or unknown; rule set by NEXT 6).
- **Clock:** first and last game date and wall-clock `emitted_at` of the session, labeled as such.
- **Tests:** `unique` on `session_id`; `relationships` to `dim_park`.

---

## Facts

### `fct_park_day` — admissions and park condition
- **Business process:** admissions (and weather, which shares the grain).
- **Grain:** one row per park per game day on the kept timeline. One park's game dates and company dates map one to one, so this is also one row per park per company day.
- **Key:** `park_day_key` = `park_id` + game year, month and day, as one text column. The key is built from the game date, not the company date, so a stamp correction never changes a key; the catalog names `park_day_key` as the semantic model's primary entity and no longer carries planned text that builds it from the company date.
- **Clock:** `company_date` (day) as the time dimension; `game_year`, `game_month`, `game_day` beside it.
- **Dimensions:** `dim_park`, `dim_date`; `session_id` is a plain column until `dim_session` is built.
- **Facts:** `admissions_increase` (count), `park_rating` (engine units, 0 to 999), `guests_in_park` (count at day start), `cash_usd`, `weather`, `temperature_c`, `is_kept_operating_day` (always true here; the count of rows is `operating_days`).
- **One clock decision:** the park snapshot is read at the start of the game day, so the rise in `total_admissions` from one kept reading to the next counts the guests admitted during the earlier day. `admissions_increase` is assigned to the earlier reading's date. The catalog's `guest_visits` description says the same: counted within one session from one kept day's reading to the next kept reading, assigned to the earlier day, and null for a session's last kept day. Assigning it to the later date would move each month's last day of visits into the next month, and 31 October's into March of the next company year. A day with no next kept reading gets null, not zero. ADR 0024 decision 7 and the `counter_change` macro own the rule; `int_park_days__kept` computes it, and its unit test covers a month end and a session boundary.
- **Sources:** `stg_park_snapshot` → `int_park_days__kept` (duplicate deliveries already removed on `event_id`; reloaded days resolved by save lineage; company date from `int_park_days__company_calendar`, one join on `park_id` and the game date).
- **Metrics served:** 18, 19, 20; denominators of 21–25; input to 30. Metric 19 is stored here as the day's `park_rating`; every coarser grain carries `park_rating_sum` and `operating_days` and divides (wide tables below).
- **Known limits:** `assert_park_day_admissions_reconcile_exactly` compares `fct_park_day` with `int_park_days__kept`, which it casts directly, so it is a self-consistency check: it catches a wrong partition or order, not a wrong counter. An alias reused inside the same select is DuckDB-only syntax; `dim_date.sql`'s site is fixed, and the remaining site is `company_year` in `models/intermediate/int_park_years__company_year.sql` (the `season_start` to `last_day` expressions read the `company_year` output alias).
- **Tests:** `unique` and `not_null` on `park_day_key`; `relationships` to `dim_park` and `dim_date`; `admissions_increase` ≥ 0 (a reload's rewound counter must never count as negative visits); identity, `reconciles_exactly`: per park and session run on the kept timeline, the sum of `admissions_increase` equals the last reading minus the first; enforced contract. When `guest_arrived` lands (full capture part 2; not built): a `warn` hypothesis check that arrivals per park-day match `admissions_increase` within a tolerance set after measuring it on the refreshed sample.

### `fct_park_month` — the monthly statement
- **Business process:** finance.
- **Grain:** one row per park per closed game month on the kept timeline (one monthly statement), dated by the statement's own month, never by the day-1 event that carried it (ADR 0008).
- **Key:** `park_month_key` = `park_id` + `statement_year` + `statement_month`.
- **Clock:** `statement_company_date` (company date, month; the first day of the statement month), computed as the catalog spec states (company year = company start year + (`statement_year` − game-year origin) from `int_park_registry__current`, ADR 0023; month = `statement_month` + 3).
- **Dimensions:** `dim_park`, `dim_date` (month start).
- **Facts:** the 14 ledger lines, `cash_usd` and `bank_loan_usd` as they arrive (costs negative, as the ledger signs them; requirements brief choice 4), plus `net_cash_change_usd` = (cash − loan) minus the previous kept statement's (cash − loan), null on a park's first statement.
- **Sources:** `stg_finance_month` → `int_statements__labeled` (every statement kept or abandoned by `timeline_status`; the mart selects the rows whose `timeline_status` is `kept`, so a reload's repeated statement resolves to the kept one).
- **Metrics served:** 1–6, 10–17; numerators of 21–25; inputs to 31–33.
- **Tests:** `unique` and `not_null` on `park_month_key`; identity, `reconciles_exactly`: the 14 lines summed equal `net_cash_change_usd` per park and month, first statement exempt (the 2026-09-30 sample balanced exactly for its two consecutive pairs; `data/sample/rehearsal/README.md`); `park_entrance_tickets_usd` = 0 at `error` on the company target and `warn` elsewhere (target-based severity, verified on dbt 1.11.15 in the findings report, section 6; not built); every closed park-year has 8 statements, March to October (NEXT 6's year-end test; not built); enforced contract with every money column `DECIMAL(18,2)`.

### `fct_ride_day` — ride operations and stall sales
- **Business process:** ride operations and stall sales, one table because both come from one daily `ride_snapshot` per ride, stall or facility.
- **Grain:** one row per ride occupancy (`ride_key`) per game day on the kept timeline.
- **Key:** `ride_day_key` = `ride_key` + game date. Foreign keys: `ride_key`, `park_id`, `item_code`, and `park_day_key` (the one fact-to-fact link, so a ride or stall row can be split by that park-day's weather, as the catalog's `park_day__weather` needs). Data-layer PR 2 builds no `item_code`; its link to `fct_park_day` is tested at `warn`.
- **Clock:** `company_date` (day); game date beside it. Counter changes run from one read to the next; reads are spread across the day by the work queue, so a daily change covers about one day, not an exact calendar day. Each change is assigned to the earlier read's date, as in `fct_park_day`; this is one stated reason the counters match the ledger only within a tolerance.
- **Daily attributes on the fact:** `classification`, `status`, `is_open_day`, `excitement_band`, `intensity_band`, `nausea_band` (edges set by NEXT 7; −1 unrated becomes null in staging), `ride_age_months`, listed prices in dollars, `reliability_pct`, `downtime_pct`, `queue_time_max_minutes`; coaster statistics when NEXT 17 captures them.
- **Facts:** `gross_sales_usd`, `photo_sales_usd` (0, never null, for a ride without photos), `profit_usd` (daily change in the dollar total profit; filled for facilities too, as `fct_ride_day.sql` takes it unfiltered from `int_ride_days__kept`, `ARCHITECTURE.md`), `units_sold` (single-item stalls; rule set by NEXT 7), `boardings` (count of `fct_ride_boarding` rows that day, a lower bound because the poll misses short rides), and, for the pricing model (NEXT 8), `price_refusals` from `guest_refused` once it lands.
- **Sources:** `stg_ride_snapshot` → `int_ride_days__kept` (ride key, deltas, item keys); `int_boardings__ride_keyed`.
- **Metrics served:** 7, 8, 9, 26, 27, 28, helper `ride_open_days`; the denominator of 29.
- **Tests:** `unique` on `ride_day_key`, with a mutation test that plants a duplicated ride-day row and requires it to fail (catalog spec, "Item keys"; not built); `relationships` to `dim_ride`, `dim_park` and `fct_park_day` (at `warn`), and to `dim_item` (not built); `photo_sales_usd` not null (not built); hypothesis, `within_tolerance` at `warn` (not built): per park and company month, the sum of 7, 8 and 9 against `fct_park_month`'s ride, food and drink, and shop lines, within max(1% of the ledger figure, $1.00) (the catalog's tolerance); enforced contract.

### `fct_ride_boarding` — one boarding
- **Business process:** ride operations (demand).
- **Grain:** one row per `guest_boarded` event on the kept timeline (one guest seated on one ride at one seat poll). **Key:** `event_id` after duplicate removal.
- **Clock:** `company_date` (day) and `detected_at_ticks` (game ticks), both from the poll.
- **Dimensions:** `dim_ride` (through `ride_key`: the occupancy of the boarding's `ride_id` with the latest `first_seen_ticks` at or before the boarding's `detected_at_ticks`), `dim_park`, `dim_date`, `dim_session`. Guest identity is `session_id` + `guest_key` and never spans sessions, because guests never return and a reload starts a new cohort.
- **Facts:** `ride_price_listed_usd` (the listed price at the poll, not the amount charged), `happiness`, `min_intensity`, `max_intensity`, `nausea_tolerance`, `guest_cash_usd` after paying.
- **Sources:** `stg_guest_boarded` → `int_boardings__ride_keyed`.
- **Metrics served:** helper `ride_boardings`; the numerator of 29. Its description must state the capture limit: a boarding shorter than 20 ticks or a second boarding of the same ride between two polls is missed.
- **Tests:** `unique` and `not_null` on `event_id`; `relationships` to `dim_ride` with `warn` (a boarding on a ride built and demolished between two daily readings finds no occupancy); enforced contract.

---

## Wide reporting tables (one big tables)
A **one big table** here is a wide, pre-joined table built only from the star, for the site's charts and the README. ADR 0012 calls them "wide views"; ADR 0013 (proposed) allows no views in a published file, so they are tables. ADR 0015 (proposed) requires every published number to be a mart column with a named reconciliation test, so every catalog metric the site shows becomes a column here, **named exactly as the catalog metric**. The final list is NEXT 15's (the site) and NEXT 3c's (the marts) to confirm; the draft set:

| Table | Grain and key | Clock | Columns | Rule and tests |
|---|---|---|---|---|
| `obt_park_month` | park × company month; `park_month_key` | company date (month) | 1–17; 18 and 20 summed over the month's park-days; `park_rating_sum` (the month's daily ratings summed) with 19 = `park_rating_sum` ÷ `operating_days`; 21–25 | Ratios and the average divide sums at this grain, never average ratios or averages. `reconciles_exactly` against `fct_park_month` and `fct_park_day` for every summed column, `park_rating_sum` included. |
| `obt_company_month` | company month; `company_date` | company date (month) | the same, all parks | Sums parks first, then divides. `reconciles_exactly`: each column equals the sum of `obt_park_month` (sums) or is recomputed from those sums (ratios and 19). 19 pools all park-days (requirements brief choice 5): the summed `park_rating_sum` ÷ the summed `operating_days`. A dbt unit test proves the pooling with two parks of unequal length: park A, two days rated 800; park B, one day rated 500; expected 700, not the 650 an average of park averages gives. |
| `obt_park_year` | park × company year, closed years only; `park_id` + `company_year` | company date (year) | 1–25 for the year (19 again as `park_rating_sum` ÷ `operating_days` for the year), 30–33 with the prior year beside them, both same-park eligibility flags, operating days for both years | A year appears only after the year-end close (NEXT 6). A singular test checks the same-park sets on a fixture with an incumbent park, a first-season park and a park with an incomplete prior year (it replaces the MetricFlow offset test; findings report, section 9). |
| `obt_company_year` | company year, closed only; `company_year` | company date (year) | as above, eligible parks together for 30–33, and every park for 34–37 with the prior year beside them | The year-end close test blocks the build of a year until every park expected that year is complete (`error` on the company target). |
| `obt_ride_day` | `ride_day_key` | company date (day) | 7–9, 26–29 and helpers with `dim_ride` and `dim_item` attributes and the park-day weather | `reconciles_exactly` against `fct_ride_day`; 29 divides summed boardings by summed open days at the queried grain, so the site re-aggregates from the two helper columns, never from 29. |

**Note, 2026-10-18 (superseded in part by ADR 0035).** The year-to-date table, built earlier as the steel-thread roll-up, is replaced by `obt_company_year`, which holds closed company years only. `obt_park_year` is built and holds every park-year with a close status (complete, open, incomplete or partial first season), not closed years only as the table above says. Read these two rows with that change. A year stays out of `obt_company_year` until every expected park is complete; the year-end close test fails the build only on a gap more play cannot fill or on a leaked year, one that `obt_company_year` holds although the register does not mark it closed (ADR 0035 decision 4), and its severity comes from `sample_warn_severity`.

---

## Deferred: guest cohort (after v1)
- **Business process:** guest experience (NEXT 9) and length of stay (NEXT 10). No catalog metric reads it, so no v1 mart is built.
- **Grain:** `fct_cohort_guest_day`, one row per cohort member per game day, from `guest_snapshot`; a member's follow-up ends at its `guest_left`. **Key:** `session_id` + `guest_key` + game date.
- **Clock:** company date (day).
- **Facts:** `happiness`, `hunger`, `thirst`, `nausea`, `energy`, `guest_cash_usd`, the first thought, the items carried.
- **Sources:** `stg_guest_snapshot`, `stg_guest_left`, `stg_guest_arrived` (`in_cohort`), staged when this work starts (findings report, section 1).
- **Tests:** `unique` on the key; every cohort member has one `guest_arrived` with `in_cohort` true in its session; at most 100 members per session (`COHORT_SIZE` in the part 2 spec).

## What these notes do not settle
- Band edges, the units-sold counter rule, item-group rulings and the photo-sales solution are NEXT 7's.
- The company date comes from the park registry feed (ADR 0023); the keys above do not depend on it.
- The managed and autopilot label and the register of parks expected each company year are NEXT 6's.
- Which wide tables the site needs is NEXT 15's.
