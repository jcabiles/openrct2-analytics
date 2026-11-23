# ADR 0046: the showcase page restores the mockup's phone layout

- Date: 2026-11-03.
- Status: Accepted 2026-11-03 (the project owner approved fixing the phone layout in the visual-fix change). It amends ADR 0043 and the "phone layout out of scope" line of `docs/ai-dlc/specs/site-mockup-port.md`.

## Bottom line

The site stylesheets again carry the mockup's width media queries, so grids collapse to one column and the page no longer scrolls sideways on a phone. The test that allowed only desktop-width queries now allows any `max-width` query of 320px or more.

## Context

The mockup port dropped every width media query and the port spec marked the phone layout out of scope. A browser comparison at 390px then showed the page scrolling sideways, with multi-column grids, the build-crew diagram and the hero ticket laid out for desktop only. `tests/test_site_tokens.py` enforced the omission by rejecting any `max-width` query below 1024px.

## Decision

1. The mockup's `max-width` and `min-width` queries are ported into the stylesheet that holds the rules they override, using the site's class names and colour tokens only.
2. The build-crew diagram's desktop rules sit inside `@media (min-width: 960px)`, as in the mockup, with the one-column form as the base.
3. The token test keeps its colour-literal, font-file and light-only rules. Its desktop-only rule becomes: every `max-width` value is a plain px, em or rem length and is at least 320px, and at least one `max-width` query below 1024px must remain, so dropping the phone layout again fails the test.

## Amendments

- ADR 0043 and the port spec's out-of-scope line: the phone layout is now in scope. Fonts, the lack of an animation library and the other decisions stay as recorded.

## Rejected alternatives

- **Hide overflow on the page and leave the desktop layout.** It hides the symptom, but the content stays cramped and cut off on a phone.
