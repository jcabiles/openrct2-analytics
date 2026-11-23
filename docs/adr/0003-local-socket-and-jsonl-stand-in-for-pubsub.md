# ADR 0003: Local socket and JSONL stand in for Pub/Sub

- Date: 2026-09-27
- Status: Accepted

## Context

OpenRCT2 plugins can only open localhost sockets; there is no path to a
cloud message queue from inside the game process. The planned pipeline
still needs an ordered, replayable event stream and a landing format that
downstream steps (Parquet split, contract checks, dbt) can read.

## Decision

The plugin streams events over a localhost TCP socket to a Python listener,
which appends each event as one line of JSON to a dated file. This needs no
cloud account and no server process beyond the listener already running on
the same machine.

The dated JSONL files play the same role a Pub/Sub topic would:

| Envelope field / concept | Pub/Sub equivalent |
|---|---|
| `session_id` | ordering key |
| the event payload | message body |
| a dated JSONL file | a landing partition |

## Consequences

- Replaying a session means replaying its dated file in order; nothing else
  tracks ordering.
- Moving to a real Pub/Sub service later means swapping the listener's
  write side only — the plugin's socket output and the envelope shape do
  not need to change.
- The listener is a single point of loss: if it is not running, the plugin
  must count and report dropped events rather than silently discarding them
  (see `.claude/rules/plugin.md`).
