// The daily ride_snapshot, one per ride, stall and facility. Game objects are native bindings and each read
// can build fresh objects (every `stations` read builds 255 slots), so each field is read once per ride.
// Money stays in the game's tenths of a dollar, and the game's placeholders (-1 for unrated, 1,275 for
// unmeasured satisfaction, the "no item" code) are sent as the game holds them. No staging model reads these
// events yet; the unit conversion and the placeholder-to-null step are deferred to the dbt design session.

// The day's ride task, created once in main(): its first item reads the ID list into a reusable array; each
// later item snapshots one ride into the one reusable payload. The array, payload and cursor are kept across
// days, so a day allocates nothing for the task itself.
function createRideTask(emitter: Emitter): DayTask {
    const ids: number[] = [];
    const stats = createRideStats();
    const buildSnapshot = createRideSnapshotBuilder(stats);
    let idCount = 0;
    let cursor = 0;
    let listPending = false;
    let categoriesLoaded = false;
    let order = 0;

    function pending(): number {
        return listPending ? 1 : idCount - cursor;
    }

    function headOrder(): number {
        return order;
    }

    function headKind(): StepKind {
        return listPending ? "ride_list" : "ride";
    }

    // A ride demolished since the list was read emits nothing: it no longer exists, so no snapshot is due.
    function runOne(): void {
        if (listPending) {
            listPending = false;
            // Once per session: play does not change the research lists' categories, and a failed read is retried.
            // It comes before the ID list so a throw leaves idCount at 0: no snapshot goes out with a partial table.
            if (!categoriesLoaded) {
                stats.loadCategories();
                categoriesLoaded = true;
            }
            idCount = readRideIds(ids);
            return;
        }
        cursor += 1;
        // The type definitions omit it, but 0.5.5 returns null for a ride ID no longer in use.
        const ride = map.getRide(ids[cursor - 1]) as Ride | null;
        if (ride !== null) {
            emitter.emit("ride_snapshot", buildSnapshot(ride));
        }
    }

    function startDay(dayOrder: number): number {
        const dropped = pending();
        listPending = true;
        idCount = 0;
        cursor = 0;
        order = dayOrder;
        return dropped;
    }

    return { pending: pending, headOrder: headOrder, headKind: headKind, runOne: runOne, startDay: startDay };
}

// Fills ids from index 0 with the current rides' IDs and returns how many it wrote.
function readRideIds(ids: number[]): number {
    const rides = map.rides;
    for (let i = 0; i < rides.length; i++) {
        ids[i] = rides[i].id;
    }
    return rides.length;
}

// Returns a builder that refills one payload object on every call, writing every field (the statistics through
// `stats`), so no value from an earlier ride survives. Safe because emitter.emit copies the payload's fields into its own event.
//
// Ride.stations always holds 255 slots in 0.5.5; a used slot has a non-null start, and an empty slot can come
// before a used one, so every slot is walked. Its length cannot tell a used slot, because flat rides and
// mazes read 0 there. stations is read once, outside the walk: each read rebuilds all 255 slots.
function createRideSnapshotBuilder(stats: RideStats): (ride: Ride) => EventFields {
    const payload: EventFields = {};
    return function (ride: Ride): EventFields {
        const stations = ride.stations;
        let stationCount = 0;
        let queueTimeMax: number | null = null;
        let hasStart = false;
        let startX = 0;
        let startY = 0;
        for (let i = 0; i < stations.length; i++) {
            const station = stations[i];
            const start = station.start;
            if (start !== null) {
                if (!hasStart) {
                    hasStart = true;
                    startX = start.x;
                    startY = start.y;
                }
                stationCount += 1;
                const queueTime = station.queueTime;
                if (queueTimeMax === null || queueTime > queueTimeMax) {
                    queueTimeMax = queueTime;
                }
            }
        }
        const rideId = ride.id;
        const rideType = ride.type;
        const rideObject = ride.object;
        const price = ride.price;
        payload.ride_id = requiredInteger("ride_id", rideId);
        payload.ride_name = ride.name;
        payload.ride_type = requiredInteger("ride_type", rideType);
        payload.ride_object = rideObject.identifier;
        payload.classification = ride.classification;
        payload.status = ride.status;
        payload.excitement_hundredths = jsonSafeInteger(ride.excitement);
        payload.intensity_hundredths = jsonSafeInteger(ride.intensity);
        payload.nausea_hundredths = jsonSafeInteger(ride.nausea);
        payload.price_1_tenths = price.length > 0 ? jsonSafeInteger(price[0]) : null;
        payload.price_2_tenths = price.length > 1 ? jsonSafeInteger(price[1]) : null;
        payload.shop_item = jsonSafeInteger(rideObject.shopItem);
        payload.shop_item_secondary = jsonSafeInteger(rideObject.shopItemSecondary);
        payload.total_customers = requiredInteger("total_customers", ride.totalCustomers);
        payload.build_date_months_elapsed = requiredInteger("build_date_months_elapsed", ride.buildDate);
        payload.age_months = requiredInteger("age_months", ride.age);
        payload.running_cost_per_fortnight_tenths = jsonSafeInteger(ride.runningCost);
        payload.total_profit_tenths = jsonSafeInteger(ride.totalProfit);
        payload.income_per_game_hour_tenths = jsonSafeInteger(ride.incomePerHour);
        payload.profit_per_game_hour_tenths = jsonSafeInteger(ride.profit);
        payload.value_tenths = jsonSafeInteger(ride.value);
        payload.reliability_pct = jsonSafeInteger(ride.reliability);
        payload.downtime_pct = jsonSafeInteger(ride.downtime);
        payload.satisfaction_pct = jsonSafeInteger(ride.satisfaction);
        payload.guests_on_ride = jsonSafeInteger(ride.guestCount);
        payload.station_count = stationCount;
        payload.queue_time_max_minutes = queueTimeMax === null ? null : jsonSafeInteger(queueTimeMax);
        stats.fill(payload, ride, rideId, stats.categoryOf(rideType), hasStart, startX, startY);
        return payload;
    };
}
