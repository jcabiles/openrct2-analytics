# ADR 0034: `weather_change` is staged later

- Date: 2026-10-17.
- Status: Accepted 2026-10-17 (ruled by the project owner, ride-statistics and weather capture slice).
- Supersedes in part: ADR 0022 (`docs/adr/0022-staging-every-event-type.md`), Decision 1 only. Every contracted event
  type except `plugin_stats` is still staged, with one exception added here: `weather_change`. The rest of ADR 0022
  stands unchanged.
- Roadmap line: "Deferred from this item" under the weather capture item in `docs/ai-dlc/roadmap/park-company.md`.

## Bottom line

The `weather_change` event type ships with its contract, landing path, converter support and plugin code, but without
a `stg_weather_change` staging model. The model is built later, as its own roadmap item.

## Context

ADR 0022 Decision 1 says every contracted event type except `plugin_stats` gets a `stg_<event_type>` model. The
ride-statistics and weather capture slice adds the 13th contract, `weather_change`, and must ship before Park 1's
first day, because weather changes cannot be recovered later. A staging model is rebuildable from the append-only raw
captures at any time (`CLAUDE.md`, "Never break" rule 2), so it does not have to come first.

## Decision

1. **`weather_change` has no staging model until the deferred roadmap item is built.** `stg_envelope` carries the
   type's deliveries meanwhile, with a second `repeat_delivery_payload_differs` entry so repeat deliveries whose
   payloads differ are still flagged as a warning.
2. **`docs/CONVENTIONS.md` records the exception** on the staging row (line 65) and in review item 13.

Gain: the slice ships before Park 1 without waiting for a model nobody reads yet. Cost: until the model exists, the
type has no unique or not_null tests and no first-received dedupe, so a repeat delivery of one `event_id` is not
removed downstream.

## Consequences

- The deferred model is a roadmap item; when it is built, this record is superseded and the exception in
  `docs/CONVENTIONS.md` is removed.
- No mart or metric may read `weather_change` before that model exists.
