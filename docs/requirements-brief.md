# Requirements brief: what the park company needs from its data

## Bottom line

The park company needs one headline number, **operating profit per company year**: what its parks earn from
running, before building and borrowing, taken straight from the game's own books and checked exactly against
the change in cash less the bank loan, less the money already booked to the new month. Two guardrails keep that number honest: **guest visits** and the **average
park rating** must not fall by more than their thresholds (section 8) to buy profit. The metric catalog (`metrics/finance.yml`, `metrics/admissions.yml` and `metrics/ride_operations.yml`) defines 37 metrics, each with a unit, a clock
and a grain; 16 of them sit in a tree beneath the headline. Every finding is observational and states its
sample; v1 runs on rehearsal data from two parks. This brief and the catalog were **confirmed by the project
owner on 2026-10-03**, with the changes listed in section 12.

**How to read the labels.** "NEXT n" is item n of the roadmap's list of validated problems
(`docs/ai-dlc/roadmap/park-company.md`); each is glossed on first use. "ADR n" is decision record n in
`docs/adr/`. "verify: owner-later", in the ruling quoted below, means agents build and check the work now and the
project owner's own check is queued.

## Rulings this brief follows

The spec interview (called Gate 1 in the spec; the spec is removed from the tree when the work ships) was answered by these
rulings, quoted verbatim:

> "NEXT 13 metric catalog: north-star metric = company operating profit per company year (ledger-reconciled);
> tree = revenue by category (ride; stall by item) and operating costs; guardrails = park rating and guest visits.
> Agents draft the requirements brief and the catalog (dbt 1.11 metric YAML shape, standalone file); the brief's
> confirmation is `verify: owner-later` → owner queue."
>
> [source: project owner's preflight rulings, 2026-10-03]

NEXT 13 is the roadmap item "What does the park company need from its data?", which this brief and the catalog
answer.

## 1. Purpose

This brief is the agreed statement of what the park company needs from its data. The metric catalog, the dbt
design session (NEXT 3·0, where grains, layers and marts are decided), the marts (NEXT 3c, the tables dashboards
read, laid out as a star schema of fact tables joined to shared dimension tables), the website (NEXT 15) and the
acceptance scenarios (NEXT 19, the walkthrough that decides whether v1 is accepted) all follow it.
When one of them disagrees with this brief, the brief is corrected first or the other work is.

## 2. Audience

- **A recruiter or hiring manager reading cold.** This is the roadmap's north-star audience: someone hiring for
  analytics-engineering or data-science roles, who should understand within minutes what the company needs and
  why.
- **The project owner, as the company's sole decision-maker.** The company is a one-person simulation. Any
  business role this brief mentions (executive, finance, park manager) is a hat that one person wears, not an
  invented stakeholder (ADR 0012, the record that adapts data-team practices for a one-person build).

## 3. The business in five lines

1. One company owns several parks, each pay-per-ride: entry is free, and rides and stalls charge.
2. Every park runs on one company calendar, and park 1's first day is 1 March 2000.
3. A season lasts eight months, March to October, and is also the fiscal year; November to February do not exist.
4. A company year's reports publish only after the year-end close, when every park has finished that year.
5. Guests never return, so guest visits per day and per month play the role that daily and monthly active users
   play in a tech company.

These lines restate the roadmap's "Business rules: the park company".

## 4. Decisions the data serves

- **Is the company making money?** Operating profit per park and for the company, per company year.
- **Which parks, rides and stalls earn it?** Revenue and profit by park, by ride, and by stall and item.
- **What grows visits?** Guest visits against park rating and ride revenue, read as observational evidence.
- **What should a ride or item cost?** Observational only: no price experiment backs v1, so no causal claim. The
  pricing model (NEXT 8) reads the listed ride price: `ride_price_listed_usd` on each ride-day, the ride's admission
  price from its daily snapshot, and on each boarding, the price listed when full capture part 2 saw the boarding.
  Both arrive in tenths of a dollar and convert to dollars once, in their staging models.
- **Do the books match the game?** Every published number reconciles to an in-game source, checked by a dbt test.

## 5. The north-star metric

A **north-star metric** is the one number that best says whether the business is succeeding; every other metric
explains or protects it. The park company's north star is **company operating profit per company year**
(`operating_profit`, metric 1 in section 7).

- **What it adds up.** Operating revenue (ride ticket sales, food and drink sales, merchandise sales, and park entry
  tickets) plus operating costs (ride running costs, staff wages, stock bought for stalls and on-ride photos,
  marketing, and research). Each of the game's 14 monthly ledger lines lands in exactly one place: those ten in
  operating profit, ride construction, land and landscaping in capital spending, and loan interest in interest
  costs.
- **Its sign.** The ledger records spending as negative numbers, and the catalog keeps that sign, so operating
  profit is a plain sum of revenue and costs.
- **Its unit.** US dollars. The game counts money in tenths of a dollar; tenths convert to dollars once, in each
  event type's staging model (staging is the dbt layer that renames, casts, converts units and keeps the
  first-received copy of each event): for the ledger that is `stg_finance_month`, ride money and prices convert in
  `stg_ride_snapshot`, the listed ride price and guest cash convert in `stg_guest_boarded`, and guest cash also converts in
  `stg_guest_arrived` and `stg_guest_snapshot`. Nothing downstream
  converts again.
