// The per-tick weather check: sends weather_change when the weather type differs from the last one it holds.

interface WeatherWatch {
    checkTick(): void;
}

// Created once in main(). The first read seeds the stored weather and sends nothing, so the first event is the
// first real change; a read that is not a string leaves the stored weather as it is. The envelope stamps the
// observing tick, so the payload carries no tick field of its own. One payload object serves the session: emit
// copies its fields into its own event.
function createWeatherWatch(emitter: Emitter, work: WorkQueue, timer: Timer): WeatherWatch {
    const payload: EventFields = {};
    let last: string | null = null;
    const seed = climate.current.weather;
    if (typeof seed === "string") {
        last = seed;
    }

    // Timed as the tick part weather, never as a work step, so worst_step_kind keeps meaning the longest work step.
    // The temperature and the upcoming weather are read only on a change.
    function checkTick(): void {
        const before = timer.tickMsSoFar();
        try {
            const current = climate.current;
            const weather = current.weather;
            if (typeof weather !== "string") {
                return;
            }
            if (last === null) {
                last = weather;
                return;
            }
            if (weather === last) {
                return;
            }
            const upcoming = climate.future.weather;
            payload.weather = weather;
            payload.previous_weather = last;
            payload.upcoming_weather = typeof upcoming === "string" ? upcoming : null;
            payload.temperature_c = jsonSafeInteger(current.temperature);
            emitter.emit("weather_change", payload);
            last = weather;
        } finally {
            work.noteTickPart("weather", before, timer.tickMsSoFar());
        }
    }

    return { checkTick: checkTick };
}
