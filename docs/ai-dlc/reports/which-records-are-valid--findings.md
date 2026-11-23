# Which records are valid, and who cleans them — research findings
status: research complete, awaiting review and the project owner's decision · date: 2026-09-29 · initiative: park-company (roadmap "Conversations to have", first item)

## Bottom line
- **Real teams split cleaning work with three questions:** does only the producer know the fact, can a wrong call be undone, and what does keeping the data cost. The producer (here, the plugin playing the app team) supplies identifiers and labels that only it knows, and it chooses which meaningful business events to send, as tracking-plan guidance recommends. It drops records it has already produced mainly when cost forces it, and every vendor that documents such dropping warns that it cannot be undone. Decisions about which duplicate, which click or which timeline counts stay with the data team.
- **Applied to our six issues,** that points to the plugin adding facts (event IDs, an exact save ID and position for lineage, preview and prediction flags) while dbt makes every validity decision with a test and a count of what each rule excluded. The one open case is construction previews: dropping them at the source fits the practice only if two things are shown first, that sending them costs the plugin real time (unmeasured) and that the preview flag never marks a real build (the roadmap's pretest can check this).
- **Employers reward visible trust work more than any specific cleaning technique.** Of 32 saved analytics-engineer postings, 26 ask for data-quality testing and 26 for trusted or governed data. 12 ask explicitly for cleaning raw or messy data, and 10 for working with producing engineers on instrumentation or source quality. Only 2 name data contracts. None says producers should clean data before it lands.
- **Hiring reviewers reward candidates who distrust their own numbers:** data problems caught, handled and written up, plus totals reconciled to an outside source. No source says whether cleaning at the producer reads as maturity or as dodging data-team work.
- **Confidence is uneven.** Duplicate handling rests on several official docs that agree. Reloaded saves and the run-on after a year-end save have no direct source in any lane; only analogues exist (event-sourcing corrections, streaming checkpoints).
- **Next:** the ideation discussion with the project owner picks an owner for each issue (section 8 lists the options), then a decision record in `docs/adr/` and updates to roadmap NEXT items 1, 2b and 3b.

## How this was produced
Four research agents ran in parallel on 2026-09-28 and 2026-09-29, each on Sonnet, blind to each other: industry practice, game-studio practice, the owner's 52 saved job postings, and hiring-manager signals. One blind reviewer from another model family (Codex, gpt-6-sol) then opened 25 of the cited pages and checked the report; its six findings and their resolutions are in `docs/ai-dlc/ledger/which-records-are-valid.md`, and this version includes the fixes. Claims carry a source URL and an "as of" date; "as of 2026-09" means the page was read then and carried no date of its own. Evidence strength is marked **strong** (several official sources agree), **moderate** (one official source, or several secondary ones) or **weak** (one secondary source, or the agent's own inference). The owner's ruling for weighing conflicts: when real-world practice and portfolio showcase disagree, real-world practice wins, and the showcase comes from documenting the choice.

## 1. How real teams split the work

**In plain terms.** The app team knows things the data team cannot reconstruct later, such as whether a click was a preview or whether a session continued from an older save. The app team's job is to write those facts down. The data team's job is to decide what counts, because that decision can be revised later only if the raw records still exist.