- **Its clock.** The company date: the date on the company calendar, as opposed to the park's own game date. Every
  company-date column is provisional, because the park registry feed that gives each park its company year
  (ADR 0023, current model `int_park_registry__current`) is not built into a `company_date` column yet.
- **Its grain.** Per park per company month, reported per company year, per park and for the company, and only
  after the year-end close.
- **How it is proved.** For each park and month, operating profit plus capital spending plus interest costs must
  equal, exactly, the change in (cash − bank loan) since the previous kept statement. "Kept" means on the save
  branch the player continued, not one abandoned by reloading an earlier save (ADR 0006, the record that the plugin
  records facts and dbt decides which rows are valid). Each park's first statement is exempt, because it has no
  previous statement.
- **Why this number.** Multi-park operators report operating profit; adjusted EBITDA (earnings before interest,
  taxes, depreciation and amortization, with one-off items removed) needs data the game does not have. The game's
  ledger makes operating profit exact rather than estimated. Wherever it is compared with real operators' figures,
  it is labeled **game operating profit**: operating profit is not EBITDA.

## 6. The sample statement

v1 runs on **rehearsal data**: headless copies (the game run with no window and no player) of at least two old
parks on one company calendar, labeled rehearsal and never mixed with company data. Every finding states its parks
and its players and says "observational", as the repo's never-break rule 7 requires (`CLAUDE.md`, "Never break").
The sample line for v1 findings is: **"rehearsal data; observational; two parks; no player during the runs."** No
experiment design backs a causal claim, so no finding says one thing caused another.

Today's committed sample (`data/sample/rehearsal/`) holds three headless sessions on one park; the second park
arrives with the two-park rehearsal (NEXT 6, the portfolio view and its year-end close test).

## 7. The metric tree and every metric

A **metric tree** breaks the north star into the metrics that make it up or drive it. Each link in the tree is one
of two kinds (ADR 0012):

- An **identity link** adds up exactly: the parent equals the sum of its children, and a dbt test reconciles it.
  An identity link never carries a tolerance.
- A **hypothesis link** is a claim that the child drives or matches the parent. It names its evidence, rival
  explanations and a check that confronts it with data, and it is labeled observational. A hypothesis whose check
  compares two figures within a margin states that margin, its **tolerance**.

### The tree

