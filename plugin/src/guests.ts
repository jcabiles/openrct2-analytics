// Guest tracking: every arrival (from the guest.generation hook, to the tick), every exit (from a daily check
// of the known guests, to the day) and every ride-refusal thought newly present at that check. Entity IDs are
// reused slots, so each guest first seen in a session gets a guest_key, counted from 1. The known-guest table
// is a set of arrays indexed by entity ID plus one dense list of the known IDs, so no object is kept per guest,
// and the two tasks reuse their arrays across days.
//
// Exits and refusals are day resolution: a refusal that appears and expires within one day is missed, and a
// thought still present is not sent again (the engine refreshes an existing thought in place).

// The thoughts that refuse a ride; for all nine the thought's item is the refused ride's ID. Not included,
// because they are not refusals of a ride: cant_afford_item, spent_money, good_value, was_great, cant_find,
// get_off, get_out, new_ride, here_we_are and the item and need thoughts.
const REFUSAL_THOUGHTS: ReadonlyArray<string> = [
    "cant_afford_ride", "bad_value", "not_paying", "intense", "more_thrilling", "sickening", "not_safe",
    "queuing_ages", "not_while_raining"
];

// Per-guest flags, by entity ID.
const IN_PARK = 1;
const ENTERED_PARK = 2;
const ARRIVED_IN_SESSION = 4;
const IN_COHORT = 8;

interface GuestTracker {
    // Continuous, kind arrival: one item per guest.generation call.
    arrivalTask: WorkTask;
    // Day-scoped: a guest_list step, then one guest step per known guest.
    dayTask: DayTask;
    // The guest.generation hook's whole work: reads nothing from the guest and emits nothing.
    recordArrival(id: number): void;
    // The key currently held for an entity ID, or null when the ID is not in the known table.
    guestKeyOf(id: number): number | null;
    known(): number;
    knownInPark(): number;
    arrivalsRecorded(): number;
}

