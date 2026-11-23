// Registers the plugin and wires its events: the session start, which reports the save keys the loaded park
// carries; the daily stats, park snapshot and monthly statement, sent directly from the day callback; the daily
// ride snapshots and guest checks, run by the tick hook through the work queue; guest arrivals, recorded by the
// guest.generation hook and run through the same queue; boardings, found by the seat poll the tick hook runs
// before the queue's steps and sent through the same queue; weather_change, from the weather check the tick
// hook runs first; game actions, copied into a buffer by the action.query and action.execute hooks and sent
// through the same queue; and save_written, from the save hook, which also writes the save keys into park storage so the
// saved file carries them. All mutable state is created inside
// main():
// OpenRCT2 0.5.5 frees a local plugin's script context on every park load and evaluates the file again, and
// keeping nothing mutable at file scope makes a restart start clean whichever way it happens.
//
// Licence is provisional (MIT) until this project's public release.

// Also sent in every event as plugin_version.
const PLUGIN_VERSION = "0.9.0";
const RECONNECT_INTERVAL_MS = 5000;

function main(): void {
    // Title-screen and editor parks never get an ID or send anything.
    if (context.mode !== "normal") {
        return;
    }
    const timer = createTimer();
    timer.timed(function (): void {
        const parkId = readOrMintParkId();
        const transport = createTransport(timer.timed);
        const nextOrder = createOrderCounter();
        const sessionId = mintSessionId();
        const emitter = createEmitter(parkId, sessionId, transport, nextOrder);
        // Queued first, so it takes seq 1 unless the queue overflows before the first hand-off.
        emitter.emit("session_start", buildSessionStart(readLoadedSave()));
        const guests = createGuestTracker(emitter, nextOrder);
        const finance = createFinanceReader();
        const dayPayloads = createDayPayloads();
        const savePayloads = createSavePayloads();
        const work = createWorkQueue(timer, emitter, transport, nextOrder);
        // Added after the ride task, so each day's guest steps take later orders than its ride items.
        work.addDayTask(createRideTask(emitter));
        work.addDayTask(guests.dayTask);
        work.addContinuousTask(guests.arrivalTask);
        const boardings = createBoardingPoll(emitter, timer, work, guests, nextOrder);
        work.addContinuousTask(boardings.boarderTask);
        const actions = createActionRecorder(emitter, nextOrder);
        work.addContinuousTask(actions.task);
        // Seeds its stored weather from the first read, so the read belongs inside this timed callback.
        const weather = createWeatherWatch(emitter, work, timer);
        timer.setTickObserver(work);

        // Work items run only in the tick hook, so nothing falls between the day's own events. The callback's
        // own time is reported to the queue as day_callback, also when the callback throws.
        function onDay(): void {
            const msBefore = timer.tickMsSoFar();
            try {
                const period = timer.closePeriod();
                const stats = dayPayloads.pluginStats(period, emitter, transport, finance, work, guests, boardings, actions);
                emitter.emit("plugin_stats", stats);
                emitter.emit("park_snapshot", dayPayloads.parkSnapshot());
                const statement = finance.statementForToday();
                if (statement !== null) {
                    emitter.emit("finance_month", statement);
                }
                work.queueDay();
                emitter.flush();
            } finally {
                work.noteDayCallback(msBefore, timer.tickMsSoFar());
            }
        }

        // Buffered actions are sent first, so an action taken before the save takes a lower seq than save_written
        // and the waiting count below includes it. The floor and the waiting count are read before save_written
        // is queued, so when that event is lost it would have taken seq floor + waiting + 1, unless the queue
        // dropped lines ahead of it. The flush lets a save made just before a quit or a load still hand off its
        // event when the queue is short.
        function onSave(): void {
            work.drainTask(actions.task);
            const saveId = mintSaveId();
            writeSaveKeys(saveId, sessionId, emitter.lastSeq(), emitter.counters().queue_length);
            emitter.emit("save_written", savePayloads.saveWritten(saveId));
            emitter.flush();
        }

        // The weather check and the seat poll run inside the tick's timed callback, so their time counts toward
        // the queue's allowance. try/finally without catch: a check or poll that throws still lets the later
        // steps run, and its error still reaches the game.
        function onTick(): void {
            try {
                weather.checkTick();
            } finally {
                try {
                    boardings.pollIfDue();
                } finally {
                    work.runTick();
                }
            }
        }

        // The guest.generation hook's ID, passed through a variable so the hook builds no function per arrival.
        let generatedId = 0;
        function onGeneration(): void {
            guests.recordArrival(generatedId);
        }

        // The action hooks' values pass through variables, so the hooks build no function per call. The copy's time
        // is a tick part, and counts toward the queue's allowance.
        let queryEvent: GameActionEventArgs | null = null;
        function onActionQuery(): void {
            const msBefore = timer.tickMsSoFar();
            try {
                actions.recordQuery(queryEvent as GameActionEventArgs);
            } finally {
                queryEvent = null;
                work.noteTickPart("action_query", msBefore, timer.tickMsSoFar());
            }
        }
        let executeEvent: GameActionEventArgs | null = null;
        function onActionExecute(): void {
            const msBefore = timer.tickMsSoFar();
            try {
                actions.recordExecute(executeEvent as GameActionEventArgs);
            } finally {
                executeEvent = null;
                work.noteTickPart("action_execute", msBefore, timer.tickMsSoFar());
            }
        }

        function onInterval(): void {
            if (transport.isConnected()) {
                emitter.flush();
            } else {
                transport.connect();
            }
        }

        transport.connect();
        context.subscribe("interval.day", function (): void { timer.timed(onDay); });
        context.subscribe("interval.tick", function (): void { timer.timed(onTick); });
        context.subscribe("map.save", function (): void { timer.timed(onSave); });
        context.subscribe("guest.generation", function (e: GuestGenerationArgs): void {
            generatedId = e.id;
            timer.timed(onGeneration);
        });
        context.subscribe("action.query", function (e: GameActionEventArgs): void {
            queryEvent = e;
            timer.timed(onActionQuery);
        });
        context.subscribe("action.execute", function (e: GameActionEventArgs): void {
            executeEvent = e;
            timer.timed(onActionExecute);
        });
        context.setInterval(function (): void { timer.timed(onInterval); }, RECONNECT_INTERVAL_MS);
    });
}

// The registered name is frozen: park storage is keyed by it, so renaming orphans every stored park ID.
registerPlugin({
    name: "openrct2-analytics",
    version: PLUGIN_VERSION,
    authors: ["John Cabiles"],
    type: "local",
    licence: "MIT",
    targetApiVersion: 122,
    main: main
});