- **Operating profit** (north star)
  - **Operating revenue** — identity
    - **Ride revenue** — identity
      - **Ride revenue by ride** — hypothesis; check: monthly sum against ride revenue; tolerance max(1% of the
        ledger figure, $1.00) per park-month
      - **Guest visits** (also a guardrail) — hypothesis: more visits, more ride revenue, same company day; check:
        read at the year-end review; no tolerance
        - **Average park rating** (also a guardrail) — hypothesis: a better rating brings more guests, with a lag of
          7, 14 or 28 days; check: read at the year-end review; no tolerance
    - **Food and drink revenue** — identity
      - **Food and drink revenue by item** — hypothesis; check: monthly sum against food and drink revenue;
        tolerance max(1% of the ledger figure, $1.00) per park-month
      - **Guest visits** (its second link) — hypothesis: more visits, more food and drink revenue, same company
        day; check: read at the year-end review; no tolerance
    - **Merchandise revenue** — identity
      - **Merchandise revenue by item**, with on-ride photo sales as their own item — hypothesis; check: monthly sum
        against merchandise revenue; tolerance max(1% of the ledger figure, $1.00) per park-month
      - **Guest visits** (its third link) — hypothesis: more visits, more merchandise revenue, same company day;
        check: read at the year-end review; no tolerance
    - **Entrance revenue** — identity
  - **Operating costs** — identity
    - **Ride running costs** — identity
    - **Staff wages** — identity
    - **Stock costs** — identity
    - **Marketing costs** — identity
    - **Research costs** — identity

**Why revenue by ride and by item are hypotheses, not identities.** The rides' and stalls' own sales counters match
their ledger line only within a margin: 19 tested comparisons fell within max(1% of the ledger figure, 10 tenths of a
dollar), and none spanned a save reload (`docs/FINDINGS.md`, 2026-09-28 revenue-check row). Each claim is that the
counters' sum per park and month equals the parent within that tolerance. Its rivals are counter drift across a save
reload (untested) and, for ride revenue and merchandise, a mid-month photo price change. Its check is a dbt test at
warn severity (it reports, it does not block) built by NEXT 4 (the monthly and annual profit-and-loss statement and
its reconciliation tests), reviewed at each company year-end close.

**On-ride photos.** A ride's own profit counter includes its on-ride photo sales, but the ledger books those sales as
merchandise. So revenue by ride subtracts photo sales, and merchandise revenue by item adds them as the item
`on_ride_photo`. NEXT 7 (ride and stall profit) solves photo sales from each ride's counters, because the game's
plugin interface cannot read the photo count. Photo sales are zero, never null, for a ride without photos, so the
difference `gross_sales_usd - photo_sales_usd` keeps every ride in revenue by ride; NEXT 7 tests `not_null`.

**Guest visits drive three revenue lines.** A metric has one parent in the tree, so guest visits sits under ride
revenue and the catalog records its links to food and drink revenue and to merchandise revenue under
`additional_links`, each a full hypothesis with its own claim, evidence, rivals and check. Stall and photo price
changes, stall placement and closures, and weather (umbrella sales, for merchandise) are the rivals.

**The guardrail hypotheses' checks.** All are read at the year-end close review (NEXT 6), at company-day grain per
park, observational, with no tolerance. Guest visits: ride revenue by ride, summed over a park's rides that day,
against guest visits that day; likewise food and drink revenue by item over the park's food and drink stalls, and
merchandise revenue by item over its shop stalls and on-ride photos. Park rating: guest visits on day d against the
rating on day d minus 7, 14 or 28 days, recording the best-fitting lag. A monthly association never satisfies any
of these checks; a series lacking day grain relabels the claim to the grain it supports.

### Every metric

Every metric is owned by "the project owner", has status `draft`, and uses the **company date** as its clock (the
wall-clock hour and game day are allowed clocks, but no metric here uses them). The grains are the finest published
level:

