# ADR 0023: company dates come from a park registry feed joined in the warehouse

- Date: 2026-10-09
- Status: Accepted, by the project owner's Gate 1 ruling of 2026-10-09 for roadmap NEXT 16 (the company calendar).
- Superseded in part by ADR 0033 (2026-10-17), for company data before go-live.
- Superseded in part by ADR 0036 (2026-10-18), for the rehearsal data set, where the capture command writes the registry delivery.
- Superseded in part by ADR 0038 (2026-10-19), for company registry deliveries.
- Supersedes: ADR 0014 (`docs/adr/0014-company-date-stamped-at-the-source.md`) wholly.
- Supersedes in part: ADR 0013, ADR 0016 and ADR 0017, for the park registry passages named in decision 9.

## Bottom line

An outside process delivers a small CSV file of park facts, the park registry feed, and the warehouse joins it to the
events to give every event its company date. Events carry no company year, and the plugin and the listener change
not at all. What is given up is the producer's own statement of its date: an event no longer says which company year
it belongs to, so a wrong registry row silently re-dates every event of that park until the row is corrected. The
feed's version history becomes the record of what was believed when.

## Context

ADR 0014 proposed that the plugin stamp every event with its company year, read from two values stored in the park's
own save file. The project owner chose instead to keep the facts about a park in a feed and compute the year in the
warehouse. The stamp would have needed a plugin change, a re-run of `make bench` (the per-tick cost measurement), and
a windowed seeding session for each save. The two-park rehearsal of 2026-10-09 (`docs/FINDINGS.md`, observational:
two rehearsal parks, one player) showed the formula holds: it gave shared company years 2003 to 2005, of which 2003 is
a partial year for Park 2. It also broke ADR 0014's claim that Park 2 starts on 1 March 2003, because that park's
first kept date was 4 June of game year 6. A design that maps years and passes the game's month and day through never
assumes a start date, so it absorbs that result. "Exactly one managed park per company year" was not tested and stays
with NEXT 6.

## Decision

1. **The feed's grain and columns.** One row per park per delivery file: its company start year, its game-year origin, its data set, a
   note, and the delivery date (`delivered_on`). A delivery is identified by its park and its file, not by
   `delivered_on`.
2. **The formula and the date macro.** Company year = company start year + (game year - game-year origin). One shared
   dbt macro, `company_date`, turns a company year with the game's month and day into a calendar date. The season is
   8 months, March to October; the game's month 0 is March, and the macro adds no other rule.
3. **Deliveries are append-only and dated.** Each delivery is a file named `park_registry_<YYYY-MM-DD>_<NN>.csv`,
   and `NN` orders same-day deliveries, from `01` to `99`; a park's deliveries run in the order of the file name's
   date, then `NN`, and `valid_from` and `valid_to` are file-name dates. `_00` is a misnamed file, left out of the
   history. A delivery holds only changed rows; a park absent from a later
   delivery keeps its last row. A duplicate park in the current delivery is an error; in a superseded delivery it is
   a warning. A file-name date that differs from `delivered_on` fails when its delivery is current and warns when
   superseded, so a later delivery always cures a bad one; a misnamed file and an out-of-bound `delivered_on` (before 2026-01-01 or after the build date) only
   warn.
4. **History is derived on every build.** An intermediate model works out type-2 history (each park's rows with the
   span each was current) with window functions, never a dbt snapshot, because ADR 0013 already rebuilds the whole
   warehouse and audits it on every publish.
5. **Staging renames and casts only.** It adds no rule and converts nothing else.
6. **The feed is a landing area with its own contract.** CSV files land per data set, each checked by its own ODCS
   data contract, on its own version line, and `make contracts` runs that check. ADR 0007's one shared version line
   covers event contracts only: the feed is not an event stream, has no `seq`, and changes for reasons the events do
   not.
7. **dbt reads the feed through `source()`, never a seed.** The seed `seeds/park_registry.csv` is removed.
8. **Models use the current registry version.** Every model that needs a park's company year reads the current model
   (`int_park_registry__current`), not the history.
9. **Passages replaced.** In ADR 0013, the "Park identity" row's rule that the publisher checks parks against a
   committed registry file, and the closing passage that names `seeds/park_registry.csv`; also the sentence "A park
   listed under both data sets in the registry fails `dbt build`" (`:74-75`), because each data set has its own feed
   and a park is checked against the one feed of its data set. In ADR 0017, only the registry clauses of the "Rows
   required at publish" row: the audit's refusal of a candidate holding "no registered `park_id`", and "The rest of
   the Park-identity row (the registry check and its `unique` test) stands." The row's `meta.expected_min_rows`
   publish rule stands. In ADR 0016, the `int_company_years__validated` and correction-seed plan (`:78-79` and `:89-90`) and the
   "Clock" row's wait on ADR 0014 (`:53`). The rest of each record stands.

## What was given up

The producer's own statement of its date. Under ADR 0014 each event said which company year it belonged to, and the
warehouse could test that stamp against the park's other events. Now the registry row is the only source of a park's
company year, so a wrong row silently re-dates every event of that park until a corrected delivery lands. The seed's
git history and ADR 0014's correction list and agreement test are replaced by the feed's version history, which keeps
every delivery and so records what was believed when.

Also given up: the plugin and `make bench` stay as they are, so there is nothing to catch a registry error at the
source. `make transform` of a new park's first capture fails until its feed row lands.

## Rejected alternatives

- **The plugin stamp (ADR 0014).** A plugin change, a `make bench` re-run, and a windowed seeding session for each
  save.
- **A stamp added by the listener.** It needs a holding store and business logic in the listener, which today only
  appends. Both are weighed in `docs/ai-dlc/reports/company-date-stamping--findings.md`, section 2.5.
- **A dbt snapshot for history.** A rebuilt warehouse (ADR 0013) has no place to keep snapshot state.
- **Keeping the seed.** The seed's only record of change is git history, and an outside process cannot deliver it.

## Consequences

- ADR 0014 gains the status line "Superseded by ADR 0023"; ADRs 0013, 0016 and 0017 each gain "Superseded in part by
  ADR 0023". No ADR body is edited.
- The metric catalog and the requirements brief name this record, the feed's current model and `company_date`.
- **How we would know this is wrong:** a registry error re-dates events and no test catches it before a report does,
  or a park's start date cannot be stated as a start year and origin. Either reopens this record.
