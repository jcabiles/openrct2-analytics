# ADR 0011: save lineage is recorded in park storage

- Date: 2026-10-02
- Status: Accepted

## Bottom line

On `map.save`, the plugin stores the save ID, writing session ID, last
handed-off sequence floor, and waiting-line count in park storage, emits
`save_written`, and flushes. The landed event's own `seq` is the exact save
cut; when it does not land, the stored floor is the fallback. The committed
sample checks the chain: sessions 2 and 3 report the save ID and session of
their predecessor and a floor below that save event's `seq`
(`tests/test_sample.py`).

## Context

ADR 0006 assigns facts that only the plugin knows to the plugin, including the
save that a session loaded. ADR 0007 stamps `seq` at socket hand-off, not when
the save hook runs. The hook therefore cannot know its own final `seq` while it
is writing the save.

## Decision

| Decision | Choice |
|---|---|
| Stored keys | Store `save_id`, `save_session_id`, `save_seq_floor`, and `save_lines_waiting` in park storage on every save. |
| Delivery | Emit `save_written` with the save ID, then call the emitter's bounded flush inside the save hook. |
| Exact cut | When `save_written` lands, use its own hand-off `seq`: all lower sequences were created before the save. |
| Fallback cut | When it does not land, use the stored floor and waiting count. The event would have taken floor plus waiting lines plus one unless queued lines ahead were dropped; the plugin counts those drops. |
| Load report | Read the four keys before `session_start` and report them as optional loaded-save fields. |

## Rejected alternatives

- **Assign a sequence in the save hook.** It would break ADR 0007's rule that
  only a handed-off line consumes a sequence.
- **Store only the save ID.** A later session could identify the save but could
  not locate its parent session or its cut.
- **Wait for a later reconnect to flush.** A save followed by quit or a park
  load could leave its lineage event queued when a short, connected flush could
  hand it off.

## Consequences

- A save whose event lands has an exact cut; a lost event has a useful but not
  exact fallback when earlier queued lines were dropped.
- Parks not saved with this plugin version report null loaded-save fields.
- The three-session sample provides an end-to-end lineage check, but it does
  not establish lineage behavior for every save mechanism.

## How we would know this is wrong

- A saved park does not retain values written inside `map.save`.
- The sample or a future chained run cannot connect a loaded session to its
  predecessor's `save_written` event.
- A dropped-line case shows that the stored fallback is interpreted as exact.
