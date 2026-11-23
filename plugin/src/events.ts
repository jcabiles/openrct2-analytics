// Event payloads other than the monthly statement (finance.ts) and the ride snapshot (rides.ts). Game objects
// are native bindings, so each field is read explicitly.

interface DayPayloads {
    parkSnapshot(): EventFields;
    pluginStats(period: TimingPeriod, emitter: Emitter, transport: Transport, finance: FinanceReader,
        work: WorkQueue, guests: GuestTracker, boardings: BoardingPoll, actions: ActionRecorder): EventFields;
}

// The day callback's payloads, created once in main(): each builder refills its one payload object, writing
// every field, so a day allocates no payload. Safe because emitter.emit copies the fields into its own event.
function createDayPayloads(): DayPayloads {
    const snapshot: EventFields = {};
    const stats: EventFields = {};

    // Read in the interval.day callback, so it describes the park at the start of that game day. Money stays
    // in the game's tenths of a dollar; staging converts it once. The engine stores temperature in degrees
    // Celsius and converts only for display (unverified against the real game).
    function parkSnapshot(): EventFields {
        snapshot.cash_tenths = park.cash;
        snapshot.guests_in_park = park.guests;
        snapshot.park_rating = park.rating;
        snapshot.total_admissions = park.totalAdmissions;
        snapshot.weather = climate.current.weather;
        snapshot.temperature_c = climate.current.temperature;
        return snapshot;
    }

    // Timing covers the period since the previous day callback; the counters are session totals, so a lost
    // plugin_stats line does not lose its counts. Built before the day's work is queued, so work_queue_length
    // describes the previous day's work. Building it closes the work queue's and the emitter's periods.
    function pluginStats(
        period: TimingPeriod,
        emitter: Emitter,
        transport: Transport,
        finance: FinanceReader,
        work: WorkQueue,
        guests: GuestTracker,
        boardings: BoardingPoll,
        actions: ActionRecorder
    ): EventFields {
        const counters = emitter.counters();
        const workCounters = work.closePeriod();
        stats.period_start_ticks = period.period_start_ticks;
        stats.period_end_ticks = period.period_end_ticks;
        stats.period_ticks = period.period_ticks;
        stats.work_ms_total = period.work_ms_total;
        stats.worst_tick_ms = period.worst_tick_ms;
        stats.worst_tick_at_ticks = period.worst_tick_at_ticks;
        stats.callbacks = period.callbacks;
        stats.warmup = period.warmup;
        stats.clock = period.clock;
        stats.game_speed = period.game_speed;
        stats.lines_dropped_total = counters.lines_dropped_total;
        stats.write_partial_total = counters.write_partial_total;
        stats.write_error_total = counters.write_error_total;
        stats.connect_attempts_total = transport.connectAttempts();
        stats.queue_length = counters.queue_length;
        stats.lines_queued_max = emitter.takeLinesQueuedMax();
        stats.finance_months_unread_total = finance.unreadTotal();
        stats.work_units_total = workCounters.work_units_total;
        stats.work_items_skipped_total = workCounters.work_items_skipped_total;
        stats.work_queue_length = workCounters.work_queue_length;
        stats.work_items_failed_total = workCounters.work_items_failed_total;
        stats.worst_step_ms = workCounters.worst_step_ms;
        stats.worst_step_kind = workCounters.worst_step_kind;
        stats.worst_tick_kind_ms = workCounters.worst_tick_kind_ms;
        stats.worst_day_start_tick_ms = workCounters.worst_day_start_tick_ms;
        stats.guest_fields_ms_total = workCounters.guest_fields_ms_total;
        stats.action_query_ms_total = workCounters.action_query_ms_total;
        stats.action_execute_ms_total = workCounters.action_execute_ms_total;
        const actionTotals = actions.totals();
        stats.game_actions_sent_preview_total = actionTotals.game_actions_sent_preview_total;
        stats.game_actions_sent_prediction_total = actionTotals.game_actions_sent_prediction_total;
        stats.game_actions_sent_confirmed_total = actionTotals.game_actions_sent_confirmed_total;
        stats.game_actions_dropped_preview_total = actionTotals.game_actions_dropped_preview_total;
        stats.game_actions_dropped_prediction_total = actionTotals.game_actions_dropped_prediction_total;
        stats.game_actions_dropped_confirmed_total = actionTotals.game_actions_dropped_confirmed_total;
        stats.game_actions_skipped_preview_total = actionTotals.game_actions_skipped_preview_total;
        stats.game_actions_skipped_prediction_total = actionTotals.game_actions_skipped_prediction_total;
        stats.game_actions_skipped_confirmed_total = actionTotals.game_actions_skipped_confirmed_total;
        stats.game_actions_skipped_unknown_total = actionTotals.game_actions_skipped_unknown_total;
        stats.game_actions_skipped_cheat_total = actionTotals.game_actions_skipped_cheat_total;
        stats.continuous_items_pending = workCounters.continuous_items_pending;
        stats.guests_known = guests.known();
        stats.guests_known_in_park = guests.knownInPark();
        stats.arrivals_recorded_total = guests.arrivalsRecorded();
        stats.boarding_polls_total = boardings.pollsCompleted();
        stats.boarders_queued_total = boardings.boardersQueued();
        return stats;
    }

    return { parkSnapshot: parkSnapshot, pluginStats: pluginStats };
}

interface SavePayloads {
    saveWritten(saveId: string): EventFields;
}

// The save callback's payload, created once in main() and refilled on each save, so a save allocates no payload.
// Safe because emitter.emit copies the fields into its own event.
function createSavePayloads(): SavePayloads {
    const written: EventFields = {};

    function saveWritten(saveId: string): EventFields {
        written.save_id = saveId;
        return written;
    }

    return { saveWritten: saveWritten };
}

// Read once in main(), so it describes the session's start. The game version is not readable through the
// 0.5.5 plugin API, so the plugin API level stands in for it. scenario.filename is never sent: it can hold a
// machine path. loadedSave carries the save keys the loaded park holds (identity.ts).
function buildSessionStart(loadedSave: LoadedSave): EventFields {
    return {
        api_version: context.apiVersion,
        park_name: park.name,
        scenario_name: scenario.name,
        // The type definitions say ui is absent when the game runs with no window.
        headless: typeof ui === "undefined",
        game_speed: context.gameSpeed,
        climate: climate.type,
        loaded_save_id: loadedSave.loaded_save_id,
        loaded_save_session_id: loadedSave.loaded_save_session_id,
        loaded_save_seq_floor: loadedSave.loaded_save_seq_floor,
        loaded_save_lines_waiting: loadedSave.loaded_save_lines_waiting
    };
}
