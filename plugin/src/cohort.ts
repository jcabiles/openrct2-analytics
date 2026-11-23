// The followed cohort: up to COHORT_SIZE guests picked at random as they arrive, each recorded once a game day
// (guest_snapshot) until it leaves, when its place frees for a later arrival. Membership itself is a flag on
// the known-guest table in guests.ts; this module holds the size, the draw and the snapshot payload.
//
// The draw uses Math.random, not context.getRandom: getRandom draws from the game's own random sequence, so a
// plugin draw could change what the game does next. Cost: a draw cannot be replayed; each guest's membership is
// recorded in the arrival event's in_cohort instead.

const COHORT_SIZE = 100;
const COHORT_JOIN_PROBABILITY = 0.5;

interface Cohort {
    // Draws for an arriving guest: false without a draw while the cohort is full, otherwise true when
    // Math.random() is below COHORT_JOIN_PROBABILITY. Does not take the place; join() does.
    draw(): boolean;
    join(): void;
    // Frees the place of a member that has left.
    release(): void;
    // The member's one reusable guest_snapshot payload, refilled in full; `thoughts` is the guest's list, already read.
    snapshot(key: number, id: number, guest: Guest, thoughts: Thought[]): EventFields;
}

// The items' type names joined by |. 0.5.5 returns each item as a GuestItem object, not a name (docs/FINDINGS.md),
// so join("|") would send "[object Object]"; the loop builds only the string.
function itemTypes(items: GuestItem[]): string {
    let text = "";
    for (let i = 0; i < items.length; i++) {
        text += (i === 0 ? "" : "|") + items[i].type;
    }
    return text;
}

function createCohort(): Cohort {
    let memberCount = 0;
    const payload: EventFields = {};

    function draw(): boolean {
        return memberCount < COHORT_SIZE && Math.random() < COHORT_JOIN_PROBABILITY;
    }

    function snapshot(key: number, id: number, guest: Guest, thoughts: Thought[]): EventFields {
        payload.guest_key = requiredInteger("guest_key", key);
        payload.guest_id = requiredInteger("guest_id", id);
        payload.happiness = jsonSafeInteger(guest.happiness);
        payload.hunger = jsonSafeInteger(guest.hunger);
        payload.thirst = jsonSafeInteger(guest.thirst);
        payload.nausea = jsonSafeInteger(guest.nausea);
        payload.energy = jsonSafeInteger(guest.energy);
        payload.guest_cash_tenths = jsonSafeInteger(guest.cash);
        payload.items_carried = itemTypes(guest.items);
        payload.thought_type = thoughts.length > 0 ? thoughts[0].type : null;
        payload.thought_item = thoughts.length > 0 ? jsonSafeInteger(thoughts[0].item) : null;
        return payload;
    }

    return {
        draw: draw,
        join: function (): void { memberCount += 1; },
        release: function (): void { memberCount -= 1; },
        snapshot: snapshot
    };
}
