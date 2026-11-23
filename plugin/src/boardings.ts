// Boardings: the game has no boarding hook and Guest has no current-ride field, so a seat poll, run from the
// tick callback at most once every POLL_INTERVAL_TICKS, reads every car's seats and finds each seat whose guest ID
// changed since the previous completed poll. Everything a boarding carries (the guest key, the guest's five
// fields and the ride's listed price) is read at that poll into the boarder task's per-field arrays, so a reused
// guest slot or a price change after the poll cannot reach an earlier boarding; the boarder step only fills the
// payload and emits it.
//
// 0.5.5 leaves a guest's ID in its seat after the guest leaves the car, until another guest takes the seat, so
// one guest can be listed by several cars at once; on a ride whose trains stop loading the IDs stay for good (two
// of the benchmark park's rides kept every seat listed for a whole run with no guest aboard). The poll therefore
// compares seat by seat, not guest by guest: a leftover listing is the same ID in the same seat at every poll, so
// it is never new, whatever other seats the guest takes or leaves. A table by guest holds one ride per guest, so a
// guest listed in several cars defeats it, and a table of (guest, ride) pairs would need a keyed set; one entry
// per car, the seat list the API already returned, costs one comparison per seat. A guest newly listed in two
// seats on one poll is listed once.
//
// Capture limit: a boarding is found only when the guest is seated at a poll. One that starts and ends between
// two polls is missed, and so is a boarding whenever a seat lists the same guest at both polls (for example the
// guest re-takes the seat that still lists them, or guest X, then Y, then X again sit in one seat between two
// polls): the seat shows no change. A boarding of any other seat, on the same ride or another, is
// found at the next poll.
//
// A poll that throws, a getter failing midway included, is a failed poll: it is counted through
// work.noteFailure(), not in boarding_polls_total, and keeps nothing it read. It fills the second seat table and
// writes its records past the boarder task's committed end; only a completed poll swaps the tables and commits
// its records. Every table and array is reused across polls, so a poll allocates nothing beyond what the API
// returns.

// Half a second of game time at normal speed: the interval the capture-schedule re-test measured.
const POLL_INTERVAL_TICKS = 20;

interface BoardingPoll {
    // Continuous, kind boarder: one item per new boarder a completed poll recorded.
    boarderTask: WorkTask;
    // Called from the tick callback before work.runTick(); polls when POLL_INTERVAL_TICKS have passed since the
    // last poll, failed or not.
    pollIfDue(): void;
    pollsCompleted(): number;
    boardersQueued(): number;
}

