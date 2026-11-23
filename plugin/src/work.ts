// The work queue: spreads capture work across game ticks. The tick hook runs steps, each either the hand-off
// of one queued line or one item of a task, always the oldest by creation order, until the plugin's time in
// the tick reaches WORK_ALLOWANCE_MS. The allowance covers all plugin time in the tick, so time another
// callback already spent there counts. A step is never cut short and at least one step runs per tick when
// any is pending, so a tick overshoots the allowance by at most one step.
//
// Tasks are objects created once in main() and kept for the session. A day-scoped task gets its items from
// startDay(), called from the day callback; items it has not run by the next day are dropped and counted. A
// continuous task is fed between days, has an order per item, and is never skipped. From the day callback's
// tick until the day's ride items are done, guest-kind steps are held; they keep their order and run afterwards.
//
// The queue also splits the plugin's time by step kind: each step adds its duration to the open tick's sum
// for its kind, and the timer (timing.ts) reports when a tick opens, when it folds, and when a folded tick is
// the period's new worst, whose sums the queue keeps. Nothing here allocates per step, per tick or per day.

const WORK_ALLOWANCE_MS = 4;

type StepKind =
    | "line"
    | "ride_list"
    | "ride"
    | "guest_list"
    | "guest"
    | "arrival"
    | "boarder"
    | "poll"
    | "boarder_read"
    | "guest_fields"
    | "action";

// The order worst_tick_kind_ms lists its parts in: the step kinds, weather and action hooks, day_callback, then
// other. Tick parts are timed with noteTickPart and never set worst_step_kind.
const TICK_PARTS: ReadonlyArray<string> = [
    "line", "ride_list", "ride", "guest_list", "guest", "arrival", "boarder", "poll", "boarder_read", "guest_fields",
    "action", "weather", "action_query", "action_execute", "day_callback"
];
const DAY_CALLBACK_PART = TICK_PARTS.length - 1;
// A part that rounds to 0.000 ms is left out of worst_tick_kind_ms.
const SMALLEST_PART_MS = 0.0005;

interface WorkTask {
    pending(): number;
    // The creation order of the oldest pending item.
    headOrder(): number;
    headKind(): StepKind;
    // Advances past the item before running it, so an item that throws is never run again.
    runOne(): void;
}

interface DayTask extends WorkTask {
    // Starts the day's items at the given creation order and returns how many unfinished items it dropped.
    startDay(order: number): number;
}

interface WorkCounters {
    work_units_total: number;
    work_items_skipped_total: number;
    work_queue_length: number;
    work_items_failed_total: number;
    worst_step_ms: number;
    worst_step_kind: StepKind | null;
    worst_tick_kind_ms: string;
    worst_day_start_tick_ms: number;
    guest_fields_ms_total: number;
    action_query_ms_total: number;
    action_execute_ms_total: number;
    continuous_items_pending: number;
}

interface WorkQueue extends TickObserver {
    addDayTask(task: DayTask): void;
    addContinuousTask(task: WorkTask): void;
    queueDay(): void;
    runTick(): void;
    drainTask(task: WorkTask): void;
    noteStep(kind: StepKind, msBefore: number, msAfter: number): void;
    noteTickPart(part: "weather" | "action_query" | "action_execute", msBefore: number, msAfter: number): void;
    noteFailure(): void;
    noteDayCallback(msBefore: number, msAfter: number): void;
    closePeriod(): WorkCounters;
}

// The one creation-order counter: it stamps every queued line and every task item.
function createOrderCounter(): () => number {
    let order = 0;
    return function (): number {
        order += 1;
        return order;
    };
}

function isGuestKind(kind: StepKind): boolean {
    return kind === "guest_list" || kind === "guest" || kind === "arrival" || kind === "boarder";
}

function isRideKind(kind: StepKind): boolean {
    return kind === "ride_list" || kind === "ride";
}

function pendingIn(tasks: WorkTask[]): number {
    let pending = 0;
    for (let i = 0; i < tasks.length; i++) {
        pending += tasks[i].pending();
    }
    return pending;
}

function zeroFill(values: number[]): void {
    for (let i = 0; i < values.length; i++) {
        values[i] = 0;
    }
}

