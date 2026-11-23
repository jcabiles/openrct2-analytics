// The day callback runs at the end of each day's first tick (observed, not verified in the engine
// source), so on day 1 guests may already have booked money to the new month's index 0. Index 1 of
// each expenditure history is the closed month's total; the statement also sends the sum of index 0 as
// new_month_booked_tenths, so the warehouse can subtract it from cash. Money stays in the game's tenths of a
// dollar; staging converts it once (docs/adr/0008-money-arrives-as-closed-month-statements.md).

// The game's 14 expenditure types, in the type definitions' order; each is sent as <type>_tenths.
const EXPENDITURE_TYPES: ReadonlyArray<ExpenditureType> = [
    "ride_construction",
    "ride_runningcosts",
    "land_purchase",
    "landscaping",
    "park_entrance_tickets",
    "park_ride_tickets",
    "shop_sales",
    "shop_stock",
    "food_drink_sales",
    "food_drink_stock",
    "wages",
    "marketing",
    "research",
    "interest"
];
// The game year has 8 months, 0 (March) to 7 (October).
const MONTHS_PER_YEAR = 8;

interface FinanceReader {
    statementForToday(): EventFields | null;
    unreadTotal(): number;
}

// Created once in main(). The statement payload and its holder array of histories are one object each,
// refilled in place every month; every field is written on each fill, and emitter.emit copies the fields
// into its own event, so a queued statement keeps its own month's values.
function createFinanceReader(): FinanceReader {
    let unread = 0;
    const histories: number[][] = [];
    const statement: EventFields = {};

    // Returns the closed month's statement on a day-1 callback, else null. A history holds months elapsed
    // plus one entries, so it lacks a closed month only when a cheat has reset the month counter; that
    // month is counted as unread, never silently skipped.
    function statementForToday(): EventFields | null {
        if (date.day !== 1) {
            return null;
        }
        for (let i = 0; i < EXPENDITURE_TYPES.length; i++) {
            const history = park.getMonthlyExpenditure(EXPENDITURE_TYPES[i]);
            if (history.length < 2) {
                unread += 1;
                return null;
            }
            histories[i] = history;
        }
        const closedInPreviousYear = date.month === 0;
        statement.statement_year = closedInPreviousYear ? date.year - 1 : date.year;
        statement.statement_month = closedInPreviousYear ? MONTHS_PER_YEAR - 1 : date.month - 1;
        let newMonthBooked = 0;
        for (let i = 0; i < EXPENDITURE_TYPES.length; i++) {
            statement[EXPENDITURE_TYPES[i] + "_tenths"] = histories[i][1];
            newMonthBooked += histories[i][0];
        }
        statement.new_month_booked_tenths = newMonthBooked;
        statement.cash_tenths = park.cash;
        statement.bank_loan_tenths = park.bankLoan;
        return statement;
    }

    function unreadTotal(): number {
        return unread;
    }

    return { statementForToday: statementForToday, unreadTotal: unreadTotal };
}
