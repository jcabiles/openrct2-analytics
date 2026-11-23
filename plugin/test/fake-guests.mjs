// The stand-in's entities: guests, cars and the other entity types a reused slot can hold, with the 0.5.5
// shapes the plugin reads. Kept apart from fake-game.mjs, which places them in ID slots and wires them into the
// game's globals. Every read of a guest's or car's member costs fake time through `spend`, so a test can give
// the reads a known duration or make one throw.

// The guest members the plugin may read, with stand-in values: the ranges the 0.5.5 type definitions state.
const GUEST_DEFAULTS = {
  happiness: 128, hunger: 64, thirst: 64, nausea: 0, energy: 96, minIntensity: 2, maxIntensity: 9,
  nauseaTolerance: 2, cash: 500, isInPark: true,
};
// No list in the 2026-09-27 capture held more than five thoughts.
export const MAX_THOUGHTS = 5;

// Defines each of `names` on `entity` as a getter that charges `spend(api)`, then reads `values[name]`, so a
// test's later change to `values` shows on the next read.
function chargedGetters(entity, names, values, api, spend) {
  for (const name of names) {
    Object.defineProperty(entity, name, {
      enumerable: true,
      get() {
        spend(api);
        return values[name];
      },
    });
  }
}

// Guest (0.5.5 `Guest`): the members in GUEST_DEFAULTS, plus `thoughts` (each `{ type, item, freshness,
// freshTimeout }`, index 0 the newest) and `items` (0.5.5 `GuestItem` objects, `{ type }`, never bare names; a
// photo or voucher carries more fields, such as `rideId`). Both lists come back as new copies on every read, as
// the engine builds them. `values` stays writable, so a test can change the guest in place.
export function createGuest(id, overrides, spend) {
  const values = { ...GUEST_DEFAULTS, thoughts: [], items: [], ...overrides };
  if (values.thoughts.length > MAX_THOUGHTS) throw new Error("stand-in guests hold at most five thoughts");
  if (!values.items.every((item) => typeof item?.type === "string")) {
    throw new Error("stand-in guest items are GuestItem objects ({ type }), as 0.5.5 returns them");
  }
  const guest = { id, type: "guest", values };
  chargedGetters(guest, Object.keys(GUEST_DEFAULTS), values, "guest.read", spend);
  Object.defineProperty(guest, "thoughts", {
    get() {
      spend("guest.read");
      return values.thoughts.map((thought) => ({ freshness: 0, freshTimeout: 0, ...thought }));
    },
  });
  Object.defineProperty(guest, "items", {
    get() {
      spend("guest.read");
      return values.items.map((item) => ({ ...item }));
    },
  });
  return guest;
}

// Car (0.5.5 `Car`): `ride` and `guests`, the guest ID in each seat or null; `guests` is a new copy on every read.
// As in 0.5.5, a seat can keep a guest's ID after the guest leaves, until another guest takes it, so one guest
// can be listed by several cars at once.
export function createCar(id, { ride = 0, guests = [] } = {}, spend) {
  const values = { ride, guests };
  const car = { id, type: "car", values };
  chargedGetters(car, ["ride"], values, "car.read", spend);
  Object.defineProperty(car, "guests", {
    get() {
      spend("car.read");
      return values.guests.slice();
    },
  });
  return car;
}

// Any other entity (0.5.5 `Entity`), such as the money_effect or litter a departed guest's slot was reused for.
export function createEntity(id, type) {
  return { id, type };
}
