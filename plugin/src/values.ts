// Integer checks for event fields. JSON carries a number exactly only when it is whole and within
// +/-(2^53 - 1); past that it rounds, and the converter rejects the row.

// 2^53 - 1, written out: Number.MAX_SAFE_INTEGER is ES2015.
const MAX_JSON_SAFE_INTEGER = 9007199254740991;

// For an optional field: a number JSON cannot carry exactly (not whole, not finite, or past the limit, such as
// a never-opened stall's -2^63 profit) is sent as null.
function jsonSafeInteger(value: number): number | null {
    return value === Math.floor(value) && Math.abs(value) <= MAX_JSON_SAFE_INTEGER ? value : null;
}

// For a required field: a value JSON cannot carry exactly throws, so the step that read it fails and is
// counted, and no event with a null in a required field is sent.
function requiredInteger(field: string, value: number): number {
    if (jsonSafeInteger(value) === null) {
        throw new Error(field + " is not a JSON-safe integer: " + value);
    }
    return value;
}

// For an optional measurement, which may be fractional: the value when it is a finite number, null for NaN or
// an infinity (JSON cannot carry either). Zero stays 0. Uses the global isFinite, which is ES5.
function jsonSafeNumber(value: number): number | null {
    return typeof value === "number" && isFinite(value) ? value : null;
}
