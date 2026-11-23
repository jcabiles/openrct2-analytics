// OpenRCT2 0.5.5 runs plugins in QuickJS-ng, which provides `performance.now()` at run time (the
// capture-schedule probe measured with it), but the game's type definitions omit it. It may be absent,
// so timing.ts feature-detects it.
declare var performance: { now(): number } | undefined;
