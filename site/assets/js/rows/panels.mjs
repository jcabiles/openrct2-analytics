// Rows for the Finance revenue-mix panel and the Operations and Attractions panels (R16): export
// rows in export order, each carrying the export columns one panel reads and a "Park N" label from
// the park number of the desk. Nothing here adds, divides, ranks or compares values; the one filter
// keeps the rows whose served `riders_rank_in_park_year` is 1 to 5. Pure: no DOM, so the build and
// a test run it under Node.
import { deskParks, parkLabels } from "./insights.mjs";

const BUSIEST = 5;

// A park with ride rows but no monthly statement has no desk entry: its rows are left out of the panels and its number stays reserved (R21).
function labelledRows(exports, rows, build) {
  const parks = deskParks(exports);
  const labels = parkLabels(parks);
  return rows.flatMap((row) => {
    const index = parks.findIndex((park) => park.park_id === row.park_id);
    return index === -1 ? [] : [build(row, labels[index])];
  });
}

// An absent export returns no rows, so its panel renders as pending: the page is also built from extracts that hold only some exports.
export function revenueMixRows(exports) {
  if (exports.park_month_revenue === undefined) return [];
  return labelledRows(exports, exports.park_month_revenue, (row, park) => ({
    key: row.park_month_key,
    park,
    month: row.company_date,
    ride: row.ride_revenue,
    foodDrink: row.food_drink_revenue,
    merchandise: row.merchandise_revenue,
    entrance: row.entrance_revenue,
    ridePct: row.ride_revenue_share_pct,
    foodDrinkPct: row.food_drink_revenue_share_pct,
    merchandisePct: row.merchandise_revenue_share_pct,
    entrancePct: row.entrance_revenue_share_pct,
  }));
}

const rideMonthRows = (exports) => {
  if (exports.ride_month === undefined) return [];
  return labelledRows(exports, exports.ride_month, (row, park) => ({
    key: row.ride_month_key,
    rideKey: row.ride_key,
    park,
    ride: row.ride_name,
    year: row.company_year,
    month: row.company_date,
    availability: row.average_availability_from_downtime_pct,
    longestLine: row.longest_queue_seen_minutes,
    riders: row.riders,
  }));
};

export const availabilityRows = rideMonthRows;
export const ridersRows = rideMonthRows;

// The longest line for the busiest rides: ride-months of a ride in a company year that
// `ride_year` ranks 1 to 5 within its park.
export function longestLineRows(exports) {
  if (exports.ride_year === undefined || exports.ride_month === undefined) return [];
  const busiest = new Set(
    exports.ride_year
      .filter((row) => row.riders_rank_in_park_year !== null && row.riders_rank_in_park_year <= BUSIEST)
      .map((row) => `${row.ride_key}|${row.company_year}`),
  );
  return rideMonthRows(exports).filter((row) => busiest.has(`${row.rideKey}|${row.year}`));
}

export function rideYearRows(exports) {
  if (exports.ride_year === undefined) return [];
  return labelledRows(exports, exports.ride_year, (row, park) => ({
    key: row.ride_year_key,
    park,
    ride: row.ride_name,
    year: row.company_year,
    riders: row.riders,
    rating: row.latest_guest_rating_pct,
    age: row.latest_ride_age_months,
  }));
}
