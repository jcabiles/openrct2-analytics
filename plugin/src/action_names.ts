// The 81 game action names of the plugin API, each with one integer code, and the two kept sub-type lists.
// The action hook looks a name up here before it reads or copies any argument. Codes:
//   0 = drop        the action is not a business action; it is counted and skipped
//   1 = keep        every call that is not a build preview is sent
//   2 = keep by sub-type   sent only when its sub-type is kept in the list below
//   3 = drop as cheat      dropped, and counted in the cheat counter (cheatset and ridefreezerating)
// A name that is not a key here is unknown and is dropped. The Python copy is
// src/openrct2_analytics/ingest/action_names.py; tests/test_action_names.py proves the two are equal.
// Sub-type codes are the integer values of OpenRCT2 v0.5.6 enums; a list entry is true for a kept code.
const ACTION_CODE_DROP = 0;
const ACTION_CODE_KEEP = 1;
const ACTION_CODE_KEEP_BY_SUBTYPE = 2;
const ACTION_CODE_CHEAT = 3;

const ACTION_NAME_CODES: { [name: string]: number } = {
    parksetentrancefee: ACTION_CODE_KEEP,
    ridesetprice: ACTION_CODE_KEEP,
    ridesetstatus: ACTION_CODE_KEEP,
    ridesetsetting: ACTION_CODE_KEEP_BY_SUBTYPE,
    ridesetvehicle: ACTION_CODE_KEEP_BY_SUBTYPE,
    parksetparameter: ACTION_CODE_KEEP,
    parkmarketing: ACTION_CODE_KEEP,
    parksetloan: ACTION_CODE_KEEP,
    parksetresearchfunding: ACTION_CODE_KEEP,
    staffhire: ACTION_CODE_KEEP,
    stafffire: ACTION_CODE_KEEP,
    staffsetorders: ACTION_CODE_KEEP,
    staffsetpatrolarea: ACTION_CODE_KEEP,
    landbuyrights: ACTION_CODE_DROP,
    ridesetcolourscheme: ACTION_CODE_DROP,
    ridesetappearance: ACTION_CODE_DROP,
    staffsetcolour: ACTION_CODE_DROP,
    staffsetcostume: ACTION_CODE_DROP,
    guestsetflags: ACTION_CODE_DROP,
    ridefreezerating: ACTION_CODE_CHEAT,
    cheatset: ACTION_CODE_CHEAT,
    scenariosetsetting: ACTION_CODE_DROP,
    parksetdate: ACTION_CODE_DROP,
    landsetrights: ACTION_CODE_DROP,
    mapchangesize: ACTION_CODE_DROP,
    peepspawnplace: ACTION_CODE_DROP,
    tilemodify: ACTION_CODE_DROP,
    gamesetspeed: ACTION_CODE_DROP,
    pausetoggle: ACTION_CODE_DROP,
    loadorquit: ACTION_CODE_DROP,
    peeppickup: ACTION_CODE_DROP,
    tracksetbrakespeed: ACTION_CODE_DROP,
    ridesetname: ACTION_CODE_DROP,
    parksetname: ACTION_CODE_DROP,
    staffsetname: ACTION_CODE_DROP,
    guestsetname: ACTION_CODE_DROP,
    bannersetname: ACTION_CODE_DROP,
    signsetname: ACTION_CODE_DROP,
    ridecreate: ACTION_CODE_DROP,
    ridedemolish: ACTION_CODE_DROP,
    trackplace: ACTION_CODE_DROP,
    trackremove: ACTION_CODE_DROP,
    trackdesign: ACTION_CODE_DROP,
    mazeplacetrack: ACTION_CODE_DROP,
    mazesettrack: ACTION_CODE_DROP,
    rideentranceexitplace: ACTION_CODE_DROP,
    rideentranceexitremove: ACTION_CODE_DROP,
    parkentranceplace: ACTION_CODE_DROP,
    parkentranceremove: ACTION_CODE_DROP,
    footpathplace: ACTION_CODE_DROP,
    footpathlayoutplace: ACTION_CODE_DROP,
    footpathremove: ACTION_CODE_DROP,
    footpathadditionplace: ACTION_CODE_DROP,
    footpathadditionremove: ACTION_CODE_DROP,
    landraise: ACTION_CODE_DROP,
    landlower: ACTION_CODE_DROP,
    landsetheight: ACTION_CODE_DROP,
    landsmooth: ACTION_CODE_DROP,
    surfacesetstyle: ACTION_CODE_DROP,
    waterraise: ACTION_CODE_DROP,
    waterlower: ACTION_CODE_DROP,
    watersetheight: ACTION_CODE_DROP,
    clearscenery: ACTION_CODE_DROP,
    smallsceneryplace: ACTION_CODE_DROP,
    smallsceneryremove: ACTION_CODE_DROP,
    smallscenerysetcolour: ACTION_CODE_DROP,
    largesceneryplace: ACTION_CODE_DROP,
    largesceneryremove: ACTION_CODE_DROP,
    largescenerysetcolour: ACTION_CODE_DROP,
    wallplace: ACTION_CODE_DROP,
    wallremove: ACTION_CODE_DROP,
    wallsetcolour: ACTION_CODE_DROP,
    bannerplace: ACTION_CODE_DROP,
    bannerremove: ACTION_CODE_DROP,
    bannersetcolour: ACTION_CODE_DROP,
    bannersetstyle: ACTION_CODE_DROP,
    signsetstyle: ACTION_CODE_DROP,
    networkmodifygroup: ACTION_CODE_DROP,
    playerkick: ACTION_CODE_DROP,
    playersetgroup: ACTION_CODE_DROP,
    balloonpress: ACTION_CODE_DROP
};

// ridesetsetting, indexed by args.setting. Source: OpenRCT2 v0.5.6 src/openrct2/actions/ride/RideSetSettingAction.h,
// enum RideSetSetting at lines 14-27, members counted from 0 in declaration order; the line of each member follows.
const RIDE_SET_SETTING_KEPT: ReadonlyArray<boolean> = [
    true, // 0 mode, RideSetSettingAction.h line 16
    true, // 1 departure, RideSetSettingAction.h line 17
    true, // 2 minWaitingTime, RideSetSettingAction.h line 18
    true, // 3 maxWaitingTime, RideSetSettingAction.h line 19
    true, // 4 operation, RideSetSettingAction.h line 20
    true, // 5 inspectionInterval, RideSetSettingAction.h line 21
    false, // 6 music, RideSetSettingAction.h line 22
    false, // 7 musicType, RideSetSettingAction.h line 23
    true, // 8 liftHillSpeed, RideSetSettingAction.h line 24
    true, // 9 numCircuits, RideSetSettingAction.h line 25
    false // 10 rideType, RideSetSettingAction.h line 26
];

// ridesetvehicle, indexed by args.type. Source: OpenRCT2 v0.5.6 src/openrct2/actions/ride/RideSetVehicleAction.cpp
// (the effect of each code) and distribution/scripting/openrct2.d.ts lines 1277-1284 (the documented codes).
// trainsReversed has no confirmed code in v0.5.6 (RideSetVehicleAction.cpp lines 176-182), so it is not listed and
// is dropped like any code past the end of the list.
const RIDE_SET_VEHICLE_KEPT: ReadonlyArray<boolean> = [
    true, // 0 numTrains, RideSetVehicleAction.cpp lines 124-133
    true, // 1 numCarsPerTrain, RideSetVehicleAction.cpp lines 134-153
    false // 2 rideEntry, RideSetVehicleAction.cpp lines 155-169
];