**The evidence.**
- **Producers are asked to guarantee structure, versioning and ownership; consumers still handle what no contract can promise.** Confluent says the upstream component enforces the data contract (https://docs.confluent.io/platform/current/schema-registry/fundamentals/data-contracts.html, as of 2026-09). Chad Sanderson argues producers must "own data quality, just as they own application reliability", meaning automated checks in their CI, not hand-cleaning (https://dataproducts.substack.com/p/the-shift-left-data-manifesto, as of 2026-09; he runs a data-contract company). Benn Stancil warns against extracting "promises from data providers that they can't and shouldn't keep" (https://benn.substack.com/p/data-contracts, 2022-09). Fowler's Tolerant Reader has consumers take only what they need (https://martinfowler.com/bliki/TolerantReader.html, 2011-05). **Moderate.**
- **Game-analytics platforms work in layers, but what they keep varies.** On the game side, SDKs buffer and batch events: PlayFab defaults to batches of 5 events or 3 seconds, a 1,024-event buffer, and an error to the game when an event would exceed the buffer (https://learn.microsoft.com/en-us/xbox/playfab/sdks/c/event-pipeline/eventpipeline, updated 2026-08). On the server side, Unity checks each event's unique ID and rejects duplicates (https://docs.unity.com/en-us/analytics/faq, as of 2026-09), and AWS's Game Analytics Pipeline validates events against a schema and tags failures, but its `raw_events` table holds validated, transformed events, and a backup of the original input is optional (https://s3.amazonaws.com/solutions-reference/game-analytics-pipeline/latest/game-analytics-pipeline-developer-guide.pdf, 2021-08, repository archived 2024-01). So "emitted", "delivered", "rejected" and "retained" are different sets, and no platform found keeps every emitted event by default. No source found a studio deciding inside the game loop whether an event counts. **Moderate**; studio talks and the "Game Analytics" book (2013) were paywalled.
- **Raw data stays as it arrived.** Databricks describes the first landing layer (bronze) as source data kept as-is and appended incrementally, so it can be reprocessed (https://docs.databricks.com/aws/en/lakehouse/medallion, as of 2026-09). dbt's own docs say nothing either way about raw data; the append-only rule comes from lakehouse practice, not dbt. **Moderate.**

## 2. Issue by issue

### 2.1 Reloaded saves branch the history
**In plain terms.** Loading an earlier save rewinds the game, so two versions of the same days get recorded. Real systems never delete the losing version; they record where the branch happened and choose which version counts.

**The evidence.**
- Event-sourcing practice keeps original events and builds corrections from a "branch point" (Fowler, https://martinfowler.com/eaaDev/RetroactiveEvent.html, as of 2026-09). Microsoft's event-sourcing pattern undoes only through compensating events and gives each event an increasing identifier (https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing, as of 2026-09).
- Snowplow's tracker records session lineage at the producer: each session carries the previous session's ID, its first event's ID and an event index (https://docs.snowplow.io/docs/events/ootb-data/user-and-session-identification/, as of 2026-09).
- No source addresses save reloads in analytics; the only save-scumming source is a forum thread about preventing it (https://discussions.unity.com/threads/how-do-you-handle-save-scumming-in-mobile-games.1029457/, 2020-12).

**What it means here.** Only the plugin can know which save a session resumed from, so lineage is a producer fact; which branch counts is a data-team decision. The spike's rule (keep a session's days only past every earlier session's furthest day) is a heuristic that cannot tell a replay from a fork. A session ID plus a game date is not enough to identify the branch point, because several saves can share a date; lineage needs a unique ID per save and the exact event position (`seq`) at which it was taken. The OpenRCT2 0.5.5 plugin API declares a `map.save` hook (`openrct2.d.ts` line 524). If it fires before the file is written, the plugin can mint a save ID, store it with the current session ID and `seq` in park storage (which is saved inside the save file), and emit a "save written" event; a later session then reads the stored values on load and reports exactly which save and position it resumed from. Whether the hook fires in time, and headless, is untested. The game-action hook (`GameActionEventArgs`) carries no identifier shared across related actions. **Weak to moderate:** the pattern is well sourced, but its application to save files is inference.

### 2.2 The run-on after a year-end save
**In plain terms.** An autopilot run saved at the year boundary, then kept running for 3 game days before it stopped. The next run loads the save, so those 3 days are a branch nobody continues.

**The evidence.** No product-analytics source. The closest analogue is streaming checkpoints: on failure, Flink rolls back to the last completed checkpoint (https://flink.apache.org/2018/02/28/an-overview-of-end-to-end-exactly-once-processing-in-apache-flink-with-apache-kafka-too/, 2018-02; single source).

**What it means here.** This is issue 2.1's case with a known branch point: the save itself. If the save-ID lineage in 2.1 works, dbt can mark everything after the save's `seq` in the parent session as abandoned once a later session reports loading that save, using the same rule as any other reload. Until that lineage is tested, the run-on still needs the high-water-mark heuristic or the post-save flag the autopilot probe already records. Having the plugin hold back or withdraw events after a save would need coordination that its time budget cannot afford. **Weak:** inference from analogues.

### 2.3 Duplicate deliveries
**In plain terms.** Delivery systems sometimes deliver the same event twice. The fix is a unique ID stamped by the producer and reused on retry, then removal of repeats downstream.

**The evidence.**
- Producers stamp the ID: Segment `messageId` (https://www.twilio.com/docs/segment/guides/duplicate-data), Amplitude `insert_id` (https://amplitude.com/docs/apis/analytics/http-v2), Mixpanel `$insert_id` (https://docs.mixpanel.com/reference/event-deduplication), and Unity `eventUUID`, which the platform uses to reject duplicates (https://docs.unity.com/en-us/analytics/faq); all as of 2026-09.
- Ingestion removes repeats only within a window: at least 24 hours at Segment and 7 days at Amplitude. Kafka's idempotent producer uses a producer ID plus a sequence number (https://developer.confluent.io/patterns/event-processing/idempotent-writer/, as of 2026-09), the same idea as this project's `session_id` plus `seq`.
- The warehouse layer finishes the job: Snowplow's dbt package removes duplicates "at the very start" (https://docs.snowplow.io/docs/modeling-your-data/modeling-your-data-with-dbt/package-mechanics/deduplication/, as of 2026-09).
- Pub/Sub delivers at least once, so subscribers must be repeat-safe (https://docs.cloud.google.com/pubsub/docs/subscription-overview, as of 2026-09). A publisher retry gets a new message ID, so deduplication must use the application's own ID (https://docs.cloud.google.com/pubsub/docs/exactly-once-delivery, as of 2026-09).

**What it means here.** The plugin already mints `event_id`. The first dbt layer removes repeats keyed on it, with a test. Duplicates in a Pub/Sub stand-in are realistic, not a flaw to hide. **Strong.**

### 2.4 One click sent as several events
**In plain terms.** Clicking a price up four times sends four events plus a duplicate; typing a price sends the old value, then the new one. These are button presses, not business decisions.

**The evidence.**
- Tracking-plan vendors want the producer to emit business events, not raw interactions: Amplitude warns that "tracking every interaction inflates data volume" (https://amplitude.com/explore/data/event-taxonomy), Segment wants a "minimal number of core events" (https://www.twilio.com/docs/segment/protocols/tracking-plan/best-practices), and Snowplow wants one purpose per event (https://docs.snowplow.io/docs/fundamentals/tracking-design-best-practice/); all as of 2026-09.
- The counter-practice captures raw clicks and defines "actions" downstream, after the fact: PostHog (https://posthog.com/docs/data/actions, as of 2026-09) and Heap.
- dbt places changes of grain (for example, many clicks into one decision) in the intermediate layer (https://docs.getdbt.com/best-practices/how-we-structure/3-intermediate, as of 2026-09).
- No official source covers debouncing analytics events (waiting for a pause in input before sending one event).

**What it means here.** Real practice favors a producer that emits the business decision ("price changed from $1.00 to $2.00"), for the sake of meaning, not only cost; Microsoft's event-sourcing guidance likewise recommends events that capture business intent. Here, though, the game's action hook reports every command, and the plugin cannot know when the player has finished adjusting a price without waiting, which costs state and time. Collapsing click runs in the intermediate layer keeps the raw presses; the risk is that a time-window rule merges two real decisions. **Moderate.**

### 2.5 Repeated confirmed actions
**In plain terms.** One ride placement arrived as four confirmed "create ride" events at the same moment, two of them network echoes, so a naive count shows four rides.

**The evidence.**
- Meta collapses the same event sent by browser and server using a shared event name and event ID, first received wins (https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events/, as of 2026-09).
- In games that predict on the client, the server's confirmation is authoritative (https://www.gabrielgambetta.com/client-side-prediction-server-reconciliation.html, as of 2026-09; single source). Unity's netcode guards one-off effects so re-simulated ticks do not repeat them (https://docs.unity3d.com/Packages/com.unity.netcode@6.5/manual/prediction-n4e.html, as of 2026-09).

**What it means here.** The four copies have different `event_id`s, so removing duplicates by ID cannot catch them. They need a shared identifier: either the plugin stamps one, or dbt derives one from the action, its arguments and the tick. Matching on tick and action type without the arguments could merge two genuinely separate actions. **Moderate.**

### 2.6 Construction previews and client-side predictions
**In plain terms.** In build mode the game places and removes a see-through preview on every mouse move. That was about 96% of action events, and previews plus predictions were 74% of the old capture's bytes.

**The evidence.**
- Dropping at the source is documented, always with a warning that it cannot be undone. Snowplow says "there is no way to recover dropped events" (https://docs.snowplow.io/docs/events/filtering-bot-events/). Blocked events at Segment are permanently removed unless forwarded (https://www.twilio.com/docs/segment/protocols/enforce/forward-blocked-events). Google Analytics calls its data filters "permanent" (https://support.google.com/analytics/answer/10108813). All as of 2026-09.
- Labelling and filtering downstream also exists: Snowplow tags bots and filters them in the data model, keeping the rows for inspection (same Snowplow page).
- Sampling can stay countable: Honeycomb stores a sample rate on each kept event so counts can be scaled back (https://docs.honeycomb.io/manage-data-volume/sample/sampled-data-in-honeycomb, as of 2026-09). This concerns probabilistic sampling of kept data, not wholesale dropping of one event class.
- Unity's current fair-usage limits count valid and invalid events alike, so noise costs money there too (https://docs.unity.com/en-us/analytics/pricing-and-billing/fair-usage-limits, as of 2026-09).

**What it means here.** The preview flag is a producer fact, and a preview has no business meaning, so this is the one issue where dropping at the source fits the practice, if cost forces it. Two things are unproven. First, whether cost forces it: the plugin cost test measured snapshots and guest scans, not action events. Second, whether the classification is right: a daily count of dropped previews measures volume but cannot reveal a real build misclassified as a preview. The roadmap's pretest (NEXT 2c) already plans that check, a positive control in which the project owner drags one preview and places one real ride and exactly one confirmed build event must arrive. The stack review of 2026-09-27 ruled that the plugin drops previews; the evidence supports that ruling only after both checks. **Moderate.**

## 3. The four approaches, tested

**In plain terms.** No single approach handles all six issues. Real pipelines combine them: the producer labels, raw keeps what arrives, dbt decides, and a quarantine table catches records that break the contract.

| Approach | Where it is used | Gain | Pitfall | Our issues it handles |
|---|---|---|---|---|
| A. Plugin drops noise only, reports a count | Snowplow `event.drop()`, Segment Block, Google Analytics filters, OpenTelemetry head sampling with Honeycomb sample rates | Saves producer cost; for this project, per-tick time | Cannot be undone, the drop cannot use later context, and a count reconciles volume but does not restore rows | 2.6 only |
| B. Raw keeps everything; every rule lives in dbt | Databricks bronze layer; Snowplow cleans duplicates and bots in dbt; dbt calls models safe to re-run and easy to backfill (https://docs.getdbt.com/best-practices/idempotence) | Rules can change and history can be rebuilt without rerunning the game | Every raw consumer must reapply the cleaning (Mixpanel's raw exports keep duplicates), and previews cost plugin time and bytes | 2.3, 2.4, and 2.5 with derived IDs |
| C. Plugin labels, never drops; dbt filters | Snowplow bot tags and session lineage; PostHog and Heap define actions after capture | Reversible, and labels carry facts only the producer knows | Consumers who forget the filter overcount; labelled previews still cost serialization time | 2.1, 2.2, 2.5, 2.6 |
| D. Quarantine table for contract breaks | Snowplow failed events land in a separate monitored table (https://docs.snowplow.io/docs/fundamentals/failed-events/); Pub/Sub dead-letter topics; Kimball's error event schema | Nothing vanishes silently, and failures are countable | Often nobody reviews the quarantine (https://www.kai-waehner.de/blog/2022/05/30/error-handling-via-dead-letter-queue-in-apache-kafka/, 2022-05), and it catches only structural failures | None directly: all six issues produce records that are valid by schema |

Snowplow is the clearest single precedent for a combination: it quarantines invalid events (D), lands valid events including duplicates and bots, then removes duplicates and filters bots in dbt using producer labels (B and C). **Moderate:** assembled from Snowplow's own docs.

## 4. What employers ask for

**In plain terms.** The owner's saved postings ask analytics engineers to make data trustworthy downstream: tested, governed, defined once, documented. Explicit cleaning and work with upstream producers matter, but less often. The specific techniques this project needs, like deduplication and handling branching history, almost never appear by name.

**The evidence.** 52 postings saved between 2025-12 and 2026-09: 32 analytics-engineer roles and 20 others (data science, data engineering, analyst). Postings are cited by number only.

| Theme | Analytics-engineer postings (of 32) | Other postings (of 20) |
|---|---|---|
| Data-quality testing or monitoring | 26 (81%) | 6 |
| Trust, governance, single source of truth | 26 (81%) | 7 |
| Data modeling as a core duty | 26 (81%) | 7 |
| Owned metric definitions or a semantic layer | 19 (59%) | 4 |
| Documentation, lineage or catalog | 17 (53%) | 5 |
| Explicit cleaning of raw or messy data | 12 (38%) | 4 |
| Working with producing engineers on instrumentation or source quality | 10 (31%) | 3 |
| Root-causing data discrepancies | 10 (31%) | 1 |
| Dimensional modeling (star schema, Kimball) | 7 (22%) | 0 |
| Reconciliation to a source of truth | 4 (13%) | 1 |
| Layered models named (staging, marts, bronze and silver) | 4 (13%) | 0 |
| Deduplication, backfills or incremental models | 3 (9%); none uses "dedup", "idempotent" or "late-arriving" | 0 |
| Data contracts by name | 2 (6%) | 1 |

Tools named most in the analytics-engineer postings are SQL (29), dbt (24), Python (23), Snowflake (17) and Looker (15). DuckDB and Dagster appear in none.

How employers phrase upstream work:
- "Triage and classify data quality alerts, distinguishing source-level issues from transform-layer failures" (P10, analytics engineer).
- "Partner with engineers to improve data quality at the source" (P50, analytics engineer).
- "Experience partnering with engineering teams to instrument new event or telemetry data, not only transforming what's already captured." (P06, analytics engineer).
- "ARR, MRR, NRR, and churn are produced by tested dbt models that reconcile to source systems" (P27, analytics engineer).

The lead session re-checked the data-contract count, the zero count for deduplication wording, and the four quotes against the raw text; all matched. A keyword search finds reconciliation in 3 analytics-engineer postings rather than the agent's 4, within the coder's judgment.

**Caveats.** The sample is one job seeker's picks, mostly US remote or Bay Area, about 15 of 52 in health care, likely skewed toward modern, AI-forward stacks. With 32 postings, differences under about 15 percentage points are noise. Postings describe duties, not who cleans in the company's architecture. **Moderate** for the pattern, **weak** for any single percentage.

## 5. What makes a portfolio credible to reviewers

**In plain terms.** Reviewers look for a candidate who expects the data to be wrong, finds out how, fixes it, and says so. A small, finished, well-explained project beats a large one.

**The evidence.**
- A recruiter's published take-home rubric rewards a model that "catches them, handles them, and flags them in the write-up" over one that silently drops seeded problems, and warns that tests on key uniqueness alone can stay green while numbers are wrong (https://www.kore1.com/analytics-engineer-interview-questions/, 2026-08; staffing-firm recruiter, single source).
- A company take-home brief warns that input "may or may not have duplicate rows" and asks candidates to record their interpretation (https://github.com/analytics-automation/data-engineer-take-home-assignment, 2022-05; primary).
- dbt Labs' hiring guide: "Analytics engineers aren't afraid of messy data because they can solve it with good SQL" (https://www.getdbt.com/data-teams/hiring-analytics-engineer/, 2024-04; primary).
- Reviewers skim first: one practitioner describes a 60-second scan, then a deep review, and says he looks for a tests folder (https://pipeline2insights.substack.com/p/how-to-create-data-engineering-data-engineers-github-portfolio-in-2026, 2026-02; community, single source).
- Over-scoping hurts: "better to create something small and effective that works end-to-end" (https://data-goblins.com/power-bi/video-games, 2023-08; named practitioner, who also argues game data simulates a real project's complexity).
- Portfolios are a "supporting actor" next to résumés, interviews and referrals (https://benjaminbennettalexander.substack.com/p/why-your-data-portfolio-is-not-getting, 2026-04; community).
- **No source found** on whether producer-side cleaning reads as maturity or dodging, on how game-themed projects are perceived, or on synthetic-data penalties.

**What it means here.** A visible account of every cleaning rule, with its test, its reason and how many rows it excluded, matches the one rubric found and the 81% testing demand. **Weak to moderate:** most hiring claims are single-source or vendor-written.

## 6. Where the sources disagree
- **Where deduplication belongs in dbt.** dbt's official staging page lists renaming, casting, basic computation and categorizing, and says nothing about deduplication or filtering (https://docs.getdbt.com/best-practices/how-we-structure/2-staging, as of 2026-09). A dbt developer blog says filtering is "ideally done as upstream as possible at a base or staging layer" (https://docs.getdbt.com/blog/how-we-remove-partial-duplicates, as of 2026-09), but it concerns partial duplicates. The intermediate page places changes of grain in intermediate. All three are dbt Labs publications, and the staging page's silence does not rebut the blog's direct guidance; the blog addresses partial duplicates, so whether event-ID deduplication belongs in staging, a base model or intermediate remains a judgment call to document.
- **Business events versus raw interactions.** Amplitude, Segment and Snowplow want producers to emit decisions; PostHog and Heap capture raw interactions and define actions later. Both are official vendor positions.
- **Whether reviewers read tests and commit history.** One community author says reviewers look for tests; another says they do not scrutinize tests or decision documents (https://dev.to/amailuk/the-github-portfolio-that-gets-you-hired-and-not-for-the-reasons-you-think-4776, undated). Both are single, unverified blogs.
- **Previews.** Industry practice allows dropping pure noise at the source when cost forces it; the postings research suggests keeping raw complete and cleaning visibly in dbt. The deciding fact, what sending previews costs the plugin per tick, is unmeasured.

## 7. Gaps
- No source on save reloads or abandoned timelines in analytics; sections 2.1 and 2.2 rest on analogues.
- The per-tick cost of sending action events, including previews, is unmeasured.
- No hiring source on producer-side cleaning, game-themed projects or synthetic data.
- Reddit and the dbt community forum were not reachable; much hiring content online is vendor search-engine marketing.
- Paywalled and not read: GDC Vault talks, the "Game Analytics" book (2013), and the text of Andrew Jones's "Driving Data Quality with Data Contracts".

## 8. Options for the ideation discussion
These are candidates, not decisions. Each issue lists who could own it; the discussion picks one per issue and checks that the whole set is consistent.

| Issue | Plugin (producer) could | dbt (data team) could | Open question |
|---|---|---|---|
| 2.1 Reloaded saves | Record lineage: on the `map.save` hook, mint a save ID, store it with the session ID and `seq` in park storage, and emit "save written"; on load, report the stored save ID (the roadmap's park-storage branch marker, made exact) | Build the timeline tree and keep the latest branch from each branch point, tagging or dropping abandoned branches | Does `map.save` fire before the file is written, including headless? Tag or drop abandoned branches? |
| 2.2 Run-on after a save | Nothing beyond 2.1's lineage | Treat the save as a branch point; mark the run-on as abandoned once a later session loads that save | Is 2.1's lineage enough, or does the harness also need to stop sooner? |
| 2.3 Duplicate deliveries | Keep minting `event_id`, reused on any resend | Remove repeats in the first layer, keyed on `event_id`, with a test and a count | Staging or a base model (dbt's official pages are silent)? |
| 2.4 One click, several events | Nothing, or debounce price edits (costs plugin state and time) | Collapse click runs into one decision in intermediate, keeping raw presses | Which time window, and how is it tested? |
| 2.5 Repeated confirmed actions | Stamp a shared action ID, or mark top-level versus nested actions | Derive a shared key from action, arguments and tick | Can the plugin tell echoes from separate actions? |
| 2.6 Previews and predictions | Drop them with a daily count, or label them and send them | Filter labelled rows in staging, reconciling to the plugin's count | Measure the per-tick cost first, and prove the flag with the pretest's positive control? |
| Showcase | — | A dbt model that counts rows kept and excluded by each rule, surfaced in the README next to the reconciliation tests | How much of this belongs on the README's first screen? |
