# ADR 0043: the showcase page uses system fonts, no animation library, styled Plot charts and story passages

- Date: 2026-11-02.
- Status: Accepted 2026-11-02 (the project owner ruled O2, no animation library and no web fonts, on 2026-11-02; the other decisions are in `docs/ai-dlc/specs/site-mockup-port.md`, D1 and D5). It amends ADR 0021 (`docs/adr/0021-showcase-site-tool.md`, `:46`) and ADR 0026 (`docs/adr/0026-build-time-json-for-the-first-site-page.md`) as set out below.
- Amended by ADR 0046 (`docs/adr/0046-showcase-phone-layout.md`), 2026-11-03: the phone layout is restored.

## Bottom line

The showcase page takes its design from the frozen mockup copy but loads nothing from another host: the animation library and the web fonts are dropped for system font stacks, and no dependency is added or removed. Charts stay on Observable Plot, styled through design tokens. The single source of story text stays in `docs/showcase/story/`, but the one-page site renders named passages of those files instead of one include per story page. This amends two earlier records, ADR 0021 at `:46` and ADR 0026.

## Context

The mockup port rebuilds the single-file steel-thread page as a one-page site with a section menu, a hero scene and a figure registry. The frozen mockup copy loads an animation library (GSAP) and Google Fonts from other hosts. ADR 0021 forbids a CDN ("never a CDN") and requires the offline page-load test. ADR 0021 `:46` also says the story files in `docs/showcase/story/` are the single source of text and that, in Eleventy, each story page holds one include. A one-page site interleaves prose with figures, so a whole-file include per story page no longer fits. ADR 0026 let the steel-thread page write its own headline and check line outside the story files, a departure that ends when that page is replaced.

## Decision

1. **System fonts, no animation library.** The font tokens use the system font stacks the frozen copy already names as fallbacks (a `system-ui` sans stack and a Georgia serif stack). No font file and no image file is added. GSAP and its scroll plugin are removed; the hero park scene keeps its own `requestAnimationFrame` loop, and scroll reveals use the browser's `IntersectionObserver`. The page and its modules load nothing from another host.
2. **Plot styled through tokens.** Charts stay on Observable Plot (ADR 0021's chart choice), styled to the mockup's colours, type and axes by reading the design tokens, so the page-check rules for chart scripts keep their exact form.
3. **Story passages, not whole story pages.** Each story file in `docs/showcase/story/` carries named passage markers, and the site renders a passage where the page needs it, through a build-time shortcode. The story files stay the single source of text for the README and the site.
4. **Prose and figures render at build time.** Every figure region comes from the figure registry (`site/figures.mjs`) through one macro (`site/_includes/figure.njk`). A region is live, or pending with a body of exactly "figure pending". Modules under `site/assets/js/` only draw and wire controls.
5. **The contract count and shared version are read at build time** from `contracts/`, so the data-stack line does not go stale when a contract version moves.

## Amendments

- **ADR 0021, `:46`, the "Carried forward" row.** Its single-source rule for story files is kept, but its form changes: "each story page holds one include" becomes "the one-page site renders named passages of the story files". Why: the page interleaves prose with figures, and a whole-file include cannot be placed between two figures. The rest of the row, including the Parquet data path (already departed from by ADR 0026 until the website build), is unchanged.
- **ADR 0026.** Its departure from the story-file rule (the steel-thread page's headline, check line and sample note written in `site/index.njk`) ends: that text now comes from story passages and the figure registry. Its embedded-JSON data path and build-time month table stay in force through this item, and its Parquet migration still waits for the website build. Why: the page that needed the departure is replaced. ADR 0026 receives one status line pointing here; its body is not edited.

## Rejected alternatives

- **Keep the web fonts and the animation library, self-hosted.** It would match the mockup exactly, but it adds files and a dependency to a site that otherwise ships none, and the project owner ruled against it.
- **Replace Plot with hand-drawn charts as in the mockup.** It would match fine details of the frozen copy, but the page-check rules for chart scripts and the data-stack copy that names Plot would need rewriting.

## Consequences

- **Gain:** the offline rule of ADR 0021 holds with no exception; no dependency changes; the page check and the data-swap tests see every sentence and number in the built HTML; the page reads without JavaScript; the story files stay the single source of text on a page that interleaves prose with figures.
- **Cost:** the page's type differs from the mockup on machines whose system fonts differ; the frozen copy's script-built text is rewritten as passages and markup rather than pasted; each story file carries passage markers; charts are rebuilt as Plot specifications, so fine details of the mockup's hand-drawn charts may differ; `site/eleventy.config.mjs` gains about ten lines reading `contracts/`, which holds no business figure.
