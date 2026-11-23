# OpenRCT2 and tool facts

**Bottom line.** This file holds what the capture depends on that the game and the pinned tools do, not what this repo
built: the 0.5.5 plugin API, its quirks, what the API does not expose, and how datacontract-cli, dbt and DuckDB behave
here. Each fact names its source. `ARCHITECTURE.md` describes the system; read this file before relying on a game
behavior.

## The game: OpenRCT2 0.5.5

The capture depends on these facts about the game. They come from the 0.5.5
plugin type definitions, the 0.5.5 engine source, and headless probe runs in
September and October 2026; the type definitions are GPL and never committed. Measured
costs and results live in `docs/FINDINGS.md`.

**Calendar and clock**

| Fact | Value |
|---|---|
| Month length | 16,384 ticks: `date.monthProgress` rises by 4 per tick to 65,536. Days per month vary, so a day averages about 518–530 ticks. |
| Year | 8 months, March (`month` 0) to October (7); `day` is 1-based, `year` starts at 1, `ticksElapsed` never resets. |
| Days per month | 31, 30, 31, 30, 31, 31, 30, 31 for `month` 0 (March) to 7 (October), so a year is 245 days. Source: OpenRCT2 0.5.5, `src/openrct2/Date.cpp`, `days_in_month`. |
| Year boundary | The first `interval.day` callback where `month === 0 && day === 1` (1 March). |
| Clock available to a plugin | `performance.now()`, with sub-microsecond resolution on 0.5.5 (verified by the capture schedule probe); JavaScript `Date` is at 1 ms. Tick and day hooks receive no arguments. The profiler's time unit is undocumented. |

**Plugin runtime**

