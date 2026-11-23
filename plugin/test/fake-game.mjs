// A stand-in for OpenRCT2 0.5.5 and, as the socket's far end, a minimal listener; the only things the plugin
// tests substitute. It loads the compiled plugin into a node:vm context whose globals are the game APIs the
// plugin uses, and lets a test drive day callbacks, socket events, interval ticks and the wall clock by hand.
// Each member names the 0.5.5 API it stands for.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { FakeSocket } from "./fake-socket.mjs";
import { createCar, createEntity, createGuest } from "./fake-guests.mjs";
import {
  createClimate, createExpenditures, createParkStorage, createRide, EXPENDITURE_MONTHS, EXPENDITURE_TYPES,
  stationStart,
} from "./fake-world.mjs";
import { createResearch, createTrackWorld } from "./fake-track.mjs";

export { createParkStorage, EXPENDITURE_TYPES };

const PLUGIN_FILE = fileURLToPath(new URL("../dist/openrct2-analytics.js", import.meta.url));

const RealDate = Date;

// One running game with one park. `storage` is shared across restarts, as a park's storage is.
export function createGame({
  mode = "normal",
  storage = createParkStorage(),
  withPerformance = true,
  withUi = false,
  daysPerMonth = 0,
  msPerTick = 0,
} = {}) {
  const game = {
    storage,
    // The wall clock, in ms since the Unix epoch; `Date` and `performance.now()` both read it.
    wallMs: RealDate.UTC(2026, 8, 30, 12),
    // Fake time each call to a game API costs, in ms, so a test can give a callback a known duration.
    costs: {
      "socket.write": 0, "park.cash": 0, "network.createSocket": 0, "map.rides": 0, "map.getRide": 0,
      "ride.stations": 0, "map.getEntity": 0, "map.getAllEntities": 0, "guest.read": 0, "car.read": 0,
      "park.research": 0, "map.getTile": 0, "map.getTrackIterator": 0, "climate.current": 0, "climate.future": 0,
    },
    // How many times each costed API was called.
    calls: {},
    // Costed APIs that throw when called, after charging their cost: the 0.5.5 binding of a getter that fails.
    throwing: new Set(),
    // Math.random() in the plugin's context returns these in turn, then real random numbers once they run out.
    draws: [],
    // Fake time each interval.tick firing adds to the wall clock, in ms. tick() adds it before the hooks run, so it
    // falls outside the plugin's own timing of its hook; a callback's measured cost comes from `costs` instead.
    msPerTick,
    // When above 0, day() wraps to day 1 of the next month once the day reaches this number; 0 leaves day() as is.
    daysPerMonth,
    writeBehavior: "ok",
    received: [],
    // Lines the listener could not parse; it lands them in its malformed file.
    malformed: [],
    sockets: [],
    dayHooks: [],
    tickHooks: [],
    saveHooks: [],
    generationHooks: [],
    actionQueryHooks: [],
    actionExecuteHooks: [],
    intervals: [],
    logs: [],
    metadata: null,
    context: null,
    // context.mode, context.gameSpeed
    mode,
    gameSpeed: 1,
    // context.apiVersion: the plugin API level
    apiVersion: 110,
    // global `date` (GameDate): year from 1, month 0-7, day from 1, ticksElapsed, monthsElapsed
    date: { year: 1, month: 0, day: 1, ticksElapsed: 1000, monthsElapsed: 0 },
    // global `park` (Park): cash and bankLoan in tenths of a dollar, guests in the park, rating,
    // totalAdmissions, name
    parkValues: {
      cash: 123450, bankLoan: 50000, guests: 1938, rating: 870, totalAdmissions: 5000, name: "Stand-in Park",
    },
    // Park.getMonthlyExpenditure's full history per type, index 0 the current month.
    expenditures: createExpenditures(),
    // global `map` (GameMap): rides, in build order; demolished rides leave the list
    rides: [],
    // global `map` (GameMap): the entity in each ID slot (a guest, car or other type), undefined for an empty slot
    entities: [],
    // global `park` (Park).research: both item lists, each ride item with its research category
    research: createResearch(),
    // global `map` (GameMap): the tracks of rides added with a `track`, read through getTile and getTrackIterator
    trackWorld: createTrackWorld(),
    // global `climate` (Climate)
    climateValues: createClimate(),
    // global `scenario` (Scenario): name, and a filename the plugin must never send
    scenarioValues: { name: "Stand-in Scenario", filename: "/stand-in/scenarios/stand-in.park" },

    // Adds a ride built by createRide(id, overrides) and returns it; the id is the lowest not in use, so a
    // demolished ride's slot is reused as in OpenRCT2. Reading its `stations` costs `costs["ride.stations"]`.
    // An extra `track` (see createTrackWorld) puts the ride's track on its first used station's tile.
    addRide({ track, ...overrides } = {}) {
      const taken = new Set(this.rides.map((r) => r.id));
      let id = 0;
      while (taken.has(id)) id += 1;
      const ride = createRide(id, overrides, () => this.spend("ride.stations"));
      this.rides.push(ride);
      if (track !== undefined) {
        const used = overrides.usedStations ?? [{ queueTime: 0 }];
        this.trackWorld.add(id, stationStart(used.findIndex((station) => station !== null)), track);
      }
      return ride;
    },

    // Demolishes a ride: it leaves map.rides and map.getRide returns null for its id.
    demolishRide(id) {
      this.rides = this.rides.filter((ride) => ride.id !== id);
    },

    spend(api) {
      this.wallMs += this.costs[api];
      this.calls[api] = (this.calls[api] ?? 0) + 1;
      if (this.throwing.has(api)) throw new Error(`stand-in ${api} throws`);
    },

    // The lowest empty ID slot, as the engine reuses a freed entity slot.
    freeSlot() {
      let id = 0;
      while (this.entities[id] !== undefined) id += 1;
      return id;
    },

    // Places a guest built by createGuest(id, overrides) in the lowest empty slot (or `id`) and returns it.
    addGuest(overrides = {}, id = this.freeSlot()) {
      const guest = createGuest(id, overrides, (api) => this.spend(api));
      this.entities[id] = guest;
      return guest;
    },

    // The engine's guest generation: places a guest, then fires guest.generation with its ID.
    generateGuest(overrides = {}, id = this.freeSlot()) {
      const guest = this.addGuest(overrides, id);
      for (const hook of this.generationHooks) hook({ id });
      return guest;
    },

    // Places a car built by createCar(id, { ride, guests }) in the lowest empty slot and returns it.
    addCar(values = {}) {
      const id = this.freeSlot();
      this.entities[id] = createCar(id, values, (api) => this.spend(api));
      return this.entities[id];
    },

    // Empties a slot (map.getEntity returns null), or with `type` gives it to an entity of that type.
    replaceEntity(id, type = null) {
      this.entities[id] = type === null ? undefined : createEntity(id, type);
    },

    land(line) {
      if (line === "") return;
      try {
        this.received.push(JSON.parse(line));
      } catch (error) {
        if (!(error instanceof SyntaxError)) throw error;
        this.malformed.push(line);
      }
    },

    get socket() {
      return this.sockets[this.sockets.length - 1];
    },

    // Evaluates the compiled plugin in a fresh script context, as Plugin::Load does on every park load.
    load() {
      this.dayHooks = [];
      this.tickHooks = [];
      this.saveHooks = [];
      this.generationHooks = [];
      this.actionQueryHooks = [];
      this.actionExecuteHooks = [];
      this.intervals = [];
      this.metadata = null;
      this.context = vm.createContext(this.globals());
      vm.runInContext(readFileSync(PLUGIN_FILE, "utf8"), this.context, { filename: PLUGIN_FILE });
      return this;
    },

    // Starts the plugin: the game calls the registered main().
    start() {
      this.metadata.main();
      return this;
    },

    // Stops the plugin's hooks and intervals and calls main() again in the same script context. The engine
    // frees the context instead; this path exposes any state left at file scope.
    restartInSameContext() {
      this.dayHooks = [];
      this.tickHooks = [];
      this.saveHooks = [];
      this.generationHooks = [];
      this.actionQueryHooks = [];
      this.actionExecuteHooks = [];
      this.intervals = [];
      return this.start();
    },

    // Moves the game date to a tick and fires the interval.day hook. With `daysPerMonth` set, the day that
    // would pass it is a month-end instead.
    day(tick) {
      if (this.daysPerMonth > 0 && this.date.day >= this.daysPerMonth) {
        this.nextMonth(tick);
        return;
      }
      this.date.ticksElapsed = tick;
      this.date.day += 1;
      for (const hook of this.dayHooks) hook();
    },

    // Fires every interval.tick hook `count` times, adding 1 to date.ticksElapsed and `msPerTick` of fake time
    // before each firing (outside the plugin's own timing of its hook).
    tick(count = 1) {
      for (let i = 0; i < count; i += 1) {
        this.date.ticksElapsed += 1;
        this.wallMs += this.msPerTick;
        for (const hook of this.tickHooks) hook();
      }
    },

    // The engine's save: fires every map.save hook synchronously, then returns the saved file, which holds a
    // deep copy of park storage.
    save() {
      for (const hook of this.saveHooks) hook();
      return { storage: structuredClone(this.storage.values) };
    },

    // Loads a saved file: park storage comes back from the file, then the plugin starts fresh as on any park load.
    loadSave(saved) {
      this.storage = createParkStorage();
      Object.assign(this.storage.values, structuredClone(saved.storage));
      return this.load().start();
    },

    // A month-end: moves the game date to a tick on day 1 of the next month (month 7 wraps to month 0 of the
    // next year), counts the month, starts a new month at index 0 of every history and fires the
    // interval.day hook. `bookedAfterShift` maps expenditure types to tenths booked to the new month after the
    // shift and before the day hook, as guest purchases are; each also moves cash.
    nextMonth(tick, bookedAfterShift = {}) {
      this.date.ticksElapsed = tick;
      this.date.day = 1;
      if (this.date.month === 7) {
        this.date.month = 0;
        this.date.year += 1;
      } else {
        this.date.month += 1;
      }
      this.date.monthsElapsed += 1;
      for (const type of EXPENDITURE_TYPES) {
        this.expenditures[type].unshift(0);
        this.expenditures[type].length = EXPENDITURE_MONTHS;
      }
      for (const [type, tenths] of Object.entries(bookedAfterShift)) {
        this.expenditures[type][0] += tenths;
        this.parkValues.cash += tenths;
      }
      for (const hook of this.dayHooks) hook();
    },

    // Moves the game date to a tick and fires every context.setInterval callback once.
    interval(tick = this.date.ticksElapsed) {
      this.date.ticksElapsed = tick;
      for (const entry of this.intervals) entry.callback();
    },

    eventsOfType(type) {
      return this.received.filter((event) => event.event_type === type);
    },

    globals() {
      const game = this;
      const globals = {
        // registerPlugin(metadata)
        registerPlugin(metadata) {
          game.metadata = metadata;
        },
        // global `console`
        console: {
          log(message) {
            game.logs.push(String(message));
          },
        },
        // global `context` (Context)
        context: {
          get mode() {
            return game.mode;
          },
          get gameSpeed() {
            return game.gameSpeed;
          },
          get apiVersion() {
            return game.apiVersion;
          },
          getParkStorage() {
            return game.storage;
          },
          subscribe(hook, callback) {
            const hooks = {
              "interval.day": game.dayHooks,
              "interval.tick": game.tickHooks,
              "map.save": game.saveHooks,
              "guest.generation": game.generationHooks,
              "action.query": game.actionQueryHooks,
              "action.execute": game.actionExecuteHooks,
            };
            if (!Object.prototype.hasOwnProperty.call(hooks, hook)) throw new Error("stand-in has no hook " + hook);
            hooks[hook].push(callback);
            return { dispose() {} };
          },
          setInterval(callback, delay) {
            game.intervals.push({ callback, delay });
            return game.intervals.length;
          },
        },
        // global `network` (Network): createSocket()
        network: {
          createSocket() {
            game.spend("network.createSocket");
            const socket = new FakeSocket(game);
            game.sockets.push(socket);
            return socket;
          },
        },
        // global `map` (GameMap); both reads cost fake time. `rides` is a new array on every read, as the real
        // game builds fresh wrappers, so a plugin that mutates it cannot change the stand-in's world.
        map: {
          get rides() {
            game.spend("map.rides");
            return game.rides.slice();
          },
          // getRide(id): the ride, or null once it has been demolished
          getRide(id) {
            game.spend("map.getRide");
            return game.rides.find((ride) => ride.id === id) ?? null;
          },
          // getTile(x, y): the tile at tile coordinates, with the elements the plugin searches for a ride's track
          getTile(x, y) {
            game.spend("map.getTile");
            return game.trackWorld.getTile(x, y);
          },
          // getTrackIterator(location, elementIndex): at world coordinates, or null
          getTrackIterator(location, elementIndex) {
            game.spend("map.getTrackIterator");
            return game.trackWorld.getTrackIterator(location, elementIndex);
          },
          // getEntity(id): the entity in the slot; null for an empty slot, though the type definitions say never
          getEntity(id) {
            game.spend("map.getEntity");
            return game.entities[id] ?? null;
          },
          // getAllEntities(type): a new array of the entities of one type, in slot order
          getAllEntities(type) {
            game.spend("map.getAllEntities");
            return game.entities.filter((entity) => entity !== undefined && entity.type === type);
          },
        },
        // global `Math`: random() returns the scripted draws first
        Math: Object.assign(Object.create(Math), {
          random: () => (game.draws.length > 0 ? game.draws.shift() : Math.random()),
        }),
        // global `climate` (Climate)
        // (`type` is a plain read; `current` and `future` are costed reads that can throw, like the other getters)
        climate: {
          get type() {
            return game.climateValues.type;
          },
          get current() {
            game.spend("climate.current");
            return game.climateValues.current;
          },
          get future() {
            game.spend("climate.future");
            return game.climateValues.future;
          },
        },
        // global `date` (GameDate)
        date: game.date,
        // global `Date`: new Date() and Date.now() read the wall clock; other forms are the real Date
        Date: Object.assign(
          function Date(...args) {
            return args.length === 0 ? new RealDate(game.wallMs) : new RealDate(...args);
          },
          { now: () => game.wallMs, UTC: RealDate.UTC, parse: RealDate.parse },
        ),
        // global `park` (Park); reading cash costs `costs["park.cash"]` of fake time
        park: {
          get research() {
            game.spend("park.research");
            return game.research;
          },
          get cash() {
            game.spend("park.cash");
            return game.parkValues.cash;
          },
          get guests() {
            return game.parkValues.guests;
          },
          get rating() {
            return game.parkValues.rating;
          },
          get totalAdmissions() {
            return game.parkValues.totalAdmissions;
          },
          get bankLoan() {
            return game.parkValues.bankLoan;
          },
          get name() {
            return game.parkValues.name;
          },
          // getMonthlyExpenditure(type): the first monthsElapsed + 1 months of the history, at most 16, as in
          // ScPark.cpp at v0.5.5; an unknown type returns an empty array
          getMonthlyExpenditure(type) {
            if (!Object.prototype.hasOwnProperty.call(game.expenditures, type)) return [];
            const months = Math.min(game.date.monthsElapsed + 1, EXPENDITURE_MONTHS);
            return game.expenditures[type].slice(0, months);
          },
        },
        // global `scenario` (Scenario)
        scenario: {
          get name() {
            return game.scenarioValues.name;
          },
          get filename() {
            return game.scenarioValues.filename;
          },
        },
      };
      // global `ui` (Ui): absent when the game runs headless, as the type definitions say
      if (this.withUi) {
        globals.ui = {};
      }
      // QuickJS-ng's `performance.now()`, driven by the wall clock
      if (this.withPerformance) {
        globals.performance = {
          now() {
            return game.wallMs;
          },
        };
      }
      return globals;
    },
  };
  game.withPerformance = withPerformance;
  game.withUi = withUi;
  return game;
}
