// Action hooks copy their values into a bounded session buffer. The work queue sends those copies in order.
const ACTION_BUFFER_CAPACITY = 2048;
const ACTION_PREVIEW_FLAG = 64;
const ACTION_FIELDS: ReadonlyArray<string> = [
    "hook", "player", "type", "action", "is_client_only", "args_flags", "action_label", "args_json",
    "args_ride", "args_ride_type", "args_ride_object", "args_price_tenths", "args_x", "args_y", "args_z",
    "result_error", "result_cost_tenths", "result_ride", "action_at_ticks", "action_game_year",
    "action_game_month", "action_game_day"
];

interface ActionTotals {
    game_actions_sent_preview_total: number;
    game_actions_sent_prediction_total: number;
    game_actions_sent_confirmed_total: number;
    game_actions_dropped_preview_total: number;
    game_actions_dropped_prediction_total: number;
    game_actions_dropped_confirmed_total: number;
    game_actions_skipped_preview_total: number;
    game_actions_skipped_prediction_total: number;
    game_actions_skipped_confirmed_total: number;
    game_actions_skipped_unknown_total: number;
    game_actions_skipped_cheat_total: number;
}

interface ActionRecorder {
    task: WorkTask;
    recordQuery(event: GameActionEventArgs): void;
    recordExecute(event: GameActionEventArgs): void;
    totals(): ActionTotals;
}

function actionNumber(value: unknown): number | null {
    return typeof value === "number" ? value : null;
}

// The preview bit wins when both raw signals are present, including when flags has its sign bit set.
function actionLabel(flags: number | null, clientOnly: boolean): "preview" | "prediction" | "confirmed" {
    if (flags !== null && (flags & ACTION_PREVIEW_FLAG) !== 0) {
        return "preview";
    }
    return clientOnly ? "prediction" : "confirmed";
}

// A sub-type is kept only when it is a whole number inside the list and its entry is true; anything else,
// including a missing or non-number value, is dropped.
function subTypeKept(kept: ReadonlyArray<boolean>, value: unknown): boolean {
    return typeof value === "number" && value >= 0 && value < kept.length && value % 1 === 0 && kept[value] === true;
}

function createActionRecorder(emitter: Emitter, nextOrder: () => number): ActionRecorder {
    const columns: (number | string | boolean | null)[][] = [];
    for (let field = 0; field < ACTION_FIELDS.length; field++) {
        columns[field] = new Array<number | string | boolean | null>(ACTION_BUFFER_CAPACITY);
    }
    const orders: number[] = new Array<number>(ACTION_BUFFER_CAPACITY);
    const payload: EventFields = {};
    const counts: ActionTotals = {
        game_actions_sent_preview_total: 0,
        game_actions_sent_prediction_total: 0,
        game_actions_sent_confirmed_total: 0,
        game_actions_dropped_preview_total: 0,
        game_actions_dropped_prediction_total: 0,
        game_actions_dropped_confirmed_total: 0,
        game_actions_skipped_preview_total: 0,
        game_actions_skipped_prediction_total: 0,
        game_actions_skipped_confirmed_total: 0,
        game_actions_skipped_unknown_total: 0,
        game_actions_skipped_cheat_total: 0
    };
    let head = 0;
    let count = 0;

    function record(hook: "query" | "execute", event: GameActionEventArgs): void {
        // Skipped calls leave here, before event.result is read, a slot is taken or nextOrder() runs, so they
        // take no seq. Nothing on this path allocates or copies an argument.
        const args = event.args as { [key: string]: unknown };
        const flags = actionNumber(args.flags);
        const label = actionLabel(flags, event.isClientOnly);
        const name = event.action;
        // An inherited key such as "constructor" is not a number, so it reads as unknown.
        const code = ACTION_NAME_CODES[name];
        let skip = false;
        if (typeof code !== "number") {
            counts.game_actions_skipped_unknown_total += 1;
            skip = true;
        } else if (code === ACTION_CODE_CHEAT) {
            counts.game_actions_skipped_cheat_total += 1;
            skip = true;
        } else if (code === ACTION_CODE_DROP || label === "preview") {
            skip = true;
        } else if (code === ACTION_CODE_KEEP_BY_SUBTYPE) {
            skip = name === "ridesetsetting"
                ? !subTypeKept(RIDE_SET_SETTING_KEPT, args.setting)
                : !subTypeKept(RIDE_SET_VEHICLE_KEPT, args.type);
        }
        if (skip) {
            if (label === "preview") counts.game_actions_skipped_preview_total += 1;
            else if (label === "prediction") counts.game_actions_skipped_prediction_total += 1;
            else counts.game_actions_skipped_confirmed_total += 1;
            return;
        }
        const result = event.result as { [key: string]: unknown };
        if (count === ACTION_BUFFER_CAPACITY) {
            if (label === "preview") counts.game_actions_dropped_preview_total += 1;
            else if (label === "prediction") counts.game_actions_dropped_prediction_total += 1;
            else counts.game_actions_dropped_confirmed_total += 1;
            return;
        }
        const slot = (head + count) % ACTION_BUFFER_CAPACITY;
        columns[0][slot] = hook;
        columns[1][slot] = event.player;
        columns[2][slot] = actionNumber(event.type);
        columns[3][slot] = event.action;
        columns[4][slot] = event.isClientOnly;
        columns[5][slot] = flags;
        columns[6][slot] = label;
        columns[7][slot] = JSON.stringify(args);
        columns[8][slot] = actionNumber(args.ride);
        columns[9][slot] = actionNumber(args.rideType);
        columns[10][slot] = actionNumber(args.rideObject);
        columns[11][slot] = actionNumber(args.price);
        columns[12][slot] = actionNumber(args.x);
        columns[13][slot] = actionNumber(args.y);
        columns[14][slot] = actionNumber(args.z);
        columns[15][slot] = actionNumber(result.error);
        columns[16][slot] = actionNumber(result.cost);
        columns[17][slot] = actionNumber(result.ride);
        columns[18][slot] = date.ticksElapsed;
        columns[19][slot] = date.year;
        columns[20][slot] = date.month;
        columns[21][slot] = date.day;
        orders[slot] = nextOrder();
        count += 1;
    }

    function runOne(): void {
        const slot = head;
        for (let field = 0; field < ACTION_FIELDS.length; field++) {
            payload[ACTION_FIELDS[field]] = columns[field][slot];
        }
        head = (head + 1) % ACTION_BUFFER_CAPACITY;
        count -= 1;
        emitter.emit("game_action", payload);
        const label = payload.action_label;
        if (label === "preview") counts.game_actions_sent_preview_total += 1;
        else if (label === "prediction") counts.game_actions_sent_prediction_total += 1;
        else counts.game_actions_sent_confirmed_total += 1;
    }

    return {
        task: {
            pending: function (): number { return count; },
            headOrder: function (): number { return orders[head]; },
            headKind: function (): StepKind { return "action"; },
            runOne: runOne
        },
        recordQuery: function (event: GameActionEventArgs): void { record("query", event); },
        recordExecute: function (event: GameActionEventArgs): void { record("execute", event); },
        totals: function (): ActionTotals { return counts; }
    };
}