// Created once in main(). The first completed poll of a session records the seats without emitting.
function createBoardingPoll(
    emitter: Emitter,
    timer: Timer,
    work: WorkQueue,
    guests: GuestTracker,
    nextOrder: () => number
): BoardingPoll {
    // Two seat tables by car ID: the seat list the car returned (the API's own array, kept, not copied) and the
    // poll attempt that wrote it, so an entry is current only when its stamp is that table's attempt and no table
    // is ever cleared. The last completed poll's table is compared against; the other is filled by the running poll.
    let lastSeats: (number | null)[][] = [];
    let lastStamp: number[] = [];
    let fillSeats: (number | null)[][] = [];
    let fillStamp: number[] = [];
    // By guest ID, the attempt that last listed the guest as a boarder, so a poll lists each guest once.
    const listedStamp: number[] = [];
    // The attempt counter, and the attempt of the last completed poll (0 before the first).
    let attempt = 0;
    let lastAttempt = 0;
    let lastPollTick: number | null = null;
    // The listed price by ride ID, read once per ride per poll, stamped like the seat tables.
    const priceOf: (number | null)[] = [];
    const priceStamp: number[] = [];
    let pollsTotal = 0;
    let queuedTotal = 0;

    // The boarder task's items, by field, run oldest first. A running poll writes from boarderTail; a completed
    // poll moves boarderTail past its records. The arrays are reused from index 0 whenever the task empties.
    const boarderIds: number[] = [];
    const boarderRides: number[] = [];
    const boarderTicks: number[] = [];
    const boarderKeys: (number | null)[] = [];
    const boarderPrices: (number | null)[] = [];
    const boarderHappiness: (number | null)[] = [];
    const boarderMinIntensity: (number | null)[] = [];
    const boarderMaxIntensity: (number | null)[] = [];
    const boarderTolerance: (number | null)[] = [];
    const boarderCash: (number | null)[] = [];
    // One creation order per completed poll, shared by its records.
    const boarderOrders: number[] = [];
    let boarderHead = 0;
    let boarderTail = 0;
    const payload: EventFields = {};

    // The poll's time is reported to the queue in parts: poll (the car reads), then per new boarder boarder_read
    // (the key, entity, ride and price lookups) and guest_fields (the five field reads). Each switch closes the
    // open part at the time the next one opens, so the parts cover the poll with no gap or overlap.
    let partKind: StepKind = "poll";
    let partStart = 0;

    function switchPart(kind: StepKind): void {
        const now = timer.tickMsSoFar();
        work.noteStep(partKind, partStart, now);
        partKind = kind;
        partStart = now;
    }

    // Fills the seat table and lists, from boarderTail, the ID and ride of each guest in a seat whose ID changed
    // since the last completed poll; returns how many it listed. A car absent from that poll is new, so every
    // listed seat in it counts. Before the first completed poll there is nothing to compare against, so it lists
    // none.
    function readSeats(): number {
        const cars = map.getAllEntities("car");
        let found = 0;
        for (let i = 0; i < cars.length; i++) {
            const rideId = cars[i].ride;
            const seats = cars[i].guests;
            const carId = cars[i].id;
            // A listed car always has an ID; an invalid entity (ID null) holds no seat to compare.
            if (carId === null) {
                continue;
            }
            const before = lastStamp[carId] === lastAttempt ? lastSeats[carId] : null;
            fillSeats[carId] = seats;
            fillStamp[carId] = attempt;
            if (lastAttempt === 0) {
                continue;
            }
            for (let s = 0; s < seats.length; s++) {
                const id = seats[s];
                if (id !== null && (before === null || before[s] !== id) && listedStamp[id] !== attempt) {
                    listedStamp[id] = attempt;
                    boarderIds[boarderTail + found] = id;
                    boarderRides[boarderTail + found] = rideId;
                    found += 1;
                }
            }
        }
        return found;
    }

    // The ride's first price, or null when the ride is gone or has no price.
    function listedPrice(rideId: number): number | null {
        if (priceStamp[rideId] !== attempt) {
            // The type definitions omit it, but 0.5.5 returns null for a ride ID no longer in use.
            const ride = map.getRide(rideId) as Ride | null;
            const price = ride === null ? null : ride.price;
            priceOf[rideId] = price !== null && price.length > 0 ? jsonSafeInteger(price[0]) : null;
            priceStamp[rideId] = attempt;
        }
        return priceOf[rideId];
    }

    // Reads one new boarder's key, entity, price and guest fields into its record. A boarder no longer
    // readable as a guest keeps null guest fields.
    function readBoarder(index: number, tick: number): void {
        switchPart("boarder_read");
        const id = boarderIds[index];
        boarderTicks[index] = tick;
        boarderKeys[index] = guests.guestKeyOf(id);
        // The type definitions say never null; null is handled as a gone guest, as map.getRide's null is.
        const entity = map.getEntity(id) as Entity | null;
        boarderPrices[index] = listedPrice(boarderRides[index]);
        switchPart("guest_fields");
        const guest = entity !== null && entity.type === "guest" ? entity as Guest : null;
        boarderHappiness[index] = guest === null ? null : jsonSafeInteger(guest.happiness);
        boarderMinIntensity[index] = guest === null ? null : jsonSafeInteger(guest.minIntensity);
        boarderMaxIntensity[index] = guest === null ? null : jsonSafeInteger(guest.maxIntensity);
        boarderTolerance[index] = guest === null ? null : jsonSafeInteger(guest.nauseaTolerance);
        boarderCash[index] = guest === null ? null : jsonSafeInteger(guest.cash);
    }

    // The only path that keeps what a poll read: swaps the seat tables and commits the poll's records.
    function commit(found: number): void {
        const seats = lastSeats;
        const stamp = lastStamp;
        lastSeats = fillSeats;
        lastStamp = fillStamp;
        fillSeats = seats;
        fillStamp = stamp;
        lastAttempt = attempt;
        if (found > 0) {
            const order = nextOrder();
            for (let i = boarderTail; i < boarderTail + found; i++) {
                boarderOrders[i] = order;
            }
        }
        boarderTail += found;
        queuedTotal += found;
        pollsTotal += 1;
    }

    // try/finally without catch: a poll that throws is counted, its time still counts, and the error still
    // reaches the game.
    function pollIfDue(): void {
        const tick = date.ticksElapsed;
        if (lastPollTick !== null && tick - lastPollTick < POLL_INTERVAL_TICKS) {
            return;
        }
        lastPollTick = tick;
        attempt += 1;
        partKind = "poll";
        partStart = timer.tickMsSoFar();
        let completed = false;
        try {
            const found = readSeats();
            for (let i = boarderTail; i < boarderTail + found; i++) {
                readBoarder(i, tick);
            }
            commit(found);
            completed = true;
        } finally {
            work.noteStep(partKind, partStart, timer.tickMsSoFar());
            if (!completed) {
                work.noteFailure();
            }
        }
    }

    // Fills the one payload from the head record and emits it; every field is written on each fill, so no value
    // from an earlier boarding survives. Each required integer goes through requiredInteger, so a bad value
    // fails the step and sends no event.
    function runBoarder(): void {
        const i = boarderHead;
        boarderHead += 1;
        if (boarderHead === boarderTail) {
            boarderHead = 0;
            boarderTail = 0;
        }
        payload.guest_id = requiredInteger("guest_id", boarderIds[i]);
        payload.guest_key = boarderKeys[i];
        payload.ride_id = requiredInteger("ride_id", boarderRides[i]);
        payload.detected_at_ticks = requiredInteger("detected_at_ticks", boarderTicks[i]);
        payload.ride_price_listed_tenths = boarderPrices[i];
        payload.happiness = boarderHappiness[i];
        payload.min_intensity = boarderMinIntensity[i];
        payload.max_intensity = boarderMaxIntensity[i];
        payload.nausea_tolerance = boarderTolerance[i];
        payload.guest_cash_tenths = boarderCash[i];
        emitter.emit("guest_boarded", payload);
    }

    return {
        boarderTask: {
            pending: function (): number { return boarderTail - boarderHead; },
            headOrder: function (): number { return boarderOrders[boarderHead]; },
            headKind: function (): StepKind { return "boarder"; },
            runOne: runBoarder
        },
        pollIfDue: pollIfDue,
        pollsCompleted: function (): number { return pollsTotal; },
        boardersQueued: function (): number { return queuedTotal; }
    };
}