- **park-month**: per park per company month; reported per company year and for the company.
- **park-day**: per park per company day; reported per month, per year and for the company.
- **ride-day**: per ride or stall per company day; reported per company year.
- **park-year**: per park per company year; reported per park and for the eligible parks together, and queried by
  `metric_time` (dbt's name for the main time axis of a metric query) at year grain.
- **company-year**: for the company per company year, all parks together, queried by `metric_time` at year grain.

Sources are dbt models: `stg_finance_month` (the monthly statements), `stg_park_snapshot` (daily park readings) and
`stg_ride_snapshot` (daily ride and stall readings) exist today; `stg_guest_boarded` (guest boardings, from full
capture part 2) exists. "Identity" rows carry no tolerance; "supporting" metrics sit
outside the tree.

| # | Name | Plain definition | Unit | Grain | Role and link | Check and tolerance | Source |
|---|---|---|---|---|---|---|---|
| 1 | `operating_profit` | Operating revenue plus operating costs: what the parks earn from running, before building and borrowing | usd | park-month | north star; guardrails 18 and 19 | exact: 1 + 16 + 17 = change in (cash − loan − money already booked to the new month) from the previous kept statement, first statement exempt | `stg_finance_month` |
| 2 | `operating_revenue` | All money guests paid: rides, food and drink, merchandise and entry | usd | park-month | tree, parent 1, identity | exact sum of its four lines (NEXT 4) | `stg_finance_month` |
| 3 | `ride_revenue` | Ride ticket sales from the ledger; never called admissions; excludes on-ride photo sales | usd | park-month | tree, parent 2, identity | exact (NEXT 4) | `stg_finance_month` |
| 4 | `food_drink_revenue` | Food and drink stall sales | usd | park-month | tree, parent 2, identity | exact (NEXT 4) | `stg_finance_month` |
| 5 | `merchandise_revenue` | Merchandise sales: shop stalls plus on-ride photos, as the ledger books them | usd | park-month | tree, parent 2, identity | exact (NEXT 4) | `stg_finance_month` |
| 6 | `entrance_revenue` | Park entry ticket sales; zero under the pay-per-ride rule, kept so the sum is complete | usd | park-month | tree, parent 2, identity | exact; a test asserts zero, failing on company data and warning on rehearsal data, where an old save may charge entry | `stg_finance_month` |
| 7 | `ride_revenue_by_ride` | Each ride's ticket sales from its own counters, without its on-ride photo sales | usd | ride-day | tree, parent 3, hypothesis | warn test (NEXT 4); max(1% of the ledger figure, $1.00) per park-month | `stg_ride_snapshot` |
| 8 | `food_drink_revenue_by_item` | Each food or drink stall's sales by the item it sells; a two-item stall stays unsplit under its item pair | usd | ride-day | tree, parent 4, hypothesis | warn test (NEXT 4); max(1% of the ledger figure, $1.00) per park-month | `stg_ride_snapshot` |
| 9 | `merchandise_revenue_by_item` | Each merchandise stall's sales by item, plus each ride's on-ride photo sales as the item `on_ride_photo`; a two-item stall under its pair | usd | ride-day | tree, parent 5, hypothesis | warn test (NEXT 4); max(1% of the ledger figure, $1.00) per park-month | `stg_ride_snapshot` |
| 10 | `operating_costs` | The cost of running the parks: rides, staff, stock, marketing and research; negative, as the ledger signs spending | usd | park-month | tree, parent 1, identity | exact sum of its five lines (NEXT 4) | `stg_finance_month` |
| 11 | `ride_running_costs` | Ride upkeep | usd | park-month | tree, parent 10, identity | exact (NEXT 4) | `stg_finance_month` |
| 12 | `staff_wages` | Staff pay | usd | park-month | tree, parent 10, identity | exact (NEXT 4) | `stg_finance_month` |
| 13 | `stock_costs` | Stock bought for stalls and on-ride photos (the cost of goods sold) | usd | park-month | tree, parent 10, identity | exact (NEXT 4) | `stg_finance_month` |
| 14 | `marketing_costs` | Marketing campaigns | usd | park-month | tree, parent 10, identity | exact (NEXT 4) | `stg_finance_month` |
| 15 | `research_costs` | Ride and stall research | usd | park-month | tree, parent 10, identity | exact (NEXT 4) | `stg_finance_month` |
| 16 | `capital_spending` | Building: ride construction, land and landscaping; outside operating profit | usd | park-month | supporting; closes the cash check of metric 1 | part of metric 1's exact check | `stg_finance_month` |
| 17 | `interest_costs` | Loan interest; outside operating profit | usd | park-month | supporting; closes the cash check of metric 1 | part of metric 1's exact check | `stg_finance_month` |
| 18 | `guest_visits` | Guests admitted; each guest is one visit, because guests never return | count | park-day | guardrail of 1; tree, parent 3, hypothesis; further hypothesis links to 4 and 5 | year-end review (NEXT 6), same day; no tolerance | `stg_park_snapshot` |
| 19 | `average_park_rating` | The game's park rating averaged over operating days, pooled across parks for the company | engine units, 0 to 999 | park-day | guardrail of 1; tree, parent 18, hypothesis | year-end review (NEXT 6), lag 7, 14 or 28 days; no tolerance | `stg_park_snapshot` |
| 20 | `operating_days` | Simulated game days a park ran on the kept timeline; closed months never count | simulated game days | park-day | supporting | none | `stg_park_snapshot` |
| 21 | `revenue_per_visit` | Operating revenue per guest visit | usd per visit | park-month | supporting | none | `stg_finance_month`, `stg_park_snapshot` |
| 22 | `ride_revenue_per_visit` | Ride revenue per guest visit | usd per visit | park-month | supporting | none | `stg_finance_month`, `stg_park_snapshot` |
| 23 | `food_drink_revenue_per_visit` | Food and drink revenue per guest visit | usd per visit | park-month | supporting | none | `stg_finance_month`, `stg_park_snapshot` |
| 24 | `merchandise_revenue_per_visit` | Merchandise revenue per guest visit | usd per visit | park-month | supporting | none | `stg_finance_month`, `stg_park_snapshot` |
| 25 | `revenue_per_operating_day` | Operating revenue per operating day | usd per operating day | park-month | supporting | none | `stg_finance_month`, `stg_park_snapshot` |
| 26 | `ride_profit` | Each ride's profit from its own counter | usd | ride-day | supporting | none | `stg_ride_snapshot` |
| 27 | `stall_profit` | Each stall's profit, by item | usd | ride-day | supporting | none | `stg_ride_snapshot` |
| 28 | `stall_units_sold` | Purchases at each single-item stall (not unique customers) | count | ride-day | supporting | none | `stg_ride_snapshot` |
| 29 | `ride_popularity` | Boardings per day the ride was open | boardings per open day | ride-day | supporting | none | `stg_ride_snapshot`, `stg_guest_boarded` |
| 30 | `same_park_guest_visits_yoy` | Change in guest visits against the prior company year, for parks with a complete prior year | fraction of the prior year | park-year | supporting | none | `stg_park_snapshot` |
| 31 | `same_park_operating_revenue_yoy` | Change in operating revenue against the prior company year, same parks | fraction of the prior year | park-year | supporting | none | `stg_finance_month` |
| 32 | `same_park_operating_profit_yoy` | Change in operating profit against the prior company year, same parks; not meaningful after a loss year, so both years are shown beside it | fraction of the prior year | park-year | supporting | none | `stg_finance_month` |
| 33 | `same_park_operating_costs_yoy` | Change in operating costs against the prior company year, same parks; both years are negative, so a positive figure means spending grew | fraction of the prior year | park-year | supporting | none | `stg_finance_month` |
| 34 | `company_guest_visits_yoy` | Change in guest visits against the prior company year, all parks, first-season parks included | fraction of the prior year | company-year | supporting | none | `stg_park_snapshot` |
| 35 | `company_operating_revenue_yoy` | Change in operating revenue against the prior company year, all parks | fraction of the prior year | company-year | supporting | none | `stg_finance_month` |
| 36 | `company_operating_profit_yoy` | Change in operating profit against the prior company year, all parks; not meaningful after a loss year, so both years are shown beside it | fraction of the prior year | company-year | supporting | none | `stg_finance_month` |
| 37 | `company_operating_costs_yoy` | Change in operating costs against the prior company year, all parks; a positive figure means spending grew | fraction of the prior year | company-year | supporting | none | `stg_finance_month` |

Two helper metrics sit outside the 37: `ride_boardings` and `ride_open_days`, the two halves of ride popularity
(metric 29). An **operating day** is a simulated game day on the kept timeline: the game ran that park that day,
which does not prove the park was open to guests, because no captured field says so yet. Guest visits come from the
rise in the park's cumulative admissions counter since the previous kept reading, computed in the intermediate layer
(NEXT 3b, the dbt layer for business logic such as save lineage and the company calendar).

**Display labels.** The site shows names a hiring manager recognizes, while the metric identifiers stay unchanged:
"Attendance (guest visits)" (18), "Total guest spend per visit" (21), "Ride spend per visit" (22), "Food and
beverage revenue" (4, and 23 per visit), "Same-park (like-for-like) growth" (30 to 33), "Revenue per simulated
operating day" (25), "Game park rating (0–999)" (19), and "game operating profit" (1) wherever operators' figures
appear beside it. The labels come from `docs/ai-dlc/reports/park-metric-conventions--findings.md`.

**Weather.** Temperature is numeric (degrees Celsius, averaged over park-days), not a category. Weather and umbrella
metrics are planned at status `draft`; they depend on the weather and umbrella spike and the weather capture it
unlocks (NEXT 18, how weather drives stall sales), and none is defined until the spike proves how weather changes
are timed and how umbrella sales are told apart from map sales.

## 8. Guardrails

A **guardrail metric** is one that must not get worse by more than its threshold while the north star improves. The park company has two:

- **Guest visits** (metric 18).
- **Average park rating** (metric 19).

Profit raised by cutting running costs, staff or marketing, or by raising prices, must not be bought with visits
or a park rating that fall by more than the thresholds below. Any finding that reports a rise in operating profit shows both guardrails beside it.

**Thresholds.** When annual company operating profit rises, a guardrail is breached if either limit fails:

- **Guest visits:** same-park guest visits year over year (metric 30) for the completed company year must be at
  least −0.02, in its unit, a fraction of the prior year. That equals same-park visits of at least 98% of the prior
  year's for the identical eligible parks.
- **Average park rating:** the change in the average park rating (metric 19) from the prior company year, current
  minus prior, must be at least −10, in its unit, engine units on the game's 0–999 scale. Each year counts only
  the same eligible parks as metrics 30 to 33, and every park-day weighs once, as metric 19 pools them. So the
  rating falls by no more than 10 points.

These limits are project decisions, not published industry norms
(`docs/ai-dlc/reports/park-metric-conventions--findings.md`). They were fixed on 2026-10-03, before any result was
seen, and are revisited after two complete company years; a limit is never changed after seeing the result it
judges. Each park's result, the eligible parks together and both years' operating days are shown; a park without a
complete prior year has no baseline, which is not an automatic pass. A breach is reported as profit rising
alongside a guardrail falling beyond its limit, never as a cause.

## 9. What no metric counts

- **Previews and client-side predictions.** Construction previews and the game's guesses before an action is
  confirmed are never player actions (ADR 0006, the plugin records facts and dbt decides validity).
- **Abandoned-timeline rows and the post-save run-on.** Rows from a save branch the player abandoned by reloading,
  and the events a session records after its last save that no later session continues from, are labeled and kept
  out of every metric.
- **Duplicate deliveries and a reload's second statement.** An event delivered twice counts once, and a reload that
  repeats a month's statement counts that month once.
- **Rehearsal and company data mixed.** No figure combines the two (ADR 0013, proposed: one DuckDB file, the local
  database, per environment).
- **Experiment copies of saves.** A deliberate copy of a park for a test never counts as a company park.
- **Closed months.** November to February never appear, not even as zero months.
- **Facilities.** Toilets, ATMs and first aid never count as rides or stalls in metrics 7 to 9 and 26 to 29.

## 10. Reporting rules

- **Same-park (like-for-like) year-over-year** (metrics 30 to 33) compares only parks with a complete prior company
  year on the kept timeline: all eight statements and every game day. It divides by the prior year's value over the same
  parks, is queried by `metric_time` at year grain, and comes with an operating-days bridge, which splits the
  change into a days effect and a rate effect. A park in its first season is listed separately. The catalog builds
  these metrics with dbt's `offset_window` (an input read one year earlier); whether dbt applies the same-park
  filter to the earlier year before joining is unverified. ADR 0016 moves the test that would prove it to the
  governed-metrics bet (the later work that serves these metrics through dbt's semantic layer), so metrics 30 to
  33 stay `draft` until that test passes. Until then the marts compute the same-park figures from the eligibility
  flags and check the eligible park sets with their own test (`docs/ai-dlc/reports/dbt-design--marts.md`).
- **Company-wide year-over-year** (metrics 34 to 37) compares every park on the kept timeline, as reported, beside
  the same-park figures. A park opens on 1 March, so its first season is a complete company year: it enters the
  company-wide figures in that year, adding its whole first year to the current year and nothing to the prior
  year, so new parks count as growth. It enters the same-park figures from its second year. The company's first
  year has no prior year, so metrics 34 to 37 start in its second.
- **A company year closes only when every park has all eight statements on the kept timeline.** October of year Y
  is the first statement on the kept branch after Y's year-end save. The game reads it on 1 March of year Y+1 but
  dates it October of year Y, so year Y cannot close before it arrives (ADR 0008, money arrives as closed-month
  statements).
- **Every published number is tied to an in-game source by a dbt test.** An exact reconciliation (an identity link)
  fails the build on a mismatch. A hypothesis check is at warn severity (it reports, it does not block), or is read
  at the year-end close review (guest visits and the average park rating have no test). `make check` builds only the
  committed sample; published numbers come from local production builds (ADR 0012).
- **Every metric names its unit and its clock** (`CLAUDE.md`, never-break rule 3).

## 11. The bus matrix

A **bus matrix** lists the company's business processes as rows and the shared dimensions (the things every
process is sliced by) as columns; a dimension shared by several rows must mean the same thing in each. A **grain**
says what one row of a process means. This grid starts from the draft in
`docs/ai-dlc/reports/data-team-practices--findings.md` section 2.4. Each grain is confirmed against a staging
model's YAML where one exists; where none exists, it is taken from the event contract and marked **provisional**.
It is input to the dbt design session (NEXT 3·0), which makes the final design.

| Business process | Grain and its evidence | Park | Ride | Stall and item | Game date | Company date |
|---|---|---|---|---|---|---|
| Admissions | **Park-day, confirmed.** `models/staging/stg_park_snapshot.yml`: one row per park snapshot, one per session per game day; a reload can repeat a park-day, which the intermediate layer resolves to one kept row. | x | | | x | x |
| Ride operations | **Ride-day, provisional.** `contracts/ride_snapshot.odcs.yaml`: one row per ride, stall or facility per snapshot step, one step per ride each game day; two steps can share a date. Boardings come from a guest-boarded contract that full capture part 2 adds. | x | x | x (on-ride photo only; corrected) | x | x |
| Stall sales | **Stall-day, provisional.** `contracts/ride_snapshot.odcs.yaml`, rows with classification `stall`; items from `shop_item` and `shop_item_secondary`. | x | | x | x | x |
| Finance | **Park-month statement, confirmed.** `models/staging/stg_finance_month.yml`: one row per statement, one per session per closed game month, read on day 1 of the next month; a reload can repeat a park-month, which the intermediate layer resolves. | x | | | x (month) | x (month) |
| Weather | **Park-day, confirmed.** `models/staging/stg_park_snapshot.yml`: weather and temperature (numeric, degrees Celsius) read at the start of each game day; empty for plugin versions before 0.3.0. | x | | | x | x |

Cell by cell, the draft holds with one correction and four notes:

- **Correction: ride operations touches the item dimension.** On-ride photo sales are sold by rides, and metric 9
  books them as the item `on_ride_photo`, so the ride operations row marks "stall and item" for that one item.
- **A ride ID alone is not a ride.** The game reuses a ride slot after demolition, so ride-day and stall-day rows
  key on park, ride ID, build month and the tick of the occupancy's first kept reading, which separates a
  same-month rebuild (ADR 0016). Stalls share that key, so the ride and stall dimensions must be conformed
  together.
- **Staging rows are per session, not yet per park.** Both confirmed staging grains can hold two rows for one park
  and day or month after a reload; the stated grains hold after the intermediate layer keeps one row per park on
  the kept timeline.
- **Finance dates are the statement's month.** A statement's game date is its own year and month, not the date of
  the event that carried it (day 1 of the following month).
- **Every company-date cell is provisional.** `int_park_days__company_calendar` gives each kept park-day its company date, using the company year
  from `int_park_years__registry_mapped` (ADR 0023).

## 12. The catalog, its checks and this brief's status

The metrics in section 7 are defined in full in the three files `metrics/finance.yml`, `metrics/admissions.yml` and `metrics/ride_operations.yml`, standalone files in dbt 1.11's metric YAML
shape, kept outside dbt's model folders so the gate can run inside the agents' sandbox. The catalog holds each
metric's formula once; this brief does not repeat formulas. Two checks guard it in `make check`:
`scripts/check_metric_catalog.py` enforces the catalog's house rules (required fields, references, units, clocks
and tree links), and `scripts/check_metric_catalog_shape.py` runs dbt's parser on a temporary copy, for real in CI.