// Created once in main(), after session_start is queued: seeds the table from the session's only all-guest
// read. Seeded guests emit nothing; their exits say arrived_in_session false.
function createGuestTracker(emitter: Emitter, nextOrder: () => number): GuestTracker {
    // By entity ID: the key (0 or absent when not known), flags, refusal keys (null until a seeded guest's
    // first check), the position in knownIds, and how many recorded arrivals have not yet run.
    const keyOf: number[] = [];
    const flagsOf: number[] = [];
    const refusalsOf: (string | null)[] = [];
    const positionOf: number[] = [];
    const arrivalsPending: number[] = [];
    const knownIds: number[] = [];
    let knownCount = 0;
    let inParkCount = 0;
    let lastKey = 0;
    let arrivalsTotal = 0;
    const payloads = createGuestPayloads();
    const cohort = createCohort();

    // The arrival task's items, run oldest first: the ID, the hook's tick and the creation order. The arrays
    // are reused from index 0 whenever the task empties.
    const arrivalIds: number[] = [];
    const arrivalTicks: number[] = [];
    const arrivalOrders: number[] = [];
    let arrivalHead = 0;
    let arrivalTail = 0;

    // The daily task's copy of the known IDs and their keys, taken by its guest_list step.
    const dayIds: number[] = [];
    const dayKeys: number[] = [];
    let dayCount = 0;
    let dayCursor = 0;
    let listPending = false;
    let dayOrder = 0;

    function guestKeyOf(id: number): number | null {
        const key = keyOf[id];
        return key > 0 ? key : null;
    }

    // An arrival pending for the ID: the arrival step owns that slot.
    function arrivalPending(id: number): boolean {
        return arrivalsPending[id] > 0;
    }

    function setInPark(id: number, inPark: boolean): void {
        const was = (flagsOf[id] & IN_PARK) !== 0;
        if (inPark && !was) {
            flagsOf[id] |= IN_PARK | ENTERED_PARK;
            inParkCount += 1;
        } else if (!inPark && was) {
            flagsOf[id] &= ~IN_PARK;
            inParkCount -= 1;
        }
    }

    function add(id: number, flags: number, refusals: string | null): number {
        lastKey += 1;
        keyOf[id] = lastKey;
        flagsOf[id] = flags;
        refusalsOf[id] = refusals;
        positionOf[id] = knownCount;
        knownIds[knownCount] = id;
        knownCount += 1;
        return lastKey;
    }

    // Emits the guest's guest_left, then removes it; the last known ID takes its place in the dense list.
    function leave(id: number, exitReason: string): void {
        emitter.emit("guest_left", payloads.left(keyOf[id], id, exitReason, flagsOf[id]));
        if ((flagsOf[id] & IN_COHORT) !== 0) {
            cohort.release();
        }
        setInPark(id, false);
        const position = positionOf[id];
        const lastId = knownIds[knownCount - 1];
        knownIds[position] = lastId;
        positionOf[lastId] = position;
        knownCount -= 1;
        keyOf[id] = 0;
    }

    function runArrival(): void {
        const id = arrivalIds[arrivalHead];
        const generatedAtTicks = arrivalTicks[arrivalHead];
        arrivalHead += 1;
        if (arrivalHead === arrivalTail) {
            arrivalHead = 0;
            arrivalTail = 0;
        }
        arrivalsPending[id] -= 1;
        // Another arrival still pending for the ID means its slot already holds a later guest.
        const entity = arrivalPending(id) ? null : map.getEntity(id) as Entity | null;
        const cash = entity !== null && entity.type === "guest" ? jsonSafeInteger((entity as Guest).cash) : null;
        // Filled before the table changes, so a value requiredInteger refuses leaves the table as it was.
        const arrived = payloads.arrived(lastKey + 1, id, generatedAtTicks, cash);
        // Still known: the ID's earlier occupant has gone.
        if (keyOf[id] > 0) {
            leave(id, "id_reused");
        }
        // Drawn after the earlier occupant's exit, which may have freed a place.
        const joins = cohort.draw();
        arrived.in_cohort = joins;
        if (joins) {
            cohort.join();
        }
        add(id, joins ? ARRIVED_IN_SESSION | IN_COHORT : ARRIVED_IN_SESSION, "");
        emitter.emit("guest_arrived", arrived);
    }

    // Emits one guest_refused per refusal key (type and item) not present at the previous check, then stores
    // the current keys. A seeded guest's first check stores its keys without emitting, so thoughts formed
    // before the session are not dated inside it.
    function checkRefusals(id: number, thoughts: Thought[]): void {
        const previous = refusalsOf[id];
        // Every ride ID this check could send is checked before any is sent, so a refused value sends none of
        // the guest's refusals and stores no keys, and the next check cannot send any of them twice.
        if (previous !== null) {
            for (let i = 0; i < thoughts.length; i++) {
                if (REFUSAL_THOUGHTS.indexOf(thoughts[i].type) !== -1) {
                    requiredInteger("ride_id", thoughts[i].item);
                }
            }
        }
        let keys = "";
        for (let i = 0; i < thoughts.length; i++) {
            const type = thoughts[i].type;
            if (REFUSAL_THOUGHTS.indexOf(type) !== -1) {
                const item = thoughts[i].item;
                const piece = "|" + type + ":" + item + "|";
                if ((keys + "|").indexOf(piece) === -1) {
                    keys += "|" + type + ":" + item;
                    if (previous !== null && (previous + "|").indexOf(piece) === -1) {
                        emitter.emit("guest_refused", payloads.refused(keyOf[id], id, type, item));
                    }
                }
            }
        }
        refusalsOf[id] = keys;
    }

    // Gone (no entity, or another type in its slot), or out of the park after being in: the guest has left. A
    // guest generated outside the park that has not entered stays known until it goes.
    function checkGuest(id: number): void {
        // The type definitions say never null; null is handled as a gone guest, as map.getRide's null is.
        const entity = map.getEntity(id) as Entity | null;
        if (entity === null || entity.type !== "guest") {
            leave(id, "left");
            return;
        }
        const guest = entity as Guest;
        const inPark = guest.isInPark;
        if (!inPark && (flagsOf[id] & ENTERED_PARK) !== 0) {
            leave(id, "left");
            return;
        }
        setInPark(id, inPark);
        const thoughts = guest.thoughts;
        checkRefusals(id, thoughts);
        if ((flagsOf[id] & IN_COHORT) !== 0) {
            emitter.emit("guest_snapshot", cohort.snapshot(keyOf[id], id, guest, thoughts));
        }
    }

    function runDayStep(): void {
        if (listPending) {
            listPending = false;
            for (let i = 0; i < knownCount; i++) {
                dayIds[i] = knownIds[i];
                dayKeys[i] = keyOf[knownIds[i]];
            }
            dayCount = knownCount;
            return;
        }
        dayCursor += 1;
        const id = dayIds[dayCursor - 1];
        // A changed key or a pending arrival: the arrival step owns this ID.
        if (keyOf[id] === dayKeys[dayCursor - 1] && !arrivalPending(id)) {
            checkGuest(id);
        }
    }

    function dayPending(): number {
        return listPending ? 1 : dayCount - dayCursor;
    }

    function startDay(order: number): number {
        const dropped = dayPending();
        listPending = true;
        dayCount = 0;
        dayCursor = 0;
        dayOrder = order;
        return dropped;
    }

    function recordArrival(id: number): void {
        arrivalsPending[id] = (arrivalPending(id) ? arrivalsPending[id] : 0) + 1;
        arrivalsTotal += 1;
        arrivalIds[arrivalTail] = id;
        arrivalTicks[arrivalTail] = date.ticksElapsed;
        arrivalOrders[arrivalTail] = nextOrder();
        arrivalTail += 1;
    }

    // A listed guest always has an ID; an invalid entity (ID null) holds no slot to track.
    const seeded = map.getAllEntities("guest");
    for (let i = 0; i < seeded.length; i++) {
        const id = seeded[i].id;
        if (id !== null) {
            add(id, 0, null);
            setInPark(id, seeded[i].isInPark);
        }
    }

    return {
        arrivalTask: {
            pending: function (): number { return arrivalTail - arrivalHead; },
            headOrder: function (): number { return arrivalOrders[arrivalHead]; },
            headKind: function (): StepKind { return "arrival"; },
            runOne: runArrival
        },
        dayTask: {
            pending: dayPending,
            headOrder: function (): number { return dayOrder; },
            headKind: function (): StepKind { return listPending ? "guest_list" : "guest"; },
            runOne: runDayStep,
            startDay: startDay
        },
        recordArrival: recordArrival,
        guestKeyOf: guestKeyOf,
        known: function (): number { return knownCount; },
        knownInPark: function (): number { return inParkCount; },
        arrivalsRecorded: function (): number { return arrivalsTotal; }
    };
}

