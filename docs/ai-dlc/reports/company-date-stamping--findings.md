# Where each event gets its company date: the plugin or the listener — research findings
status: research complete; reviewed blind twice (Codex, 2026-10-03) and all eleven findings folded in; awaiting the project owner's ruling (plugin or listener) · date: 2026-10-03 · initiative: park-company (roadmap NEXT 16, "Does every event carry its date on the company calendar?", research step only)

## Bottom line
- **Recommendation: the plugin stamps the company date.** It reads two numbers stored once in the park's own save file (its company start year and its game-year origin) and adds one field, `company_year`, to every event; the month and day stay the game's own. The plugin sends nothing until both numbers are stored, so no event ever lacks a company date. This gains events that are complete when they are created, values that travel with the park through every reload, autopilot run and year-end save, and a listener that stays a plain pass-through. It costs a plugin change re-measured with `make bench`, a one-time in-game prompt for each park (including one windowed session for each existing rehearsal save and the benchmark save), no capture at all in a session whose prompt is cancelled, and the formula written twice (once in the plugin, once in the dbt check).
- **A wrong start is corrected downstream, the same way under either option.** Every event keeps its game date, and a park registry (a small table in the repo listing each park's two values) is the authority. dbt recomputes the company year from the game date and the registry and keeps both the raw stamp and the corrected value; a test fails any mismatch that has no listed correction for its park, session and wrong value. Models use the validated stamp, never a recomputed date: recomputation is the test, not a source. Raw files are never rewritten.
- **Autopilot parks stay in step without sharing a clock.** The company year advances with the game year by the formula, so an autopilot park needs only its own two values. What keeps the parks together is a scheduling rule: an autopilot run covers company year Y only after the hand-played park has begun Y. The year-end save does not stop the game, so the few events recorded after it are kept and dbt leaves them out of the closed year (ADR 0006). The year-end close register that NEXT 6 (the portfolio view and park-identity rules) already plans checks the result.
- **The listener option can also date every event, and is cheaper today.** It must hold or reject a new park's events until someone adds that park's registry row, which can happen only after the plugin has minted the park ID during its first session. Holding needs a store before raw and a release step; rejecting loses the events. Business logic also moves into the listener, so the planned replay and a future swap to a real message queue must carry it.
- **Two facts are untested and the build must probe them first:** that park storage (the plugin's data kept inside the save file) survives a save made while the plugin is not installed (the 0.5.5 source suggests it does), and that the prompt works in windowed play.
- **Decision needed:** the project owner rules whether the plugin or the listener stamps the company date. Until then the build waits; the draft decision record is `docs/adr/0014-company-date-stamped-at-the-source.md`.

## How this was produced
One Claude research agent worked this lane on 2026-10-03. It read this repo (the plugin, the listener, the contracts, the capture and benchmark harnesses, ADRs 0003, 0006, 0007, 0009, 0011 and 0012, `ARCHITECTURE.md` and `docs/FINDINGS.md`), the OpenRCT2 0.5.5 plugin type definitions installed by `make setup` (GPL, never committed), the 0.5.5 engine source on GitHub, and official documentation for the practices in section 2. Nothing was run against the game. Two blind review rounds followed (Codex, 2026-10-03, `docs/ai-dlc/reviews/company-date-stamping-1-sol.md` and `docs/ai-dlc/reviews/company-date-stamping-2-sol.md`); their eleven findings are folded in and tracked in `docs/ai-dlc/ledger/company-date-stamping.md`.

Each claim carries its source and an "as of" date; "as of 2026-10" means the page was read then and carried no date of its own. Evidence strength follows the house scale: **strong** (several primary sources agree, or the engine source says it directly), **moderate** (one primary source, or several secondary ones), **weak** (one secondary source, or inference).

## Decisions at a glance

| Question | Recommendation | Main alternative | Confidence |
|---|---|---|---|
| Who stamps the company date | The plugin, from values in park storage | The listener, from a registry file | moderate |
| What the event carries | One `company_year` field in the envelope (the fields every event carries), never blank: the plugin sends nothing until it can fill it; month and day stay the game's | Three company-date fields | moderate |
| How a hand-played park gets its values | The analytics plugin's own first run: a one-time in-game prompt, plus a menu item to view or correct them | A `capture-data` option | moderate |
| How a rehearsal park gets its values | The same first run: the old save is opened once in the windowed game, answered and saved; headless runs load that save | A separate seed-helper plugin | moderate |
| How an autopilot park gets its values | Inherited from its own save; nothing to set | A registry lookup | strong |
| How a wrong start is corrected | dbt recomputes from the registry and game date only to test the stamp and keeps both values; a mismatch passes only with a listed correction for its park, session and wrong value; models use the validated stamp; raw stays as landed | Rewriting raw files (forbidden) | strong |
| How autopilot parks stay in step | A run rule (start company year Y only after the managed park has begun it), dbt excluding events after the year-end save from the closed year, and the year-end register | A shared clock passed between runs | moderate |

## 1. What the repo does today

### 1.1 How the plugin stamps every event
**In plain terms.** The plugin gives every event its identity and its times when the event is created, and numbers it when it hands the line to the socket. The park's ID lives inside the park's own save file, so it survives reloads and saves.

**Technical detail.** `emit()` in `plugin/src/emit.ts` is the only way to create an event. It stamps `schema_version`, `event_type`, `plugin_version`, `park_id`, `session_id`, `game_year`, `game_month`, `game_day`, `game_ticks_elapsed` and `emitted_at` at creation; `seq` and `event_id` are stamped at hand-off (ADR 0007, `seq` stamped at hand-off). `readOrMintParkId()` in `plugin/src/identity.ts` reads `park_id` from `context.getParkStorage()` (stored inside the `.park` file) and mints one when absent; `session_id` is minted fresh in every `main()`. The save keys of ADR 0011 (save lineage recorded in park storage) use the same storage. The plugin never uses `context.sharedStorage` (the per-install store). Repo evidence, **strong**.

### 1.2 How the listener lands events
**In plain terms.** The listener adds only the time a line arrived and writes it to a dated file; it never changes what the plugin said.

**Technical detail.** `Lander.land()` in `src/openrct2_analytics/ingest/listener.py` adds `received_at`, refuses any line that already carries one, and appends the event to `v<schema_version>/events-<date>.jsonl`; bad lines go to a malformed file with their reason. Its docstring already warns that a replay must strip broker fields such as `received_at`. ADR 0003 (local socket and JSON Lines stand in for Pub/Sub) says moving to a real message queue swaps only the listener's write side. Repo evidence, **strong**.

### 1.3 How the contract defines the envelope
**In plain terms.** One contract lists the fields every event carries; all seven contracts share one version number, and new optional fields have been added before as a minor version.

**Technical detail.** `contracts/envelope.odcs.yaml` (version 1.2.0) lists the stamped fields plus `received_at`, described as the listener's clock. ADR 0007 bumps the envelope and event contracts together. The precedent for an additive change is `contracts/session_start.odcs.yaml`, whose save-lineage fields are `required: false` and "absent in events from plugins before 0.3.0". The converter types every field from the contracts, so a new optional field needs no converter code. Repo evidence, **strong**.

### 1.4 How the harnesses launch the game and pass options
**In plain terms.** For hand play, `make capture-data` installs the plugin and listens while the player starts the game; it passes nothing to the plugin. For headless runs, the benchmark builds a private game folder per run and can already drop a small generated helper plugin into it.

**Technical detail.** `src/openrct2_analytics/ingest/capture.py` takes only test and process options (`--game-process`, `--game-check-command`, `--port`, `--plugin-file`, `--poll-seconds`), runs its own listener in-process, installs one plugin file with an install record (ADR 0009, `capture-data` removes only a plugin it can prove it installed), and removes it when the game quits. `src/openrct2_analytics/ingest/bench_run.py` launches `OpenRCT2 host <park copy> --headless --port <port> --user-data-path <isolated folder>` with an in-process listener; `src/openrct2_analytics/ingest/bench_setup.py` writes a fresh `config.ini` and, in sample mode, a save helper plugin whose filename and day count are substituted into its text. That substitution is the existing way a value reaches a headless run. Repo evidence, **strong**.

### 1.5 What each option would touch

| Area | Plugin stamps | Listener stamps |
|---|---|---|
| Plugin | `identity.ts` (two storage keys), `emit.ts` (stamp `company_year`), `main.ts` (keep the emitter closed until the values exist, prompt and menu item), `events.ts` (report the values in `session_start`), plugin tests, a version bump, and a `make bench` re-run | none |
| Ingest | the harnesses report an empty capture as a failure; existing saves are seeded once in windowed play | `listener.py` (look up, stamp, and hold or reject lines for unregistered parks), `config.py` (registry location), `capture.py` and `bench_run.py` (pass the registry) |
| Contracts | envelope and `session_start` gain optional fields; the set moves to 1.3.0 | envelope gains an optional listener-added field; the set moves to 1.3.0 |
| Reference data | a registry in `seeds/` for dbt's check and corrections | the same registry, read by the listener as well as dbt |
| dbt | staging passes the field through; the intermediate date mapping (NEXT 3b) checks it | the same |
| Replay and queue swap | unaffected | replay must strip and re-add the field; a real queue needs the lookup in a subscriber |

## 2. Practice: where business time gets stamped

### 2.1 Event time, processing time and ingestion time
**In plain terms.** Mature streaming systems separate when something happened from when a machine saw it. Results built on the time something happened come out the same however late the data arrives; results built on arrival time do not.

**The evidence.**
- Apache Flink defines event time as "the time that each individual event occurred on its producing device", embedded in the record before it enters the system, and says event-time results stay correct even "when reprocessing historic data"; processing time "does not provide determinism" (https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/time/, as of 2026-10). **Strong.**
- Older Flink releases also defined ingestion time, assigned once at the source operator (https://nightlies.apache.org/flink/flink-docs-release-1.10/dev/event_time.html, as of 2026-10). **Moderate.**

**What it means here.** The game date is the event time, `emitted_at` the producer's wall clock and `received_at` the ingestion time. The company date is a business-calendar view of the event time: a fixed function of the game date and two per-park values. Whoever stamps it, the result is reproducible only if those two values are versioned.

### 2.2 Systems of record stamp a business date beside the system date
**In plain terms.** Hotel systems record two dates on every charge: the hotel's business date, which a controlled end-of-day process advances, and the computer's own date. This is the closest real analogue to a company date stamped at the source.

**The evidence.**
- Oracle OPERA records each posting's "Revenue Date" as the "property business date when the revenue from this transaction was posted" and its "Posting Date" as the "system date" (https://docs.oracle.com/cd/E98457_01/opera_5_6_core_help/posting_history.htm, as of 2026-10). **Moderate, one vendor.**
- OPERA Cloud's end-of-day sequence (the night audit) "rolls the business date"; its Change Business Date utility, which runs several night audits in a row, is allowed only before any financial transaction has been posted (https://docs.oracle.com/cd/F34189_01/doc.201/f42091/t_toolbox_managing_business_date.htm, as of 2026-10). **Moderate.**

**What it means here.** The managed park plays the role of the night audit: it sets the company clock. Stamping the company year at the source matches how a system of record behaves, and keeping the game date beside it matches OPERA's second date.

### 2.3 Analytics pipelines keep raw times and derive corrected ones downstream
**In plain terms.** Event-collection products keep every time the device and the server recorded, and compute the "best" time in the pipeline, so the computation can be redone.

**The evidence.**
- Segment keeps four timestamps per call and computes `timestamp` at ingestion as `receivedAt - (sentAt - originalTimestamp)` to correct device clock skew (https://www.twilio.com/docs/segment/connections/spec/common, as of 2026-10). **Strong.**
- Snowplow's tracker sets device timestamps, its collector sets `collector_tstamp`, and its Enrich step computes `derived_tstamp`, which Snowplow recommends for reporting (https://docs.snowplow.io/docs/events/timestamps/, as of 2026-10). **Strong.**

**What it means here.** Both products derive a better time from fields the producer already sent, so any stage can redo it. The company date also needs two values the event does not carry, so whichever stage stamps it must hold those values. That is the real difference between the two options.

### 2.4 Enrichment at the source versus in the pipeline
**In plain terms.** Enrichment means adding fields to an event from another source of data. Doing it at the source makes every copy of the event complete; doing it in the pipeline keeps the producer simple, but the added value depends on what the lookup table held when the event arrived.

**The evidence.**
- Martin Fowler's "event-carried state transfer" lets receivers work without calling the source, at the cost of "lots of copies" of the data (https://martinfowler.com/articles/201701-event-driven.html, 2017-02). **Strong.**
- Snowplow's Enrich step adds fields after collection, which it calls "dimension widening" (https://docs.snowplow.io/docs/pipeline/enrichments/, as of 2026-10), and Apache Beam's Enrichment transform does a key-value lookup inside the pipeline (https://beam.apache.org/documentation/transforms/python/elementwise/enrichment/, as of 2026-10). **Strong.**
- Pitfall: in ksqlDB, a stream-to-table join is a lookup when the event arrives; "updates on the table side don't produce updated join output", an event that arrives before its table row gets nulls in a left join, and Confluent advises loading reference data before events flow (https://docs.confluent.io/platform/current/ksqldb/developer-guide/joins/join-streams-and-tables.html, as of 2026-10). **Strong.**

**What it means here.** A listener lookup is exactly this stream-to-table join. The source says only that a lookup finds nothing when the row is absent at lookup time; it does not make an undated first session inevitable. A listener can hold or reject lines for a park with no registry row until the row exists, as Confluent's advice to load reference data first implies. A row that is wrong when its events land, however, stays wrong in the append-only raw files, and only dbt can repair it.

### 2.5 Reference data and corrections
**In plain terms.** Small, slowly changing lookup tables belong in version control. When they were wrong, teams append the correction and recompute, rather than erase what was believed.

**The evidence.**
- dbt seeds (CSV files that dbt loads as tables) are "best suited to static data which changes infrequently", and being in the repo they are "version controlled and code reviewable" (https://docs.getdbt.com/docs/build/seeds, as of 2026-10). **Strong.**
- Kimball's late-arriving dimension: when facts arrive before their dimension row, the warehouse creates a placeholder row holding the known key and overwrites it when the real row arrives (https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/late-arriving-dimension/, as of 2026-10). **Strong.**
- Kimball's calendar date dimension holds fiscal periods and similar attributes so they are looked up, not computed in queries (https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/calendar-date-dimension/, as of 2026-10). **Strong.**
- Fowler's bitemporal history: a record of what was believed "is append only"; a correction is new knowledge added beside the old (https://martinfowler.com/articles/bitemporal-history.html, 2021-04). **Strong.**

**What it means here.** The registry is a dbt seed, and its git history is the record of what was believed when. A stamped value is the producer's belief at the time; the registry is the corrected truth; the models carry both.

### 2.6 Re-deriving from raw data
**In plain terms.** If raw input is kept unchanged, any derived value can be recomputed with better logic or better reference data.

**The evidence.**
- Jay Kreps describes reprocessing as running an improved job from the beginning of the retained raw log into a new output table, then switching readers to it (https://www.oreilly.com/radar/questioning-the-lambda-architecture/, 2014-07). **Strong.**
- Maxime Beauchemin's "Functional Data Engineering" argues for a persistent, immutable staging area and pure, rerunnable tasks (https://maximebeauchemin.medium.com/functional-data-engineering-a-modern-paradigm-for-batch-data-processing-2327ec32c42a, 2018). The page returned HTTP 403 on 2026-10-03, so this summary comes from secondary accounts. **Weak.**

**What it means here.** The repo already works this way: raw JSON Lines are append-only and every `dbt build` recomputes from the Parquet. Because each event keeps its game date, the company date can always be recomputed.

### 2.7 Adding a field without breaking old data
**In plain terms.** A new field must be optional, or have a default, so data written before it existed still reads.

**The evidence.**
- Confluent Schema Registry: a new field without a default breaks backward compatibility "since it's not clear what value should be assigned to the new field, which is missing in the old data"; backward compatibility is the default so consumers can rewind to the start of a topic (https://docs.confluent.io/platform/current/schema-registry/fundamentals/schema-evolution.html, as of 2026-10). **Strong.**

**What it means here.** `company_year` must be `required: false` in the envelope, absent before the plugin version that adds it, as the save-lineage fields were. A dbt test, not the contract, then requires it on events from that version on.

## 3. OpenRCT2 0.5.5 facts

### 3.1 What park storage guarantees
**In plain terms.** A value written to park storage is saved inside the park's file and comes back on every reload, autosave and copy. A save made before the value was written does not have it.

**The evidence.**
- The type definitions say park storage "is stored inside the .park file" and is serialised on every save, including autosaves; `getParkStorage(name)` returns the store of a named plugin (0.5.5 type definitions). The 0.5.5 source confirms the named lookup accepts any plugin name (https://github.com/OpenRCT2/OpenRCT2/blob/v0.5.5/src/openrct2/scripting/bindings/game/ScContext.hpp, as of 2026-10). **Strong.**
- The engine writes all plugins' park storage as one JSON chunk on save and restores it on load; it skips the chunk when storage is empty (https://github.com/OpenRCT2/OpenRCT2/blob/v0.5.5/src/openrct2/park/ParkFile.cpp, as of 2026-10). Because the whole object is written back, **inference:** a park saved while this plugin is not installed keeps the plugin's values. This matters because `capture-data` removes the plugin after every session. **Moderate; untested.**
- Converting a save to a scenario clears plugin storage since v0.4.22 (https://github.com/OpenRCT2/OpenRCT2/pull/24069, merged 2025-05). **Strong.**
- Repo measurements (observational): values written inside the save hook reach plugin saves, autosaves and Save Game As menu saves, and a park ID survives a year-end save and resume; a save made before the ID existed had none, so the plugin minted a new one (`docs/FINDINGS.md`, rows of 2026-09-28 to 2026-10-01). **Strong for what was run, on a narrow sample.** The save-hook test ran on copies of one park (the 1,938-guest benchmark park): 6 valid headless runs plus one windowed menu-save session by one player and three headless reloads, on one Apple silicon machine (arm64, 8 cores). The year-end test ran 6 headless runs, each once, on copies of three parks with a day-counting probe rather than the capture workload, on one MacBook Air (Apple M1, 16 GB). Not covered: plain Save Game, the save offered on quit, a save made with the plugin absent, and any park beyond those copies.

**What it means here.** Autopilot runs inherit the values from the save. Two pitfalls follow: a file copy carries the values (the same open question as copying a park ID, which NEXT 6 settles), and loading an earlier save after a correction brings back the old values.

### 3.2 Prompting the player
**In plain terms.** A plugin can show a text box in a windowed game, but not in a headless one.

**The evidence.** `ui.showTextInput` takes a title, description, initial value, maximum length and a callback that fires on OK, and `ui.registerMenuItem` adds a menu entry (0.5.5 type definitions). OpenRCT2's scripting guide says the `ui` namespace "is not available in headless mode" (https://github.com/OpenRCT2/OpenRCT2/blob/develop/distribution/scripting/scripting.md, develop branch, as of 2026-10). **Strong.**

### 3.3 How a headless run can receive a value
**In plain terms.** A plugin cannot read command-line options, environment variables or files. A headless run can only learn a value from its save, from storage that was written for it, or over its localhost socket.

**The evidence and the channels.**
- Plugins run in a sandbox "with no direct access to your computer" and can open sockets only to localhost (scripting guide, above). **Strong.**
- **Park storage already in the save:** the real company's autopilot parks were hand-played first, so they already carry the values. **Strong (section 3.1).**
- **A helper plugin in a seed run:** the harness could write a one-off helper, like the existing save helper, that calls `context.getParkStorage("openrct2-analytics")`, sets the two values and saves. It cannot know the park ID the analytics plugin will mint, so it would need a copy of the identity code to keep one ID across seeding and capture, and two plugins' start order is not documented. **Moderate; untested; not used:** ADR 0014 keeps one bootstrap, the analytics plugin's own first run.
- **`plugin.store.json`:** shared storage lives in this file in the user folder (https://github.com/OpenRCT2/OpenRCT2/blob/v0.5.5/src/openrct2/PlatformEnvironment.cpp, as of 2026-10). The benchmark's private folder could hold one per run, but in the player's own folder it is shared by every park and every plugin. **Strong for the file; rejected for hand play.**
- **The socket:** sockets can receive data (`on("data")` in the type definitions), so the listener could send the values back. This makes stamping depend on a live connection. **Moderate; not recommended.**
- **The stdin console:** it evaluates JavaScript, but a third-party report on 0.5.5 says it starts only when stdin and stdout are terminals, not pipes (https://github.com/MatthewT1/matts-openrct2-plugins/issues/46, 2026-09). **Weak; rejected.**

## 4. Recommendation

### 4.1 The plugin stamps `company_year`
**In plain terms.** Each event gains one number, the company year; together with the game's month and day it is the company date.

**Technical detail.** Park storage gains `company_start_year` and `game_year_origin`. `emit()` stamps `company_year = company_start_year + (game_year − game_year_origin)`; a stored pair whose origin is after the current game year counts as missing. `main()` mints or reads the park ID, then reads the two values; while either is missing, the emitter stays closed (no socket, no queue, no `session_start`) and the plugin shows a message instead. When the prompt writes both values, the emitter opens and `session_start` takes `seq` 1. No event is ever sent with a blank company year. `session_start` reports both values as read. The cost per event is one addition and one comparison, and about 20 bytes per JSON line; `make bench` re-measures it under ADR 0005's per-tick budget. One field instead of three keeps the month and day single-sourced; dbt checks each row by its offset (company year minus game year, which must equal the registry's start year minus origin) and by origin (no stamp before it).

### 4.2 How each kind of park gets its values
- **One bootstrap for every park: the analytics plugin's own first run.** When park storage lacks the values and `ui` exists, the plugin mints the park ID, asks for the company start year, then for the origin with the current game year filled in, writes both and opens the emitter; a menu item views or corrects them later. Cancelling stores nothing and sends nothing for that session; the menu item reopens the prompt. Headless, where there is no prompt, the plugin prints a console line and sends nothing. Writing storage does not change the simulation, so it stays within the no-go on plugin actions that change a park.
- **A rehearsal park or the benchmark save:** each old save is opened once in the windowed game with the plugin installed (through `make capture-data`), answered and saved. That session's `session_start` gives the registry row, and every later headless run loads the seeded save, so seeding, registration and first capture share one `park_id`. Until then, a headless run on the save captures nothing, and the harnesses must report that as a failure.
- **An autopilot park:** nothing to set; the values come from its save.

### 4.3 The correction path
- **The registry** is a dbt seed in `seeds/`: one row per park with `park_id`, its two values, a rehearsal label and a note. Its git history records what was believed when.
- **dbt checks every event, and a listed correction lets a known mismatch pass.** dbt recomputes the expected company year from the game date and the registry only to test the stamp; the intermediate date mapping (NEXT 3b) uses the validated stamp (the raw stamp once the test passes, or the corrected value on a corrected row), never the recomputed date. Staging keeps the raw stamp and the corrected value as two columns and labels corrected rows, so every mismatch stays auditable. The test (severity error) passes a row when its stamp equals the registry value or a correction row (`park_id`, `session_id`, wrong stamp value, corrected value, reason) matches its park, session and wrong value; an unlisted mismatch fails, including a second, different wrong stamp in a session that already has a row for another. Raw files stay as landed (`CLAUDE.md`, "Never break" 2).
- **Future events are fixed at the source** through the menu item, in a windowed session for any park.
- **Known trap:** loading an earlier save revives the earlier values. The dbt test catches it, and the correction row covers it.
- **Gain and cost:** a wrong start never needs a raw rewrite and every correction is reviewable in git; the cost is a second copy of the formula in dbt and one more seed to maintain.

### 4.4 Keeping autopilot parks in step
- **No shared clock is needed.** Each autopilot run starts from the 1 March save of the previous run, which the 2026-09-28 year-end test showed chains with no gap or overlap (`docs/FINDINGS.md`; observational: 6 headless runs on copies of three parks, one MacBook Air, a day-counting probe rather than the capture workload, and no chain longer than one resume), so its game year, and by the formula its company year, rise by exactly one per run.
- **The run rule:** an autopilot run for company year Y starts only once the hand-played park has begun Y (an event with that company year has landed). The future autopilot runner reads that fact from landed data before launching.
- **The year-end save does not end the game.** In the same test, run 1 kept playing for 3 game days (1,586 ticks) after its save until the harness stopped it. The runner stops after the save, not at the boundary, and that abandoned post-save play meets the rule that an autopilot park never runs past its year end. The plugin records those events and raw keeps them; dbt excludes them from the closed company year, because the next run resumes from the save and leaves them on an abandoned branch (ADR 0006). The build's acceptance test: after a year-end run, no event after the year-end save advances the kept company timeline or allows an early close; it reads the captured events, not the time the runner stopped.
- **The year-end close register** (planned in NEXT 6) lists the parks expected in each company year from the registry and blocks the annual marts until each has a complete, kept year.
- **Gain and cost:** the parks cannot drift because the formula has no state to lose; the cost is a check the autopilot runner must make before every run.

### 4.5 What each option gives up

| | Plugin stamps (recommended) | Listener stamps |
|---|---|---|
| Events complete at the source | yes, as a system of record stamps its business date | no; complete only after landing |
| A new park's first session | nothing is sent until the prompt is answered; a cancelled prompt captures nothing | lines are held or rejected until someone adds a registry row for a park ID minted during that session; rejecting loses them |
| Append-only raw | raw holds only stamped lines | met only if the holding store is append-only too and release appends stamped copies to raw |
| Reloads, copies, autopilot runs | values carried in the save; copies inherit them (NEXT 6 rule needed) | looked up by park ID; copies share the ID anyway (same NEXT 6 rule) |
| Setting the values | a prompt in the game, once per park, including one windowed session per existing save | one registry edit per park, made after its ID exists (a harness can write it for headless parks) |
| Correcting future events | the menu item, in a windowed session | edit the registry |
| Replay and a real queue (ADR 0003) | unaffected | replay strips and re-adds the field; a subscriber must take over the lookup |
| Reproducibility | the stamp is fixed in the line | the stamp depends on the registry when the line arrived |
| Work now | plugin change, plugin tests, `make bench`, windowed seeding of existing saves | listener, config and harness changes, a holding store; no plugin change |

### 4.6 What the build must probe first
A short headless probe on copies, before the spec is final: a park saved and reloaded with the plugin absent keeps the plugin's park storage. The build's acceptance criteria (every event dated or nothing captured, one stable park ID per old save, corrections that pass and stay visible, the two-park calendar case with at least two shared company years, and year-end run-on that never counts) are listed in ADR 0014. In windowed play, the prompt and menu item need the project owner's check (owner-later). If probe 1 fails, `capture-data` would have to keep the plugin installed between sessions, and the listener option becomes the stronger choice.

## 5. Where sources disagree
- **Stamp at the source, or derive in the warehouse.** Kimball puts fiscal and calendar attributes in the warehouse's date dimension; OPERA stamps a business date at the source; the project owner's scope ruling of 2026-10-02 requires an upstream stamp. Resolved: the source stamps the company year as its own assertion, the warehouse validates it against the registry, and the company-date dimension owns every other calendar attribute.
- **Derive at ingestion, or at the source.** Segment and Snowplow derive corrected times at ingestion, which supports the listener, but they derive only from fields the producer already sent. The company date also needs per-park values the event does not carry, so the analogy is partial.

## 6. Gaps and thin evidence
- No source describes game telemetry stamped with a business calendar; the analogues are hotel systems and analytics trackers.
- Untested in this repo: park storage surviving a save without the plugin; `ui.showTextInput` in play; plain Save Game and the save offered on quit; a listener that holds lines for an unregistered park. The repo probes cited here are observational and narrow (section 3.1).
- Single-source or weak: the OPERA field definitions (one vendor), the stdin console report (third party), and the Beauchemin article (not opened).
- Not designed here, by design: the autopilot runner itself, the copy rule for park identity (NEXT 6), and the company-date dimension (the dbt design session).

## 7. What changes on the roadmap
- NEXT 16 records that this research is done and is blocked on the project owner's ruling; the build waits.
- Once ruled, the build slice adds the field (minor contract version), the registry seed, the dbt agreement test and correction rows, and either the plugin's closed emitter and prompt or the listener's lookup and hold. It starts with the probe in section 4.6.
- NEXT 6 gains two inputs: the copy rule must clear or reset the company values along with the park ID, and the year-end register reads the registry.
