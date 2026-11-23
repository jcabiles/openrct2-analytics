# ADR 0002: Pin TypeScript 5.9 for ES5 output

- Date: 2026-09-27
- Status: Accepted

## Context

The OpenRCT2 plugin runs inside the game's Duktape JavaScript engine, which
only executes ES5. TypeScript 6 deprecates ES5 as a compile target, and
TypeScript 7 removes it entirely (verified 2026-09-27).

## Decision

Pin `typescript` to exactly `5.9.3` in `package.json`, the newest release
that still compiles cleanly to ES5 without a deprecation warning.

## Consequences

- The plugin cannot take a TypeScript 6 or 7 feature until either OpenRCT2
  changes its script engine or this pin is revisited.
- Upgrading past 5.9 without also changing the compile target would silently
  emit code Duktape cannot run; this ADR is the flag to check first.