function createWorkQueue(timer: Timer, emitter: Emitter, transport: Transport, nextOrder: () => number): WorkQueue {
    const tasks: WorkTask[] = [];
    const dayTasks: DayTask[] = [];
    const continuousTasks: WorkTask[] = [];
    // The open tick's time per part, and the copy kept for the period's worst tick.
    const tickSums: number[] = [];
    const worstTickSums: number[] = [];
    for (let i = 0; i < TICK_PARTS.length; i++) {
        tickSums.push(0);
        worstTickSums.push(0);
    }
    let tickSumsUsed = false;
    let worstTickMs = 0;
    let unitsTotal = 0;
    let skippedTotal = 0;
    let failedTotal = 0;
    let worstStepMs = 0;
    let worstStepKind: StepKind | null = null;
    let guestFieldsMs = 0;
    let actionQueryMs = 0;
    let actionExecuteMs = 0;
    let worstDayStartMs = 0;
    // Guest steps are held from the day callback's tick until a tick starts with no ride item pending.
    let holding = false;
    // The game day the queue last saw. The engine runs the tick hook before the day callback on a tick whose
    // day changed (docs/FINDINGS.md), so the tick hook spots the new day and holds guest steps from then.
    let seenDay = date.day;
    // The open tick is a day-start tick: the one the day changed on, or a later one that started with ride items
    // pending. Guest steps never run on one, so the day-start measure times only the day-start work.
    let dayStartTick = false;
    // The head order of the task oldestTask() last chose.
    let chosenOrder = 0;
    const counters: WorkCounters = {
        work_units_total: 0,
        work_items_skipped_total: 0,
        work_queue_length: 0,
        work_items_failed_total: 0,
        worst_step_ms: 0,
        worst_step_kind: null,
        worst_tick_kind_ms: "",
        worst_day_start_tick_ms: 0,
        guest_fields_ms_total: 0,
        action_query_ms_total: 0,
        action_execute_ms_total: 0,
        continuous_items_pending: 0
    };

    function addDayTask(task: DayTask): void {
        tasks.push(task);
        dayTasks.push(task);
    }

    function addContinuousTask(task: WorkTask): void {
        tasks.push(task);
        continuousTasks.push(task);
    }

    // Each day-scoped task takes its own order, in the order the tasks were added.
    function queueDay(): void {
        for (let i = 0; i < dayTasks.length; i++) {
            skippedTotal += dayTasks[i].startDay(nextOrder());
        }
        markDayStart();
    }

    function markDayStart(): void {
        seenDay = date.day;
        holding = true;
        dayStartTick = true;
    }

    function rideWorkPending(): boolean {
        for (let i = 0; i < dayTasks.length; i++) {
            if (dayTasks[i].pending() > 0 && isRideKind(dayTasks[i].headKind())) {
                return true;
            }
        }
        return false;
    }

    // The pending task with the oldest head item, passing over guest kinds while they are held; null if none.
    function oldestTask(): WorkTask | null {
        let oldest: WorkTask | null = null;
        for (let i = 0; i < tasks.length; i++) {
            const task = tasks[i];
            if (task.pending() > 0 && !(holding && isGuestKind(task.headKind()))) {
                const order = task.headOrder();
                if (oldest === null || order < chosenOrder) {
                    oldest = task;
                    chosenOrder = order;
                }
            }
        }
        return oldest;
    }

    function addToTick(part: number, ms: number): void {
        tickSums[part] += ms;
        tickSumsUsed = true;
    }

    function noteTickPart(part: "weather" | "action_query" | "action_execute", msBefore: number, msAfter: number): void {
        const ms = msAfter - msBefore;
        addToTick(TICK_PARTS.indexOf(part), ms);
        if (part === "action_query") {
            actionQueryMs += ms;
        } else if (part === "action_execute") {
            actionExecuteMs += ms;
        }
    }

    function noteStep(kind: StepKind, msBefore: number, msAfter: number): void {
        const ms = msAfter - msBefore;
        addToTick(TICK_PARTS.indexOf(kind), ms);
        if (worstStepKind === null || ms > worstStepMs) {
            worstStepMs = ms;
            worstStepKind = kind;
        }
        if (kind === "guest_fields") {
            guestFieldsMs += ms;
        }
    }

    function noteFailure(): void {
        failedTotal += 1;
    }

    function noteDayCallback(msBefore: number, msAfter: number): void {
        addToTick(DAY_CALLBACK_PART, msAfter - msBefore);
    }

    // Runs one step (a line hand-off when task is null) and returns the plugin's time in the tick after it.
    // try/finally without catch: a step that throws is counted, its time still counts, and the error still
    // reaches the game.
    function runStep(task: WorkTask | null, msBefore: number): number {
        const kind: StepKind = task === null ? "line" : task.headKind();
        let finished = false;
        let msAfter = msBefore;
        try {
            if (task === null) {
                emitter.handOffOne();
            } else {
                task.runOne();
            }
            finished = true;
        } finally {
            msAfter = timer.tickMsSoFar();
            noteStep(kind, msBefore, msAfter);
            if (task !== null) {
                unitsTotal += 1;
            }
            if (!finished) {
                failedTotal += 1;
            }
        }
        return msAfter;
    }

    // A line step needs a connected socket; while disconnected, task items still run and lines wait for the
    // reconnect interval's flush. A hand-off that throws marks the socket disconnected, ending line steps.
    function runTick(): void {
        if (date.day !== seenDay) {
            markDayStart();
        } else if (holding && !dayStartTick) {
            if (rideWorkPending()) {
                dayStartTick = true;
            } else {
                holding = false;
            }
        }
        let msSoFar = timer.tickMsSoFar();
        let steps = 0;
        while (steps === 0 || msSoFar < WORK_ALLOWANCE_MS) {
            const lineOrder = transport.isConnected() ? emitter.headOrder() : null;
            const task = oldestTask();
            if (lineOrder !== null && (task === null || lineOrder < chosenOrder)) {
                msSoFar = runStep(null, msSoFar);
            } else if (task !== null) {
                msSoFar = runStep(task, msSoFar);
            } else {
                return;
            }
            steps += 1;
        }
    }

    // Runs every pending item of one task now, with no allowance, each timed as a step like a tick's steps.
    function drainTask(task: WorkTask): void {
        while (task.pending() > 0) {
            runStep(task, timer.tickMsSoFar());
        }
    }

    function openTick(): void {
        if (tickSumsUsed) {
            zeroFill(tickSums);
            tickSumsUsed = false;
        }
        dayStartTick = false;
    }

    // The whole tick, nothing subtracted: the day-start measure in docs/adr/0018-guest-capture.md.
    function foldTick(ms: number): void {
        if (dayStartTick && ms > worstDayStartMs) {
            worstDayStartMs = ms;
        }
    }

    function keepTickRecord(ms: number): void {
        for (let i = 0; i < tickSums.length; i++) {
            worstTickSums[i] = tickSums[i];
        }
        worstTickMs = ms;
    }

    function appendPart(text: string, name: string, ms: number): string {
        if (ms < SMALLEST_PART_MS) {
            return text;
        }
        return (text === "" ? "" : text + "|") + name + ":" + ms.toFixed(3);
    }

    // name:ms pairs joined by |; other is the rest of the worst tick's plugin time (other callbacks and time
    // between steps), so the parts sum to worst_tick_ms.
    function worstTickKindMs(): string {
        let text = "";
        let rest = worstTickMs;
        for (let i = 0; i < worstTickSums.length; i++) {
            rest -= worstTickSums[i];
            text = appendPart(text, TICK_PARTS[i], worstTickSums[i]);
        }
        return appendPart(text, "other", rest);
    }

    // Called once a period, when the plugin_stats row is built: fills the one counters object, then starts
    // the next period's values. The timer's closePeriod() has already run, so no tick folds in between.
    function closePeriod(): WorkCounters {
        counters.work_units_total = unitsTotal;
        counters.work_items_skipped_total = skippedTotal;
        counters.work_queue_length = pendingIn(dayTasks);
        counters.work_items_failed_total = failedTotal;
        counters.worst_step_ms = worstStepMs;
        counters.worst_step_kind = worstStepKind;
        counters.worst_tick_kind_ms = worstTickKindMs();
        counters.worst_day_start_tick_ms = worstDayStartMs;
        counters.guest_fields_ms_total = guestFieldsMs;
        counters.action_query_ms_total = actionQueryMs;
        counters.action_execute_ms_total = actionExecuteMs;
        counters.continuous_items_pending = pendingIn(continuousTasks);
        worstStepMs = 0;
        worstStepKind = null;
        guestFieldsMs = 0;
        actionQueryMs = 0;
        actionExecuteMs = 0;
        worstDayStartMs = 0;
        zeroFill(worstTickSums);
        worstTickMs = 0;
        return counters;
    }

    return {
        addDayTask: addDayTask,
        addContinuousTask: addContinuousTask,
        queueDay: queueDay,
        runTick: runTick,
        drainTask: drainTask,
        noteStep: noteStep,
        noteTickPart: noteTickPart,
        noteFailure: noteFailure,
        noteDayCallback: noteDayCallback,
        openTick: openTick,
        foldTick: foldTick,
        keepTickRecord: keepTickRecord,
        closePeriod: closePeriod
    };
}
