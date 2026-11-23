// Stand-ins for what the ride statistics read besides the ride itself: the 11 statistics' defaults, the research
// lists (park.research) and a ride's track (map.getTile and map.getTrackIterator). Kept apart from fake-game.mjs
// to stay under the file-size cap. Each member names the 0.5.5 API it stands for.

// The 11 statistics a ride holds, every one non-zero and distinct so a swapped field shows; the measurements keep a fraction so an integer guard shows. A test overrides
// them per ride; a newly built ride reads all 0 until its first test run.
export function createStatistics() {
  return {
    maxSpeed: 61.5, averageSpeed: 33.25, rideTime: 94.5, rideLength: 1204.25, maxPositiveVerticalGs: 3.75,
    maxNegativeVerticalGs: -1.5, maxLateralGs: 2.25, totalAirTime: 7.5, numDrops: 4, numLiftHills: 2,
    highestDropHeight: 38.5,
  };
}

// park.research: ride types 3 and 7 are coasters (7 not yet researched), 0 and 52 are not, and the scenery
// item has no ride type. Type 99 is in neither list. The ride type numbers differ from the ride IDs the tests
// use, so a lookup by the wrong key gives another category.
export function createResearch() {
  return {
    inventedItems: [
      { type: "ride", category: "gentle", rideType: 0 },
      { type: "scenery", category: "scenery", rideType: undefined },
      { type: "ride", category: "rollercoaster", rideType: 3 },
      { type: "ride", category: "thrill", rideType: 52 },
    ],
    uninventedItems: [{ type: "ride", category: "rollercoaster", rideType: 7 }],
  };
}

// The tile elements a ride's track tile holds: a surface and another ride's track ahead of the ride's own, so
// the plugin must find the element's index rather than assume one.
const OWN_ELEMENT_INDEX = 2;

// One ride's track as a list of segments, each { countsAsInversion } or null (a segment the game cannot
// describe). `startIndex` is the segment on the first station's tile. With `closed`, next() from the last
// segment wraps to the first and previous() from the first wraps to the last; otherwise both end the track.
// `noElement` leaves the tile without the ride's track element; `nullIterator` makes getTrackIterator return null.
export function createTrackWorld() {
  const tracks = [];
  return {
    // Registers a ride's track on the tile of its first used station, `start` in world coordinates.
    add(rideId, start, track) {
      tracks.push({ rideId, start, ...track });
    },

    // map.getTile(x, y), in tile coordinates
    getTile(x, y) {
      const track = tracks.find((t) => t.start.x === x * 32 && t.start.y === y * 32);
      const elements = [{ type: "surface" }];
      if (track !== undefined && !track.noElement) {
        elements.push({ type: "track", ride: track.rideId + 100 }, { type: "track", ride: track.rideId });
      }
      return { x, y, elements, numElements: elements.length };
    },

    // map.getTrackIterator(location, elementIndex), in world coordinates; null for tile coordinates or any other
    // tile or index, as the real game, and for a track made with `nullIterator`
    getTrackIterator(location, elementIndex) {
      const track = tracks.find((t) => t.start.x === location.x && t.start.y === location.y);
      if (track === undefined || track.nullIterator || elementIndex !== OWN_ELEMENT_INDEX) return null;
      const last = track.segments.length - 1;
      let at = track.startIndex;
      return {
        get position() {
          return { x: track.start.x + 32 * (at - track.startIndex), y: track.start.y, z: track.start.z, direction: 0 };
        },
        get segment() {
          return track.segments[at];
        },
        next() {
          if (at < last) at += 1;
          else if (track.closed) at = 0;
          else return false;
          return true;
        },
        previous() {
          if (at > 0) at -= 1;
          else if (track.closed) at = last;
          else return false;
          return true;
        },
      };
    },
  };
}
