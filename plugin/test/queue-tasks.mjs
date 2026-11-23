// Test tasks for the work queue, added in the plugin's context to the queue main() created. They stand in for the
// guest and arrival tasks: their kinds are the ones the queue holds on day-start ticks.

// Starts a loaded game with main()'s work queue, timer and order counter captured, so a test can add tasks to the
// queue and report steps to it.
export function startCapturingQueue(game) {
  const captured = {};
  const createWorkQueue = game.context.createWorkQueue;
  game.context.createWorkQueue = (timer, emitter, transport, nextOrder) => {
    captured.work = createWorkQueue(timer, emitter, transport, nextOrder);
    captured.timer = timer;
    captured.nextOrder = nextOrder;
    return captured.work;
  };
  game.start();
  return captured;
}

// A day-scoped test task of `count` items a day, each costing `ms` of fake time; `ran` holds each item's tick.
export function dayTask(game, kind, count, ms) {
  let left = 0;
  let order = 0;
  const ran = [];
  return {
    ran,
    pending: () => left,
    headOrder: () => order,
    headKind: () => kind,
    runOne() {
      left -= 1;
      game.wallMs += ms;
      ran.push(game.date.ticksElapsed);
    },
    startDay(dayOrder) {
      const dropped = left;
      left = count;
      order = dayOrder;
      return dropped;
    },
  };
}

// A continuous test task: feed(n) adds n items, each taking the plugin's next creation order.
export function continuousTask(game, kind, nextOrder, ms) {
  const orders = [];
  const ran = [];
  return {
    ran,
    feed(count) {
      for (let i = 0; i < count; i++) orders.push(nextOrder());
    },
    pending: () => orders.length,
    headOrder: () => orders[0],
    headKind: () => kind,
    runOne() {
      orders.shift();
      game.wallMs += ms;
      ran.push(game.date.ticksElapsed);
    },
  };
}
