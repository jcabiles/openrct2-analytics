"""The 81 game action names the plugin knows, split into kept and dropped.

It also holds the two kept sub-type lists. The plugin keeps the same table in
plugin/src/action_names.ts; tests/test_action_names.py proves the two equal. Sub-type codes are
the integer values of OpenRCT2 v0.5.6 enums (the TypeScript file cites the source lines).
"""

import json
from typing import Any

KEPT_ACTION_NAMES = frozenset(
    {
        "parksetentrancefee",
        "ridesetprice",
        "ridesetstatus",
        "ridesetsetting",
        "ridesetvehicle",
        "parksetparameter",
        "parkmarketing",
        "parksetloan",
        "parksetresearchfunding",
        "staffhire",
        "stafffire",
        "staffsetorders",
        "staffsetpatrolarea",
    }
)

# Kept only for the sub-types below; every other kept name is kept whole.
SUBTYPE_FILTERED_ACTION_NAMES = frozenset({"ridesetsetting", "ridesetvehicle"})

DROPPED_ACTION_NAMES = frozenset(
    {
        "landbuyrights",
        "ridesetcolourscheme",
        "ridesetappearance",
        "staffsetcolour",
        "staffsetcostume",
        "guestsetflags",
        "ridefreezerating",
        "cheatset",
        "scenariosetsetting",
        "parksetdate",
        "landsetrights",
        "mapchangesize",
        "peepspawnplace",
        "tilemodify",
        "gamesetspeed",
        "pausetoggle",
        "loadorquit",
        "peeppickup",
        "tracksetbrakespeed",
        "ridesetname",
        "parksetname",
        "staffsetname",
        "guestsetname",
        "bannersetname",
        "signsetname",
        "ridecreate",
        "ridedemolish",
        "trackplace",
        "trackremove",
        "trackdesign",
        "mazeplacetrack",
        "mazesettrack",
        "rideentranceexitplace",
        "rideentranceexitremove",
        "parkentranceplace",
        "parkentranceremove",
        "footpathplace",
        "footpathlayoutplace",
        "footpathremove",
        "footpathadditionplace",
        "footpathadditionremove",
        "landraise",
        "landlower",
        "landsetheight",
        "landsmooth",
        "surfacesetstyle",
        "waterraise",
        "waterlower",
        "watersetheight",
        "clearscenery",
        "smallsceneryplace",
        "smallsceneryremove",
        "smallscenerysetcolour",
        "largesceneryplace",
        "largesceneryremove",
        "largescenerysetcolour",
        "wallplace",
        "wallremove",
        "wallsetcolour",
        "bannerplace",
        "bannerremove",
        "bannersetcolour",
        "bannersetstyle",
        "signsetstyle",
        "networkmodifygroup",
        "playerkick",
        "playersetgroup",
        "balloonpress",
    }
)

# Counted as cheats, not as plain drops.
CHEAT_ACTION_NAMES = frozenset({"cheatset", "ridefreezerating"})

# ridesetsetting, by args.setting: mode, departure, minWaitingTime, maxWaitingTime, operation,
# inspectionInterval, liftHillSpeed, numCircuits. Dropped: 6 music, 7 musicType, 10 rideType.
RIDE_SET_SETTING_KEPT_SUBTYPES = frozenset({0, 1, 2, 3, 4, 5, 8, 9})

# ridesetvehicle, by args.type: numTrains, numCarsPerTrain. Dropped: 2 rideEntry.
RIDE_SET_VEHICLE_KEPT_SUBTYPES = frozenset({0, 1})


def dropped_action_row(row: dict[str, Any]) -> bool:
    """Return whether a row violates the kept-action rule."""
    action = row["action"]
    if action not in KEPT_ACTION_NAMES or row["action_label"] == "preview":
        return True
    if action not in SUBTYPE_FILTERED_ACTION_NAMES:
        return False
    arguments = json.loads(row["args_json"])
    if action == "ridesetsetting":
        value = arguments.get("setting")
        return not (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value in RIDE_SET_SETTING_KEPT_SUBTYPES
        )
    value = arguments.get("type")
    return not (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value in RIDE_SET_VEHICLE_KEPT_SUBTYPES
    )
