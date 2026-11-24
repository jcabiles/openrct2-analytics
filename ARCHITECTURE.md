# Architecture

<!-- This document describes what the system IS, right now. Update it in the
     same change that changes the system's shape; do not let it drift. -->

## Summary

Thirteen event types flow through the system: daily `park_snapshot` and
`plugin_stats`, `session_start`, monthly `finance_month`, daily
`ride_snapshot`, `save_written`, `weather_change` (one event per observed change of the weather type), `game_action`, and five guest events (`guest_arrived`,
`guest_left`, `guest_refused`, `guest_snapshot`, `guest_boarded`). The plugin sends them, the listener lands
them, the converter types them and audits `seq`, the contract runner checks
them, and the dbt staging models rename, type, deduplicate and convert
money to dollars. Each stage runs from its own `make` target on the previous stage's
output, and every command that reads or writes a capture names its data set
(`DATA_SET=rehearsal` or `DATA_SET=company`). `make pipeline` chains the last
three, `make publish` turns a data set's Parquet into an audited, read-only
warehouse file, `make capture-data` runs a play session from installation to
conversion, and `make bench` measures the plugin headless on a benchmark
fixture. Every contracted event type except `plugin_stats` and `weather_change`, guests included, has a staging
model (`weather_change` is staged later, ADR 0034); the intermediate layer holds the park registry, company-year, session
lineage, labeled statement, guest stay, park-day and ride-day models
(`int_guest_stays` is still provisional: it does not yet label its rows kept or
abandoned). The marts layer holds fourteen models, `fct_park_day` (kept park-day
readings), `dim_date` (whole company months, March to October), `dim_park`
(registered parks), `fct_park_month` (operating profit per park per company
month), `obt_park_month` (one summary row per park per kept statement month),
`obt_company_month` (one summary row per company month, with ratings pooled over
park-days and `parks_reporting`), `obt_park_year` (one row per park per company year, with a close status) and `obt_company_year` (one row per closed company year; operating profit
per year), `obt_ride_month` (one row per ride per game month, rides only) and `obt_ride_year` (one row per ride per company year, with a rank within the park), `dim_ride` (one row per ride occupancy), `dim_item`
(item codes seen, no names), `fct_ride_day` (kept ride-day readings) and `fct_cleaning_rule_count` (one row per cleaning rule per model, counting the rows
each rule keeps, removes or changes). The
repository serves two site pages, the showcase page and the player guide at `/guide`, and eight committed JSON files (`site/`): seven exports and the sample record `sample.json`; the showcase page reads all eight.

## Pipeline as built