**Status: confirmed by the project owner on 2026-10-03.** The six drafting choices were confirmed as written:

1. **Landscaping is capital spending**, because it is spent building the park. Confirmed by the project owner,
   2026-10-03.
2. **Interest sits below operating profit**, because it is the cost of financing, not of running parks. Confirmed
   by the project owner, 2026-10-03.
3. **Research is an operating cost.** Confirmed by the project owner, 2026-10-03.
4. **Costs keep the ledger's negative sign**, so the tree is a plain sum. Confirmed by the project owner,
   2026-10-03.
5. **Average park rating pools all park-days**, so a park with more days weighs more in the company figure.
   Confirmed by the project owner, 2026-10-03.
6. **Same-park year-over-year is defined now**, as metrics 30 to 33, with eligibility by a complete prior kept
   company year, the prior year as denominator and an operating-days bridge. Confirmed by the project owner,
   2026-10-03.

The confirmation added these changes, all applied in this brief and the catalog:

- Guest visits is a hypothesis driver of food and drink revenue and of merchandise revenue, as well as ride revenue
  (section 7).
- Company-wide year-over-year metrics 34 to 37 sit beside the same-park ones, and same-park is labeled
  like-for-like (sections 7 and 10).
- The listed ride price is a field the pricing model can read, converted from tenths once in staging (section 4).
- Temperature is numeric; weather and umbrella metrics are planned at status `draft`, waiting on the weather spike
  (section 7).
- Tenths convert to dollars once in each event type's staging model, not only the finance model (section 5).
- The guardrails have thresholds (section 8) and the metrics have display labels (section 7).

A later correction to any of these reopens this brief, the catalog and every slice built on them.

Separately, every company-date column is provisional on ADR 0023 (company dates come from a park registry feed, whose
current model `int_park_registry__current` feeds `company_date`), built under NEXT 16; this brief adds no new question there.
