// The one emit module: emit() is the only way to create an event and stamps every creation-time field;
// flush() stamps seq and event_id at hand-off to the socket. A line dropped from the queue therefore never
// uses a seq, so drops before hand-off leave no gap, and every drop is counted in lines_dropped_total. A gap
// in the landed data therefore means loss after hand-off; a partial send can lose a line's tail, which
// merges with the next line's head and so can lose the cut line and the next one. Each line keeps its
// creation order (from the counter main() creates) beside it, never inside the event, so the work queue can
// serve the oldest line or task first without the order being sent.

const SCHEMA_VERSION = 1;
const QUEUE_MAX_LINES = 5000;
// One flush hands off at most this many lines, so a backlog drains over several callbacks, not one tick.
const FLUSH_MAX_LINES = 10;

type EventFields = { [field: string]: number | string | boolean | null };

interface EmitCounters {
    lines_dropped_total: number;
    write_partial_total: number;
    write_error_total: number;
    queue_length: number;
}

interface Emitter {
    emit(eventType: string, payload: EventFields): void;
    flush(): void;
    handOffOne(): void;
    headOrder(): number | null;
    lastSeq(): number;
    counters(): EmitCounters;
    takeLinesQueuedMax(): number;
}

function createEmitter(parkId: string, sessionId: string, transport: Transport, nextOrder: () => number): Emitter {
    const queue: EventFields[] = [];
    const orders: number[] = [];
    let seq = 0;
    let dropped = 0;
    let writePartial = 0;
    let writeErrors = 0;
    let queuedMax = 0;
    const emitCounters: EmitCounters = {
        lines_dropped_total: 0, write_partial_total: 0, write_error_total: 0, queue_length: 0
    };

    function emit(eventType: string, payload: EventFields): void {
        const event: EventFields = {
            schema_version: SCHEMA_VERSION,
            event_type: eventType,
            plugin_version: PLUGIN_VERSION,
            park_id: parkId,
            session_id: sessionId,
            game_year: date.year,
            game_month: date.month,
            game_day: date.day,
            game_ticks_elapsed: date.ticksElapsed,
            emitted_at: new Date().toISOString()
        };
        for (const field in payload) {
            if (payload.hasOwnProperty(field)) {
                event[field] = payload[field];
            }
        }
        queue.push(event);
        orders.push(nextOrder());
        if (queue.length > QUEUE_MAX_LINES) {
            queue.shift();
            orders.shift();
            dropped += 1;
        }
        if (queue.length > queuedMax) {
            queuedMax = queue.length;
        }
    }

    // Hands the head line to the socket. Callers check that a line is queued and the socket is connected.
    function handOffOne(): void {
        const next = seq + 1;
        const event = queue[0];
        event.seq = next;
        event.event_id = sessionId + "-" + next;
        let partial: boolean;
        try {
            partial = transport.write(JSON.stringify(event) + "\n");
        } catch (err) {
            // Deliberate fallback: the line keeps its place at the head of the queue and its seq stays
            // unused; the failure is counted, and the reconnect interval replaces the socket.
            writeErrors += 1;
            transport.markDisconnected("write threw " + err);
            return;
        }
        seq = next;
        queue.shift();
        orders.shift();
        // In 0.5.5 write returns false when the whole line was sent and true when only part of it was
        // (ScSocket.hpp): the line is lost after hand-off, so it is counted, never resent.
        if (partial) {
            writePartial += 1;
        }
    }

    // A throw inside handOffOne() marks the socket disconnected, which ends the loop.
    function flush(): void {
        for (let handed = 0; handed < FLUSH_MAX_LINES && queue.length > 0 && transport.isConnected(); handed++) {
            handOffOne();
        }
    }

    function headOrder(): number | null {
        return orders.length > 0 ? orders[0] : null;
    }

    // The last seq handed off, 0 before the first hand-off; read-only, so seq stays this module's own.
    function lastSeq(): number {
        return seq;
    }

    // Refills one object, so reading the counters allocates nothing.
    function counters(): EmitCounters {
        emitCounters.lines_dropped_total = dropped;
        emitCounters.write_partial_total = writePartial;
        emitCounters.write_error_total = writeErrors;
        emitCounters.queue_length = queue.length;
        return emitCounters;
    }

    // The period's highest queue length, read when the plugin_stats row is built; the next period starts from
    // the length now.
    function takeLinesQueuedMax(): number {
        const max = queuedMax;
        queuedMax = queue.length;
        return max;
    }

    return {
        emit: emit, flush: flush, handOffOne: handOffOne, headOrder: headOrder, lastSeq: lastSeq, counters: counters,
        takeLinesQueuedMax: takeLinesQueuedMax
    };
}