1. **Plugin** (`plugin/src/`, TypeScript compiled to ES5). `main.ts` registers the plugin; `identity.ts` mints or
   reads `park_id` and mints `session_id`; `events.ts` builds the daily `park_snapshot` and `plugin_stats` and the
   one-off `session_start`; `finance.ts` reads the monthly statement; `emit.ts` stamps the envelope and owns the line
   queue; `work.ts` owns the work queue and its per-tick allowance; `rides.ts` builds `ride_snapshot`; `guests.ts`
   tracks guests, exits and refusals; `boardings.ts` polls car seats; `cohort.ts` follows the random guest sample;
   `values.ts` checks required integers; `transport.ts` owns the socket and its reconnects; `timing.ts` times every plugin callback. It streams events over localhost TCP
   to `127.0.0.1:8765`, always: the plugin has no port setting, so `OPENRCT2_LISTENER_PORT` moves only the listener
   and is for tests. A real capture needs the default. The build is one ES5 script with no modules (`outFile` in
   `plugin/tsconfig.json`), so top-level names in every `plugin/src/` file share one namespace. Its tests run in Node
   against a stand-in for the game (`plugin/test/*.test.mjs`).

   The work queue runs oldest-first steps in `interval.tick`. Its 4 ms allowance covers all plugin time already spent
   in that tick as well as its own work. It never cuts a step short and runs one pending step even when the allowance
   has already been reached, so an overshoot is at most one step. A day callback keeps its existing events direct and
   queues only the daily ride work. On the next day, unfinished work is skipped and counted, preventing backlog across
   days. A disconnected socket leaves line steps in place while item work can continue.

   The queue holds task objects created once in `main()`. Day-scoped tasks (the ride task and the guest task) get
   their items from the day callback. Continuous tasks (arrivals and boarders) are fed between days and never skipped.
   From the day callback's tick until the day's ride items are done, no guest-kind step runs (`guest_list`, `guest`,
   `arrival`, `boarder`); they keep their order and run afterwards. Every payload builder fills one reusable object per
   event type and writes every field on each fill, which is safe because `emit.ts` copies a payload's fields into its
   own event. The queue adds each step's time to a sum for its kind, so each `plugin_stats` row carries the period's
   worst tick split by kind (`worst_tick_kind_ms`, whose largest entry is that tick's source) and
   `worst_day_start_tick_ms`, the highest whole time of its day-start ticks. A step or seat poll that throws adds 1 to
   `work_items_failed_total`, is not retried, and its error still reaches the game
   (`docs/adr/0018-guest-capture.md`).

   Events beyond the daily pair: `session_start` and `finance_month` from plugin 0.2.0, and `ride_snapshot`, the
   weather and climate fields, and `save_written` from plugin 0.3.0, and the five guest events from plugin 0.4.0. Plugin 0.5.0 adds `weather_change` and thirteen ride statistics on `ride_snapshot`. Plugin 0.6.0 adds `new_month_booked_tenths` on `finance_month`.
   - `session_start` is emitted in `main()` right after the emitter is created, so it is queued first and gets `seq` 1
     (unless the queue drops it before the first hand-off). It carries the plugin API level (standing in for the game
     version; the 0.5.5 plugin API did not expose it; not re-checked on 0.5.6), park name, scenario name, whether the game has a window,
     and game speed.
   - `finance_month` is a monthly statement: one per closed game month. How the plugin reads a statement: in the day
     callback on day 1, index 1 of each of the game's 14 monthly expenditure histories is the closed month's total for
     that line. `statement_year` and `statement_month` are the month before the envelope date, wrapping month 0 to
     month 7 of the previous year. Cash, bank loan and the money already booked to the new month (index 0 of the 14
     histories, summed) are read in the same callback, so each statement is a closing balance and (cash − loan − booked)
     changes from one statement to the next by exactly the later statement's 14 lines; a statement without the booked
     field counts it as 0. On
     day 1 the events take consecutive `seq` values in the order `plugin_stats`, `park_snapshot`, `finance_month`. A
     month the plugin cannot read (a history shorter than 2 entries) sends no statement and adds 1 to the optional
     `plugin_stats` field `finance_months_unread_total`; an increment on a session's last day is never reported. The
     counter exists for a cheat that resets the month counter; a new park's first day-1 callback is 1 April, when
     every history already has 2 entries (inferred from the type definitions' month counter, not yet observed on a new
     park), so a new park counts nothing unread. A session sends a statement only from a day-1 callback: one whose
     first day callback is day 1 (a save loaded on a month's last day) sends that month's statement, and one loaded
     mid-month sends nothing until the next day 1. A save made earlier on day 1 puts that day's statement after the
     save's cut and the next session does not resend it, so the kept timeline can lack that month (inferred from the
     sample's session boundaries, not observed); the missing-month check of roadmap item 4 must catch it. A
     statement still queued when the game quits during a listener outage is lost and uncounted (`docs/adr/0008-money-arrives-as-closed-month-statements.md`).
   - `ride_snapshot` is one daily event for every ride, stall, and facility. The day callback queues a read of the
     ride IDs, then one snapshot step per ID. A ride demolished before its step runs produces no snapshot and is not
     counted as skipped, because no snapshot is due. It records station count and maximum station queue time alongside
     the ride's as-read facts. From plugin 0.5.0 it also carries thirteen ride statistics (speeds, ride time and
     length, vertical and lateral G-forces, air time, drop and lift hill counts, highest drop, inversion count and
     ride category), read through the work queue.
   - `park_snapshot` records optional weather and temperature, while `session_start` records optional climate. Weather
     is read in the direct day callback; climate is read at plugin start.
   - `weather_change` is one event per change of the park's weather type, from plugin 0.5.0. The plugin reads the
     weather every tick (timed as the tick part `weather`, not as a work step) and sends the change at the tick it
     first sees it. The first read of a session sets the starting weather and sends nothing. The type has a contract
     and a landing path but no staging model yet (`docs/adr/0034-weather-change-staged-later.md`).
   - `save_written` records a newly minted save ID. Inside `map.save`, the plugin writes that ID, the writing session
     ID, the last handed-off `seq`, and the count of waiting lines to park storage, then flushes. A later
     `session_start` reports those four loaded-save values.
   - Guest events never read every guest after session start: `main()` reads all guests once to seed a known-guest
     table (seeded guests emit nothing), and each guest first seen gets a `guest_key`, counted from 1 per session,
     because entity IDs are reused slots.
   - `guest_arrived`: the `guest.generation` hook only records the ID and the tick; an `arrival` step emits the event,
     so arrivals have tick resolution. An ID the hook reports again while still known first emits `guest_left` with
     `exit_reason` `id_reused`.
   - `guest_left` and `guest_refused`: a daily `guest` step per known guest reads `map.getEntity(id)`. A null, a
     non-guest, or a guest out of the park after being in is an exit; a ride-refusal thought (nine types, with the ride
     ID in `thought.item`) absent at the guest's previous check is a refusal. Both have day resolution: a refusal that
     appears and expires within a day is missed, and a thought still present is not re-sent.
   - `guest_snapshot`: one per game day for each member of a cohort of up to 100 arrivals. Each arrival joins with
     probability 0.5 (`Math.random`, so the game's own random sequence is untouched) while a place is free; a member
     leaves at its exit. Seeded guests never join, and a reload starts an empty cohort. `items_carried` is the item
     types joined by `|`.
   - `guest_boarded`: a seat poll every 20 ticks, before the queue's steps in the same timed callback, reads every
     car's seats. A seat whose guest ID changed since the last completed poll is a new boarder, and everything the event
     carries is read at that poll. The game leaves a guest's ID in a seat after the guest leaves, so a leftover listing
     is never new. A boarding is missed when it starts and ends between two polls, and when a seat lists the same guest
     at both polls; rides with no cars record none. `ride_price_listed_tenths` is the listed price, standing in for the
     price paid, which the API does not expose.
2. **Listener** (`src/openrct2_analytics/ingest/listener.py`, `make listen DATA_SET=<set>`). It adds `received_at` to
   each valid line and appends it to a dated JSON Lines file under `data/<set>/raw/v1/`, standing in for a Pub/Sub
   topic. A line it cannot accept goes, with the reason, to a `malformed-` file beside them; nothing is dropped or
   rewritten. With no data set it prints one line and exits 2 before binding a port (`CAPTURE_DEFAULT_DATA_SET` in
   `config.py` is `None` until the clean start).
3. **Converter** (`src/openrct2_analytics/ingest/convert.py`, `make convert DATA_SET=<set>`). It reads the raw files
   with in-memory DuckDB and writes one typed Parquet file per event type under `data/<set>/parquet/v1/`. Field names
   and types come from the contracts. An event type with no events gets a zero-row file with the contract's column
   types, so the contract check and dbt always see every table; a raw folder with no events at all still raises its
   no-input error and writes nothing. Events from plugin 0.1.0, which has no statements, no session starts and no
   `finance_months_unread_total`, still convert, pass the contracts and build in dbt, because the new `plugin_stats`
   field is optional; a capture that mixes 0.1.0 and 0.2.0 events converts the same way. It also writes the `seq`
   audit, `data/<set>/parquet/audit/seq_audit.parquet`, one row per session, taken over every event type together
   (`seq` counts all types, so an audit of one type reports false gaps), and exits non-zero when any session has a
   gap, a repeat, or a first `seq` other than 1, or carries more than one `park_id`. A schema error writes nothing.
   The whole run holds the landing lock `data/<set>/parquet.lock` (`src/openrct2_analytics/ingest/lock.py`), which a publish snapshot also
   takes: a taken lock exits 2 with nothing written, and SIGINT, SIGHUP or SIGTERM exit 130 after the lock is removed.
4. **Contract runner** (`src/openrct2_analytics/ingest/contracts.py`, `make contracts DATA_SET=<set>`). It checks the
   Parquet against the fourteen contracts in `contracts/` (an envelope contract and thirteen event contracts) through
   throwaway DuckDB views, and fails on any result that is not a pass. Rules for contract files: a field without
   `required: true` is optional (the ODCS default); only the logical types integer, number, boolean, string and
   timestamp are accepted, so payloads are flat; `schema.name` is the event type and becomes a view name, so it must
   be a plain identifier; and a field sent as read gets no range rule unless the rule admits every placeholder its
   description lists (a rating's minimum is −1). A payload field that shares an envelope field's name must share its
   type (the runner checks); between payloads nothing checks it, yet the envelope view and the capture report read all
   types together by name, so a reused name keeps one type. The park registry feed's contract, `contracts/reference/park_registry.odcs.yaml`, is not one of the fourteen: `registry_feed.py` (`python -m openrct2_analytics.ingest.registry_feed`, run by `make check` on the committed sample, by `make contracts` and by `make transform`) checks the feed's CSV files against it through one throwaway view and never writes to the feed. The play-mode label feed has a third one, `contracts/reference/session_play_mode.odcs.yaml`, which `python -m openrct2_analytics.ingest.play_mode_feed` checks (`make check` on the sample, `make contracts`, `make transform` and the publish contract step); a data set with no label file is clean. The save-file records have their own contract there, `contracts/reference/save_file_observation.odcs.yaml`, which `python -m openrct2_analytics.ingest.save_files` checks (`make contracts` and `make check` run it) in the same way.
5. **dbt** (`models/staging/`, `make transform DATA_SET=<set>`). Every model is a table (`+materialized: table` in
   `dbt_project.yml`), never a view. Staging has one model per contracted event type, plus `stg_envelope`; `plugin_stats`
   and `weather_change` (staged later, ADR 0034) have none. Each reads its Parquet through a source whose data root is the dbt variable `parquet_root`, lists the
   envelope columns first (including `received_at`, `_raw_file` and `_raw_line`), then the payload, and does only five
   things: rename, cast, turn placeholders into null, convert money from tenths to
   dollars through the one `tenths_to_usd` macro, and keep the first-received delivery of each `event_id`. The
   placeholders that become null, each in its own column only, are −1 in a ride's three ratings, 1,275 in unmeasured
   satisfaction and 255 in `shop_item` and `shop_item_secondary` (`stg_ride_snapshot`), and 65535 in
   `stg_guest_snapshot.thought_item`. 255 in the guest `happiness`, `hunger`, `thirst` and `nausea` columns is a real
   maximum and stays, as does the empty `items_carried` that means "none" (ADR 0028,
   `docs/adr/0028-guest-staging-keeps-255-and-nulls-65535.md`). A null `thought_item` means no argument, no thought or
   a failed item read; `thought_type` says whether a thought exists. On the committed sample (1,478 guest snapshot rows, measured 2026-10-21) 277 rows carry 65535 and 1,227 have a null or 65535 `thought_item` before staging; staged, 1,227 are null and none is 65535. The tie-break
   for that dedupe is `received_at`, then `_raw_file`, then `_raw_line`, so the same input always keeps the same row.
   The models that carry money (`stg_ride_snapshot`, `stg_park_snapshot`, `stg_finance_month`, `stg_guest_arrived`,
   `stg_guest_boarded` and `stg_guest_snapshot`) declare enforced contracts, with money as `decimal(18,2)`.
   `stg_finance_month` converts all 17 money columns (the 14 ledger lines, cash and bank loan) and has one row per
   statement (a reload can give two rows for one park and month, which `int_statements__labeled` resolves by labeling
   at most one of them kept).
   `stg_session_start` has at most one row per session (a session from plugin 0.1.0, or one whose `session_start` the
   queue dropped before the first hand-off, has none), so a consumer starts from events and left-joins sessions, never
   the reverse. `stg_session_start` also carries `play_mode`, `managed` or `autopilot`: it left-joins `stg_session_play_mode`, which stages the play-mode label feed (one row per labeled session), on `session_id`, and a session with no label row is `managed` (ADR 0049). `stg_envelope` is the exception to the dedupe: it keeps every landed delivery, holds only the envelope
   columns, and exists for the landed-event count check. The park registry is a feed, not a seed: `stg_park_registry`
   reads the CSV deliveries under the `registry_root` variable (the dev and ci targets default to the committed sample
   feed; rehearsal and company have no default), and `int_park_registry__history`, `int_park_registry__current`,
   `int_park_years__company_year`, `int_park_years__registry_mapped`, `int_park_years__year_close` (one row per expected park and company year, with its close status), `int_park_days__company_calendar`,
   `int_park_days__kept` and `int_ride_days__kept` build on it. `int_park_years__registry_mapped` owns the company-year
   rule (`company_start_year + (game_year - game_year_origin)`); the company-year, statement and calendar models read
   it. A park the registry cannot map to a company year fails the build through
   `assert_every_park_year_has_a_company_year`. Save-reload lineage builds on staging: `int_sessions__lineage` links
   each session to the save it loaded and marks the kept path (ADR 0024), and `int_statements__labeled` labels every
   statement `kept` or `abandoned` and gives each mapped statement a company date. These singular tests fail the build
   on bad data: `assert_kept_sessions_never_overlap`, `assert_every_park_has_a_kept_session` (which also catches a
   session that names itself as its parent), and `assert_every_kept_statement_has_a_company_date` (which also catches a
   mapped statement with no company date). A fourth, `assert_counter_change_stays_within_one_session`, checks the
   `counter_change` macro on fixed readings. The company calendar and the park-day mart add
   `assert_company_calendar_matches_the_macro`, `assert_dim_date_has_whole_months_and_seasons`,
   `assert_every_kept_statement_finds_its_company_year`, `assert_admissions_increase_is_never_negative` and
   `assert_park_day_admissions_reconcile_exactly`. `assert_every_kept_statement_finds_its_company_year` cannot fail on the sample, because both sides read the same year; the statement-only-year unit test is the real proof. The ride-day mart adds `assert_customers_increase_is_never_negative`
   and `assert_ride_day_counters_reconcile_exactly`.

   Two tests watch the game days of a closed month (a month with a
   kept statement). `assert_every_day_of_a_closed_month_was_captured` fails the build on a day that no session
   captured, from the park's first captured day onward; it only warns on `ci` and on `dev` over the committed sample. `assert_every_captured_day_of_a_closed_month_is_kept`
   only warns, listing each captured day that was dropped, with the reason `save_boundary`, `no_cut` or `abandoned_session` (ADR 0031).

   The calendar, park-day and ride-day models follow these rules. The calendar is built from each mapped park-year's
   eight month starts, not day by day through the `company_date` macro, because that macro casts text and day 31 of
   game month 1 would fail the build instead of giving null; it keeps a date only while it stays in its month, so
   248 days are built per park-year and 3 dropped (245 rows on the sample). A park-year with no company year has no
   calendar row. `int_park_years__registry_mapped` knows no months, so the month-range check
   (`game_month_out_of_range`) stays in `int_park_years__company_year` and `int_statements__labeled`. `dim_date` is
   generated by a recursive step between the first day of the earliest company month with a kept park-day or kept
   mapped statement and the last day of the latest, with November to February dropped (ADR 0030). `dim_park` takes
   name, scenario and climate from the park's latest kept `session_start` (greatest `emitted_at`, then
   `session_id`), so an abandoned branch never names a park and a park with only abandoned sessions shows null names.
   `fct_park_day` carries `event_id` and `session_id` and an always-true `is_kept_operating_day`.

   Ride occupancy and the ride-day fact. The game reuses ride, stall and facility slots, so `int_ride_days__kept`
   finds occupancies over every kept reading of a slot across sessions, in one total order: `game_ticks_elapsed`,
   then the session's `session_started_at` from `int_sessions__lineage` (nulls first), then `session_id`, then `seq`.
   A reading opens a new occupancy when it is the slot's first, when its `build_date_months_elapsed`, `ride_type`,
   `ride_object` or `classification` differs from the previous reading's, or when `total_customers` falls. `ride_key`
   is `park_id`, `ride_id`, build month and the occupancy's least tick. Two limits are stated, not hidden. A
   replacement with the same type, object, classification and build month whose customers are at or above its
   predecessor's last reading keeps its predecessor's key. Two occupancies first seen at the one tick that two kept
   sessions share (ADR 0024 allows one shared tick), with one build month, share a key; that gives two rows one
   `ride_day_key`, so the error-level `unique` tests fail the build. Per occupancy and game date, the day's last kept
   reading in that order supplies the snapshot columns. `customers_increase` and `profit_usd` are `counter_change`
   rises computed per reading within one session and occupancy before that choice, then summed per day (null only
   when every rise is null), so a dropped same-day reading loses no rise; one day's change can hold rises from two
   sessions while the row's `session_id` names only the chosen reading's session. `fct_ride_day` carries `status`,
   `is_open_day`, `ride_age_months`, the three ratings, `price_1_usd`, `price_2_usd`, `ride_price_listed_usd`
   (`price_1_usd` for rides, else null), `classification`, `ride_type` and the two counter changes; `profit_usd` is
   filled for facilities too. It also carries three figures for rides only (null for stalls and facilities):
   `availability_from_downtime_pct` (100 minus the game's downtime reading at the day's last kept reading),
   `longest_queue_seen_minutes` (the largest queue reading of the day's kept readings) and `guest_rating_pct` (the
   game's satisfaction at the day's last kept reading); `reliability_pct` is not built. These are mart columns over
   fields the contract already carries, so the contract does not change. Its keys resolve to `dim_ride`, `dim_park`
   and `dim_date` at error severity and to `fct_park_day` at warn. `dim_ride` is one row per `ride_key`, with
   descriptive columns from the occupancy's latest kept ride-day, so a renamed ride shows its latest name and an
   earlier name is not kept. `dim_item` is one row per distinct non-null `shop_item` or `shop_item_secondary` on a
   kept ride-day: codes only, no names and no seed. It is keyed `shop_item` so that it never clashes with the
   catalog's planned text `item_code`; the design's pair form and `on_ride_photo` wait for the roadmap item that owns
   item rules, because neither can be built from the ride snapshot alone. The ride-day catalog entry keeps
   `timeline_status` and `data_set` in `planned_columns`, where the park-day entry deleted the same two because a
   kept-only mart builds neither.
6. Marts and the site page. `models/marts/` holds `fct_park_day`, `dim_date`, `dim_park`, `fct_park_month`,
   `obt_park_month`, `obt_company_month`, `obt_park_year`, `obt_company_year`, `obt_ride_month`, `obt_ride_year`, `dim_ride`, `dim_item`, `fct_ride_day` and `fct_cleaning_rule_count`; the last is not exported to the site. `site/_data/` holds seven committed JSON exports and the sample record `sample.json`, eight files in all (ADR 0045, ADR 0056 and ADR 0057). The page reads them as follows: `fct_park_month`, `obt_park_year` and `obt_company_year` (`site/_data/park_month.json`,
   `site/_data/park_year.json` and `site/_data/company_year.json`) feed the operating profit figures, and the department figures of `obt_ride_month`, `obt_ride_year` and the revenue lines and shares of `obt_park_month` (`site/_data/ride_month.json`, `site/_data/ride_year.json` and `site/_data/park_month_revenue.json`) feed the six served department panels, which show live figures; `dim_park` (`site/_data/park.json`, one row per park) gives each park its number, the one home of the park order. The Guest visits panel and the ride price chart stay pending. The exports are written from the sample warehouse by `make site-export` and compared with a
   fresh build in `make check` (`src/openrct2_analytics/showcase/export.py`; the allowlist is `site/exports.toml`). The sample record `site/_data/sample.json` is written and compared in the same run but is not an allowlist entry: one row of `data_set`, `parks` (distinct parks in `obt_park_year`), `sessions` (distinct sessions in `fct_park_day`) and `player_played` (whether any of those sessions was not headless). The evidence block prints the page's sample statement from it, so the page states its own sample. The
   singular tests `assert_park_month_cash_change_reconciles_exactly`,
   `assert_obt_park_year_reconciles_exactly` and `assert_obt_company_year_reconciles_exactly` fail the build when a mart
   disagrees with the ledger or with the mart it rolls up. The first test also fails on a missing month between two kept statements
   (`months_since_previous_statement`); it fails at error severity with no recovery path yet for a data set that lacks a
   month, and that decision is open with the project owner. A game day of a closed month that no session captured, from the park's first captured day onward, now
   fails real-data builds too, through `assert_every_day_of_a_closed_month_was_captured`; recovery is still to replay
   the save that the failure names. A park's first kept statement has no earlier statement to
   reconcile, so the page marks it "not checked: first month". The page draws the Finance "Operating profit by month" chart, one bar per company month stacked per park, and the month table
   beside it. The evidence block in `#infra` lists every park-year (`obt_park_year`, with its close status) and every closed
   company year (`obt_company_year`), each labelled "not yet reconciled"; it picks no latest year and has no headline
   figure. `int_park_years__year_close` owns the close rule: a company year closes only when every park expected in it has
   all eight monthly statements and at least one of them is complete, and a park's partial first season never holds a year
   open (a first captured day 1 of month m already carries month m - 1's statement, so the first reportable month is m - 1).
   The test `assert_every_expected_park_closes_its_company_year` fails real-data builds when a park has moved on to a later
   year while still missing an earlier statement, or (outside a partial first season) has kept a later month of the
   same year than one it is missing, or when `obt_company_year` holds a year the register does not mark
   closed; it warns on `ci` and on `dev` over the committed sample, where
   `obt_park_year` has 1 row and `obt_company_year` has 0 (ADR 0035). `months_checked` counts park-months whose
   identity was tested; in `obt_company_year` it sums across parks, so with two parks a closed year can show up to twice
   the months of one park, and the page heads that column "Park-months checked". The 8 in the park-years table is the
   mart column `statements_expected`. Every other figure on the page is read live from the exports or reads "figure
   pending", as the figure registry (`site/figures.mjs` and `site/figures/`) decides. Page prose comes from the story
   passages in `docs/showcase/story/`, and sentences that carry export values come from the figure registry; the only numbers on the page that are not export values are the cited copy
   numbers listed in `tests/site_copy_figures/*.toml`. `npm run site:build` writes the page to `site/_site/` (git-ignored). Reading Parquet in the
   browser from a published file waits for roadmap NEXT 15 (ADR 0026). `obt_park_month` has one row per park and kept
   statement month; `obt_company_month` has one row per company month, pools ratings over park-days and counts
   `parks_reporting`; both read only the park-month and park-day facts, and `rows_on_sample` counts 3 rows in each on
   the sample. The park-month reconciliation test ties that table to the park-month and park-day facts; the
   company-month one ties that table to `obt_park_month`. Balance test A fails any `obt_` model whose SQL text names a
   day-start balance column (`cash_usd` or `guests_in_park`), summed or not; balance test B fails when a statement's
   closing cash differs from the next game day's opening cash, and its count guard applies only on target `ci`. Three
   planned dbt exposures, one exposure for the built operating-profit page, and the docs overview block (with the bus
   matrix) declare the reporting; `scripts/check_exposures.py` fails an `obt_` model with no exposure. Downstream
   dashboards will read only `models/marts/`, in a published file (see "Environments and publishing").

**Capture command** (`make capture-data DATA_SET=<set>`, `src/openrct2_analytics/ingest/capture.py`). It wraps stages 1
to 3 for a player who owns the game. With no data set it refuses first, before any folder, port, build or install. It
refuses, changing nothing, when it is unsafe to start; builds the plugin; installs it in the player's OpenRCT2 `plugin`
folder with an install record in its capture folder; runs the listener on `127.0.0.1:8765` until a once-a-second game
check sees the game quit; and removes the plugin however the session ends. After a normal quit it converts the capture
and prints a report of the run, including a "Save files" section. It never runs the contract check or dbt: `make
pipeline DATA_SET=<set>` (`make convert`, `make contracts`, `make transform`, stopping at the first failure) does. Exit
codes are 0 clean, 1 capture problem, 2 refused and 130 interrupted. `make play DATA_SET=<set>` is the same command with
`--open-game`: it opens the game itself (see "Play launcher and backup" below). Its modules:
- `capture.py` owns the options, the refusal order and the cleanup order; its signal handlers come from `lock.py`.
- `capture_session.py` owns the session (install, serve and watch, cleanup) and the convert-and-report step.
- `save_watch.py` owns the save-file watcher thread, `save_files.py` the save-file records' folder, reader and contract
  check, and `save_pairing.py` the pure pairing rule and the text of the "Save files" section.
- `save_backup.py` owns the backup of each park's last recorded save and the warning before play.
- `plugin_install.py` owns the default OpenRCT2 folder per platform, the build, the install record and the proof that
  a plugin file is the command's own.
- `game_check.py` answers whether the game runs, by `pgrep`'s exit-code contract (`tasklist` on Windows).
- `capture_report.py` summarizes the run's Parquet, including the plugin's tick cost against
  `docs/adr/0005-plugin-per-tick-budget.md`.

Behavior a maintainer cannot see quickly from the code:
- **Where it installs.** The OpenRCT2 user folder defaults to `~/Library/Application Support/OpenRCT2` on macOS,
  `$XDG_CONFIG_HOME/OpenRCT2` (else `~/.config/OpenRCT2`) on Linux and `%USERPROFILE%\Documents\OpenRCT2` on Windows;
  `OPENRCT2_USER_DIR` overrides it. The plugin goes into the `plugin` folder inside it as `openrct2-analytics.js`.
  Game process names are `OpenRCT2`, `openrct2` and `openrct2.exe` (`--game-process` overrides). Only `config.py`
  reads these variables. Only macOS has run against the real game; Windows and Linux are untested.
- **Refusals** exit 2 with "Nothing was changed.", checked in this order before any write: the save-file folder
  `data/<set>/save_files` would equal, contain or lie inside another landing folder, or it or its `v1` resolves
  outside the data set's own folder (compared after resolving links; a relocated data folder is allowed); the user folder, its `plugin` folder or its `save` folder is missing; the game runs or cannot be checked;
  the fixed address `127.0.0.1:8765` cannot be bound;
  the install record names another path; the install path holds a file that is not the command's own, a symlink, a
  non-regular file or a file with more than one hard link (the one exception is the command's own temporary name); the
  temporary name holds a foreign file; another `.js` file in the plugin folder holds both `registerPlugin` and
  `"openrct2-analytics"`; a setting is invalid; the plugin build failed; or the game was opened while the plugin built
  (the game check runs again just before the install). The command ignores the listener host and port settings,
  because the plugin sends only to 8765; `--port` is a test seam and prints that the real plugin cannot reach such a
  listener. On macOS a bind to `127.0.0.1` still succeeds while another program listens on `0.0.0.0` on the same port,
  so the busy-port refusal covers only the same address.
- **Watching the save folders** (`docs/adr/0037-save-file-records-outside-the-event-envelope.md`, and
  `docs/adr/0040-watch-the-games-remembered-save-folder.md` for the fourth folder). The plugin cannot see file names,
  so a daemon thread scans up to four folders once per `--poll-seconds`: `save`, `save/autosave`, the user folder
  itself and, when `config.ini` names one, the game's remembered save folder, kind `remembered` (each folder's own
  entries only). `remembered_folder` reads `last_game_directory` under `[general]` of `<user folder>/config.ini` once,
  before the watcher starts (a quoted value loses one pair of quotes; empty is `""`). With no usable value it adds
  nothing. A missing `config.ini`, a missing key or an empty value prints `Note: config.ini names no remembered save
  folder; watching the save, autosave and user folders only.`; an unreadable or malformed `config.ini`, an unusable
  path and a relative path each print their own `Note:` line instead. A value that
  names a default folder is not watched twice. A value outside the user folder prints `Warning: the game's remembered
  save folder <folder> is outside the OpenRCT2 user folder; watching it too.`; a folder that cannot be listed prints
  `Note: ... cannot be read (...); it is not watched.` and is dropped; a missing one is waited for. The thread appends
  one JSON Lines record for each `.park` file created or changed, to `data/<set>/save_files/v1/save_file_observation_<UTC
  date>.jsonl` (contract `contracts/reference/save_file_observation.odcs.yaml`; a base name and kind, never a path). The
  first scan runs on the main thread before the "Open OpenRCT2 now" line and writes a `start` record for every
  `.park` file (ADR 0048; before it, only `*-main` files). A missing `autosave` or remembered folder is waited for; a folder that vanishes mid-run prints a line
  when it vanishes and another when it returns, and is not a failure, but any other I/O error in a later scan,
  remembered folder included, stops the watcher and fails the capture with exit 1. The thread shares no object with
  the listener and writes none of its files. Convert, the event contract check and dbt never read `save_files`;
  `make contracts` checks the records against their own contract. The alias check on the folder is one way:
  `registry_dir` and `make delete-company-data` do not compare against `save_files`.
- **Save pairing and the exit rule.** After convert, the report pairs each `save_written` event of this run, one to one,
  with a file of this run. Rows are first cut to the run by `received_at`, then reduced to the first-received row per
  `event_id`, with ties on `received_at` broken by `_raw_file`, then `_raw_line`, as in
  `models/staging/stg_save_written.sql`. Three things are new in `save_pairing.py`: the window and pairing rule, the cut
  of rows to one run by `received_at`, and the first-received dedupe done within that cut run (staging dedupes over all
  rows, so an `event_id` delivered in two runs keeps the later run's row here and the earlier run's row there). Only `created`
  and `modified` records count (`start` records never pair). A candidate is a distinct file
  (folder kind plus name) with at least one such record whose modified time lies in `[emitted_at, emitted_at + 5 s]`;
  its latest record in that window stands for it. An event pairs only when it has exactly one candidate file and none
  of its in-window records lies in another event's window (ADR 0053: the same file saved again later, outside this
  window, does not count as shared); all of the file's in-window records then count as paired. Otherwise (several
  candidate files, or a record that another event's window also holds) the event fails; failing events that are linked through
  shared files form one two-candidate window failure that names all their events and files. An event with no candidate
  fails on its own. These failures, a watcher error and a record line of this run that cannot be read make the run exit
  1. A write record that pairs with nothing is a note; so is an unreadable record line from an earlier run, which does
  not change the exit code. Warnings that never change the exit code compare each `start` record with that file's last
  paired write in an earlier run (for a file without the `-main` suffix, only a change is printed; the "no earlier
  paired write" note and the lost-event warning are `-main` only), and flag a `-main` name written by more than one
  park. An error after
  the first scan is stored and printed when it happens, and the listener keeps running. A failure in the first scan
  raises `WatcherStartFailed`: the run stops before the "Open OpenRCT2 now" line, removes the plugin and exits 1 (not
  130) with no "Save pairing skipped" line. Precedence: a refusal (2), then an interrupt (130), then a stored watcher
  error (1); the error is printed whichever code results. On an interrupt, a stuck connection thread, zero events, a
  converter failure or a watcher that did not stop within its 5-second join limit, pairing is skipped with a "Save
  pairing skipped" line and the records are kept. A later run's report pairs an interrupted run's records using its
  converted events for the `-main` and park lines only; it never prints that run's pairing failure lines.
- **Play launcher and backup** (`docs/adr/0048-open-the-game-and-back-up-the-last-recorded-save.md`). `make launcher`
  compiles the "OpenRCT2 Enterprise" app into `~/Applications` (macOS only, never committed); it opens the committed
  `launcher/play-company.command` in Terminal, in the checkout the app was built from. Every place that shows a park (the filing questions, `make unfiled`, `make autopilot-parks`, the launcher menu, the dashboard banner and the delete preview) takes its label, `<name> (first played <Mon D>)`, from `src/openrct2_analytics/ingest/park_label.py`, the one home of a park's display name, first-played time and label (ADR 0058, `docs/adr/0058-parks-are-named-by-first-played-day.md`). After the direnv checks the
  script first runs `make unfiled DATA_SET=company` (`unfiled.py`: read-only, holding DuckDB's read-only lock on the
  development warehouse only while it reads), shows any play waiting to be filed and, when the first line is `offer` or
  `offer-after-convert`, offers to file it before this play (after a convert for the latter; a session that failed its
  `seq` audit, a raw recording file with a line that cannot be read (named by file), a live recording, or a warehouse being built withholds the offer; filing itself also refuses while a failed session waits). Then it
  asks "Where should this play count?" (Company, Sandbox or "Run autopilot on a finished park"). The third answer
  reads the park list from `make autopilot-parks DATA_SET=company` through `src/openrct2_analytics/ingest/autopilot_menu.py`, offers the
  parks with no `source_problem` (the others are shown with their reason and cannot be chosen), asks for the
  `READY` phrase (ADR 0049) on a park's first run, starts the dashboard if needed, runs `make auto-file DATA_SET=company RECORD=yes`, then
  `make autopilot-year DATA_SET=company PARK=<id>` under `caffeinate -i` (about two hours, window kept open), then
  `make auto-file DATA_SET=company COUNT_AS=company` and opens the dashboard; a park list that cannot be read gives
  `make autopilot-parks DATA_SET=company` and says to choose 3 again, a failed record step says to choose 3 again, and a
  year that does not finish says to choose 3 again when its messages show nothing was written or company data was not
  touched (or make stopped with a line starting with `***`), otherwise the window gives the
  `make auto-file DATA_SET=company COUNT_AS=company` command to file by hand, because the year may have landed; a failed
  filing gives the same command (ADR 0051 decision 1 amendment). For Company and Sandbox it starts the local company dashboard when nothing
  answers on port 8780, runs `make auto-file DATA_SET=company RECORD=yes`, then
  `direnv exec . make play DATA_SET=company`, and after a play that exits 0 runs
  `make auto-file DATA_SET=company COUNT_AS=<company|practice>` (ADR 0051; a play that opened several new parks asks about each, ADR 0055; `practice` is the stored value shown as
  Sandbox), then opens the dashboard app's Executive page in the browser once filing exits 0. After any other exit of the play it prints
  the `make auto-file` line to run by hand, because `make` reports every
  failed recipe as exit 2. With `--open-game`, the command prints any pre-play warning (a `.park` file whose start record
  differs from its last paired write, with the newest game-folder backup of its park), then the "Open OpenRCT2 now"
  line, then runs `open -a OpenRCT2` and must see the game within 60 seconds (the limit runs only while the check
  clearly says "not running" and no event landed), else it cleans up, exits 1 and, if the game appeared meanwhile,
  prints a loud "NOT recording" line. After a
  healthy `company` run (pairing, watcher and `seq` audit all passed), each park's last paired save is copied to
  `<user dir>/save/<park name>-last-plugin-save-YYYY-MM-DD.park` (replaced by a later run that day only while its
  bytes equal one of the park's archive copies; otherwise written beside it with `-HHMMSS` added) and to
  `OPENRCT2_BACKUP_DIR/<park_id>/<park name>-YYYY-MM-DD-HHMMSS.park` (default `local/park-backups`, never replaced).
  A park whose chosen file, or another of its paired files, was written again later in the run is skipped with a line.
  The source must match its record's size and millisecond modified time before and after the copy; a failed copy exits
  1 and says the recorded data is fine. A run with no recorded save exits 0 with a note. Rehearsal runs make no copy.
- **Build.** The plugin is rebuilt on every run. The TypeScript compiler writes its output even on a type error, so a
  file's age cannot show a good build. The output is deleted before each build and again after a failed one, and a
  build that exits 0 without writing it refuses.
- **Install and ownership** (`docs/adr/0009-capture-data-removes-only-a-plugin-it-can-prove-it-installed.md`). The
  install record `installed-plugin.json` in the capture folder is written first (install path, SHA-256 of the bytes,
  time); then the plugin is copied to the temporary name `.openrct2-analytics.js.capture-tmp` (no `.js` suffix, so the
  game never loads it), published with a hard link that fails instead of overwriting a file that appeared after the
  checks, and the temporary name is removed. Signals are held until the install step ends. A file is the command's own
  only when the recorded path equals the install path and its SHA-256 equals the recorded one. The next start removes
  such a leftover from a killed run (plugin or temporary file), and clears a record whose files are gone.
- **Watching the game.** The game check runs once a second under `pgrep`'s exit-code contract: 0 running, 1 not
  running, anything else cannot tell (retried while waiting, a refusal at start). The default is `pgrep -x <name>`
  (`tasklist` on Windows); `--game-check-command` replaces it. The game has quit when the check answers 1 after
  answering 0. The command never reads input; on a terminal it discards typed-ahead input at cleanup with
  `termios.tcflush`, so a line typed during play never runs as a shell command afterwards. The agent sandbox has no
  pseudo-terminal and cannot list processes, so the tests use a Python child process as the stand-in game, and the
  real `pgrep` and `tcflush` paths ran only in the 2026-10-01 macOS session.
- **Cleanup on every ending.** The first SIGINT, SIGHUP or SIGTERM sets all three to ignored before it interrupts the
  session, because `uv run` forwards SIGHUP and SIGTERM (a Terminal close delivers the signal twice) and a second
  signal used to cut cleanup short. The order is: remove the plugin, close the listener, write the report; a print
  that fails never stops cleanup. The listener stops accepting, closes open connections and waits up to 10 seconds for
  its connection threads, so conversion never reads a file still being written. The plugin file is removed only under
  the ownership proof, and the record is deleted only after the file is gone, so a failed removal keeps the record and
  exits 1. A normal game quit loses no line. In an interrupted run with the game still connected, macOS discards bytes
  received but not yet read, so the session's last lines are lost and a line cut in half lands as one malformed
  record; the `seq` values that land stay contiguous. An interrupted run exits 130 without converting and keeps the
  raw capture. A SIGKILL cannot be handled; the next start recovers it.
- **Conversion and report.** After a normal quit the command calls the converter over the whole raw folder. It exits 1
  when no event landed (it prints "No event landed in this run." and converts nothing), when the converter raises (a
  taken landing lock included) or a schema error occurs (no report is built from older Parquet), when a session of
  this run has a `seq` violation, or when plugin removal fails. A session belongs to this run when any of its events
  has `received_at` at or after the command's start; violations in earlier sessions only warn. The converter, though,
  exits non-zero for a violation anywhere in the raw history, so once any session has one, `make pipeline` stops at
  convert on every later run (the Parquet is still written). The malformed-line count covers the whole raw folder.
  Session IDs print in full: they begin with a millisecond time, so their first 8 characters repeat for sessions
  minutes apart.
- **Judging the plugin's cost.** Judged rows are this run's `plugin_stats` rows with `warmup = false`,
  `clock = 'performance'` and `game_speed = 1`. The worst tick is the largest `worst_tick_ms` and the mean is the sum
  of `work_ms_total` over the sum of `period_ticks`, in milliseconds. Both limits pass at equality (10 ms, 1.25 ms per
  tick). With no judged rows the report prints no numbers. A monthly statement's covering `plugin_stats` row is the
  one with `period_start_ticks` at or below the statement's `game_ticks_elapsed` and `period_end_ticks` above it, not
  "the next row", because a row the plugin's queue dropped would shift that.

`make check` runs the plugin tests, the contract check, dbt and the SQL lint over the committed sample in
`data/sample/rehearsal/`, on the `ci` target in a temporary folder; `make transform DATA_SET=<set>` builds dbt over
`data/<set>/parquet/` into `warehouse/dev/dev.duckdb`. After the zero-row dbt build, `scripts/check_model_columns.py`
compares every built model's columns in `ci.duckdb` with its YAML columns and fails on an undocumented column, an
unbuilt YAML column, a model with no built relation, or a `_tenths` column built outside `models/staging/`. Then
`dbt docs generate --target ci` builds the docs site and its overview, and `scripts/check_exposures.py` fails when an
`obt_` model has no exposure. Then `scripts/check_cleaning_rule_counts.py` fails when a known cleaning filter has no row in
`fct_cleaning_rule_count`; the SQL lint follows. See
`docs/adr/0003-local-socket-and-jsonl-stand-in-for-pubsub.md` for why the pipeline is shaped this way and
`docs/adr/0007-seq-stamped-at-hand-off-and-one-contract-version.md` for the event envelope,
`docs/adr/0010-work-queue-spreads-capture-across-ticks.md` for the work queue,
`docs/adr/0008-money-arrives-as-closed-month-statements.md` for why money arrives as monthly statements, and
`docs/adr/0011-save-lineage-is-recorded-in-park-storage.md` for save lineage.

**Player actions.** The plugin hooks the game's action pipeline twice (`action.query` and `action.execute`) and sends one `game_action` event per call to a kept action (contract 1.8.0). Before the call enters the 2,048-row buffer, `plugin/src/action_names.ts` keeps 13 business actions by name (`ridesetsetting` only for codes 0 to 5, 8 and 9, `ridesetvehicle` only for types 0 and 1) and drops every other action, every preview, every unlisted sub-type and every unknown name; a dropped call takes no `seq`, and five `plugin_stats` counters (`game_actions_skipped_preview_total`, `_prediction_`, `_confirmed_`, `_unknown_` and `_cheat_`) count the drops (ADR 0042, `docs/adr/0042-plugin-sends-only-business-actions.md`). The `action_label` of a sent row is `preview` (only in rows from plugins before 0.8.0) when `args_flags & 64` is non-zero, else `prediction` when the hook reports the call as client-only, else `confirmed`; both raw signals (`args_flags`, `is_client_only`) are kept. `int_game_actions__labeled` keeps every staged row and adds `is_plugin_issued` (the row's `player` is in the dbt variable `plugin_issued_player_values`, or its arguments carry the key `analytics_issued_by`), `is_player_action` (true only for an `execute` row labeled `confirmed` that the plugin did not issue; previews and predictions never count, invariant 4) and `is_refused` (a non-zero result error). `plugin_issued_player_values` is set in `dbt_project.yml`; the value comes from the headless benchmark host and the human value is checked by `make real-play-check` (`src/openrct2_analytics/ingest/real_play_check.py`), which prints whether the plugin captured what it should in the latest practice session. The rules are in `docs/ai-dlc/specs/player-actions.md`.

**Benchmark** (`make bench`, `make bench-sample`): the rules, refusals, verdict and sample method are in `docs/architecture/benchmark.md`.

## Environments and publishing

Each environment is its own DuckDB file, because DuckDB lets one process write a file or many read it, never both. A
data set is `rehearsal` or `company`; each has its own landing folders and, once published, its own file
(`docs/adr/0013-one-duckdb-file-per-environment.md`,
`docs/adr/0017-data-set-from-the-command-line-and-safe-warehouse-paths.md`). `data/raw/`, `data/parquet/` and
`warehouse/openrct2.duckdb` are no longer read by any command; captures already in them stay until the project owner
decides whether they move to `data/rehearsal/`.

| Environment | dbt target | DuckDB file | Parquet it reads | Built by |
|---|---|---|---|---|
| Development | `dev` (the default) | `warehouse/dev/dev.duckdb` | `data/<set>/parquet/` and the feed `data/<set>/registry/`; the committed sample for a hand-typed `dbt` | `make transform DATA_SET=<set>` |
| Test (CI) | `ci` | `ci.duckdb` in a fresh `$TMPDIR/openrct2-ci.*` folder (`OPENRCT2_CI_DIR`), removed at exit | `data/sample/rehearsal/` and the feed in `data/sample/rehearsal/registry/` | `make check` |
| Production | `rehearsal`, `company` | `warehouse/candidate/run-<run ID>/<set>.duckdb`, renamed to `warehouse/<set>.duckdb` | a copy of `data/<set>/parquet/v1/` and of the feed `data/<set>/registry/v1/` | `make publish DATA_SET=<set>` |

- **Targets.** `profiles.yml` names no published file. A production build needs `OPENRCT2_PUBLISH_RUN_ID`; a value
  other than 1 to 64 letters, digits and dashes sends the build to a folder that never exists, so DuckDB fails at open.
  `ci` needs `OPENRCT2_CI_DIR`. `_sources.yml` defaults `parquet_root` to the sample for `dev` and `ci` only.
  `make check` builds in a `mktemp -d` folder under `$TMPDIR`, runs dbt and `sqlfluff` there, and removes it on exit
  or on SIGINT, SIGHUP or SIGTERM, so it creates no `warehouse/`; `make setup` creates `warehouse/dev/`.
- **`DATA_SET`** comes only from the `make` command line. `listen`, `capture-data`, `capture-rehearsal`, `convert`,
  `contracts`, `transform`, `pipeline`, `publish`, `rollback` and `site-company` stop before any recipe when it is
  exported or is any word but `rehearsal` or `company`; `make check` ignores it.
- **Path guard** (`warehouse_guard.py`). Before every dbt build `make` starts (in `make check`, `make transform` and
  publish) and before the rollback's rename, it exits 2 before anything opens the file when a symbolic link sits in any component of the
  build's absolute path, ancestors of the root included (`symlink`; `make check` resolves its CI folder with `pwd -P`
  first, because macOS keeps `$TMPDIR` under a link), the path is a published file, another name for one or for a file
  under `warehouse/previous/` (hard link included) or itself under `warehouse/previous/`
  (`published`), or it resolves outside the root or holds `..` (`outside-root`). Publish runs it on the published file and
  `warehouse/previous/<set>.duckdb` before the lock is taken, and on the candidate before its build.
- **Publish** (`publish.py`, steps in `publish_*.py`), all inside the lock `warehouse/<set>.lock` (one line: run ID,
  process ID, start time): finish any interrupted rotation; create `warehouse/candidate/run-<run ID>/`; copy
  `data/<set>/parquet/v1/*.parquet` and the feed's `park_registry_*.csv` and `session_play_mode_*.csv` into it under the landing lock; recompute the `seq` audit over the copy; run the
  contract check and the feed checks (registry and play-mode) on the copy; run one `dbt build --target <set>` with `registry_root` set to the copy's feed; audit the candidate (no view; every model whose YAML
  `meta: {expected_min_rows: n}` has n above 0 holds at least n rows, read through the manifest's `relation_name`, and
  a model without the key is exempt; some non-null `park_id` and `session_id`; every `park_id` is registered for the data
  set in the model whose YAML meta says `park_registry: current`, `int_park_registry__current`); set the file to mode 0444; refuse if a `.wal` sits beside the candidate or the published
  file; then hard-link the published file to `warehouse/previous/<set>.duckdb.new`, rename the candidate over the
  published file and rename `.new` over `warehouse/previous/<set>.duckdb` (a first publish only renames the
  candidate). The candidate folder and the lock go however the run ends. `make rollback` takes the same lock,
  finishes any rotation and renames the previous file over the published one: one step back, then no previous file.
  Exit 0 done, after printing `published warehouse/<set>.duckdb: <T> tables, <R> rows; kept <file> for one rollback` (or `no earlier file kept`) as the last line, where the counts cover every base table outside the system schemas and `dbt_test__audit`; 1 a step failed (`publish failed: <reason>: <detail>`, for example `wal`, `no-previous`,
  `rotation-leftover` or `unsafe-path` at the candidate build); 2 refused (`publish refused: <reason>: <detail>`: no or
  unknown data set, an invalid run ID, a taken lock, or `unsafe-path` at step 1 or 2 or in rollback); 130 a signal, after
  the same cleanup. Before the renames, a failure leaves the published file unchanged.
- **Registry and row counts.** The registry comes from the feed: `int_park_registry__current` lists each park's data set, and the audit reads
  it through `relation_name`. A park the registry cannot map fails the build itself, so `make transform` and a publish
  stop earlier than the audit's `unregistered-park` check. The staging row floor (`expected_min_rows`) is 0 for `stg_guest_refused` and `stg_game_action`, so a data set with no rows for either event type can be published, 1 for `stg_guest_left` and every other staging model; a data set with no rows of an event type whose floor is 1 (for example no guest rows, from a short session or a plugin before 0.4.0) cannot be published. The two marts also declare `expected_min_rows: 1`, so `make publish` refuses a warehouse with no kept monthly statement. A
  company park is registered by `make register-parks DATA_SET=company` after its capture is converted (ADR 0038); until
  that has run, every company publish fails at the dbt step or at `unregistered-park` or `no-park`.
- **Registry feed landing.** Rehearsal deliveries come from the rehearsal capture command (`make capture-rehearsal`, ADR 0036), which writes the delivery itself through the protocol below; company deliveries come from `make register-parks` (ADR 0038), which writes one row per captured park the registry does not list yet (or, with `PARKS="<id>:company,<id>:practice"`, only the listed parks, each with its own choice, `practice` shown as Sandbox), through the same protocol. The first company park and every sandbox park get company start year 2000; with `START_YEAR=<year>` (ADR 0050) the one non-sandbox park of a run is written with that year, which is required once a non-sandbox company park is registered and must be the company year after the latest year the registered company parks hold (for each registered park, the later of its start year and its last managed year, read from the converted Parquet; abandoned play after a closing 1 March raises it); more than one non-sandbox park in one run is refused (`make auto-file` files several company parks by one run of this registration per park, each with the year it plans; ADR 0055). The year is checked before the lock and again under it. Company deliveries allow a pre-go-live delete (ADR 0033). The landing process writes one CSV per delivery in `data/<set>/registry/v1/`, named
  `park_registry_<YYYY-MM-DD>_<NN>.csv` (`NN` from `01` to `99` orders same-day deliveries; `_00` is a misnamed file).
  The file name, not `delivered_on`, identifies a delivery, and deliveries are only added, except company deletion before go-live (ADR 0033). A
  delivery holds changed rows only: a park absent from a later one keeps its last row, so a delivery never removes a park; a pre-go-live company delete may remove it (ADR 0033). The
  process writes under a name the glob does not match (`.incoming-park_registry_...csv`), runs
  `python -m openrct2_analytics.ingest.registry_feed --file <path>`, and renames the file into place only if that passes.
  The play-mode label feed lands in the same folder as `session_play_mode_<YYYY-MM-DD>_<NN>.csv`, written only by `make autopilot-year` through its landing (below), and is checked by `play_mode_feed`; a `session_id` may appear once across all its files.
  A file that lands anyway makes `make contracts`, `make transform` and the publish fail closed, naming it, until it is
  moved to `data/<set>/registry/rejected/` (ADR 0027). A duplicate park in the current delivery, or a file-name date
  that differs from `delivered_on` there, is an error; in a superseded delivery either is a warning. `registry_feed`
  refuses a feed folder that equals, contains or lies inside any other feed, raw or Parquet folder (exit 2). The
  `company_date` macro (`macros/company_date.sql`) turns a company year with the game's month and day into a date.
- **Readers** open published files with `read_only=true` and close every connection to a file before reopening it to
  see a new publish, because DuckDB keeps one open database per path in a process. `open_warehouse`
  (`publish_audit.py`) refuses a write-mode open of a published or `warehouse/previous/` file.
- **Local company dashboard** (`dashboard.py`, the app in `src/openrct2_analytics/dashboard/`; ADR 0054).
  `make dashboard DATA_SET=company` serves a five-page app (Executive, Finance, Attractions, Pricing, Operations; `/` is
  Executive) on `127.0.0.1:8780` from the development warehouse (it refuses 8765, the recorder's port), for the project
  owner only; the launcher starts it in the background. A page load rebuilds when `warehouse/dev/dev.duckdb` changed:
  it copies the file into `local/dashboard/` (never opening the original, so a running `make transform` cannot fail
  on its lock), skips the copy while a `.wal` file exists, and `data.py` in that package reads the copy's marts into
  one `data.js` that the app's static pages read. The All parks figures leave out Sandbox parks (null
  `dim_park.park_number`) by default: every total is a sum of `marts.obt_park_month` over the parks in view, and cash and
  guests are the sum of each park's last kept reading of the company month (ADR 0059). A switch in `shell()` of
  `src/openrct2_analytics/dashboard/app/shared.js`, drawn under the park picker when a Sandbox park exists, brings them back; its state is only the page
  address query `?sandbox=shown`. The server passes park labels through `window.DASHBOARD_LABELS`, written after the
  banner on each page load. A day counts only when its month has a monthly statement and the park
  day is kept; a ride is shown only when it carried a rider on a counted day. A failed rebuild keeps the last good
  build, and a banner on every page names it, with any Sandbox park or data set other than company, and the parks
  with play waiting to be filed. It also names play that can't be filed right now: a recording under way or a session
  that failed its seq audit, which the app will not offer. While the copy is stale (a rebuild failed or a `.wal` file
  exists, seen even when the warehouse file is unchanged), the banner says the play may still be waiting and to check in
  the app, and its count comes from the older copy. The line comes from
  `unfiled.find_unfiled` over the converted Parquet, the audit file, the raw files and
  the warehouse copy's filed sessions; recomputed when those files, the game state or the landing lock change, or
  when a live recording's 2 minutes pass, without rebuilding the figures. The server binds
  its port before it removes an earlier server's builds; `--detach` (set by the launcher) makes it ignore the hang-up
  signal so it outlives its Terminal window. The single-threaded server never serves files outside the current build
  folder. Each entry of `parks` in `data.js` carries `game_years`, read from `marts.obt_park_month`: for each company year
  (company date clock) the park's game year (`statement_year`, game calendar clock) and the first company month number
  it has a row in; the Executive page uses it to name, beside the company year chips, each park's game year for the shown
  company year and month.
- **Company site build** (`site_company.py`, landing in `site_company_land.py`; ADR 0044 and ADR 0056). `make site-company
  DATA_SET=company` reads the published `warehouse/company.duckdb` read-only and writes the allowlisted export files to
  the git-ignored `local/site-data/`, then builds the site from a copy of `site/` with those files as its data folder into
  the git-ignored `site/_site/`. The committed `site/_data/` stays the sample that `make check` compares and is never
  written. Order of checks, all before anything is written: data set (only `company`), the lock
  `warehouse/company.lock`, the published file (not a link, nor inside a linked `warehouse/`), the identity snapshot of that file, the output folders (no link, alias or non-folder in `local/`, `local/site-data/`,
  `site/` or `site/_site/`; `local/` and `site/` on one filesystem), no link inside the copied `site/` tree, `npm`, then a registry read that refuses a published
  file listing a throwaway sandbox park (ADR 0038). Everything is staged in `local/.site-company-stage-<process ID>/`, and the build input is copied to `local/.site-company-input-<random>/`; `make delete-company-data` removes either one a killed run leaves.
  After the export and before the build, the record guard (the staged `sample.json` must be labeled `company` and must differ from the committed
  `site/_data/sample.json` in `parks`, `sessions` or `player_played`; otherwise exit 2, reason `sample-record`; a missing or malformed record is refused here, before the template can crash on it), then the build, and the page
  check (which also checks the page's sample statement against the staged record) pass, the command writes the build stamp `.site-company-build` (a source line and the SHA-256 of
  `index.html`), then landing re-checks the lock and the published file's inode and modified time, then renames each
  existing output into the stage folder and each staged folder onto its target, so no file is written into an existing
  output folder and a link inside one is never followed. Signals are recorded, not acted on, while landing runs: a signal during the landing is recorded and the command still exits 0 once the landing completes, while one in the gap after it exits 130; a partial landing is put back (exit 1, or 130 on a signal); if a restoring rename fails, the stage folder is kept, its path is printed and nothing is deleted (exit 1). The command holds no lock, so it does not block a publish.
  Exit 0 done, 1 failed (`site-build`, `page-check` or `io`), 2 refused, 130 interrupted. The page prints its sample
  statement from `site/_data/sample.json` (the evidence block, `site/_includes/evidence.njk`, with the sentence in
  `site/figures.mjs`), and the page check verifies it against the served record.
  `make delete-company-data` previews and removes `local/site-data/` and a `site/_site/` for which
  `site_company_land.is_company_build` is true (a real folder whose stamp still matches its `index.html`, so a sample
  build is kept), and keeps `local/site-data/` and the leftover folders when `local/` is a link or resolves elsewhere, and keeps a linked `local/site-data/` unfollowed, and keeps `site/_site/` when `site/` is a link or resolves elsewhere (ADR 0033).

**Crash points.** A SIGKILL or power cut runs no cleanup (no step calls `fsync`) and leaves the lock `warehouse/<set>.lock`,
so the next publish or rollback exits 2 at the lock until "Stale locks" is followed; each rename happens whole or
not at all. After that, the next publish or rollback does this:

| Crash right after | Left on disk | The next publish or rollback |
|---|---|---|
| the lock, up to the candidate folder (C1) | lock; maybe the empty `warehouse/candidate/run-<run ID>/` | nothing to finish |
| the landing lock, during the copy (C2) | lock, `data/<set>/parquet.lock`, a partial candidate folder | nothing to finish; `make convert` also exits 2 until that lock is removed |
| the snapshot, through build, audit, read-only and the `.wal` check (C3) | lock, candidate folder | nothing to finish; published and previous are untouched |
| the hard link (C4) | lock, candidate folder, `.new` as a second name for the published file | finds the same file and removes `.new` |
| the candidate's rename on a later publish (C5) | lock, candidate folder; `.new` holds the replaced version | finds a different file and renames `.new` over `previous/<set>.duckdb` |
| the rename of a first publish (C6), of `.new` (C7), the folder removal (C8) or a rollback's rename (C9) | lock (and the folder for C6 and C7) | nothing to finish |

**`rotation-leftover`.** No crash leaves `.new` without a published file, so `.new` with no `warehouse/<set>.duckdb`
means a file was removed by hand. The commands change nothing and exit 1, because they cannot tell which version
belongs; the message names both paths. Open `warehouse/previous/<set>.duckdb.new` read-only to see which version it
holds, run `mv warehouse/previous/<set>.duckdb.new warehouse/<set>.duckdb`, then run the command again.

**Stale locks.** A lock whose process is gone (a crash point above, or a conversion killed holding
`data/<set>/parquet.lock`) is removed by hand. Read the lock's line and confirm with `ps -p <process ID>` that no such
process runs. For `warehouse/<set>.lock` (line: run ID, process ID, start time): `rm warehouse/<set>.lock`, then
`rm -rf warehouse/candidate/run-<run ID>/` (the folder may be empty or absent; a rollback's run ID is `rollback` and it
makes no folder). For `data/<set>/parquet.lock` (line: `pid <process ID> started <time>`): `rm data/<set>/parquet.lock`,
`rm -rf data/<set>/.parquet-*` (the converter's staging folders), then `make convert DATA_SET=<set>`, which rebuilds
`v1` and `audit` folders from the raw capture (normally append-only; company data
allows a pre-go-live delete under ADR 0033). The publish and convert refusals print
the lock file, its line and a pointer to this section; the exception is a lone stale
`data/<set>/parquet.lock`, which makes publish exit 1 with `converting` and no
pointer, so follow the `data/<set>/parquet.lock` steps above.

**Accepted residual: a hand-typed dbt build.** `dbt build --target ci` typed by hand, or a production target with a run
ID set by hand, runs no recipe, so the guard never sees it: a profile cannot `lstat`, and dbt's `on-run-start` hooks run
after the file is open. Such a build is kept off a published file only by its mode 0444: a write-mode open fails with
"Permission denied", also through a symbolic link, and anyone with write permission on `warehouse/` can change that mode
on purpose. An `OPENRCT2_DATA_DIR` left exported moves every command to another root.

## OpenRCT2 and tool facts

The game's behavior and the pinned tools' behavior, with sources, are in `docs/architecture/openrct2-facts.md`.

## Layout

- `src/openrct2_analytics/config.py` — settings loaded from environment variables and validated at
  startup: the listener's host and port (loopback only), each data set's landing folders (`landing_dirs`; the root
  `data/` moves with `OPENRCT2_DATA_DIR`, a test seam; `src/openrct2_analytics/ingest/landing_paths.py` turns those folders into absolute paths: a relative folder is joined to the project folder, an absolute one is used as is), the capture default data set, the capture folder
  (`OPENRCT2_CAPTURE_DIR`), the benchmark work folder (`OPENRCT2_BENCH_DIR`), its binary, fixture and game-path
  settings, and the optional OpenRCT2 user folder (`OPENRCT2_USER_DIR`, else a per-platform default built from
  `XDG_CONFIG_HOME`, `USERPROFILE` and the home folder). `config.py` reads the environment only; the game's binary,
  game folder and the benchmark park are resolved by `load_settings` in `src/openrct2_analytics/ingest/bench_setup.py`, the one loader for
  every benchmark, rehearsal and autopilot command: an exported value, else the git-ignored
  `local/game-settings.env` (read-only; only those three keys; read by `game_settings.py` beside it, as is `config.ini`), else a default (the macOS app location; the
  `game_path` of the game's own `config.ini`; none for the park). `state.py` is the second environment-reading module and
  owns only `OPENRCT2_STATE_DIR`, the external archive and go-live marker folder.
- `src/openrct2_analytics/domain/` — pure logic. Its `ruff.toml` bans web, database, network, and environment access,
  and `openrct2_analytics.config`, for every file in the folder. The full list is in `docs/CONVENTIONS.md` section 3.
- `src/openrct2_analytics/domain/example_service.py` — template placeholder; no domain logic exists yet.
- `src/openrct2_analytics/ingest/` — the listener, converter, contract runner, capture command (`capture.py` and `capture_session.py`), and benchmark modules;
  `lock.py` (the lock and signal handling the converter, capture and publish share); `warehouse_guard.py`; and the
  `publish*.py` modules (`publish.py` is the command, the others hold its steps); the only code that opens sockets,
  reads or writes event files or warehouse files, launches the benchmark game, or installs the plugin file. Company raw
  captures and registry deliveries permit a pre-go-live delete (ADR 0033), done by `delete_data.py` (the command),
  `delete_plan.py` (scopes, IDs and the plan), `delete_apply.py` (derived-file removal and the changes to originals),
  `delete_archive.py` (the verified archive copy and manifest) and `go_live.py` (the go-live command, which refuses
  today); see "Deleting company data and going live". Two modules serve an after-play panel outside this repo:
  `play_status.py` (`make play-status`) prints one JSON object naming the dev warehouse's state (`ready`, `missing`, or
  `building` while a writer holds its lock) and each converted session it does not hold yet, with each park's name,
  registration and last paired save file. It writes nothing, but holds DuckDB's read-only lock on the warehouse
  while it reads, so a build that opens the file then fails; it runs on demand, never on a timer during a build. `after_play.py` (`make after-play`) refuses while the
  landing lock exists, the dev warehouse is being built, a session that failed its `seq` audit waits unfiled (`seq-failed`: filing files every waiting session, so nothing is filed while one waits; `check_can_start`, which `auto_file.py` also runs first), a waiting park is missing from `PARKS`, a listed park is
  neither waiting nor registered or is registered with the other choice, or `START_YEAR=<year>` breaks the register rules above, then registers
  the waiting parks not yet registered (passing `START_YEAR` on), runs `make contracts` and `make transform` and prints `make results`,
  stopping at the first failing step; rerunning it resumes, because registered parks are skipped. `auto_file.py` (`make auto-file`; ADR 0051 and ADR 0055) has two modes. `--record` writes the IDs of the converted sessions and of the sessions in the raw captures to the git-ignored `local/auto-file/converted-before.json`. `--count-as <company|practice>` reads the waiting sessions (`play_status`) and the registry, treats a park with a waiting session missing from that file as this play's park, asks about any unregistered park from an earlier play and about a registered park whose saved choice differs from this play's, and, when two or more parks are new in this play, about each of them (`several_parks.py`: its label and played game days, then "Opened first", "Opened second", ... or "Sandbox"; the "Opened n" answers must match the order of the parks' first recorded sessions, Sandbox parks counted). It prints one line per park about to be registered. With one company park to register it takes the one accepted start year from `start_year.next_start_year` (when that park registers after the first) and runs `after_play.main` with `--parks` (and `--start-year`). With two or more company parks `several_parks.plan_chain` plans every company park's year in the order of the first recorded sessions (the pure rule is `src/openrct2_analytics/domain/start_year_plan.py`; the year reads are in `start_year.py`, which `register_parks.py` and `next_start_year` share), runs every refusal check for all of them (the registry feed, a park of another data set, a staged delivery left over, a company raw file holding a session never converted, the game-year origin of a typed year, the free delivery names, and a waiting list that changed during the questions), and `several_parks.file_chain` registers the parks one at a time through `register_parks.register` (one delivery each, each year checked again under the landing lock) before one `after_play.main` call that passes `registrations_landed`, so its refusal lines drop "Nothing was changed." The answers to the per-park questions (never a choice taken from `COUNT_AS`) are stored in `local/auto-file/answers.json` before the first registration; the file is removed when a run ends with no registration landed, so the rerun asks again, and kept after a failure that follows a landed registration, so that rerun asks nothing twice. When a failure ends a run after a registration landed, it reads the registry again, names the parks already filed and the rerun command, and exits 1 (130 when interrupted); "Nothing was changed" stays before the first registration only. The return is after-play's exit code, except that once a registration landed a non-zero code other than 130 is returned as 1 (`several_parks.py`), with the filed-parks lines after after-play's own; the record file is removed after a successful after-play, before the closing lines print (an interrupt while they print exits 130 after the cleanup), and the answers file then, by `--record`, and when a run ends with no registration landed. After after-play exits 0 it prints one line for each company park the run registered, `<name> joins the company as Park <n>, starting in company year <Y>`, in order of `<n>`, reading the number and year from `marts.dim_park` of the development warehouse (`play_status.dim_park_numbers`); a warehouse that cannot be read, or a park without a number, gives a fallback line and the exit code stays 0 (`several_parks.py`). After those lines `previous_park.note_lines` prints one note for each company park registered after an earlier one. The previous company park is the company park with the latest start year below the new park's (the lowest park ID on a tie), and a Sandbox park is never noted or named as previous. The note says that the previous park's scenario challenge is not recorded, so whether it was finished is not checked, and gives its profit in its latest complete company year (US dollars, from `marts.obt_park_year` of the development warehouse, read once and read-only) or says it has none. A read failure prints `auto-file: the play is filed, but the note about the previous company park could not be shown (<reason>).` once instead, and the exit code stays 0. An interrupt during that read or the park-number read exits 130 before any of these lines print (`query_interrupt.interrupt_as_signal` turns DuckDB's interrupt error back into the interrupt). It runs `after_play.check_can_start` first, so the refusals that need no question come before any question. `autopilot_parks.py` (`make autopilot-parks`) prints the registered company parks that are not sandbox parks as one JSON object, each with its newest archive copy, the reason no source is proven (or null) and whether its first run needs `READY`; it writes nothing and takes no lock. `autopilot_year.py`
  (`make autopilot-year DATA_SET=company PARK=<id> [READY="<phrase>"]`; ADR 0049) plays a finished company park's last
  recorded save, taken from the backup archive and proven to be its last recorded save (`autopilot_source.py`),
  headless with the plugin in its own work folder (`autopilot_run.py`) until 1 March of the next game year, checks the
  capture there, and only then lands it (`autopilot_land.py`) under the company landing lock in this order: the label
  row in the play-mode feed, the save-file records, then one raw file, so a crash leaves at most a label or records
  that name no landed session and never an unlabeled autopilot session. The registry is re-checked under that lock. The landed files are named `save_file_observation_<date>-autopilot-<session id>.jsonl` and `events-<date>-autopilot-<session id>.jsonl` (`autopilot_land.py`, `suffix` and `raw_name`).
  The year rule (`src/openrct2_analytics/domain/company_years.py`, with `managed_years.py` reading converted Parquet) lets a park run only a
  company year that another park has played by hand. The run is then converted, the end-of-year save is copied to the
  archive and to the game's save folder under a dated name that replaces nothing, and `autopilot_report.py` prints the
  report. While the game runs, `autopilot_progress.py` prints one line per game month (events so far, elapsed time and an estimate of the time left) and one warning per stall of 60 seconds without an event; after the run it sums the 14 statement lines of every `finance_month` event into the report's `Profit:` line, which `display_usd` shows in dollars (ADR 0052; nothing converted is stored), beside the `Started from:` and `Guests in the park:` lines. Success needs the archive to hold a copy of the end-of-year save; without it the command exits 1 with the
  steps to make the backup, and a failure of the dated copy alone exits 1 without them. Exit codes: 0 landed, 1 a run,
  check, landing or backup problem, 2 refused (nothing written), 130 interrupted. `site_company.py`
  (`make site-company`) builds the public site from the published company warehouse and `site_company_land.py` lands
  its output folders by rename and writes the build stamp; see "Environments and publishing".
- `plugin/src/` — the plugin, ES5 only; `plugin/test/` — its Node tests and the stand-in game.
- `contracts/` — the fourteen data contracts (the envelope and thirteen event types), on one shared version line, currently
  1.8.0; `contracts/reference/` holds the park registry feed's contract and the save-file observation contract.
- `models/staging/` — the source definition, `stg_envelope` and the event-type models `stg_finance_month`,
  `stg_park_snapshot`, `stg_ride_snapshot`, `stg_save_written`, `stg_session_start`, `stg_guest_arrived`,
  `stg_guest_boarded`, `stg_guest_left`, `stg_guest_refused`, `stg_guest_snapshot` and `stg_game_action`, plus `stg_park_registry`, the
  staging model of the park registry feed;
  `models/intermediate/` — `int_park_registry__history`, `int_park_registry__current`,
  `int_park_years__company_year`, `int_park_years__registry_mapped` (one row per park and game year landed or stated, with its company year when mapped), `int_park_years__year_close` (one row per expected park and company year, with its close status),
  `int_park_days__company_calendar` (every valid day of each mapped park-year), `int_park_days__kept` (kept park-day
  readings with company date and admissions increase), `int_ride_days__kept` (one row per ride occupancy per kept game
  day, with company date and counter changes), `int_sessions__lineage` (one row per play session: the save it
  loaded, its cut and whether it is on the kept timeline; ADR 0024), `int_statements__labeled` (every monthly statement
  labeled kept or abandoned, with a company date from its own year), `int_game_actions__labeled` (one row per staged `game_action` with `is_plugin_issued`, `is_player_action` and `is_refused`; see "Player actions") and `int_guest_stays` (one row per guest arrival,
  paired with its exit when one is seen, else left open, and its stay length in whole game days on the game clock; the
  start is the date the plugin's queued arrival step ran, at most 8 ticks after the hook on the committed sample with no
  limit set by the capture, and an exit is noticed late, so a stay can be shorter or longer; a guest seeded at session
  start has no arrival and no row, and a guest across a reload is one open row, never joined across sessions, ADR 0029;
  provisional until it is labeled with `timeline_status`). The macros `timeline_status` (labels an event kept or abandoned from its session's lineage row)
  and `counter_change` (a counter's change between kept readings within one session) sit in `macros/`.
  `models/marts/` — `fct_park_day` (one row per park per kept game day), `dim_date` (whole company months, March to
  October), `dim_park` (one row per registered park; its `park_number` column is the one home of the park order, read by the filing line and served to the site as `site/_data/park.json`), `fct_park_month`, `obt_park_month` (one row per park per kept statement month), `obt_company_month` (one row per company month), `obt_park_year` (one row per park per company year), `obt_company_year` (one row per closed company year), `obt_ride_month` (one row per ride per game month), `obt_ride_year` (one row per ride per company year),
  `dim_ride` (one row per ride occupancy), `dim_item` (one row per item code seen, no names), `fct_ride_day` (one row per
  ride occupancy per kept game day) and `fct_cleaning_rule_count` (one row per cleaning rule per model, counting the rows
  each rule keeps, removes or changes). `profiles.yml`
  holds the four dbt targets.
- `site/` — the Eleventy site: the showcase page `site/index.njk` and the player guide `site/guide.njk` (checked by `src/openrct2_analytics/showcase/page_check_guide.py`), with their frame and section includes in
  `site/_includes/` and one figure macro (`figure.njk`); the figure registry `site/figures.mjs` (with a file per
  section in `site/figures/`), which gives every figure region its sentences, unit line and live or pending state;
  `site/eleventy.config.mjs` (the story-passage shortcode, the contract count and version, and passthrough of the
  stylesheets in `site/assets/css/`, the title image in `site/assets/img/` and the modules in `site/assets/js/`); shared modules under `site/assets/js/`
  (`boot`, `data`, `dom`, `motion`, `chart-style`, `nav`, `hero-scene`) that only draw and wire controls, and `site/assets/js/rows/park-month.mjs`, `site/assets/js/rows/story.mjs` and `site/assets/js/rows/insights.mjs`, pure row functions (no DOM); one module per section that draws it (`story`, `insights`, `finance`, `crew`, `extract-roll`, `infra-track`);
  `site/assets/park-month-chart.mjs`; the prose of the page in `docs/showcase/story/` as named passages
  (ADR 0043); the export allowlist `site/exports.toml` and the seven committed exports in `site/_data/` (`park_month.json`, `park_year.json`, `company_year.json`,
  `ride_month.json`, `ride_year.json`, `park_month_revenue.json`, `park.json`) and the sample record `site/_data/sample.json`;
  `src/openrct2_analytics/showcase/` — `export.py` (writes or checks the exports) `page_check.py` (checks the
  built page against the served data, and the player guide through `page_check_guide.py`), `page_check_site.py` (the site-specific page rules), `page_check_guide.py` (the player guide's rules, called by `page_check.py`) and `page_check_text.py` (the
  page text and copy-number rules) and `page_check_sample.py` (the sample statement against `sample.json`).
  The page rules refuse every `src` and every `href` that names another host, with one exception
  (ADR 0060): an `<a href>` to the public repository, its author's profile or a file under the
  repository's main branch. The public preview links to its own repository and its author's
  profile; it still loads nothing from another host.
  The page header shows one game image, the OpenRCT2 title screen in `site/assets/img/` (ADR 0061);
  every other image on the page is an original drawing.
- `docs/showcase/` — `docs/showcase/story/` and `trace-operating-profit.md` (follows one month's operating profit from the page
  back to the game event).
- `metrics/finance.yml`, `metrics/admissions.yml` and `metrics/ride_operations.yml` — the metric catalog, split by
  business process (ADR 0016): the park company's north-star metric (operating profit per company year), the metric
  tree beneath it, its guardrails and every v1 metric, each with unit, clock, grain, owner, status and source models,
  in dbt 1.11's semantic-model and metric YAML shape. It sits outside dbt's resource folders, so dbt never reads it
  directly. A YAML anchor cannot point across files, so an anchor used by two files is defined in each. The three
  company year-over-year metrics built on finance sit in `admissions.yml` with their shared anchors, apart from the
  finance metrics they compare; `finance.yml` was within about 19 lines of the 500-line limit when split. The project
  owner confirmed it and the brief on 2026-10-03. `docs/requirements-brief.md` says what the
  company needs from its data and is the catalog's source of meaning.
- `docs/review-catches.md` — four cases where independent review or the gate caught a defect before merge, each with its commit.
- `docs/acceptance/scenarios.yml` — the v1 acceptance scenarios (business questions the company's owner must be able
  to answer from the site, each tied to catalog metrics), checked by `tests/test_acceptance_scenarios.py`; the project
  owner's walkthrough results go in `docs/acceptance/walkthrough-<YYYY-MM-DD>.md`.
- `tests/` — behavioral tests, no mocks of in-repo code; `tests/dbt/` holds dbt singular tests.
- `data/sample/rehearsal/` — the committed rehearsal extract: Parquet from three chained headless runs on a copy of
  the benchmark park, plus its README. `data/rehearsal/` and `data/company/` (each holding a `raw` and a `parquet` folder),
  `data/capture/` (the install record, which holds a private home path), `data/bench/`, and `warehouse/` (see
  "Environments and publishing") are pipeline output and are not committed; the plugin build's output folder
  `plugin/dist/` is not committed either.
- `scripts/check_file_sizes.py`, `scripts/check_docs.py` and `scripts/check_local_paths.py` — stdlib-only repo checks
  run by `make check`: the 500-line limit, docs that name only things that exist, and no absolute local path in a
  tracked file. The git hook also runs the size check.
- `scripts/doctor.py` — stdlib-only health check of `.venv`, run as `make doctor`, at the end of `make setup` and at the
  start of `make check`: uv's managed Python, every file in each package's install record present, and `dbt` importable.
- `scripts/check_metric_catalog.py` — the validator: it reads every `metrics/*.yml` file, merges them and fails with
  one `rule <number><letter>` line per house rule broken (names, required fields and meta, references, columns, money
  units, tree links, no zero months, year over year); the rules themselves live in `scripts/metric_catalog_rules.py`. It reads YAML with dbt's non-public
  `dbt.clients.checked_load`, which dbt 2.x removes; the fallback is a direct PyYAML import, which needs approval and
  loses duplicate-key reporting.
  `scripts/check_metric_catalog_shape.py` copies the dbt project to a temporary folder, adds the catalog and runs
  `dbt parse` there, so dbt's own semantic rules apply; it swaps dbt's validator process pool for a thread pool so it
  runs inside the agents' sandbox, and its skip rule applies only while `CI` is unset.
  `scripts/metric_catalog_yaml.py` holds their shared YAML helpers.

## Deleting company data and going live

`make delete-company-data` prints its plan and exact confirmation phrase without
writing. Supply `PARK=<id>` or `SESSION=<id>` for a named scope, or neither for all
company data. `CONFIRM="<phrase>"` authorizes that scope. Exported values and dollar
signs are refused by make. Rehearsal data and capture installation records stay. Before go-live, delete-all also
removes the save-file records under `data/company/save_files/`, because it removes every file under `data/company/`
except the parquet lock (derived Parquet goes as rebuildable output); a named park or session scope leaves them,
because they carry no `park_id` and the plan reads only raw event files and registry rows.

Before writing, the command checks the ID, external state location, landing aliases,
warehouse paths, game status, both capture/listener ports, and go-live markers. A
confirmed run holds both port probes and takes the company publish lock followed
by the conversion lock. It rebuilds the plan inside these locks, copies each
original into a dated archive, verifies SHA-256 hashes, writes a manifest, removes
derived files, and re-hashes each original before replacing or removing it.
Registry records and raw lines that remain retain their original bytes. A difference
from the archived hash stops a file before it changes. The residual race is the
instant between that final hash and the replacement or removal, if a writer uses
neither held port. A mixed park session is refused. Missing days in a closed month
fail the missing-day test by design, and later sessions that loaded its saves may
become orphans: replay the save, then rebuild with
`make pipeline DATA_SET=company`. The dev warehouse stays; the next transform
rebuilds it. Candidates are removed only with exclusively company evidence.

Further safety rules:

- **Folder identity.** Before any lock or write, previews included, the command
  refuses (exit 2, `unsafe-path`) when the `company` folder of the data root is a symlink or does not
  resolve to `<resolved data root>/company`, so it can never reach rehearsal data
  or the committed sample through an alias.
- **Archive folder.** It refuses (exit 2, `unsafe-path`) when the archive folder or
  the dated run folder is a symlink, or when the resolved archive folder lies inside
  the project folder or the data root. This is checked when refusals are decided
  and again just before the first archive write.
- **Capture port.** The port check binds the listener's configured host as well as
  `127.0.0.1`.
- **Delete-all preview.** It lists every raw file with its session IDs and line
  counts. Lines without a readable session ID are counted and never cause a
  refusal; delete-all still removes whole files.
- **Registry check up front.** For a park delete, the registry check runs on the
  current company deliveries inside the locks, before anything is archived. A
  failure refuses (exit 2, `registry-check`; fix the failing delivery first) with
  nothing changed. The check after the changes stays.

### State layout

`OPENRCT2_STATE_DIR` names an external state folder. Defaults are
`~/Library/Application Support/openrct2-analytics` on macOS,
`$XDG_DATA_HOME/openrct2-analytics` (or `~/.local/share/openrct2-analytics`) on Linux,
and `%LOCALAPPDATA%/openrct2-analytics` on Windows. It must be outside the project
and OpenRCT2 user folder and cannot overlap the data root or warehouse.
It contains `archive/<UTC>-<scope>/`, preserving paths relative to the data root,
and `go-live-company.json`. A second marker is `<data root>/company/go-live.json`.
Either marker, unreadable state, or corrupt marker is treated as live: named
deletion is refused, and all removes only rebuildable files,
including the published warehouse and its rollback copy.

`make go-live` currently refuses because the roadmap's "A way around the seq stop
in make pipeline" is not built. The marker writer is tested directly (ADR 0033).

A lock left by a killed run is removed by hand; the one place that says how is the
"Stale locks" paragraph in "Environments and publishing", which covers
`warehouse/company.lock` and the company `parquet.lock`.

### Recovery

| Crash during | Left on disk | Recovery |
|---|---|---|
| Archive copies | Partial archive, no manifest; originals untouched | Remove the partial archive folder; run the same command again |
| Derived removal | Verified archive and manifest; some derived files remain; originals untouched | Run the same command again with a new archive |
| Original changes | Archive; derived gone; some originals changed; possible `.delete-tmp` | Run again while the ID still exists; if all changes finished, an unknown-ID refusal means nothing remains to do. To undo, restore originals listed in the manifest |
| Registry check after the changes | Originals changed; a delivery that stays fails the check | Fix the failing delivery first (the rewrite removed only the park's rows, so the problem is in a row that stays), or copy the affected deliveries back from the archive and fix them, then run again; rerunning without a fix fails the same check |
| Any locked step | Normal exit releases locks and sockets; a killed process leaves locks | Follow "Stale locks" (publishing section), then run again |

No step calls `fsync`, matching publish. There is no restore command; use the
manifest for manual restoration. Named park
deletes leave two traces: rejected registry deliveries and malformed lines whose
text contains that park ID. Delete-all removes both. Windows testing is out of scope.
