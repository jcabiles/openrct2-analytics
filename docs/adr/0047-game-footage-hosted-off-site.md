# ADR 0047: game footage is hosted on a video site and linked, never committed

- Date: 2026-11-03.
- Status: Accepted 2026-11-03 (the project owner approved the proposal and its three conditions). It narrows "Never break" rule 5 in `AGENTS.md` and `docs/ai-dlc/profile.md`, and the matching line in the roadmap's "Out of scope / no-gos": game footage may now appear on the site as a link to a video hosting site. The page check gains one narrow exception when the first footage link is built (Decision 2).

## Bottom line

The showcase may show recorded game footage, but only as a video on a hosting site such as YouTube, reached from the page by an outbound link. The repository still holds no game files, screenshots or video frames, and the page still makes no request to another host when it opens.

## Context

Rule 5 banned game files and screenshots from the repository to keep clear of copyright trouble. The page explains the game poorly to a cold reader, and recorded play is the most direct way to show what the game looks like. A web search on 2026-11-03 found that long gameplay videos are a legal gray area: they stay up because publishers tolerate them, not because a court has ruled them fair use. No video policy from Atari, the RollerCoaster Tycoon owner, was found. OpenRCT2 distributes none of the original game's assets; each player supplies them. Short, narrated or captioned, non-commercial clips on a video site are the use publishers most often allow, and claims against them are handled by the site rather than by this repository. This is a project decision, not legal advice.

## Decision

1. **Nothing from the game is committed.** Game files, screenshots and video frames stay out of git, including a video's cover image. Every committed image is an original drawing.
2. **Footage lives on a video hosting site and the page links out to it.** The project owner records, narrates and uploads it. The page reaches a video only by a plain outbound link (`<a href>`), placed on an original drawing or on text. The page never embeds the video site's player, scripts, frames or images, so it loads no third-party tracking and keeps ADR 0021's offline page-load rule.
   - Today the page check rejects every outside URL: `check_page` in `src/openrct2_analytics/showcase/page_check.py` fails on any `src` or `href` that names a host, and rule PC2 in `src/openrct2_analytics/showcase/page_check_site.py` fails on any remote string in a built module.
   - The build that adds the first footage link amends `check_page` with one exception: an `<a href>` whose host is on a short allowlist of video hosting sites, named in that build. `src` attributes, `iframe`, `script`, `link` and image loads stay forbidden, and PC2 is unchanged. The amending change carries a test that a listed link passes and an embedded player still fails.
3. **No game music.** Clips are recorded with the game's music off, or carry narration in its place, since original game music is the most likely trigger for the video site's automatic copyright matching.
4. **Clips are short and explained.** Each clip shows only what the explanation needs and carries narration or captions. The maximum length is set in the brainstorm for the content item that first uses footage.

## Consequences

- The footer passage in `docs/showcase/story/the-game.md` ("no game art, sprites or logos are used. Footage is coming soon.") is reworded when footage lands, so it states that the footage is hosted elsewhere and that the page itself holds only original drawings.
- A takedown or a policy change by the game's owner removes the video, not part of the repository; the page's link then needs replacing, and the page must still make sense without the video.

## Rejected alternatives

- **Keep the full ban on footage.** It avoids all doubt, but leaves the page with words and drawings only, which explain the game poorly to a reader who has never played it.
- **Commit short clips or screenshots to the repository.** It keeps the page fully self-contained, but makes the public repository redistribute the game owner's art, the one clear legal risk.
- **Embed the video player, even one that loads on click.** It keeps readers on the page, but puts the video site's code and URLs into the built page, which the page check and the offline rule forbid, and a click-to-load player still needs a larger exception than a plain link.
