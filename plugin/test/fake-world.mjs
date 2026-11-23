// The park's contents in the stand-in: park storage, expenditure histories, rides and climate, with the 0.5.5
// shapes the plugin reads. Kept apart from fake-game.mjs, which wires them into the game's globals.
import { createStatistics } from "./fake-track.mjs";

// Park storage: context.getParkStorage() returns a Configuration (get/set/has/getAll). It outlives the
// script context, as a park's storage is saved with the park.
export function createParkStorage() {
  const values = {};
  return {
    values,
    sets: 0,
    get(key, defaultValue) {
      return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : defaultValue;
    },
    set(key, value) {
      this.sets += 1;
      values[key] = value;
    },
    has(key) {
      return Object.prototype.hasOwnProperty.call(values, key);
    },
    getAll() {
      return { ...values };
    },
  };
}

// The 0.5.5 ExpenditureType names, the stand-in's own list: never imported from the plugin, so a misspelled
// type in the plugin cannot pass.
export const EXPENDITURE_TYPES = [
  "ride_construction", "ride_runningcosts", "land_purchase", "landscaping", "park_entrance_tickets",
  "park_ride_tickets", "shop_sales", "shop_stock", "food_drink_sales", "food_drink_stock", "wages",
  "marketing", "research", "interest",
];
// kExpenditureTableMonthCount at 0.5.5: a history holds at most 16 months.
export const EXPENDITURE_MONTHS = 16;

// One 16-month history per type, index 0 the current month; every entry distinct, so a wrong index shows.
export function createExpenditures() {
  const histories = {};
  EXPENDITURE_TYPES.forEach((type, i) => {
    histories[type] = Array.from({ length: EXPENDITURE_MONTHS }, (_, month) => -(i + 1) * 1000 - month);
  });
  return histories;
}

// Ride.stations at 0.5.5 holds 255 slots; a used slot is marked by a non-null `start`, an unused one has
// start null, length 0 and queueTime 0 (observed 2026-10-01).
export const STATION_SLOTS = 255;

// `used` lists the stations by slot index, each { queueTime }, or null for an empty slot before a used one, which
// the 0.5.5 engine allows.
function createStations(used) {
  return Array.from({ length: STATION_SLOTS }, (_, i) =>
    i < used.length && used[i] !== null
      ? {
          start: stationStart(i),
          length: 3,
          entrance: { x: 32 * (i + 1), y: 64, z: 14, direction: 0 },
          exit: { x: 32 * (i + 1), y: 96, z: 14, direction: 2 },
          queueTime: used[i].queueTime ?? 0,
        }
      : { start: null, length: 0, entrance: null, exit: null, queueTime: 0 },
  );
}

// The start of the station in slot `i`, in world coordinates.
export function stationStart(i) {
  return { x: 32 * (i + 1), y: 64, z: 14 };
}

// A ride (or stall, or facility) with every field the plugin reads. `overrides` replaces any field; the
// extra `usedStations` (an array of { queueTime } or null, default one station) builds the 255 slots in `stations`.
// `stations` is a getter that builds fresh slots on every read, as the real game does, and calls
// `onStationsRead` each time so the game can charge for the read.
export function createRide(id, overrides = {}, onStationsRead = () => {}) {
  const { usedStations = [{ queueTime: 0 }], ...fields } = overrides;
  return {
    id,
    name: "Ride " + id,
    type: 0,
    classification: "ride",
    status: "open",
    price: [100],
    excitement: 650,
    intensity: 550,
    nausea: 300,
    totalCustomers: 1200,
    buildDate: 3,
    age: 4,
    runningCost: 800,
    totalProfit: 5000,
    incomePerHour: 2000,
    profit: 400,
    value: 30000,
    reliability: 9000,
    downtime: 5,
    satisfaction: 70,
    guestCount: 12,
    ...createStatistics(),
    object: { identifier: "rct2.ride.stand-in", shopItem: 0, shopItemSecondary: 0 },
    get stations() {
      onStationsRead();
      return createStations(usedStations);
    },
    ...fields,
  };
}

// global `climate` (Climate): type, current and upcoming weather, settable by tests.
export function createClimate() {
  return {
    type: "coolAndWet",
    current: { weather: "sunny", temperature: 18 },
    future: { weather: "partiallyCloudy", temperature: 18 },
  };
}