interface GuestPayloads {
    arrived(key: number, id: number, generatedAtTicks: number, cash: number | null): EventFields;
    left(key: number, id: number, exitReason: string, flags: number): EventFields;
    refused(key: number, id: number, thoughtType: string, rideId: number): EventFields;
}

// One payload object per event type, refilled on every call with every field written, so no value from an
// earlier guest survives. Safe because emitter.emit copies the payload's fields into its own event. Each required
// integer goes through requiredInteger, so a bad value fails the step and sends no event. The arrival step sets
// in_cohort on the arrival; an exit reports the flag the guest held.
function createGuestPayloads(): GuestPayloads {
    const arrivedPayload: EventFields = {};
    const leftPayload: EventFields = {};
    const refusedPayload: EventFields = {};

    function arrived(key: number, id: number, generatedAtTicks: number, cash: number | null): EventFields {
        arrivedPayload.guest_key = requiredInteger("guest_key", key);
        arrivedPayload.guest_id = requiredInteger("guest_id", id);
        arrivedPayload.generated_at_ticks = requiredInteger("generated_at_ticks", generatedAtTicks);
        arrivedPayload.in_cohort = false;
        arrivedPayload.guest_cash_tenths = cash;
        return arrivedPayload;
    }

    function left(key: number, id: number, exitReason: string, flags: number): EventFields {
        leftPayload.guest_key = requiredInteger("guest_key", key);
        leftPayload.guest_id = requiredInteger("guest_id", id);
        leftPayload.exit_reason = exitReason;
        leftPayload.entered_park = (flags & ENTERED_PARK) !== 0;
        leftPayload.arrived_in_session = (flags & ARRIVED_IN_SESSION) !== 0;
        leftPayload.in_cohort = (flags & IN_COHORT) !== 0;
        return leftPayload;
    }

    function refused(key: number, id: number, thoughtType: string, rideId: number): EventFields {
        refusedPayload.guest_key = requiredInteger("guest_key", key);
        refusedPayload.guest_id = requiredInteger("guest_id", id);
        refusedPayload.thought_type = thoughtType;
        refusedPayload.ride_id = requiredInteger("ride_id", rideId);
        return refusedPayload;
    }

    return { arrived: arrived, left: left, refused: refused };
}
