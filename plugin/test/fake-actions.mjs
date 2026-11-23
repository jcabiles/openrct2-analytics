// Fire the stand-in game's action hooks with the engine's event shape and a chosen binding read cost.
export function fireAction(game, {
  hook = "execute", player = -1, type = 2, action = "ridesetprice", isClientOnly = false,
  args = {}, result = {}, cost = 0,
} = {}) {
  const hooks = hook === "query" ? game.actionQueryHooks : game.actionExecuteHooks;
  if (hook !== "query" && hook !== "execute") throw new Error("unknown action hook " + hook);
  const event = {
    player, type, action, isClientOnly,
    get args() {
      game.wallMs += cost;
      return args;
    },
    result,
  };
  for (const callback of hooks) callback(event);
  return event;
}
