// Self-timing, the method of docs/FINDINGS.md ("Capture schedule re-test"). Every plugin callback runs
// through timed(), which adds its wall-clock duration to the bucket of the game tick it started on. A bucket
// folds into the open period when a later callback starts on a later tick, or on the same tick more than
// PAUSED_BUCKET_MS after the bucket opened: while the game is paused, date.ticksElapsed stands still but the
// 5-second reconnect interval keeps firing, and those attempts must not add up to one "tick". Ticks with no
// callback add nothing, so they count as 0 ms within period_ticks. The tick observer (the work queue) hears
// when a bucket opens, when it folds, and when a folded bucket becomes the period's worst tick.

const PAUSED_BUCKET_MS = 100;

interface TimingPeriod {
    period_start_ticks: number;
    period_end_ticks: number;
    period_ticks: number;
    work_ms_total: number;
    worst_tick_ms: number;
    worst_tick_at_ticks: number;
    callbacks: number;
    warmup: boolean;
    clock: string;
    game_speed: number;
}

interface TickObserver {
    openTick(): void;
    foldTick(ms: number): void;
    keepTickRecord(ms: number): void;
}

interface Timer {
    timed(fn: () => void): void;
    tickMsSoFar(): number;
    closePeriod(): TimingPeriod;
    setTickObserver(observer: TickObserver): void;
}

function createTimer(): Timer {
    const perf = typeof performance !== "undefined" && typeof performance.now === "function" ? performance : null;
    const clock = perf !== null ? "performance" : "date";
    const now = perf !== null
        ? function (): number { return perf.now(); }
        : function (): number { return Date.now(); };

    let bucketTick = -1;
    let bucketOpenedAt = 0;
    let bucketMs = 0;
    let bucketCallbacks = 0;
    // The start of the innermost running timed() callback; null when none is running.
    let runningSince: number | null = null;

    // The first period starts when the timer is created in main(), so it includes startup.
    let periodStart = date.ticksElapsed;
    let workMs = 0;
    // A period with no timed work reports 0 ms at its start tick.
    let worstMs = 0;
    let worstAt = periodStart;
    let callbacks = 0;
    let warmup = true;
    // Set once main() has created the work queue, which needs the timer; the startup bucket opens before it.
    let observer: TickObserver | null = null;
    // The one period object, refilled by each closePeriod().
    const closed: TimingPeriod = {
        period_start_ticks: 0,
        period_end_ticks: 0,
        period_ticks: 0,
        work_ms_total: 0,
        worst_tick_ms: 0,
        worst_tick_at_ticks: 0,
        callbacks: 0,
        warmup: true,
        clock: clock,
        game_speed: 0
    };

    function foldBucket(): void {
        if (bucketTick === -1) {
            return;
        }
        workMs += bucketMs;
        callbacks += bucketCallbacks;
        if (observer !== null) {
            observer.foldTick(bucketMs);
        }
        if (bucketMs > worstMs) {
            worstMs = bucketMs;
            worstAt = bucketTick;
            if (observer !== null) {
                observer.keepTickRecord(bucketMs);
            }
        }
    }

    function timed(fn: () => void): void {
        const t0 = now();
        const tick = date.ticksElapsed;
        if (tick !== bucketTick || t0 - bucketOpenedAt > PAUSED_BUCKET_MS) {
            foldBucket();
            bucketTick = tick;
            bucketOpenedAt = t0;
            bucketMs = 0;
            bucketCallbacks = 0;
            if (observer !== null) {
                observer.openTick();
            }
        }
        bucketCallbacks += 1;
        // Restored on exit, so a nested call leaves the outer callback's start in place.
        const outerSince = runningSince;
        runningSince = t0;
        // try/finally without catch: an error still reaches the game, and its time still counts.
        try {
            fn();
        } finally {
            bucketMs += now() - t0;
            runningSince = outerSince;
        }
    }

    // The plugin's time so far in the current tick: the open bucket, when it belongs to this tick, plus the
    // running callback's time so far.
    function tickMsSoFar(): number {
        const bucketSoFar = bucketTick === date.ticksElapsed ? bucketMs : 0;
        return runningSince === null ? bucketSoFar : bucketSoFar + now() - runningSince;
    }

    // Called from inside the day callback. The current tick's bucket stays open, so the period ends before
    // the day callback, and the day callback's own duration lands in the next period.
    function closePeriod(): TimingPeriod {
        const end = date.ticksElapsed;
        closed.period_start_ticks = periodStart;
        closed.period_end_ticks = end;
        closed.period_ticks = end - periodStart;
        closed.work_ms_total = workMs;
        closed.worst_tick_ms = worstMs;
        closed.worst_tick_at_ticks = worstAt;
        closed.callbacks = callbacks;
        closed.warmup = warmup;
        closed.game_speed = context.gameSpeed;
        periodStart = end;
        workMs = 0;
        worstMs = 0;
        worstAt = end;
        callbacks = 0;
        warmup = false;
        return closed;
    }

    function setTickObserver(tickObserver: TickObserver): void {
        observer = tickObserver;
    }

    return { timed: timed, tickMsSoFar: tickMsSoFar, closePeriod: closePeriod, setTickObserver: setTickObserver };
}
