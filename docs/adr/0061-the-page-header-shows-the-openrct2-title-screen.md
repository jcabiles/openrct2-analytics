# ADR 0061: the page header shows the OpenRCT2 title screen

- Date: 2026-11-23.
- Status: Accepted 2026-11-23 (the project owner chose the image). It narrows Decision 1 of ADR 0047, the no-image-file rule of ADR 0043, and "Never break" rule 5 in `AGENTS.md` and `docs/ai-dlc/profile.md` by one named exception.

## Bottom line

The showcase page shows one game image: a cropped capture of the OpenRCT2 title screen, in the red panel at the top of the page. A reader who lands on the page cold sees at once which game it is about. Every other rule of ADR 0047 stands: no other game file, screenshot or video frame is committed.

## Context

The top of the page held only text and original drawings, so a first-time reader had no picture telling them the project is about OpenRCT2. The page is now public and linked from job applications, where that first glance matters most. ADR 0047 kept every game image out of git to stay clear of copyright trouble. The likely worst case for one non-commercial identifying image is a takedown request to GitHub. Removing the image answers it, though a notice can name the whole repository until it is removed. This is a project decision, not legal advice.

## Decision

1. **One game image is committed:** `site/assets/img/openrct2-title.webp`, the OpenRCT2 logo over the title screen's park scene, cropped and scaled to 720 by 452 pixels.
2. **It is captioned "OpenRCT2 title screen"**, and the footer says it is a capture of the game shown to identify it. The footer still says the project is unaffiliated with OpenRCT2 or the RollerCoaster Tycoon owners.
3. **The RollerCoaster Tycoon logo is not used.** The copy that was offered is a fan render of the game owner's trademark, so it carries two owners' claims.
4. **`tests/test_site_tokens.py` pins the image list,** so any further image needs its own decision.

## Consequences

- A takedown request removes `site/assets/img/openrct2-title.webp` and its `<figure>` in `site/_includes/hero.njk`; the page still reads correctly without it.

## Rejected alternatives

- **Keep the header text-only.** It avoids all doubt, but a cold reader cannot tell from the top of the page which game it is about.
- **Draw an original game-like logo.** It avoids the copyright question, but takes design time and would only look like the game, not show it.
