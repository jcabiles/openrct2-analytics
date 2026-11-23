// Park, session and save identity. Park storage is keyed by the registered plugin name, so renaming the plugin
// orphans every stored park ID and save key.

const PARK_ID_KEY = "park_id";
// Written on every save, so the saved file records which save it is, which session wrote it and where the save
// cut that session's seq (ADR 0006).
const SAVE_ID_KEY = "save_id";
const SAVE_SESSION_ID_KEY = "save_session_id";
const SAVE_SEQ_FLOOR_KEY = "save_seq_floor";
const SAVE_LINES_WAITING_KEY = "save_lines_waiting";
// 36^6: the random part is up to 6 base-36 characters.
const ID_RANDOM_RANGE = 2176782336;
// The largest loaded_save_lines_waiting the session_start contract's INTEGER column holds.
const MAX_LINES_WAITING = 2147483647;

// The save keys as read back at session start, each null when absent or of the wrong type.
interface LoadedSave {
    loaded_save_id: string | null;
    loaded_save_session_id: string | null;
    loaded_save_seq_floor: number | null;
    loaded_save_lines_waiting: number | null;
}

function mintId(prefix: string): string {
    return prefix + new Date().getTime() + "-" + Math.floor(Math.random() * ID_RANDOM_RANGE).toString(36);
}

// Reads the park's ID from park storage, minting and storing one when absent or not a non-empty string.
// Storage errors propagate, so no event is ever sent without a park ID.
function readOrMintParkId(): string {
    const storage = context.getParkStorage();
    const stored = storage.get<unknown>(PARK_ID_KEY);
    if (typeof stored === "string" && stored !== "") {
        return stored;
    }
    const minted = mintId("k");
    storage.set(PARK_ID_KEY, minted);
    return minted;
}

function mintSessionId(): string {
    return mintId("s");
}

function mintSaveId(): string {
    return mintId("v");
}

// seqFloor is the last seq handed off in this session (0 if none); linesWaiting counts the lines queued and not
// yet handed off. Storage errors propagate: if a write after the first fails, the saved file can carry the new
// save_id beside an earlier save's session, floor and waiting count, with no save_written for that ID.
function writeSaveKeys(saveId: string, sessionId: string, seqFloor: number, linesWaiting: number): void {
    const storage = context.getParkStorage();
    storage.set(SAVE_ID_KEY, saveId);
    storage.set(SAVE_SESSION_ID_KEY, sessionId);
    storage.set(SAVE_SEQ_FLOOR_KEY, seqFloor);
    storage.set(SAVE_LINES_WAITING_KEY, linesWaiting);
}

function idOrNull(value: unknown): string | null {
    return typeof value === "string" && value !== "" ? value : null;
}

// A non-negative whole number JSON can carry exactly (rides.ts owns that rule), else null.
function countOrNull(value: unknown): number | null {
    return typeof value === "number" && value >= 0 ? jsonSafeInteger(value) : null;
}

// A count the converter can store in the INTEGER column, else null.
function linesWaitingOrNull(value: unknown): number | null {
    const count = countOrNull(value);
    return count !== null && count <= MAX_LINES_WAITING ? count : null;
}

// Reads the save keys the loaded park carries; a park never saved by plugin 0.3.0 or later has none, so all four
// read null. Storage errors propagate.
function readLoadedSave(): LoadedSave {
    const storage = context.getParkStorage();
    return {
        loaded_save_id: idOrNull(storage.get<unknown>(SAVE_ID_KEY)),
        loaded_save_session_id: idOrNull(storage.get<unknown>(SAVE_SESSION_ID_KEY)),
        loaded_save_seq_floor: countOrNull(storage.get<unknown>(SAVE_SEQ_FLOOR_KEY)),
        loaded_save_lines_waiting: linesWaitingOrNull(storage.get<unknown>(SAVE_LINES_WAITING_KEY))
    };
}
