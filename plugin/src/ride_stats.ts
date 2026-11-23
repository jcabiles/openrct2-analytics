// The ride statistics of the daily ride_snapshot: the 11 numbers the game keeps per ride, the research
// category of the ride's type, and the inversion count from walking a coaster's track. Each property is read
// once per snapshot because game objects are native bindings that rebuild on every read. The 11 numbers read 0
// until the ride's first test run and are sent as read, zero included. The inversion count is taken from the
// built track, so an untested coaster can carry a count while its statistics are 0.

// The walk stops with a null count after this many moves, both legs together.
const MAX_WALK_STEPS = 5000;
// World coordinates are tile coordinates times this; map.getTrackIterator takes world coordinates and
// map.getTile takes tile coordinates.
const TILE_SIZE = 32;

interface RideStats {
    // Reads both research lists into the category table. Called once per session.
    loadCategories(): void;
    // The research category of a ride type, or null when the type is in neither list.
    categoryOf(rideType: number): string | null;
    // Writes the 11 statistics, inversion_count and ride_category into the payload. startX and startY are the first used
    // station's start, or hasStart is false when the ride has none.
    fill(payload: EventFields, ride: Ride, rideId: number, category: string | null, hasStart: boolean, startX: number, startY: number): void;
}

// One instance per session: the category table and the walk's coordinates object are kept across days.
function createRideStats(): RideStats {
    // Indexed by ride type; the entry is the research category's text, and a type in neither list is undefined.
    const categories: string[] = [];
    const coords: CoordsXY = { x: 0, y: 0 };

    function loadCategories(): void {
        const research = park.research;
        const lists = [research.inventedItems, research.uninventedItems];
        for (let l = 0; l < lists.length; l++) {
            const items = lists[l];
            for (let i = 0; i < items.length; i++) {
                const item = items[i];
                if (item.type === "ride") {
                    categories[item.rideType] = item.category;
                }
            }
        }
    }

    function categoryOf(rideType: number): string | null {
        const category = categories[rideType];
        return typeof category === "string" ? category : null;
    }

    // The index of the ride's own track element on a tile, or -1 when the tile has none.
    function trackElementIndex(tileX: number, tileY: number, rideId: number): number {
        const elements = map.getTile(tileX, tileY).elements;
        for (let i = 0; i < elements.length; i++) {
            const element = elements[i];
            if (element.type === "track" && element.ride === rideId) {
                return i;
            }
        }
        return -1;
    }

    // Counts the segments flagged as adding to the inversion counter, walking forward from the station's track
    // element until the circuit closes or the track ends; at a dead end it walks backward from the same element
    // and adds that leg. Null when the count cannot be trusted: no element or iterator, a null segment, or more
    // than MAX_WALK_STEPS moves. An unfinished track or a shuttle layout is counted as built, not null.
    function countInversions(rideId: number, startX: number, startY: number): number | null {
        const tileX = Math.floor(startX / TILE_SIZE);
        const tileY = Math.floor(startY / TILE_SIZE);
        const index = trackElementIndex(tileX, tileY, rideId);
        if (index < 0) {
            return null;
        }
        coords.x = tileX * TILE_SIZE;
        coords.y = tileY * TILE_SIZE;
        const forward = map.getTrackIterator(coords, index);
        if (forward === null) {
            return null;
        }
        const first = forward.position;
        const firstX = first.x;
        const firstY = first.y;
        const firstZ = first.z;
        const firstDirection = first.direction;
        const firstSegment = forward.segment;
        if (firstSegment === null) {
            return null;
        }
        let count = firstSegment.countsAsInversion ? 1 : 0;
        let steps = 0;
        while (forward.next()) {
            steps += 1;
            if (steps > MAX_WALK_STEPS) {
                return null;
            }
            const position = forward.position;
            if (position.x === firstX && position.y === firstY && position.z === firstZ && position.direction === firstDirection) {
                return count;
            }
            const segment = forward.segment;
            if (segment === null) {
                return null;
            }
            if (segment.countsAsInversion) {
                count += 1;
            }
        }
        const backward = map.getTrackIterator(coords, index);
        if (backward === null) {
            return null;
        }
        while (backward.previous()) {
            steps += 1;
            if (steps > MAX_WALK_STEPS) {
                return null;
            }
            const segment = backward.segment;
            if (segment === null) {
                return null;
            }
            if (segment.countsAsInversion) {
                count += 1;
            }
        }
        return count;
    }

    function fill(payload: EventFields, ride: Ride, rideId: number, category: string | null, hasStart: boolean, startX: number, startY: number): void {
        payload.max_speed_mph = jsonSafeNumber(ride.maxSpeed);
        payload.average_speed_mph = jsonSafeNumber(ride.averageSpeed);
        payload.ride_time_seconds = jsonSafeNumber(ride.rideTime);
        payload.ride_length_meters = jsonSafeNumber(ride.rideLength);
        payload.max_positive_vertical_g = jsonSafeNumber(ride.maxPositiveVerticalGs);
        payload.max_negative_vertical_g = jsonSafeNumber(ride.maxNegativeVerticalGs);
        payload.max_lateral_g = jsonSafeNumber(ride.maxLateralGs);
        payload.total_air_time_seconds = jsonSafeNumber(ride.totalAirTime);
        payload.drop_count = jsonSafeInteger(ride.numDrops);
        payload.lift_hill_count = jsonSafeInteger(ride.numLiftHills);
        payload.highest_drop_height_units = jsonSafeNumber(ride.highestDropHeight);
        payload.inversion_count = category === "rollercoaster" && hasStart ? countInversions(rideId, startX, startY) : null;
        payload.ride_category = category;
    }

    return { loadCategories: loadCategories, categoryOf: categoryOf, fill: fill };
}