| Fact | Value |
|---|---|
| One plugin per file | The engine loads each `.js` file in the plugin folder as a separate plugin, so a plugin or probe must ship as one file. |
| Park storage | `context.getParkStorage()` is stored inside the `.park` file and keyed by the plugin's registered name, which is case-sensitive; the name must match across runs. |
| Pausing | `context.paused` is read-only in network mode, which includes a headless `host` server. A headless run needs `pause_server_if_no_clients = false` in its `config.ini`. |
| Tick hook while paused | While the game is paused, `date.ticksElapsed` stands still but the 5-second reconnect interval keeps firing (`plugin/src/timing.ts`, comment above `PAUSED_BUCKET_MS`). |
| Hook order | **Inference:** on a tick where both hooks run, `interval.tick` runs before `interval.day`. The benchmark's day callback stayed below the 4 ms allowance, so a tick hook after it would have started that day's ride snapshots on the same tick; none carried that tick (`docs/adr/0010-work-queue-spreads-capture-across-ticks.md`). |
| Game speed | Read-only on `context`; it changes only through the `gamesetspeed` action. |
| Socket backpressure | In 0.5.5 `ScSocket::write` returns false when the whole line was sent or the socket has no connection, and true when only part of it was sent (the cut line then runs into the next one, so one partial send can lose two lines); it throws on a disposed socket. The plugin must queue, and count what it drops and what a partial send loses. |
| Payload names and the envelope | `plugin/src/emit.ts` builds the envelope first, then copies every payload field onto the event, so a payload field that reuses an envelope name (for example `game_ticks_elapsed`) silently replaces the envelope value. Tick fields in payloads therefore take other names (`generated_at_ticks`, `detected_at_ticks`). Source: `plugin/src/emit.ts`, the `emit` function; the naming rule came from the part 2 contracts scan (removed from the tree in commit 4f60210). |
| Socket close | `destroy()` raises the `close` event synchronously, so a replaced socket must stop being the current one before it is destroyed. |
| Engine and reloads | 0.5.5 runs plugins in QuickJS-ng, not Duktape. It frees the plugin's script context and runs `main()` again on every park load, so all plugin state must be created inside `main()`. |
| Timers | `context.setInterval` and `context.setTimeout` count real milliseconds, and in a headless run a `setTimeout` did not fire within a tick and waited a whole game day. They cannot schedule per-tick work; use a tick hook. |
| Title screen and editor | A plugin also loads for the title screen's parks and in the editor. `context.mode` says which (`"normal"` is a real game), so a plugin that must run only in play checks it. |
| Local plugins and `map.changed` | A `"local"` plugin is stopped and started again on every load, and `map.changed` fires only for intransient plugins. The plugin therefore treats every load as a fresh `main()` and mints `session_id` inside it. Real play confirmed it on 2026-10-01: each in-game load started a new `session_id` at `seq` 1. |
| Saving | `context.saveGame({ filename })` writes `<user data>/save/<name>.park`: the filename is relative to the save folder and `.park` is appended. With no options it saves to the park's existing path, or shows a save menu for a park never saved. The file is written after the current tick completes, so a run resumed from it starts 1 tick later. The game's log records nothing about any save. |
| Save hook (`map.save`) | The callback takes no arguments, so it cannot tell which file is being written, and the type definitions do not order it against the write. Observed in 0.5.5, headless and windowed: it fires for plugin saves (inside `saveGame`, on the same tick as the call), autosaves and Save Game As menu saves, and a value the plugin writes to park storage inside it reaches the saved file (`docs/FINDINGS.md`, "Save hook"). It fires 0.001 to 0.136 s before an autosave or menu file appears, so pairing a hook to its file by time needs a window of seconds, not equality. Plain Save Game and the save offered when quitting are untested. |
| Autosave setting | The `autosave` key under `[general]` in `config.ini`: `0` saves every minute (measured 60 s apart), `1` about every 5 minutes (the project owner's own setting; a windowed run landed autosaves 300 s apart), `5` never. Headless runs autosave too. |
| Save As dialog | The windowed Save As dialog first opens in the folder the park was loaded from, one level above the game's `save` folder, so a menu save lands outside a script that watches only `save`. |
| Remembered save folder | The game keeps a remembered folder in `config.ini` as `last_game_directory` under `[general]`, with the value in double quotes, and as `""` when none is set (observed 2026-10-20 in OpenRCT2 0.5.6). That the game writes the folder of the last save or load into it is unverified; only the key, section and quoting were observed. The capture command watches that folder as kind `remembered` when it is not one of the three default folders (`docs/adr/0040-watch-the-games-remembered-save-folder.md`). |
| Track iterator coordinates | `map.getTrackIterator` takes world coordinates, which are tile coordinates times 32, while `map.getTile` takes tile coordinates; passing tile coordinates returns a null iterator. The ride statistics spike found this when all three coasters read a null iterator on its first dry run (`docs/FINDINGS.md`, "Ride statistics spike: cost of counting inversions by walking each coaster's track"). |
| Track element position (`station.start`) | `station.start` is in world coordinates on 0.5.6: the walk divides by 32 (`plugin/src/ride_stats.ts:65-66`), and the 2026-10-17 judged benchmark found 0, 2 and 1 inversions on coasters 1, 3 and 18, matching the game's ride window (`docs/FINDINGS.md`, row dated 2026-10-17). |
| Ride type category | Each ride-type entry in `park.research.inventedItems` and `park.research.uninventedItems` carries a `category`, and `"rollercoaster"` is the game's own coaster grouping, so a ride type's category can be looked up there instead of from a hand-made list of ride names. The ride statistics spike used this lookup on 2026-10-03 to choose the rides it walked (`docs/FINDINGS.md` has the spike's two rows for context, not this lookup). |
| `ratings.calculate` headless | The `ride.ratings.calculate` hook fires in a headless run: the ride statistics spike's dry run on 2026-10-03 received 605 `ratings_calc` events (`docs/FINDINGS.md` has the spike's two rows for context, not this count). |
| Socket signatures and types | `destroy(error)` requires an argument. The type definitions omit `performance`, so the plugin declares it (`plugin/src/performance.d.ts`). |
| Headless launch | `OpenRCT2 host <park copy> --headless --port 11799 --user-data-path <isolated folder>`. The folder holds a plugin folder, a save folder and a fresh `config.ini` with `pause_server_if_no_clients = false`, `advertise = false` and `game_path` (a private machine path that stays out of the repo). Port 11799 is the game server's, so the plugin's socket never uses it. |

**What the API does and does not expose**

| Fact | Value |
|---|---|
| Park fields | `park.cash` is in tenths of a dollar with no unit in the type. `park.guests` counts guests inside the park, not those still outside on the map, so it is used instead of counting guest entities (a full guest-list read cost 24.9 ms). `park.rating` is in engine units. `park.value` and `park.companyValue` refresh only every 512 ticks, so they lag a day callback. `park.totalAdmissions` is cumulative and a reload rewinds it. `park.name` is not unique, so it is never an identity. `date.monthsElapsed` can be reset by cheats, so `date.ticksElapsed` is the clock to use. |
| Missing hooks | No hook fires on boarding, guest thoughts, a guest leaving, or entity removal; these are inferred by polling. `ride.breakdown` works although it is missing from the hook-name union. |
| Entity IDs | Reused slots, not identities. A cache keyed by entity ID can attribute one guest's state to another. |
| Listing guests | `map.getAllEntities("guest")` is the only guest list and reads every guest at once. `map.getEntity(id)` reads one entity, and `Entity.id` is null for an invalid entity. `park.guests` is a count with no IDs. A new guest arrives on `guest.generation` carrying only `{ id }`. The type definitions say `getEntity` never returns null, but what it returns for a departed guest's ID is observed, not specified: in the capture-schedule probe all 15 departed guests' IDs read as another entity type (14 `money_effect`, 1 `litter`), none as null. A check of a remembered ID therefore treats null, a non-guest, or a guest with a different minted key as "left". |
| Rides | `map.rides` returns every ride; `map.getRide(id)` returns one, and null means the ride was demolished. The relative cost of the two is unmeasured. `ride.stations` returns 255 slots in 0.5.5; a used slot has a non-null `start` (`plugin/src/rides.ts`, comment above `buildRideSnapshot`), and a used slot can follow an empty one (a reviewer's reading of the 0.5.5 engine source, not confirmed by this repo), so the snapshot reads `ride.stations` once and walks all 255 slots. |
| Guest thoughts | `Guest.thoughts` is a snapshot copy with `type`, `item`, `freshness` and `freshTimeout`. The ride-refusal types are `cant_afford_ride`, `bad_value`, `not_paying`, `intense`, `more_thrilling`, `sickening`, `not_safe`, `queuing_ages` and `not_while_raining`, and `item` is the refused ride's ID. In the 2026-09-27 capture (21,139 sampled guest-days) no list held more than five thoughts, index 0 was the newest, an absent argument read 65535, and `item` equalled a ride ID in the same snapshot for all 1,025 refusals of the six types that occurred; `bad_value`, `not_paying` and `not_safe` never occurred there, and in the part 2 benchmark every `bad_value` ride ID matched a ride snapshot while `not_paying` and `not_safe` still did not occur, so those two are unconfirmed. |
| Car seats | `Car.guests` lists guest IDs by seat and `map.getAllEntities("car")` lists every car; there is no boarding hook and `Guest` has no current-ride, state or amount-paid field. 0.5.5 leaves a guest's ID in its seat after the guest leaves, until another guest takes the seat, and one guest can be listed by several cars at once (two benchmark rides kept every seat listed for a whole run with nobody aboard), so only a change of the ID in a seat is a boarding. |
| Guest items and price | `Guest.items` holds objects such as `{ "type": "map" }`, not names (15,328 non-empty lists in the 2026-09-27 capture), so the plugin joins each item's `type`. The API exposes no amount paid; `ride.price[0]` is the listed admission price. |
| Weather | The global `climate` has `type` (`coolAndWet`, `warm`, `hotAndDry` or `cold`) and read-only `current` and `future` states, each with `weather` and `temperature`; `future` is the next weather, and nothing says when it takes over. `weather` is one of `sunny`, `partiallyCloudy`, `cloudy`, `rain`, `heavyRain`, `thunder`, `snow`, `heavySnow` or `blizzard`. There is no weather hook, so a change is timed only as closely as `climate` is read. Read every tick in 0.5.5, it caught all 62 and all 80 changes of the two 480-day weather runs; every change but one fell between day callbacks, and a day callback therefore misses nearly all of them (`docs/FINDINGS.md`, weather and umbrella spike rows). Reading its four values plus three counters cost 0.022 ms per tick on average, above the 0.0125 ms ceiling. |
| Stall items | A stall or kiosk is a ride whose object gives `shopItem` and `shopItemSecondary`; `price[0]` is the first item's price and `price[1]` the second's. There is no per-item sold count, and item costs are not exposed. Information kiosks (`rct2.ride.infok`) sell the map (item 2) and the umbrella (item 4); their running cost is 31 tenths. Each sale adds the price minus the item's cost to `totalProfit` (9 tenths per map and 180 per umbrella at prices of 10 and 200) and one to `totalCustomers`, so at fixed prices a kiosk-day splits exactly into maps and umbrellas. `Guest.hasItem` and `Guest.items` show who holds an umbrella; a scan of every guest costs 15 to 21 ms per pass in a park of 1,900 to 2,750 guests. |
| Stalls | A stall is a ride with `classification: "stall"`; facilities (kiosks, restrooms, ATMs, first aid) are a third classification. |
| Monthly ledger | `park.getMonthlyExpenditure(type)` returns history with index 0 the current month, with months elapsed plus 1 entries, at most 16; an unknown type returns an empty array (read from `ScPark.cpp` in the 0.5.5 source). There are 14 types: `ride_construction`, `ride_runningcosts`, `land_purchase`, `landscaping`, `park_entrance_tickets`, `park_ride_tickets`, `shop_sales`, `shop_stock`, `food_drink_sales`, `food_drink_stock`, `wages`, `marketing`, `research`, `interest`. A closed month is index 1 at the rollover that closes it; the plugin reads it in the day-1 callback (see how the plugin reads a statement, above). In all 14 rollovers of the schema 0 capture the new month's index 0 was 0 in every type at that reading (observational, one park, one player), but it is not always 0: in the 2026-10-09 two-park capture about 11 of 67 pairs show money booked to the new month before the reading, which the plugin now sends as `new_month_booked_tenths` (ADR 0039; the engine order behind it is unverified against the source). Spending is normally negative and income positive, but a refund can make a spending line positive (demolishing a ride refunds `ride_construction`). |
| Session facts | `context.apiVersion` is the plugin API level; no game build string is readable. `scenario.name` exists, and `scenario.filename` can hold a machine path, so the plugin never reads it. The global `ui` is absent in headless mode, so `typeof ui === "undefined"` means headless; headless runs confirmed true, and the real-play capture of 2026-10-01 confirmed false in a windowed game. `context.gameSpeed` read 1 at normal speed in every headless run, although the type definitions' comment says 0 is normal. `park.name` is not unique (see Park fields). |
| Build previews | A `game_action` with `args.flags` bit 64 set is a construction preview, not a player action. Plugin 0.8.0 and later drop previews before sending (ADR 0042); the flag matters for rows captured by earlier plugins. |
| Never-opened stall | Reports income, profit and running cost as −9223372036854775808, which JSON rounds. |

**Where cash and counters diverge from the ledger**

| Fact | Value |
|---|---|
| Cash outside the ledger | Loan principal moves `cash` and `bankLoan` together (only interest is a ledger type), and cheats can set cash with no ledger line. |
| Ride counters | Tickets are charged on boarding; `totalCustomers` rises when the rider leaves. Counters go backward when a ride is demolished or a save is reloaded. |
| Cash read after the month shift | The day-1 callback runs at the end of the month's first tick, after guests may have booked money to the new month, so cash at the reading can include money the next statement's ledger also counts. The statement sends that amount as `new_month_booked_tenths`, and the cash check subtracts it (ADR 0039). |
| Reloaded months | Loading a save from earlier in game time replays the months after it, so the same statement month can arrive from two sessions with different values (seen in real play, 2026-10-01). Staging keeps both; a model that reads statements chooses one per park and month. |
| Prices | Captured once per game day, so a day with a price change has an unknown split between old and new price. |
| Stall sales category | Whether a stall's sales book to `shop_sales` or `food_drink_sales` depends on its item, which must come from the ride `type`. |
| Profit fields | `totalProfit` is net of item cost and upkeep and moves in the same engine code as the ledger, so matching it proves attribution, not an independent count. |

## External tools: how they behave here

These are facts about the pinned versions that shaped the pipeline (datacontract-cli 1.2.2, dbt 1.11.15 on
dbt-duckdb 1.11.0, DuckDB 1.5.6). A version bump should re-check them.

- **datacontract-cli cannot type-check Parquet.** On a `local` Parquet server every type check returns a
  warning, and its command-line tool exits 0 on a warning. The runner therefore reads the Parquet through
  throwaway DuckDB views, calls the Python API, and fails unless every result is exactly "passed". Even then
  the type check is per family (text, number, timestamp): a DOUBLE `seq` of 2.5 passes "integer", so the
  converter enforces exact types and the contract's SQL rules catch fractional values in integer fields.
- **Contract files need exact headers and explicit numeric widths.** `kind: DataContract` and an `apiVersion`
  starting `v3` are required, or the file is silently read as the older format. `logicalType: integer` is
  32-bit, so 64-bit fields declare `physicalType: BIGINT`. Columns not in a contract are ignored, which lets
  the envelope contract check every event type's file. With no server, or several and none chosen, a run is a
  warning. When the caller passes no `config`, `DATACONTRACT_DUCKDB_DATABASE` in the environment redirects the check to
  another database, so the runner passes the database path itself. A sequence gap cannot be a built-in check; the converter's audit owns it.
- **dbt reads the Parquet through `config.external_location`.** A `var()` inside it renders, which is how
  `parquet_root` switches between the committed sample and a data set's Parquet folder (`dev` and `ci` default to
  the sample; `rehearsal` and `company` fail the build unless `make` passes a folder). `dbt build` creates tables that
  hold the data, so a built file answers without the Parquet, but the Parquet must exist at build time, and the
  committed sample is what keeps CI green. A dbt unit test
  whose input is such a source fails with a dict fixture (dbt asks the warehouse for columns of a table that
  does not exist), so the test uses `format: sql`. A unit test compares through a double, so expected values
  that differ only beyond double precision (900719925474099.2 and .3) compare equal: a plain double path on a
  money column passes the unit test and is caught only by the singular test that pins `DECIMAL(18,2)`. A
  unit test also needs a distinct value in each same-typed column, or a swap of two columns passes. Every `dbt`
  call passes `--profiles-dir .`.
- **dbt reads the registry feed with a `read_csv` string.** With dbt-core 1.11.15 and dbt-duckdb 1.11.0, a
  `read_csv('<root>/v1/park_registry_*.csv', header=true, filename=true, all_varchar=true, union_by_name=true)`
  string is accepted as a source `external_location`, `filename` reaches the staging model, and a dot-prefixed
  file adds no row. Without `union_by_name=true`, a later delivery with quoted text cells keeps the quote
  marks and one without `note` fails the build. The `dev` and `ci` targets default to the committed sample
  feed; `rehearsal` and `company` have no default, so a build without a feed folder fails with "No files
  found" (`models/staging/_sources.yml:985` says they "fail the build unless a feed folder is passed", and
  `:990` holds the default).
- **dbt 1.11 macro arguments accept `list[string]`, not `type: list`.** `type: list` in a macro's YAML
  makes every parse warn ("has an invalid type"); the gate does not fail on that warning, so the mistake is
  silent (`macros/counter_change.yml` declares `list[string]`).
- **DuckDB surprises.** `/` returns a DOUBLE, so `cash_usd` multiplies a `DECIMAL(18,0)` by 0.1 instead. A
  timestamp ending in `Z` is read as zoneless, so the converter reads timestamps as text and sets the session
  time zone to UTC. Type inference over JSON samples rows, so types come from the contracts. DuckDB has one
  writer per file, which is why each environment has its own file, and the converter opens no warehouse
  file. `executemany` raises on an empty
  parameter list, so the converter skips the load when no rows exist and the no-input error follows.
- **Two traps in the repo's tooling.** `pyarrow` and `pandas` are in `uv.lock` only as untyped transitive
  dependencies, so no code imports them (DuckDB writes Parquet itself). The secret scan flags long hex strings
  (`HexHighEntropyString`), so IDs in fixtures must not be 32 or more hex characters.
